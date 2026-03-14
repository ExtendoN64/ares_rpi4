#!/usr/bin/env python3
"""
controller_test.py — Bluetooth Gamepad Control for ARES RPi4.

Controls mecanum motors and servos via any Linux-compatible Bluetooth
gamepad (PS4, Xbox, 8BitDo, generic HID) using the evdev input subsystem.

Control scheme:
  Left stick Y      Forward / reverse throttle
  Left stick X      Strafe left / right (mecanum, ALL mode)
  Right stick X     Rotation / yaw (mecanum, ALL mode)
  Right stick Y     Servo angle (selected servo)
  A / Cross         Emergency stop (coast all motors)
  Y / Triangle      Toggle ALL vs individual wheel mode
  B / Circle        Next wheel
  L1                Previous wheel
  X / Square        Next servo
  R1                Previous servo

Hardware note:
  LF + RF share speed pin (GPIO 12), LR + RR share speed pin (GPIO 13).
  In mecanum mixing mode, each chip's speed is set to max(abs(pair)).
  Individual per-motor speed granularity is limited by this hardware design.

Prerequisites:
    pip install evdev
    sudo pigpiod                 # For encoder feedback (optional)

Usage:
    python3 controller_test.py
"""

import sys
import os
import time
import signal
import select
import atexit

try:
    import evdev
    from evdev import InputDevice, ecodes
except ImportError:
    print("ERROR: evdev not installed. Run: pip install evdev")
    sys.exit(1)

import config
from motor_test import MotorController
from servo_test import ServoCalibrator


# ─── Defaults (overridable via config.py) ──────────────────────────────────

DEADZONE = getattr(config, "GAMEPAD_DEADZONE", 0.15)
UPDATE_HZ = getattr(config, "GAMEPAD_UPDATE_HZ", 20)


# ─── GamepadController ────────────────────────────────────────────────────

class GamepadController:
    """Translates gamepad input into motor and servo commands."""

    def __init__(self, motor_ctrl, servo_cal):
        self.motor_ctrl = motor_ctrl
        self.servo_cal = servo_cal
        self.device = None

        # Selection state
        self.wheel_names = ["LF", "RF", "LR", "RR"]
        self.servo_channels = sorted(servo_cal.servos.keys())
        self.wheel_mode = "all"     # "all" or "individual"
        self.wheel_index = 0
        self.servo_index = 0

        # Stick state (normalized -1.0 to 1.0)
        self.left_x = 0.0
        self.left_y = 0.0
        self.right_x = 0.0
        self.right_y = 0.0

        # Axis calibration (populated from device absinfo)
        self._axis_info = {}  # code -> (min, max)

        self._running = False

    # ─── Device Discovery ──────────────────────────────────────────────

    def find_gamepad(self):
        """Scan /dev/input/event* for a device with analog sticks.

        Returns True if a gamepad was found and opened.
        """
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        except PermissionError:
            print("ERROR: Permission denied reading input devices.")
            print("  Fix: sudo usermod -aG input $USER  (then log out/in)")
            return False

        gamepads = []
        for dev in devices:
            caps = dev.capabilities()
            if ecodes.EV_ABS in caps:
                gamepads.append(dev)

        if not gamepads:
            return False

        if len(gamepads) == 1:
            self.device = gamepads[0]
        else:
            print("Multiple gamepads found:")
            for i, gp in enumerate(gamepads):
                print(f"  {i}: {gp.name} ({gp.path})")
            # Use first by default
            self.device = gamepads[0]

        # Read axis ranges from absinfo for proper normalization
        caps = self.device.capabilities(absinfo=True)
        if ecodes.EV_ABS in caps:
            for code, absinfo in caps[ecodes.EV_ABS]:
                self._axis_info[code] = (absinfo.min, absinfo.max)

        print(f"Gamepad: {self.device.name}")
        print(f"  Path: {self.device.path}")
        return True

    def list_devices(self):
        """List all input devices for troubleshooting."""
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        except PermissionError:
            print("Permission denied. Run: sudo usermod -aG input $USER")
            return

        if not devices:
            print("No input devices found. Check:")
            print("  1. Is the gamepad paired? (bluetoothctl)")
            print("  2. Is the user in the 'input' group?")
            print("     sudo usermod -aG input $USER")
            return

        print("Available input devices:")
        for dev in devices:
            caps = dev.capabilities()
            has_abs = ecodes.EV_ABS in caps
            has_key = ecodes.EV_KEY in caps
            flags = []
            if has_abs:
                flags.append("axes")
            if has_key:
                flags.append("buttons")
            print(f"  {dev.path}: {dev.name} [{', '.join(flags)}]")

    # ─── Axis Normalization ────────────────────────────────────────────

    def _normalize_axis(self, code, value):
        """Normalize an axis value to -1.0..1.0 using device-reported range."""
        if code in self._axis_info:
            lo, hi = self._axis_info[code]
            if hi == lo:
                return 0.0
            # Map [lo, hi] to [-1.0, 1.0]
            return (2.0 * (value - lo) / (hi - lo)) - 1.0
        # Fallback: assume signed 16-bit
        return value / 32767.0

    def _apply_deadzone(self, value):
        """Apply deadzone — values within the zone become 0."""
        if abs(value) < DEADZONE:
            return 0.0
        # Rescale so output starts from 0 at the edge of the deadzone
        sign = 1.0 if value > 0 else -1.0
        return sign * (abs(value) - DEADZONE) / (1.0 - DEADZONE)

    # ─── Event Processing ──────────────────────────────────────────────

    def _process_event(self, event):
        """Handle a single evdev input event."""
        if event.type == ecodes.EV_ABS:
            norm = self._normalize_axis(event.code, event.value)
            if event.code == ecodes.ABS_X:
                self.left_x = self._apply_deadzone(norm)
            elif event.code == ecodes.ABS_Y:
                self.left_y = self._apply_deadzone(-norm)  # Invert: stick up = positive
            elif event.code == ecodes.ABS_RX:
                self.right_x = self._apply_deadzone(norm)
            elif event.code == ecodes.ABS_RY:
                self.right_y = self._apply_deadzone(-norm)

        elif event.type == ecodes.EV_KEY and event.value == 1:  # Key down only
            if event.code == ecodes.BTN_SOUTH:      # A / Cross
                self._emergency_stop()
            elif event.code == ecodes.BTN_NORTH:     # Y / Triangle
                self._toggle_wheel_mode()
            elif event.code == ecodes.BTN_EAST:      # B / Circle
                self._cycle_wheel(1)
            elif event.code == ecodes.BTN_TL:        # L1
                self._cycle_wheel(-1)
            elif event.code == ecodes.BTN_WEST:      # X / Square
                self._cycle_servo(1)
            elif event.code == ecodes.BTN_TR:        # R1
                self._cycle_servo(-1)

    # ─── Motor Control ─────────────────────────────────────────────────

    def _update_motors(self):
        """Apply stick input to motors."""
        throttle = self.left_y
        strafe = self.left_x
        rotation = self.right_x

        if self.wheel_mode == "all":
            # Mecanum drive mixing
            speeds = {
                "LF": throttle + strafe + rotation,
                "RF": throttle - strafe - rotation,
                "LR": throttle - strafe + rotation,
                "RR": throttle + strafe - rotation,
            }

            # Normalize if any exceeds 1.0
            max_val = max(abs(v) for v in speeds.values())
            if max_val > 1.0:
                speeds = {k: v / max_val for k, v in speeds.items()}

            # Group by DRV8833 chip and set each chip's speed to max of its pair
            chip1_duty = int(max(abs(speeds["LF"]), abs(speeds["RF"])) * 100)
            chip2_duty = int(max(abs(speeds["LR"]), abs(speeds["RR"])) * 100)

            for name, power in speeds.items():
                motor = self.motor_ctrl.motors[name]
                if abs(power) < 0.01:
                    motor.coast()
                elif power > 0:
                    motor.forward()
                else:
                    motor.reverse()

            # Set chip speeds (LF/RF share, LR/RR share)
            self.motor_ctrl.set_speed("LF", chip1_duty)
            self.motor_ctrl.set_speed("LR", chip2_duty)
        else:
            # Individual wheel mode: throttle controls selected wheel only
            name = self.wheel_names[self.wheel_index]
            motor = self.motor_ctrl.motors[name]
            power = throttle
            duty = int(abs(power) * 100)

            if abs(power) < 0.01:
                motor.coast()
                self.motor_ctrl.set_speed(name, 0)
            elif power > 0:
                motor.forward()
                self.motor_ctrl.set_speed(name, duty)
            else:
                motor.reverse()
                self.motor_ctrl.set_speed(name, duty)

    # ─── Servo Control ─────────────────────────────────────────────────

    def _update_servos(self):
        """Map right stick Y to servo angle on the selected servo."""
        if abs(self.right_y) < 0.01:
            return  # No stick input, don't move

        ch = self.servo_channels[self.servo_index]
        info = self.servo_cal.servos[ch]

        # Map stick (-1 to 1) to servo range [min, max]
        angle = ((self.right_y + 1.0) / 2.0) * (info["max"] - info["min"]) + info["min"]
        self.servo_cal.set_angle(ch, int(angle))

    # ─── Selection Cycling ─────────────────────────────────────────────

    def _toggle_wheel_mode(self):
        if self.wheel_mode == "all":
            self.wheel_mode = "individual"
            # Stop all motors when switching to individual
            self.motor_ctrl.stop_all()
        else:
            self.wheel_mode = "all"
        self._print_mode_change()

    def _cycle_wheel(self, direction):
        self.wheel_index = (self.wheel_index + direction) % len(self.wheel_names)
        if self.wheel_mode == "individual":
            # Stop the previously-selected motor when cycling
            self.motor_ctrl.stop_all()
        self._print_mode_change()

    def _cycle_servo(self, direction):
        self.servo_index = (self.servo_index + direction) % len(self.servo_channels)
        ch = self.servo_channels[self.servo_index]
        name = self.servo_cal.servos[ch]["name"]
        print(f"\r  Servo -> {name} (ch{ch})" + " " * 40)

    def _emergency_stop(self):
        self.motor_ctrl.stop_all()
        self.left_x = 0.0
        self.left_y = 0.0
        self.right_x = 0.0
        print(f"\r  !! EMERGENCY STOP !!" + " " * 40)

    def _print_mode_change(self):
        wheel_sel = "ALL" if self.wheel_mode == "all" else self.wheel_names[self.wheel_index]
        print(f"\r  Wheel -> {wheel_sel}" + " " * 40)

    # ─── Status Display ────────────────────────────────────────────────

    def _print_status(self):
        """Single-line live status (overwrites with \\r)."""
        wheel_sel = "ALL" if self.wheel_mode == "all" else self.wheel_names[self.wheel_index]
        ch = self.servo_channels[self.servo_index]
        servo_info = self.servo_cal.servos[ch]
        servo_angle = servo_info["angle"]
        angle_str = f"{servo_angle}" if servo_angle is not None else "?"

        line = (f"W:{wheel_sel} S:{servo_info['name']}={angle_str}deg "
                f"L:({self.left_x:+.1f},{self.left_y:+.1f}) "
                f"R:({self.right_x:+.1f},{self.right_y:+.1f})")
        print(f"\r{line:<72}", end="", flush=True)

    # ─── Main Loop ─────────────────────────────────────────────────────

    def run(self):
        """Main control loop — reads gamepad events, updates outputs."""
        self._running = True
        update_interval = 1.0 / UPDATE_HZ
        status_interval = 0.5
        last_update = 0.0
        last_status = 0.0

        print("\nControls:")
        print("  L-stick: drive  |  R-stick Y: servo  |  R-stick X: rotate")
        print("  A: E-stop  Y: toggle all/individual  B/L1: wheel  X/R1: servo")
        print("  Ctrl+C to quit\n")
        self._print_status()

        try:
            while self._running:
                # Non-blocking read with 20ms timeout
                r, _, _ = select.select([self.device.fd], [], [], 0.02)
                if r:
                    for event in self.device.read():
                        self._process_event(event)

                now = time.monotonic()
                if now - last_update >= update_interval:
                    self._update_motors()
                    self._update_servos()
                    last_update = now
                if now - last_status >= status_interval:
                    self._print_status()
                    last_status = now

        except KeyboardInterrupt:
            print("\n\nCtrl+C received.")
        finally:
            self._emergency_stop()

    # ─── Cleanup ───────────────────────────────────────────────────────

    def cleanup(self):
        """Release the gamepad device."""
        self._running = False
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  ARES RPi4 — Bluetooth Gamepad Controller")
    print("=" * 56)

    # Initialize hardware
    motor_ctrl = MotorController()
    servo_cal = ServoCalibrator()

    try:
        motor_ctrl.setup()
    except Exception as e:
        print(f"Motor init failed: {e}")
        return

    try:
        servo_cal.setup()
    except SystemExit:
        print("Servo init failed. Continuing with motors only.")
        servo_cal = None

    atexit.register(motor_ctrl.cleanup)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    if servo_cal is None:
        # Create a minimal stub so GamepadController doesn't crash
        print("WARNING: Servos unavailable. Servo controls disabled.")
        servo_cal = ServoCalibrator()
        servo_cal.servos = {}
        servo_cal._initialized = False

    gc = GamepadController(motor_ctrl, servo_cal)

    if not gc.find_gamepad():
        print("\nNo gamepad found.")
        gc.list_devices()
        print("\nBluetooth pairing:")
        print("  sudo bluetoothctl")
        print("  agent on && default-agent")
        print("  scan on")
        print("  pair <MAC> && connect <MAC> && trust <MAC>")
        print("\nThen re-run this script.")
        motor_ctrl.cleanup()
        if servo_cal._initialized:
            servo_cal.release_all()
        return

    try:
        gc.run()
    finally:
        gc.cleanup()
        motor_ctrl.cleanup()
        if servo_cal._initialized:
            servo_cal.release_all()


if __name__ == "__main__":
    main()
