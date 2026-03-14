#!/usr/bin/env python3
"""
servo_test.py — Interactive Servo Calibration for OSOYOO PWM HAT v2.0.

Controls servos via the PCA9685 16-channel PWM controller over I2C.
Use this to manually position each servo, find its min/max angles,
and verify correct channel assignments.

Usage:
    python3 servo_test.py
"""

import sys
import time
import config

try:
    from adafruit_servokit import ServoKit
except ImportError:
    print("ERROR: adafruit-circuitpython-servokit not installed.")
    print("  Run: pip install adafruit-circuitpython-servokit")
    sys.exit(1)


class ServoCalibrator:
    """Manages servo calibration state and PCA9685 control."""

    def __init__(self):
        self.kit = None
        self.servos = {}  # channel -> {name, angle, min, max}
        self._initialized = False

    def setup(self):
        """Initialize the PCA9685 and register configured servos."""
        try:
            self.kit = ServoKit(
                channels=config.SERVO_CHANNELS,
                address=config.PCA9685_ADDRESS,
            )
        except Exception as e:
            print(f"ERROR: Could not initialize PCA9685 at 0x{config.PCA9685_ADDRESS:02X}.")
            print(f"  {e}")
            print("  Check: Is the OSOYOO HAT connected? Is I2C enabled?")
            sys.exit(1)

        for name, channel in config.SERVO_MAP.items():
            self.servos[channel] = {
                "name": name,
                "angle": None,    # Unknown until first move
                "min": config.SERVO_MIN_ANGLE,
                "max": config.SERVO_MAX_ANGLE,
            }

        self._initialized = True
        print(f"Servo controller initialized (PCA9685 at 0x{config.PCA9685_ADDRESS:02X}).")
        print(f"  Configured servos: {len(self.servos)}")
        for ch, info in sorted(self.servos.items()):
            print(f"    Channel {ch}: {info['name']}")

    def set_angle(self, channel, angle):
        """Move a servo to a specific angle.

        Args:
            channel: PCA9685 channel number.
            angle: Target angle in degrees.

        Returns:
            True if successful, False otherwise.
        """
        info = self.servos.get(channel)
        if info is None:
            print(f"Channel {channel} is not configured.")
            return False

        angle = max(0, min(180, angle))

        if angle < info["min"] or angle > info["max"]:
            print(f"  WARNING: {angle}° is outside calibrated range "
                  f"[{info['min']}°-{info['max']}°] (moving anyway).")

        try:
            self.kit.servo[channel].angle = angle
            info["angle"] = angle
            return True
        except Exception as e:
            print(f"  ERROR setting angle: {e}")
            return False

    def nudge(self, channel, delta):
        """Adjust the current angle by delta degrees."""
        info = self.servos.get(channel)
        if info is None or info["angle"] is None:
            print("  Servo not positioned yet. Use 'angle <deg>' or 'center' first.")
            return False

        new_angle = info["angle"] + delta
        return self.set_angle(channel, new_angle)

    def center(self, channel):
        """Move a servo to the default center position."""
        return self.set_angle(channel, config.SERVO_DEFAULT_ANGLE)

    def sweep(self, channel, step=5, delay=0.05):
        """Sweep a servo through its calibrated range and back.

        Args:
            channel: PCA9685 channel.
            step: Degrees per step.
            delay: Seconds between steps.
        """
        info = self.servos.get(channel)
        if info is None:
            return

        lo = info["min"]
        hi = info["max"]
        print(f"  Sweeping {info['name']} (ch{channel}): {lo}° → {hi}° → {lo}°")

        # Forward sweep
        angle = lo
        while angle <= hi:
            self.kit.servo[channel].angle = angle
            info["angle"] = angle
            time.sleep(delay)
            angle += step

        # Make sure we hit the max
        self.kit.servo[channel].angle = hi
        info["angle"] = hi
        time.sleep(delay)

        # Return sweep
        angle = hi - step
        while angle >= lo:
            self.kit.servo[channel].angle = angle
            info["angle"] = angle
            time.sleep(delay)
            angle -= step

        # Make sure we hit the min
        self.kit.servo[channel].angle = lo
        info["angle"] = lo
        print("  Sweep complete.")

    def set_min_limit(self, channel):
        """Record the current position as the minimum limit."""
        info = self.servos.get(channel)
        if info is None or info["angle"] is None:
            print("  Servo not positioned yet.")
            return
        info["min"] = info["angle"]
        print(f"  Min limit set to {info['min']}°")

    def set_max_limit(self, channel):
        """Record the current position as the maximum limit."""
        info = self.servos.get(channel)
        if info is None or info["angle"] is None:
            print("  Servo not positioned yet.")
            return
        info["max"] = info["angle"]
        print(f"  Max limit set to {info['max']}°")

    def get_info(self, channel):
        """Print the current state of a servo."""
        info = self.servos.get(channel)
        if info is None:
            print(f"  Channel {channel} is not configured.")
            return

        angle_str = f"{info['angle']}°" if info["angle"] is not None else "unknown"
        print(f"  {info['name']} (channel {channel}):")
        print(f"    Current angle:  {angle_str}")
        print(f"    Min limit:      {info['min']}°")
        print(f"    Max limit:      {info['max']}°")
        print(f"    Range:          {info['max'] - info['min']}°")

    def auto_test(self, step=5, delay=0.05):
        """Run automatic test: center each servo, then sweep."""
        print("\n--- Auto Test: Center + Sweep all servos ---")
        for ch in sorted(self.servos.keys()):
            info = self.servos[ch]
            print(f"\n  Testing {info['name']} (channel {ch})...")
            self.center(ch)
            time.sleep(0.5)
            self.sweep(ch, step=step, delay=delay)
            time.sleep(0.5)
        print("\n--- Auto test complete. ---\n")

    def release(self, channel):
        """Release a servo (stop sending PWM signal)."""
        try:
            self.kit.servo[channel].angle = None
            self.servos[channel]["angle"] = None
            print(f"  Servo on channel {channel} released.")
        except Exception as e:
            print(f"  ERROR releasing servo: {e}")

    def release_all(self):
        """Release all configured servos."""
        for ch in self.servos:
            try:
                self.kit.servo[ch].angle = None
            except Exception:
                pass
        print("All servos released.")


# ─── Interactive Console ────────────────────────────────────────────────────

SERVO_HELP = """
Commands:
  n / p            Next / previous servo
  select <n>       Select servo by channel number (0-3)
  angle <degrees>  Set angle (0-180)
  center           Move to center (90°)
  min / max        Move to min / max limit
  +<n> / -<n>      Nudge by N degrees (e.g., +5, -1)
  sweep            Sweep through calibrated range
  setmin / setmax  Save current position as limit
  release          Stop sending signal to current servo
  info             Show current servo state
  test             Auto-test all servos (center + sweep)
  list             List all configured servos
  help             Show this help
  quit / exit      Release servos and exit
"""


def interactive_loop(calibrator):
    """Run the interactive servo calibration console."""
    channels = sorted(calibrator.servos.keys())
    if not channels:
        print("No servos configured. Check config.py SERVO_MAP.")
        return

    ch_index = 0
    active_ch = channels[ch_index]

    print("\n" + "=" * 50)
    print("  ARES RPi4 — Servo Calibration")
    print("=" * 50)
    print(SERVO_HELP)

    while True:
        info = calibrator.servos[active_ch]
        angle_str = f"{info['angle']}°" if info["angle"] is not None else "?"

        try:
            cmd = input(f"{info['name']} ch{active_ch} {angle_str} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not cmd:
            continue

        if cmd in ("quit", "exit"):
            break

        if cmd == "help":
            print(SERVO_HELP)
            continue

        # Toggle cycling
        if cmd == "n":
            ch_index = (ch_index + 1) % len(channels)
            active_ch = channels[ch_index]
            print(f"  -> {calibrator.servos[active_ch]['name']} (ch{active_ch})")
            continue
        if cmd == "p":
            ch_index = (ch_index - 1) % len(channels)
            active_ch = channels[ch_index]
            print(f"  -> {calibrator.servos[active_ch]['name']} (ch{active_ch})")
            continue

        if cmd == "list":
            for ch in channels:
                calibrator.get_info(ch)
            continue

        if cmd == "test":
            calibrator.auto_test()
            continue

        if cmd == "info":
            calibrator.get_info(active_ch)
            continue

        if cmd == "center":
            calibrator.center(active_ch)
            print(f"  -> {config.SERVO_DEFAULT_ANGLE}°")
            continue

        if cmd == "min":
            calibrator.set_angle(active_ch, info["min"])
            print(f"  -> {info['min']}°")
            continue
        if cmd == "max":
            calibrator.set_angle(active_ch, info["max"])
            print(f"  -> {info['max']}°")
            continue

        if cmd == "setmin":
            calibrator.set_min_limit(active_ch)
            continue
        if cmd == "setmax":
            calibrator.set_max_limit(active_ch)
            continue

        if cmd == "sweep":
            calibrator.sweep(active_ch)
            continue

        if cmd == "release":
            calibrator.release(active_ch)
            continue

        # Nudge: +N or -N
        if cmd.startswith("+") or cmd.startswith("-"):
            try:
                delta = int(cmd)
                if calibrator.nudge(active_ch, delta):
                    print(f"  -> {calibrator.servos[active_ch]['angle']}°")
            except ValueError:
                print("  Usage: +<degrees> or -<degrees>  (e.g., +5, -1)")
            continue

        parts = cmd.split()

        # select <channel>
        if parts[0] == "select" and len(parts) >= 2:
            try:
                ch = int(parts[1])
                if ch in calibrator.servos:
                    ch_index = channels.index(ch)
                    active_ch = ch
                    print(f"  -> {calibrator.servos[ch]['name']} (ch{ch})")
                else:
                    print(f"  Channel {ch} not configured. Available: {channels}")
            except ValueError:
                print("  Usage: select <channel_number>")
            continue

        # angle <degrees>
        if parts[0] == "angle" and len(parts) >= 2:
            try:
                deg = float(parts[1])
                if calibrator.set_angle(active_ch, deg):
                    print(f"  -> {calibrator.servos[active_ch]['angle']}°")
            except ValueError:
                print("  Usage: angle <degrees>  (0-180)")
            continue

        print(f"  Unknown command: '{cmd}'. Type 'help' for usage.")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    calibrator = ServoCalibrator()
    try:
        calibrator.setup()
        interactive_loop(calibrator)
    finally:
        calibrator.release_all()


if __name__ == "__main__":
    main()
