#!/usr/bin/env python3
"""
motor_test.py — Interactive Motor Test for Cokoino Pi Power & 4WD HAT.

Controls 4 CQR37D DC motors (70:1, 64 CPR encoder) via two DRV8833 dual
H-bridge chips on the Cokoino HAT. Reads encoder feedback via pigpio.

NOTE: LF + RF share one speed setting (DRV8833 #1 / NSLEEP GPIO 12).
      LR + RR share another speed setting (DRV8833 #2 / NSLEEP GPIO 13).

⚠️  DRV8833 is rated 1.5A continuous. CQR37D stall current is 5.5A @ 12V.
    Fine for bench testing but will overheat under heavy mechanical load.

Prerequisites:
    sudo pigpiod                 # Start the pigpio daemon (required for encoders)
    pip install pigpio           # Install pigpio Python bindings

Usage:
    python3 motor_test.py
"""

import sys
import time
import signal
import atexit
import threading
import config

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("ERROR: RPi.GPIO not available. This script must run on a Raspberry Pi.")
    sys.exit(1)

# pigpio is optional — encoders are disabled gracefully if unavailable
try:
    import pigpio
    _PIGPIO_AVAILABLE = True
except ImportError:
    _PIGPIO_AVAILABLE = False


# ─── Encoder Reader ─────────────────────────────────────────────────────────

class EncoderReader:
    """Reads a quadrature encoder via pigpio daemon callbacks.

    Uses channel A edges for counting and channel B level for direction.
    RPM is computed from the pulse delta over a sampling window.

    Why pigpio instead of RPi.GPIO?
      At 150 RPM output × 70:1 ratio, the motor shaft spins at 10,500 RPM.
      With 16 physical slots per encoder channel, that's ~2,800 pulses/sec.
      RPi.GPIO's Python-level interrupts drop edges above ~1,000/sec under
      CPU load. pigpio's C daemon handles counting at kernel level, good
      to ~100,000 edges/sec.
    """

    def __init__(self, pi, enc_a_pin, enc_b_pin, name=""):
        self.pi = pi
        self.enc_a = enc_a_pin
        self.enc_b = enc_b_pin
        self.name = name

        self._count = 0
        self._lock = threading.Lock()
        self._last_count = 0
        self._last_time = time.monotonic()
        self._rpm = 0.0

        # Configure encoder pins as inputs with pull-up
        self.pi.set_mode(self.enc_a, pigpio.INPUT)
        self.pi.set_mode(self.enc_b, pigpio.INPUT)
        self.pi.set_pull_up_down(self.enc_a, pigpio.PUD_UP)
        self.pi.set_pull_up_down(self.enc_b, pigpio.PUD_UP)

        # Register callback on channel A rising edges
        self._cb = self.pi.callback(self.enc_a, pigpio.RISING_EDGE, self._pulse)

    def _pulse(self, gpio, level, tick):
        """Callback fired on each channel A rising edge."""
        # Read channel B to determine direction
        b_level = self.pi.read(self.enc_b)
        with self._lock:
            if b_level:
                self._count += 1   # Forward
            else:
                self._count -= 1   # Reverse

    def get_count(self):
        """Return the cumulative encoder count (signed)."""
        with self._lock:
            return self._count

    def reset(self):
        """Zero the encoder counter."""
        with self._lock:
            self._count = 0
            self._last_count = 0
            self._last_time = time.monotonic()
            self._rpm = 0.0

    def get_rpm(self):
        """Compute RPM at the output shaft from the pulse delta.

        Call this periodically (e.g., every 100-500ms) for a fresh reading.
        """
        now = time.monotonic()
        with self._lock:
            count = self._count
        dt = now - self._last_time
        if dt < 0.01:
            return self._rpm  # Too soon, return last value

        d_count = count - self._last_count
        # counts per second → revolutions per second → RPM
        # Each motor-shaft revolution = ENCODER_CPR counts (rising edges on A)
        # But we only count rising edges on A = CPR/4 per motor-shaft rev
        # Actually: 64 CPR typically means 64 state changes in full quadrature.
        # With RISING_EDGE only on channel A, we get CPR/4 = 16 pulses per
        # motor-shaft revolution. After gear ratio: 16 * 70 = 1120 per output rev.
        pulses_per_output_rev = (config.ENCODER_CPR / 4) * config.MOTOR_GEAR_RATIO
        revs = d_count / pulses_per_output_rev
        self._rpm = (revs / dt) * 60.0

        self._last_count = count
        self._last_time = now
        return self._rpm

    def cancel(self):
        """Stop the callback."""
        if self._cb is not None:
            self._cb.cancel()
            self._cb = None


# ─── Motor ──────────────────────────────────────────────────────────────────

class Motor:
    """A single DC motor controlled by two GPIO direction pins."""

    def __init__(self, name, in1_pin, in2_pin):
        self.name = name
        self.in1 = in1_pin
        self.in2 = in2_pin

    def forward(self):
        GPIO.output(self.in1, GPIO.LOW)
        GPIO.output(self.in2, GPIO.HIGH)

    def reverse(self):
        GPIO.output(self.in1, GPIO.HIGH)
        GPIO.output(self.in2, GPIO.LOW)

    def coast(self):
        """Free-spin stop (no braking torque)."""
        GPIO.output(self.in1, GPIO.LOW)
        GPIO.output(self.in2, GPIO.LOW)

    def brake(self):
        """Active braking (short-brake)."""
        GPIO.output(self.in1, GPIO.HIGH)
        GPIO.output(self.in2, GPIO.HIGH)


# ─── Motor Controller ──────────────────────────────────────────────────────

class MotorController:
    """Manages 4 motors via two DRV8833 chips with NSLEEP PWM speed control
    and optional encoder feedback via pigpio."""

    def __init__(self):
        self.motors = {}
        self.encoders = {}          # name -> EncoderReader (or empty if pigpio unavailable)
        self.pwm_objects = {}       # nsleep_pin -> GPIO.PWM object
        self.speeds = {}            # nsleep_pin -> current duty cycle %
        self._pi = None             # pigpio.pi() connection
        self._encoders_available = False
        self._initialized = False

    def setup(self):
        """Configure all GPIO pins, start PWM, and initialize encoders."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Set up direction pins for each motor
        for name, pins in config.MOTOR_MAP.items():
            GPIO.setup(pins["in1"], GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(pins["in2"], GPIO.OUT, initial=GPIO.LOW)
            self.motors[name] = Motor(name, pins["in1"], pins["in2"])

        # Set up NSLEEP PWM pins (one per DRV8833 chip)
        for nsleep_pin in [config.MOTOR_NSLEEP1, config.MOTOR_NSLEEP2]:
            GPIO.setup(nsleep_pin, GPIO.OUT, initial=GPIO.LOW)
            pwm = GPIO.PWM(nsleep_pin, config.MOTOR_PWM_FREQUENCY)
            pwm.start(0)  # Start at 0% — motors disabled until speed is set
            self.pwm_objects[nsleep_pin] = pwm
            self.speeds[nsleep_pin] = 0

        # Initialize encoders via pigpio
        if _PIGPIO_AVAILABLE:
            try:
                self._pi = pigpio.pi()
                if not self._pi.connected:
                    raise RuntimeError("pigpiod not running")

                for name, pins in config.MOTOR_MAP.items():
                    enc = EncoderReader(
                        self._pi, pins["enc_a"], pins["enc_b"], name=name
                    )
                    self.encoders[name] = enc

                self._encoders_available = True
                print("Encoders initialized via pigpio daemon.")
            except Exception as e:
                print(f"WARNING: Encoder init failed: {e}")
                print("  Encoders disabled. To enable, run: sudo pigpiod")
                self._encoders_available = False
        else:
            print("WARNING: pigpio not installed. Encoders disabled.")
            print("  Install with: pip install pigpio")
            print("  Then start daemon: sudo pigpiod")

        self._initialized = True
        print("Motor controller initialized. All motors stopped.")

    def set_speed(self, motor_name, duty_cycle):
        """Set speed for the DRV8833 chip that controls the given motor.

        Note: This affects BOTH motors on the same chip.
        """
        duty_cycle = max(0, min(100, duty_cycle))
        nsleep_pin = config.MOTOR_MAP[motor_name]["nsleep"]
        self.pwm_objects[nsleep_pin].ChangeDutyCycle(duty_cycle)
        self.speeds[nsleep_pin] = duty_cycle

        # Find which motors share this chip
        siblings = [n for n, p in config.MOTOR_MAP.items() if p["nsleep"] == nsleep_pin]
        return siblings, duty_cycle

    def set_all_speed(self, duty_cycle):
        """Set speed for all DRV8833 chips."""
        duty_cycle = max(0, min(100, duty_cycle))
        for nsleep_pin, pwm in self.pwm_objects.items():
            pwm.ChangeDutyCycle(duty_cycle)
            self.speeds[nsleep_pin] = duty_cycle

    def get_speed(self, motor_name):
        """Get current speed (duty cycle %) for a motor's chip."""
        nsleep_pin = config.MOTOR_MAP[motor_name]["nsleep"]
        return self.speeds.get(nsleep_pin, 0)

    def get_rpm(self, motor_name):
        """Get current RPM for a motor (from encoder). Returns None if unavailable."""
        enc = self.encoders.get(motor_name)
        if enc:
            return enc.get_rpm()
        return None

    def get_encoder_count(self, motor_name):
        """Get encoder count for a motor. Returns None if unavailable."""
        enc = self.encoders.get(motor_name)
        if enc:
            return enc.get_count()
        return None

    def reset_encoders(self):
        """Reset all encoder counters to zero."""
        for enc in self.encoders.values():
            enc.reset()

    def stop_all(self):
        """Coast-stop all motors and set speed to 0."""
        for motor in self.motors.values():
            motor.coast()
        self.set_all_speed(0)

    def run_auto_test(self, speed=None, duration=None):
        """Test each motor one at a time: forward, then reverse.

        Args:
            speed: Duty cycle % (default: config.MOTOR_SLOW_SPEED).
            duration: Seconds per direction (default: config.MOTOR_TEST_DURATION).
        """
        if speed is None:
            speed = config.MOTOR_SLOW_SPEED
        if duration is None:
            duration = config.MOTOR_TEST_DURATION

        wheel_order = ["LF", "RF", "LR", "RR"]
        wheel_labels = {
            "LF": "Left Front",
            "RF": "Right Front",
            "LR": "Left Rear",
            "RR": "Right Rear",
        }

        print(f"\n--- Auto Test: speed={speed}%, duration={duration}s per direction ---")
        if self._encoders_available:
            self.reset_encoders()
            print("  (Encoder feedback enabled — RPM shown during test)")

        for name in wheel_order:
            if name not in self.motors:
                print(f"  WARNING: Motor '{name}' not configured, skipping.")
                continue

            label = wheel_labels.get(name, name)
            motor = self.motors[name]

            # Forward
            print(f"\n  [{name}] {label} — FORWARD...", end="", flush=True)
            motor.forward()
            self.set_speed(name, speed)
            time.sleep(duration)
            rpm = self.get_rpm(name)
            motor.coast()
            self.set_speed(name, 0)
            rpm_str = f" RPM={rpm:+.1f}" if rpm is not None else ""
            print(f" done.{rpm_str}")

            time.sleep(0.5)

            # Reverse
            print(f"  [{name}] {label} — REVERSE...", end="", flush=True)
            motor.reverse()
            self.set_speed(name, speed)
            time.sleep(duration)
            rpm = self.get_rpm(name)
            motor.coast()
            self.set_speed(name, 0)
            rpm_str = f" RPM={rpm:+.1f}" if rpm is not None else ""
            print(f" done.{rpm_str}")

            time.sleep(0.5)

        print("\n--- Auto test complete. All motors stopped. ---")
        if self._encoders_available:
            print("  Final encoder counts:")
            for name in wheel_order:
                count = self.get_encoder_count(name)
                if count is not None:
                    print(f"    {name}: {count:+d} counts")
        print()

    def cleanup(self):
        """Stop all motors, cancel encoders, and release GPIO resources."""
        if self._initialized:
            self.stop_all()
            for pwm in self.pwm_objects.values():
                pwm.stop()
            for enc in self.encoders.values():
                enc.cancel()
            if self._pi is not None:
                self._pi.stop()
                self._pi = None
            GPIO.cleanup()
            self._initialized = False
            print("Motor controller cleaned up.")


# ─── Interactive Console ────────────────────────────────────────────────────

MOTOR_HELP = """
Commands:
  n / p            Next / previous motor (LF->RF->LR->RR->ALL)
  fwd              Forward (selected motor or all)
  rev              Reverse (selected motor or all)
  stop             Coast stop (selected motor or all)
  brake            Active brake (selected motor or all)
  speed <0-100>    Set speed (duty cycle %)
  test             Auto test (each motor fwd/rev)
  rpm              Show RPM for all motors
  enc              Show encoder counts
  enc reset        Zero all encoders
  status           Show speed + RPM for all
  <motor> fwd      Direct command (LF, RF, LR, RR)
  <motor> rev/stop/brake
  help             Show this help
  quit / exit      Stop all and exit
"""


def interactive_loop(controller):
    """Run the interactive motor test console."""
    current_speed = config.MOTOR_SLOW_SPEED
    wheel_order = ["LF", "RF", "LR", "RR"]
    sel_index = -1  # -1 = ALL mode
    sel_mode = "all"

    print("\n" + "=" * 50)
    print("  ARES RPi4 — Motor Test")
    print("  Motors: LF  RF  LR  RR")
    enc_status = "ON" if controller._encoders_available else "OFF"
    print(f"  Encoders: {enc_status}")
    print("=" * 50)
    print(MOTOR_HELP)

    controller.set_all_speed(current_speed)
    print(f"Speed: {current_speed}%  |  Selection: ALL")

    def _get_sel_label():
        return "ALL" if sel_mode == "all" else wheel_order[sel_index]

    def _do_action(action):
        """Apply action to selected motor(s)."""
        if sel_mode == "all":
            for motor in controller.motors.values():
                getattr(motor, action)()
            label = "All motors"
        else:
            name = wheel_order[sel_index]
            getattr(controller.motors[name], action)()
            label = name

        if action in ("forward", "reverse"):
            if sel_mode == "all":
                controller.set_all_speed(current_speed)
            else:
                controller.set_speed(wheel_order[sel_index], current_speed)
        return label

    while True:
        try:
            cmd = input(f"[{_get_sel_label()} speed={current_speed}%] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not cmd:
            continue

        parts = cmd.split()

        if parts[0] in ("quit", "exit"):
            break
        elif parts[0] == "help":
            print(MOTOR_HELP)
            continue

        # Toggle cycling: n/p through LF -> RF -> LR -> RR -> ALL -> LF...
        if parts[0] == "n":
            if sel_mode == "all":
                sel_index = 0
                sel_mode = "individual"
            elif sel_index == len(wheel_order) - 1:
                sel_mode = "all"
                sel_index = -1
            else:
                sel_index += 1
            print(f"  -> {_get_sel_label()}")
            continue
        if parts[0] == "p":
            if sel_mode == "all":
                sel_index = len(wheel_order) - 1
                sel_mode = "individual"
            elif sel_index == 0:
                sel_mode = "all"
                sel_index = -1
            else:
                sel_index -= 1
            print(f"  -> {_get_sel_label()}")
            continue

        # Shorthand commands for selected motor(s)
        if parts[0] == "fwd":
            label = _do_action("forward")
            print(f"  {label} forward.")
            continue
        if parts[0] == "rev":
            label = _do_action("reverse")
            print(f"  {label} reverse.")
            continue
        if parts[0] == "stop":
            label = _do_action("coast")
            print(f"  {label} stopped (coast).")
            continue
        if parts[0] == "brake":
            label = _do_action("brake")
            print(f"  {label} braking.")
            continue

        if parts[0] == "test":
            controller.run_auto_test(speed=current_speed)
            continue
        elif parts[0] == "status":
            print("\nMotor Status:")
            for name in wheel_order:
                spd = controller.get_speed(name)
                rpm = controller.get_rpm(name)
                rpm_str = f"  RPM={rpm:+.1f}" if rpm is not None else ""
                count = controller.get_encoder_count(name)
                enc_str = f"  enc={count:+d}" if count is not None else ""
                sel = " *" if (sel_mode == "individual" and wheel_order[sel_index] == name) else ""
                print(f"  {name}: speed={spd}%{rpm_str}{enc_str}{sel}")
            continue
        elif parts[0] == "rpm":
            if not controller._encoders_available:
                print("Encoders not available. Run: sudo pigpiod")
                continue
            for name in wheel_order:
                rpm = controller.get_rpm(name)
                print(f"  {name}: {rpm:+.1f} RPM" if rpm is not None else f"  {name}: N/A")
            continue

        # enc / enc reset
        if parts[0] == "enc":
            if not controller._encoders_available:
                print("Encoders not available. Run: sudo pigpiod")
                continue
            if len(parts) >= 2 and parts[1] == "reset":
                controller.reset_encoders()
                print("All encoder counters reset to 0.")
            else:
                for name in wheel_order:
                    count = controller.get_encoder_count(name)
                    print(f"  {name}: {count:+d} counts" if count is not None else f"  {name}: N/A")
            continue

        # speed <value>
        if parts[0] == "speed" and len(parts) >= 2:
            try:
                val = int(parts[1])
                controller.set_all_speed(val)
                current_speed = max(0, min(100, val))
                print(f"Speed: {current_speed}%")
            except ValueError:
                print("Usage: speed <0-100>")
            continue

        # <motor> <action> — direct command (doesn't change selection)
        if len(parts) >= 2:
            motor_name = parts[0].upper()
            action = parts[1]

            if motor_name not in controller.motors:
                print(f"Unknown motor '{motor_name}'. Use: LF, RF, LR, RR")
                continue

            motor = controller.motors[motor_name]
            if action == "fwd":
                motor.forward()
                controller.set_speed(motor_name, current_speed)
                print(f"  {motor_name} forward.")
            elif action == "rev":
                motor.reverse()
                controller.set_speed(motor_name, current_speed)
                print(f"  {motor_name} reverse.")
            elif action == "stop":
                motor.coast()
                print(f"  {motor_name} stopped.")
            elif action == "brake":
                motor.brake()
                print(f"  {motor_name} braking.")
            else:
                print(f"Unknown action '{action}'. Use: fwd, rev, stop, brake")
            continue

        print(f"Unknown command: '{cmd}'. Type 'help' for usage.")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    controller = MotorController()
    atexit.register(controller.cleanup)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    try:
        controller.setup()
        interactive_loop(controller)
    finally:
        controller.cleanup()


if __name__ == "__main__":
    main()
