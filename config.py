#!/usr/bin/env python3
"""
config.py — Centralized Hardware Configuration for ARES RPi4 Test Suite.

All GPIO pin numbers use BCM numbering.
Motor pin assignments sourced from Cokoino CKK0011 Demo2.py:
  https://github.com/Cokoino/CKK0011

If your wiring differs, edit ONLY this file — all other scripts import from here.
"""

# ─── I2C Configuration (OSOYOO PWM HAT v2.0 / PCA9685) ─────────────────────

I2C_BUS = 1                     # /dev/i2c-1 on Raspberry Pi 4
PCA9685_ADDRESS = 0x40           # Default; change if A0-A5 address pads are soldered
SERVO_CHANNELS = 16              # PCA9685 has 16 PWM channels
SERVO_FREQUENCY = 50             # 50 Hz is standard for hobby servos

# Known I2C device addresses for identification during scanning
KNOWN_I2C_DEVICES = {
    0x40: "PCA9685 PWM Controller (OSOYOO Servo HAT v2.0)",
    0x70: "PCA9685 All-Call Address",
}

# ─── Servo Channel Assignments ──────────────────────────────────────────────
# Map logical servo names to PCA9685 channel numbers (0-15).
# Adjust to match which physical port each servo is plugged into.

SERVO_MAP = {
    "servo_0": 0,
    "servo_1": 1,
    "servo_2": 2,
    "servo_3": 3,
}

SERVO_MIN_ANGLE = 0              # Degrees
SERVO_MAX_ANGLE = 180            # Degrees
SERVO_DEFAULT_ANGLE = 90         # Center position

# ─── CQR37D Motor Specifications ─────────────────────────────────────────────
# Motor: CQR37D 70:1 geared DC motor with 64 CPR quadrature encoder
# Datasheet: http://www.cqrobot.wiki/index.php/DC_Gearmotor_SKU:_CQR37D
# Wiring: Red/Black = motor power, Gray = encoder GND, Blue = encoder VCC,
#         Yellow = encoder channel A, White = encoder channel B

MOTOR_VOLTAGE = 12               # Operating voltage (V)
MOTOR_NOLOAD_RPM = 150           # No-load output shaft speed @ 12V
MOTOR_NOLOAD_CURRENT = 0.2       # No-load current (A)
MOTOR_STALL_CURRENT = 5.5        # Stall current @ 12V (A)
MOTOR_GEAR_RATIO = 70            # Gearbox reduction ratio

# ⚠️ CURRENT LIMIT WARNING:
# The DRV8833 is rated 1.5A continuous / 2A peak per channel.
# The CQR37D draws 5.5A at stall @ 12V — this EXCEEDS the DRV8833's limit.
# Fine for bench testing (no-load = 0.2A), but under real mechanical load
# the DRV8833 will overheat or trigger thermal shutdown.
# For production use, consider TB6612FNG (3.2A peak) or dedicated drivers.

# ─── Encoder Configuration ───────────────────────────────────────────────────
# The CQR37D has a built-in Hall-effect quadrature encoder (channels A + B).
# 64 CPR on the motor shaft → 64 × 70 = 4480 counts per output shaft revolution.
# Encoder VCC accepts 3.3V–24V, so it connects directly to the Pi's 3.3V rail.
#
# Encoder wires connect DIRECTLY to free GPIO pins on the Pi header
# (the Cokoino HAT does not have encoder input headers).

ENCODER_CPR = 64                 # Counts per revolution (motor shaft)
EFFECTIVE_CPR = ENCODER_CPR * MOTOR_GEAR_RATIO   # 4480 CPR at output shaft

# Encoder GPIO pin assignments (BCM numbering)
# These are wired directly from the motor encoder cables to the Pi GPIO header.
ENCODER_LF_A = 5                 # Left Front  — Yellow wire → GPIO 5
ENCODER_LF_B = 6                 # Left Front  — White wire  → GPIO 6
ENCODER_RF_A = 19                # Right Front — Yellow wire → GPIO 19
ENCODER_RF_B = 20                # Right Front — White wire  → GPIO 20
ENCODER_LR_A = 21                # Left Rear   — Yellow wire → GPIO 21
ENCODER_LR_B = 4                 # Left Rear   — White wire  → GPIO 4
ENCODER_RR_A = 18                # Right Rear  — Yellow wire → GPIO 18
ENCODER_RR_B = 7                 # Right Rear  — White wire  → GPIO 7

# ─── Motor GPIO Configuration (Cokoino Pi Power & 4WD HAT) ──────────────────
# Two DRV8833 dual H-bridge chips, each controlling 2 motors.
# Speed is controlled via PWM on the NSLEEP (enable) pins.
# GPIO 12 and 13 are Raspberry Pi 4 hardware PWM pins (PWM0_0, PWM0_1).
#
# DRV8833 Truth Table:
#   IN1=LOW,  IN2=HIGH → Forward  (direction depends on motor wiring polarity)
#   IN1=HIGH, IN2=LOW  → Reverse
#   IN1=LOW,  IN2=LOW  → Coast (free spin)
#   IN1=HIGH, IN2=HIGH → Brake (short brake)

# DRV8833 Chip #1
MOTOR_NSLEEP1 = 12               # GPIO 12 — hardware PWM0_0 (speed for LF + RF)
MOTOR_A1_IN1  = 17               # Chip #1, Motor A, IN1
MOTOR_A1_IN2  = 27               # Chip #1, Motor A, IN2
MOTOR_B1_IN1  = 22               # Chip #1, Motor B, IN1
MOTOR_B1_IN2  = 23               # Chip #1, Motor B, IN2

# DRV8833 Chip #2
MOTOR_NSLEEP2 = 13               # GPIO 13 — hardware PWM0_1 (speed for LR + RR)
MOTOR_A2_IN1  = 24               # Chip #2, Motor A, IN1
MOTOR_A2_IN2  = 25               # Chip #2, Motor A, IN2
MOTOR_B2_IN1  = 26               # Chip #2, Motor B, IN1
MOTOR_B2_IN2  = 16               # Chip #2, Motor B, IN2

# Logical wheel-to-pin mapping for mecanum drive.
# If a wheel label doesn't match the physical wheel, swap entries here.
# Each entry includes motor direction pins, speed (NSLEEP), and encoder pins.
MOTOR_MAP = {
    "LF": {"in1": MOTOR_A1_IN1, "in2": MOTOR_A1_IN2, "nsleep": MOTOR_NSLEEP1,
            "enc_a": ENCODER_LF_A, "enc_b": ENCODER_LF_B},
    "RF": {"in1": MOTOR_B1_IN1, "in2": MOTOR_B1_IN2, "nsleep": MOTOR_NSLEEP1,
            "enc_a": ENCODER_RF_A, "enc_b": ENCODER_RF_B},
    "LR": {"in1": MOTOR_A2_IN1, "in2": MOTOR_A2_IN2, "nsleep": MOTOR_NSLEEP2,
            "enc_a": ENCODER_LR_A, "enc_b": ENCODER_LR_B},
    "RR": {"in1": MOTOR_B2_IN1, "in2": MOTOR_B2_IN2, "nsleep": MOTOR_NSLEEP2,
            "enc_a": ENCODER_RR_A, "enc_b": ENCODER_RR_B},
}

# All motor-related GPIO pins (used by i2c_scanner for connectivity check)
ALL_MOTOR_PINS = [
    MOTOR_NSLEEP1, MOTOR_A1_IN1, MOTOR_A1_IN2, MOTOR_B1_IN1, MOTOR_B1_IN2,
    MOTOR_NSLEEP2, MOTOR_A2_IN1, MOTOR_A2_IN2, MOTOR_B2_IN1, MOTOR_B2_IN2,
]

# Encoder GPIO pins (checked separately as inputs, not outputs)
ALL_ENCODER_PINS = [
    ENCODER_LF_A, ENCODER_LF_B,
    ENCODER_RF_A, ENCODER_RF_B,
    ENCODER_LR_A, ENCODER_LR_B,
    ENCODER_RR_A, ENCODER_RR_B,
]

# Motor speed / timing defaults
MOTOR_PWM_FREQUENCY = 1000      # Hz for NSLEEP PWM
MOTOR_SLOW_SPEED = 25           # Duty cycle % for "slow" test
MOTOR_TEST_DURATION = 2.0       # Seconds to run each motor during auto-test

# ─── Gamepad Configuration (controller_test.py) ──────────────────────────

GAMEPAD_DEADZONE = 0.15          # Analog stick deadzone (0.0-1.0)
GAMEPAD_UPDATE_HZ = 20           # Motor/servo output update rate (Hz)
