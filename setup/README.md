# ARES RPi4 — Raspberry Pi 4B Setup Guide

Complete setup guide for preparing a fresh Raspberry Pi 4B to run the ARES robot test suite.

---

## Quick Start (Automated)

```bash
# Clone the repo
git clone https://github.com/ExtendoN64/ares_rpi4.git
cd ares_rpi4

# Run the setup script
sudo python3 setup/setup.py

# Log out and back in (for group permissions)
logout

# Then:
cd ~/ares_rpi4
source venv/bin/activate
python3 combined_test.py
```

---

## Manual Setup (Step by Step)

### 1. Update the OS

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Install System Packages

#### Core Python
```bash
sudo apt install -y python3 python3-pip python3-venv python3-dev
```

#### Build tools (for compiling native extensions)
```bash
sudo apt install -y build-essential libffi-dev libssl-dev
```

#### I2C (for PCA9685 servo controller)
```bash
sudo apt install -y i2c-tools python3-smbus
```

#### GPIO
```bash
sudo apt install -y python3-rpi.gpio libgpiod2
```

#### pigpio (for encoder feedback)
```bash
sudo apt install -y pigpio python3-pigpio
```

#### Bluetooth (for gamepad controller)
```bash
sudo apt install -y bluetooth bluez bluez-tools
```

#### Git
```bash
sudo apt install -y git
```

### 3. Enable I2C

```bash
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable
```

Or non-interactively:
```bash
sudo raspi-config nonint do_i2c 0
```

Ensure the kernel module loads on boot:
```bash
echo "i2c-dev" | sudo tee -a /etc/modules
sudo modprobe i2c-dev
```

Add your user to the I2C group (for non-root access):
```bash
sudo usermod -aG i2c $USER
```

Verify I2C is working:
```bash
i2cdetect -y 1
# You should see 0x40 (PCA9685) if the servo HAT is connected
```

### 4. Enable and Start pigpiod

```bash
sudo systemctl enable pigpiod    # Auto-start on boot
sudo systemctl start pigpiod     # Start now
```

Verify:
```bash
sudo systemctl status pigpiod
# Should show "active (running)"
```

### 5. Set Up Bluetooth

```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

Add your user to required groups:
```bash
sudo usermod -aG bluetooth $USER
sudo usermod -aG input $USER     # Required for evdev to read gamepads
```

### 6. Create Python Virtual Environment

```bash
cd ~/ares_rpi4
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 7. Log Out and Back In

Group membership changes (`i2c`, `bluetooth`, `input`) only take effect after logging out:
```bash
logout
# Then SSH back in
```

---

## Python Packages Reference

| Package | Version | Purpose | Used By |
|---------|---------|---------|---------|
| `smbus2` | >=0.4.0 | I2C bus communication | `i2c_scanner.py` |
| `adafruit-circuitpython-servokit` | >=1.3.0 | PCA9685 servo control | `servo_test.py` |
| `Adafruit-Blinka` | >=8.0.0 | CircuitPython compatibility layer | Required by Adafruit libs |
| `pigpio` | >=1.78 | Encoder reading via pigpio daemon | `motor_test.py` |
| `evdev` | >=1.6.0 | Linux input for Bluetooth gamepads | `controller_test.py` |

**Pre-installed on Pi OS** (no pip install needed):
- `RPi.GPIO` — GPIO pin control for motor direction
- `pigpio` — Usually pre-installed, but Python bindings may need `pip install`

---

## Bluetooth Gamepad Pairing

### Automated (recommended)
```bash
python3 setup/bluetooth_pair.py
```

### Manual pairing with bluetoothctl

```bash
# Start bluetoothctl
sudo bluetoothctl

# Inside the bluetoothctl prompt:
agent on
default-agent
scan on

# Wait for your controller to appear, note the MAC address
# Example: [NEW] Device AA:BB:CC:DD:EE:FF Wireless Controller

pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF

# Exit bluetoothctl
exit
```

### Putting controllers in pairing mode

| Controller | How to Enter Pairing Mode |
|-----------|--------------------------|
| PS4 DualShock 4 | Hold **Share + PS** button until light bar flashes rapidly |
| PS5 DualSense | Hold **Create + PS** button until light bar flashes |
| Xbox One/Series | Hold **pairing button** (top edge) until Xbox logo flashes fast |
| 8BitDo Pro 2 | Hold **Start + pair** (or Start + B for Switch mode) |
| Generic | Usually hold power/home until LED blinks rapidly |

### Verify the gamepad is connected

```bash
# Check if input events exist
ls /dev/input/event*

# See device names
cat /proc/bus/input/devices | grep -A4 "Name"

# Quick test (shows raw events — press buttons to see output)
sudo evtest
```

---

## Troubleshooting

### I2C not detecting PCA9685

```bash
# Check if I2C is enabled
sudo raspi-config nonint get_i2c
# 0 = enabled, 1 = disabled

# Scan the bus
i2cdetect -y 1
# PCA9685 should appear at 0x40

# If not found:
# - Check the OSOYOO HAT is seated properly on the GPIO header
# - Check power supply to the HAT
# - Verify no address conflicts (check A0-A5 solder pads)
```

### pigpiod won't start

```bash
# Check status
sudo systemctl status pigpiod

# If it fails, try starting manually
sudo pigpiod -v

# Common fix: kill stale instance
sudo killall pigpiod
sudo pigpiod
```

### Permission denied reading gamepad (`evdev`)

```bash
# Add user to input group
sudo usermod -aG input $USER

# Log out and back in
logout

# Verify
groups
# Should include 'input'
```

### Gamepad paired but not responding

```bash
# Check if the device is connected
bluetoothctl info AA:BB:CC:DD:EE:FF
# Look for "Connected: yes"

# If not connected, try:
bluetoothctl connect AA:BB:CC:DD:EE:FF

# Some controllers need to be removed and re-paired:
bluetoothctl remove AA:BB:CC:DD:EE:FF
# Then pair again from scratch
```

### Adafruit library import errors

```bash
# Make sure you're in the virtual environment
source venv/bin/activate

# Reinstall
pip install --force-reinstall adafruit-circuitpython-servokit Adafruit-Blinka

# If board detection fails:
pip install --force-reinstall adafruit-blinka
```

### RPi.GPIO "not available" error

```bash
# RPi.GPIO comes pre-installed on Pi OS.
# If using a venv and it's not found:
pip install RPi.GPIO

# If it fails to build, install headers:
sudo apt install python3-dev
```

### Encoder readings are zero

```bash
# Verify pigpiod is running
pigs t   # Should return microseconds (the tick count)

# Check encoder wiring:
#   Gray  → Pi GND
#   Blue  → Pi 3.3V (pin 1 or 17)
#   Yellow → GPIO (channel A)
#   White  → GPIO (channel B)

# Test a single encoder pin manually
pigs r 5   # Read GPIO 5 (LF encoder A) — returns 0 or 1
```

### SSH connection

```bash
# From Windows/Mac:
ssh pi@raspberrypi.local

# If .local doesn't resolve, find the IP:
# On the Pi:
hostname -I

# Or scan your network:
# Windows: arp -a
# Mac/Linux: nmap -sn 192.168.1.0/24
```

---

## Hardware Wiring Reference

See `config.py` for the complete pin mapping. Quick summary:

```
Motor GPIO Pins (DRV8833 H-Bridge):
  LF: IN1=17, IN2=27, NSLEEP=12 (Chip #1)
  RF: IN1=22, IN2=23, NSLEEP=12 (Chip #1)
  LR: IN1=24, IN2=25, NSLEEP=13 (Chip #2)
  RR: IN1=26, IN2=16, NSLEEP=13 (Chip #2)

Encoder GPIO Pins:
  LF: A=5,  B=6
  RF: A=19, B=20
  LR: A=21, B=4
  RR: A=18, B=7

Servo (PCA9685 via I2C):
  I2C address: 0x40
  Channels: 0, 1, 2, 3
```
