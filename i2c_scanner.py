#!/usr/bin/env python3
"""
i2c_scanner.py — I2C Bus Scanner and GPIO Connectivity Check.

Detects I2C devices (OSOYOO PWM HAT / PCA9685) and verifies GPIO pin
accessibility for the Cokoino Motor HAT (which uses GPIO, not I2C).

Usage:
    python3 i2c_scanner.py
"""

import sys
import config

try:
    import smbus2
except ImportError:
    print("ERROR: smbus2 not installed. Run: pip install smbus2")
    sys.exit(1)

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None


# ─── I2C Scanning ───────────────────────────────────────────────────────────

def scan_i2c_bus(bus_number=None):
    """Scan the I2C bus and return a list of detected device addresses.

    Args:
        bus_number: I2C bus number (default: config.I2C_BUS).

    Returns:
        List of integer addresses found on the bus.
    """
    if bus_number is None:
        bus_number = config.I2C_BUS

    found = []
    try:
        bus = smbus2.SMBus(bus_number)
    except FileNotFoundError:
        print(f"ERROR: /dev/i2c-{bus_number} not found.")
        print("  Enable I2C: sudo raspi-config → Interface Options → I2C → Enable")
        return found
    except PermissionError:
        print(f"ERROR: Permission denied on /dev/i2c-{bus_number}.")
        print("  Run with sudo, or add your user to the i2c group:")
        print("    sudo usermod -aG i2c $USER  (then log out and back in)")
        return found

    for addr in range(0x03, 0x78):
        try:
            bus.read_byte(addr)
            found.append(addr)
        except OSError:
            pass

    bus.close()
    return found


def identify_device(address):
    """Return a human-readable name for a known I2C address."""
    return config.KNOWN_I2C_DEVICES.get(address, "Unknown device")


def validate_pca9685(bus_number=None, address=None):
    """Read PCA9685 registers to confirm its identity.

    Returns:
        dict with register values, or None if device is not accessible.
    """
    if bus_number is None:
        bus_number = config.I2C_BUS
    if address is None:
        address = config.PCA9685_ADDRESS

    try:
        bus = smbus2.SMBus(bus_number)
        mode1 = bus.read_byte_data(address, 0x00)       # MODE1 register
        mode2 = bus.read_byte_data(address, 0x01)       # MODE2 register
        prescale = bus.read_byte_data(address, 0xFE)     # PRE_SCALE register
        bus.close()

        # Calculate the PWM frequency from prescale value
        # Formula: frequency = 25MHz / (4096 * (prescale + 1))
        osc_clock = 25_000_000
        if prescale > 0:
            frequency = osc_clock / (4096 * (prescale + 1))
        else:
            frequency = 0

        return {
            "mode1": mode1,
            "mode2": mode2,
            "prescale": prescale,
            "frequency_hz": round(frequency, 1),
            "sleep": bool(mode1 & 0x10),
            "auto_increment": bool(mode1 & 0x20),
        }
    except OSError:
        return None


def print_i2c_grid(found_addresses):
    """Print an i2cdetect-style grid of detected devices."""
    print("\nI2C Bus Scan Results (/dev/i2c-{})".format(config.I2C_BUS))
    print("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f")
    for row in range(8):
        base = row * 16
        line = f"{base:02x}: "
        for col in range(16):
            addr = base + col
            if addr < 0x03 or addr > 0x77:
                line += "   "
            elif addr in found_addresses:
                line += f"{addr:02x} "
            else:
                line += "-- "
        print(line)


# ─── GPIO Connectivity Check ────────────────────────────────────────────────

def check_gpio_pins():
    """Test GPIO pin accessibility for all motor and encoder pins.

    Motor pins are tested as outputs, encoder pins as inputs.

    Returns:
        dict mapping pin number to True (accessible) or error string.
    """
    if GPIO is None:
        print("WARNING: RPi.GPIO not available (not running on Raspberry Pi?)")
        return {}

    results = {}
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Motor direction + NSLEEP pins → test as OUTPUT
    for pin in config.ALL_MOTOR_PINS:
        try:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            results[pin] = True
        except Exception as e:
            results[pin] = str(e)

    # Encoder pins → test as INPUT (pull-up, since encoders are open-collector)
    for pin in config.ALL_ENCODER_PINS:
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.input(pin)  # Read to verify access
            results[pin] = True
        except Exception as e:
            results[pin] = str(e)

    GPIO.cleanup()
    return results


def print_gpio_results(results):
    """Print a table of GPIO pin check results."""
    if not results:
        print("\nGPIO check skipped (RPi.GPIO not available).")
        return

    print("\nMotor & Encoder GPIO Pin Check:")
    print(f"  {'GPIO':>6}  {'Status':<10}  {'Function'}")
    print(f"  {'─'*6}  {'─'*10}  {'─'*40}")

    pin_functions = {
        config.MOTOR_NSLEEP1: "DRV8833 #1 NSLEEP (PWM speed for LF+RF)",
        config.MOTOR_A1_IN1:  "DRV8833 #1 Motor A IN1 (LF direction)",
        config.MOTOR_A1_IN2:  "DRV8833 #1 Motor A IN2 (LF direction)",
        config.MOTOR_B1_IN1:  "DRV8833 #1 Motor B IN1 (RF direction)",
        config.MOTOR_B1_IN2:  "DRV8833 #1 Motor B IN2 (RF direction)",
        config.MOTOR_NSLEEP2: "DRV8833 #2 NSLEEP (PWM speed for LR+RR)",
        config.MOTOR_A2_IN1:  "DRV8833 #2 Motor A IN1 (LR direction)",
        config.MOTOR_A2_IN2:  "DRV8833 #2 Motor A IN2 (LR direction)",
        config.MOTOR_B2_IN1:  "DRV8833 #2 Motor B IN1 (RR direction)",
        config.MOTOR_B2_IN2:  "DRV8833 #2 Motor B IN2 (RR direction)",
        config.ENCODER_LF_A:  "Encoder LF channel A (Yellow wire)",
        config.ENCODER_LF_B:  "Encoder LF channel B (White wire)",
        config.ENCODER_RF_A:  "Encoder RF channel A (Yellow wire)",
        config.ENCODER_RF_B:  "Encoder RF channel B (White wire)",
        config.ENCODER_LR_A:  "Encoder LR channel A (Yellow wire)",
        config.ENCODER_LR_B:  "Encoder LR channel B (White wire)",
        config.ENCODER_RR_A:  "Encoder RR channel A (Yellow wire)",
        config.ENCODER_RR_B:  "Encoder RR channel B (White wire)",
    }

    all_pins = config.ALL_MOTOR_PINS + config.ALL_ENCODER_PINS
    for pin in all_pins:
        status = results.get(pin)
        if status is True:
            status_str = "OK"
        else:
            status_str = f"FAIL: {status}"
        func = pin_functions.get(pin, "Unknown")
        print(f"  GPIO {pin:>2}  {status_str:<10}  {func}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  ARES RPi4 — I2C Scanner & GPIO Connectivity Check")
    print("=" * 56)

    # I2C scan
    print("\nScanning I2C bus {}...".format(config.I2C_BUS))
    found = scan_i2c_bus()
    print_i2c_grid(found)

    if found:
        print(f"\nDetected {len(found)} device(s):")
        for addr in found:
            name = identify_device(addr)
            print(f"  0x{addr:02X} — {name}")

        # Validate PCA9685 if found
        if config.PCA9685_ADDRESS in found:
            print(f"\nValidating PCA9685 at 0x{config.PCA9685_ADDRESS:02X}...")
            info = validate_pca9685()
            if info:
                print(f"  MODE1 register:  0x{info['mode1']:02X}")
                print(f"  MODE2 register:  0x{info['mode2']:02X}")
                print(f"  PRE_SCALE:       {info['prescale']} ({info['frequency_hz']} Hz)")
                print(f"  Sleep mode:      {'Yes' if info['sleep'] else 'No'}")
                print(f"  Auto-increment:  {'Yes' if info['auto_increment'] else 'No'}")
                print("  Status: PCA9685 confirmed and responding.")
            else:
                print("  WARNING: Could not read PCA9685 registers.")
    else:
        print("\nNo I2C devices found.")
        print("  Check: Is the OSOYOO PWM HAT connected?")
        print("  Check: Is I2C enabled? (sudo raspi-config → Interface Options → I2C)")

    # GPIO check
    print("\n" + "─" * 56)
    print("Checking motor & encoder GPIO pins...")
    results = check_gpio_pins()
    print_gpio_results(results)

    # Summary
    print("\n" + "─" * 56)
    i2c_ok = config.PCA9685_ADDRESS in found

    motor_pins_ok = all(
        results.get(p) is True for p in config.ALL_MOTOR_PINS
    ) if results else False
    encoder_pins_ok = all(
        results.get(p) is True for p in config.ALL_ENCODER_PINS
    ) if results else False

    print("Summary:")
    print(f"  Servo HAT (I2C):     {'DETECTED' if i2c_ok else 'NOT FOUND'}")
    print(f"  Motor HAT (GPIO):    {'ALL PINS OK' if motor_pins_ok else 'CHECK RESULTS ABOVE'}")
    print(f"  Encoders (GPIO):     {'ALL PINS OK' if encoder_pins_ok else 'CHECK RESULTS ABOVE'}")

    if i2c_ok and motor_pins_ok and encoder_pins_ok:
        print("\n  All systems ready. You can proceed with motor and servo tests.")
    print()


if __name__ == "__main__":
    main()
