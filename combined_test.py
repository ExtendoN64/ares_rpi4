#!/usr/bin/env python3
"""
combined_test.py — Combined Test Suite for ARES RPi4 Dual-HAT Configuration.

Menu-driven serial console that integrates:
  - I2C bus scanning       (i2c_scanner.py)
  - GPIO connectivity check (i2c_scanner.py)
  - Motor testing + encoder feedback (motor_test.py)
  - Servo calibration       (servo_test.py)

Hardware:
  - OSOYOO PWM HAT v2.0   — PCA9685 servo controller (I2C 0x40)
  - Cokoino Pi Power & 4WD — DRV8833 motor drivers    (GPIO)
  - 4x CQR37D 70:1 motors — 64 CPR quadrature encoders (GPIO via pigpio)

Usage:
    sudo pigpiod                 # Start pigpio daemon (for encoders)
    python3 combined_test.py

SSH Setup (Windows → Raspberry Pi):
  1. Enable SSH on Pi:      sudo raspi-config → Interface Options → SSH → Enable
  2. Enable I2C on Pi:      sudo raspi-config → Interface Options → I2C → Enable
  3. Find Pi IP address:    Run 'hostname -I' on the Pi, or check your router's
                            DHCP client list, or try: ping raspberrypi.local
  4. Connect from Windows:  Open PowerShell or Windows Terminal and run:
                              ssh pi@<ip-address>
                            Or use PuTTY (putty.org): Host = Pi IP, Port = 22
  5. Install dependencies:  cd ~/ares_rpi4 && pip install -r requirements.txt
  6. Start pigpio daemon:   sudo pigpiod
  7. Run this script:       python3 combined_test.py
"""

import sys
import time
import config
import i2c_scanner
from motor_test import MotorController
from servo_test import ServoCalibrator


# ─── pigpiod check ─────────────────────────────────────────────────────────

def check_pigpiod():
    """Check if the pigpio daemon is running. Print a warning if not."""
    try:
        import pigpio
        pi = pigpio.pi()
        if pi.connected:
            pi.stop()
            return True
        else:
            pi.stop()
            return False
    except Exception:
        return False


# ─── Banner & Menu ──────────────────────────────────────────────────────────

BANNER = """
╔══════════════════════════════════════════════════════╗
║          ARES RPi4 — Combined Test Suite             ║
║  OSOYOO PWM HAT v2.0  +  Cokoino Pi Power & 4WD HAT ║
║  Motors: 4x CQR37D 70:1 w/ 64 CPR encoders          ║
╚══════════════════════════════════════════════════════╝
"""

MENU = """
  1. I2C Bus Scan
  2. GPIO Pin Check (Motor + Encoder pins)
  3. Motor Test (Interactive, with encoder feedback)
  4. Servo Test (Interactive)
  5. Quick System Check (auto scan + brief test)
  6. Help / Hardware Info
  7. Gamepad Controller (Bluetooth)
  0. Exit
"""

HARDWARE_INFO = """
─── Hardware Overview ────────────────────────────────────

OSOYOO PWM HAT v2.0 (Servo Controller):
  Chip:         PCA9685 16-channel PWM controller
  Interface:    I2C (address 0x{pca_addr:02X})
  Pins used:    GPIO 2 (SDA), GPIO 3 (SCL)
  Servo freq:   {servo_freq} Hz
  Power:        6-18V DC via screw terminal
  Channels:     {servo_count} servos configured (of 16 available)

Cokoino Pi Power & 4WD HAT (Motor Controller):
  Chips:        2x DRV8833 dual H-bridge motor drivers
  Interface:    GPIO (direct pin control + NSLEEP PWM)
  Speed pins:   GPIO 12 (chip #1), GPIO 13 (chip #2) — hardware PWM
  Power:        Battery via HAT power input

CQR37D Motors (70:1 geared DC with encoder):
  Voltage:      {motor_v}V
  No-load RPM:  {motor_rpm} RPM (output shaft)
  Stall current:{motor_stall}A  ⚠️  Exceeds DRV8833 1.5A limit!
  Encoder:      {enc_cpr} CPR motor shaft = {eff_cpr} counts/rev output
  Encoder VCC:  3.3V (from Pi header)

─── Motor + Encoder Pin Map ──────────────────────────────

  Motor │ IN1  │ IN2  │ NSLEEP │ Enc A │ Enc B │ DRV8833
  ──────┼──────┼──────┼────────┼───────┼───────┼────────
  LF    │ {LF_in1:>4} │ {LF_in2:>4} │ {LF_ns:>6} │ {LF_ea:>5} │ {LF_eb:>5} │ Chip #1
  RF    │ {RF_in1:>4} │ {RF_in2:>4} │ {RF_ns:>6} │ {RF_ea:>5} │ {RF_eb:>5} │ Chip #1
  LR    │ {LR_in1:>4} │ {LR_in2:>4} │ {LR_ns:>6} │ {LR_ea:>5} │ {LR_eb:>5} │ Chip #2
  RR    │ {RR_in1:>4} │ {RR_in2:>4} │ {RR_ns:>6} │ {RR_ea:>5} │ {RR_eb:>5} │ Chip #2

  Servo channels: {servo_chs}

─── Encoder Wiring (CQR37D → Pi GPIO header) ────────────

  Wire Color │ Function    │ Connect To
  ───────────┼─────────────┼─────────────────────────────
  Red        │ Motor +     │ Cokoino HAT motor terminal
  Black      │ Motor -     │ Cokoino HAT motor terminal
  Gray       │ Encoder GND │ Pi GND pin (any)
  Blue       │ Encoder VCC │ Pi 3.3V pin (pin 1 or 17)
  Yellow     │ Encoder A   │ Assigned GPIO (see table)
  White      │ Encoder B   │ Assigned GPIO (see table)

  Note: Use a common bus for 3.3V and GND across all 4 encoders.

─── SSH Quick Reference ──────────────────────────────────

  From Windows PowerShell / Terminal:
    ssh pi@<raspberry-pi-ip-address>

  Find the Pi's IP (run on the Pi):
    hostname -I

  Enable SSH (run on the Pi):
    sudo raspi-config → Interface Options → SSH → Enable

  Start pigpio daemon (required for encoders):
    sudo pigpiod
    sudo systemctl enable pigpiod   # auto-start on boot

──────────────────────────────────────────────────────────
"""


def print_banner():
    print(BANNER)
    # Check pigpiod status
    if not check_pigpiod():
        print("  ⚠️  pigpiod not running — encoder feedback will be disabled.")
        print("     Start it with: sudo pigpiod")
        print()


def print_menu():
    print(MENU)


def print_help():
    m = config.MOTOR_MAP
    servo_chs = ", ".join(
        f"{name}=ch{ch}" for name, ch in sorted(config.SERVO_MAP.items())
    )
    print(HARDWARE_INFO.format(
        pca_addr=config.PCA9685_ADDRESS,
        servo_freq=config.SERVO_FREQUENCY,
        servo_count=len(config.SERVO_MAP),
        motor_v=config.MOTOR_VOLTAGE,
        motor_rpm=config.MOTOR_NOLOAD_RPM,
        motor_stall=config.MOTOR_STALL_CURRENT,
        enc_cpr=config.ENCODER_CPR,
        eff_cpr=config.EFFECTIVE_CPR,
        LF_in1=m["LF"]["in1"], LF_in2=m["LF"]["in2"], LF_ns=m["LF"]["nsleep"],
        LF_ea=m["LF"]["enc_a"], LF_eb=m["LF"]["enc_b"],
        RF_in1=m["RF"]["in1"], RF_in2=m["RF"]["in2"], RF_ns=m["RF"]["nsleep"],
        RF_ea=m["RF"]["enc_a"], RF_eb=m["RF"]["enc_b"],
        LR_in1=m["LR"]["in1"], LR_in2=m["LR"]["in2"], LR_ns=m["LR"]["nsleep"],
        LR_ea=m["LR"]["enc_a"], LR_eb=m["LR"]["enc_b"],
        RR_in1=m["RR"]["in1"], RR_in2=m["RR"]["in2"], RR_ns=m["RR"]["nsleep"],
        RR_ea=m["RR"]["enc_a"], RR_eb=m["RR"]["enc_b"],
        servo_chs=servo_chs,
    ))


# ─── Menu Actions ───────────────────────────────────────────────────────────

def run_i2c_scan():
    print("\n" + "─" * 50)
    print("I2C Bus Scan")
    print("─" * 50)
    found = i2c_scanner.scan_i2c_bus()
    i2c_scanner.print_i2c_grid(found)

    if found:
        print(f"\nDetected {len(found)} device(s):")
        for addr in found:
            name = i2c_scanner.identify_device(addr)
            print(f"  0x{addr:02X} — {name}")

        if config.PCA9685_ADDRESS in found:
            info = i2c_scanner.validate_pca9685()
            if info:
                print(f"\n  PCA9685 validated: PRE_SCALE={info['prescale']} "
                      f"({info['frequency_hz']} Hz), "
                      f"sleep={'yes' if info['sleep'] else 'no'}")
    else:
        print("\nNo I2C devices found. Is the OSOYOO HAT connected?")


def run_gpio_check():
    print("\n" + "─" * 50)
    print("Motor & Encoder GPIO Pin Check")
    print("─" * 50)
    results = i2c_scanner.check_gpio_pins()
    i2c_scanner.print_gpio_results(results)


def run_motor_test():
    print("\nStarting Motor Test (type 'quit' to return to main menu)...")
    controller = MotorController()
    try:
        controller.setup()
        from motor_test import interactive_loop
        interactive_loop(controller)
    finally:
        controller.cleanup()
    print("\nReturned to main menu.\n")


def run_servo_test():
    print("\nStarting Servo Test (type 'quit' to return to main menu)...")
    calibrator = ServoCalibrator()
    try:
        calibrator.setup()
        from servo_test import interactive_loop
        interactive_loop(calibrator)
    finally:
        calibrator.release_all()
    print("\nReturned to main menu.\n")


def run_controller_test():
    print("\nStarting Gamepad Controller (press Ctrl+C to return)...")
    try:
        from controller_test import GamepadController
    except ImportError as e:
        print(f"  ERROR: {e}")
        print("  Install evdev: pip install evdev")
        return

    motor_ctrl = MotorController()
    servo_cal = ServoCalibrator()
    try:
        motor_ctrl.setup()
        servo_cal.setup()

        gc = GamepadController(motor_ctrl, servo_cal)
        if not gc.find_gamepad():
            print("\n  No gamepad found.")
            gc.list_devices()
            print("\n  Pair a Bluetooth gamepad and try again.")
        else:
            gc.run()
            gc.cleanup()
    except SystemExit:
        pass
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        motor_ctrl.cleanup()
        servo_cal.release_all()
    print("\nReturned to main menu.\n")


def run_quick_check():
    """Automated system check: scan I2C, check GPIO, brief motor/servo test."""
    print("\n" + "=" * 50)
    print("  Quick System Check")
    print("=" * 50)

    # Step 1: I2C Scan
    print("\n[1/4] Scanning I2C bus...")
    found = i2c_scanner.scan_i2c_bus()
    i2c_ok = config.PCA9685_ADDRESS in found
    print(f"  Servo HAT (PCA9685 @ 0x{config.PCA9685_ADDRESS:02X}): "
          f"{'FOUND' if i2c_ok else 'NOT FOUND'}")

    # Step 2: GPIO Check (motor + encoder pins)
    print("\n[2/4] Checking motor & encoder GPIO pins...")
    gpio_results = i2c_scanner.check_gpio_pins()
    motor_pins_ok = all(
        gpio_results.get(p) is True for p in config.ALL_MOTOR_PINS
    ) if gpio_results else False
    encoder_pins_ok = all(
        gpio_results.get(p) is True for p in config.ALL_ENCODER_PINS
    ) if gpio_results else False
    motor_count = sum(1 for p in config.ALL_MOTOR_PINS if gpio_results.get(p) is True)
    enc_count = sum(1 for p in config.ALL_ENCODER_PINS if gpio_results.get(p) is True)
    print(f"  Motor GPIO:   {motor_count}/{len(config.ALL_MOTOR_PINS)} pins OK")
    print(f"  Encoder GPIO: {enc_count}/{len(config.ALL_ENCODER_PINS)} pins OK")

    # Step 3: Motor quick test (with encoder verification)
    motor_ok = False
    encoder_ok = False
    if motor_pins_ok:
        print("\n[3/4] Motor quick test...")
        resp = input("  Spin each motor briefly? Motors must be powered. (y/n) > ").strip().lower()
        if resp == "y":
            controller = MotorController()
            try:
                controller.setup()
                if controller._encoders_available:
                    controller.reset_encoders()

                for name in ["LF", "RF", "LR", "RR"]:
                    print(f"    {name} forward...", end="", flush=True)
                    controller.motors[name].forward()
                    controller.set_speed(name, config.MOTOR_SLOW_SPEED)
                    time.sleep(1.0)
                    rpm = controller.get_rpm(name)
                    count = controller.get_encoder_count(name)
                    controller.motors[name].coast()
                    controller.set_speed(name, 0)

                    rpm_str = f" RPM={rpm:+.1f}" if rpm is not None else ""
                    enc_str = f" enc={count}" if count is not None else ""
                    print(f" OK{rpm_str}{enc_str}")
                    time.sleep(0.3)

                motor_ok = True

                # Verify encoders produced counts
                if controller._encoders_available:
                    all_nonzero = all(
                        controller.get_encoder_count(n) != 0
                        for n in ["LF", "RF", "LR", "RR"]
                    )
                    encoder_ok = all_nonzero
                    if not all_nonzero:
                        print("    ⚠️  Some encoders read 0 — check wiring")
                    else:
                        print("    Encoder feedback verified on all 4 motors.")

            except Exception as e:
                print(f"    ERROR: {e}")
            finally:
                controller.cleanup()
        else:
            print("  Skipped motor test.")
    else:
        print("\n[3/4] Motor quick test — SKIPPED (GPIO check failed)")

    # Step 4: Servo quick test
    servo_ok = False
    if i2c_ok:
        print("\n[4/4] Servo quick test...")
        try:
            calibrator = ServoCalibrator()
            calibrator.setup()
            for ch in sorted(calibrator.servos.keys()):
                name = calibrator.servos[ch]["name"]
                print(f"    {name} (ch{ch}): center → 45° → 135° → center...", end="", flush=True)
                calibrator.set_angle(ch, 90)
                time.sleep(0.3)
                calibrator.set_angle(ch, 45)
                time.sleep(0.3)
                calibrator.set_angle(ch, 135)
                time.sleep(0.3)
                calibrator.set_angle(ch, 90)
                time.sleep(0.3)
                print(" OK")
            servo_ok = True
            calibrator.release_all()
        except Exception as e:
            print(f"    ERROR: {e}")
    else:
        print("\n[4/4] Servo quick test — SKIPPED (PCA9685 not found)")

    # Summary
    print("\n" + "─" * 50)
    print("Quick Check Summary:")
    print(f"  I2C Scan:      {'PASS' if i2c_ok else 'FAIL'}")
    print(f"  Motor GPIO:    {'PASS' if motor_pins_ok else 'FAIL' if gpio_results else 'N/A'}")
    print(f"  Encoder GPIO:  {'PASS' if encoder_pins_ok else 'FAIL' if gpio_results else 'N/A'}")
    print(f"  Motor Test:    {'PASS' if motor_ok else 'SKIPPED/FAIL'}")
    print(f"  Encoder Test:  {'PASS' if encoder_ok else 'SKIPPED/FAIL'}")
    print(f"  Servo Test:    {'PASS' if servo_ok else 'SKIPPED/FAIL'}")

    all_pass = i2c_ok and motor_pins_ok and encoder_pins_ok and motor_ok and servo_ok
    if all_pass:
        print("\n  All systems operational!")
    elif encoder_ok is False and motor_ok:
        print("\n  Core systems OK. Check encoder wiring for full functionality.")
    print("─" * 50 + "\n")


# ─── Main Loop ──────────────────────────────────────────────────────────────

def main():
    print_banner()

    while True:
        print_menu()
        try:
            choice = input("Select option > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if choice == "1":
            run_i2c_scan()
        elif choice == "2":
            run_gpio_check()
        elif choice == "3":
            run_motor_test()
        elif choice == "4":
            run_servo_test()
        elif choice == "5":
            run_quick_check()
        elif choice == "6":
            print_help()
        elif choice == "7":
            run_controller_test()
        elif choice == "0":
            print("Exiting. Goodbye.")
            break
        else:
            print("Invalid option. Enter 0-7.")

    sys.exit(0)


if __name__ == "__main__":
    main()
