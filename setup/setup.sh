#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh — Full Raspberry Pi 4B Setup for ARES Robot Platform
#
# Installs all system packages, Python dependencies, enables hardware
# interfaces (I2C, Bluetooth), and configures services (pigpiod).
#
# Usage:
#   chmod +x setup.sh
#   sudo ./setup.sh
#
# What this script does:
#   1. Updates the OS and installs system packages
#   2. Enables I2C interface via raspi-config
#   3. Installs and enables the pigpio daemon (encoder feedback)
#   4. Configures Bluetooth for gamepad support
#   5. Creates a Python virtual environment with all dependencies
#   6. Verifies the installation
#
# Tested on: Raspberry Pi OS (Bookworm) — 64-bit and 32-bit
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ─── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No color

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ─── Root Check ──────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root."
    echo "  Usage: sudo ./setup.sh"
    exit 1
fi

# Detect the real user (not root) who invoked sudo
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")

# ─── Project Path ────────────────────────────────────────────────────────────

# Default: assume the project is cloned to ~/ares_rpi4
PROJECT_DIR="${1:-$REAL_HOME/ares_rpi4}"

if [[ ! -f "$PROJECT_DIR/requirements.txt" ]]; then
    fail "Project not found at $PROJECT_DIR"
    echo "  Clone the repo first:"
    echo "    git clone https://github.com/ExtendoN64/ares_rpi4.git"
    echo "  Or pass the project path:"
    echo "    sudo ./setup.sh /path/to/ares_rpi4"
    exit 1
fi

info "Project directory: $PROJECT_DIR"

# ─── Step 1: System Update ──────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 1/6: System Update"
echo "═══════════════════════════════════════════════════════"

info "Updating package lists..."
apt-get update -y

info "Upgrading installed packages..."
apt-get upgrade -y

ok "System updated."

# ─── Step 2: System Packages ────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 2/6: System Packages"
echo "═══════════════════════════════════════════════════════"

PACKAGES=(
    # Python
    python3
    python3-pip
    python3-venv
    python3-dev

    # Build tools (needed for compiling native Python extensions)
    build-essential
    libffi-dev
    libssl-dev

    # I2C tools (i2cdetect, i2cget, etc.)
    i2c-tools
    python3-smbus

    # GPIO
    python3-rpi.gpio
    libgpiod2

    # pigpio (daemon + Python bindings for encoder reading)
    pigpio
    python3-pigpio

    # Bluetooth (for gamepad controller)
    bluetooth
    bluez
    bluez-tools

    # Git (for updates)
    git
)

info "Installing system packages..."
apt-get install -y "${PACKAGES[@]}"

ok "System packages installed."

# ─── Step 3: Enable I2C ─────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 3/6: Enable I2C Interface"
echo "═══════════════════════════════════════════════════════"

# Enable I2C via raspi-config non-interactive mode
if raspi-config nonint get_i2c | grep -q "1"; then
    info "Enabling I2C interface..."
    raspi-config nonint do_i2c 0
    ok "I2C enabled."
else
    ok "I2C already enabled."
fi

# Ensure i2c-dev kernel module loads on boot
if ! grep -q "^i2c-dev" /etc/modules 2>/dev/null; then
    echo "i2c-dev" >> /etc/modules
    info "Added i2c-dev to /etc/modules."
fi

# Load it now if not already loaded
if ! lsmod | grep -q i2c_dev; then
    modprobe i2c-dev
    info "Loaded i2c-dev kernel module."
fi

# Add user to i2c group (allows non-root I2C access)
if ! groups "$REAL_USER" | grep -q "\bi2c\b"; then
    usermod -aG i2c "$REAL_USER"
    info "Added $REAL_USER to 'i2c' group."
fi

ok "I2C configured."

# ─── Step 4: pigpio Daemon ──────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 4/6: pigpio Daemon (Encoder Feedback)"
echo "═══════════════════════════════════════════════════════"

# Enable pigpiod to start on boot
if systemctl is-enabled pigpiod &>/dev/null; then
    ok "pigpiod already enabled on boot."
else
    systemctl enable pigpiod
    ok "pigpiod enabled on boot."
fi

# Start pigpiod now if not running
if systemctl is-active pigpiod &>/dev/null; then
    ok "pigpiod is running."
else
    systemctl start pigpiod
    ok "pigpiod started."
fi

# ─── Step 5: Bluetooth Setup ────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 5/6: Bluetooth (Gamepad Support)"
echo "═══════════════════════════════════════════════════════"

# Enable bluetooth service
if systemctl is-enabled bluetooth &>/dev/null; then
    ok "Bluetooth service already enabled."
else
    systemctl enable bluetooth
    ok "Bluetooth service enabled."
fi

if systemctl is-active bluetooth &>/dev/null; then
    ok "Bluetooth service is running."
else
    systemctl start bluetooth
    ok "Bluetooth service started."
fi

# Add user to bluetooth and input groups
for grp in bluetooth input; do
    if ! groups "$REAL_USER" | grep -q "\b${grp}\b"; then
        usermod -aG "$grp" "$REAL_USER"
        info "Added $REAL_USER to '$grp' group."
    fi
done

ok "Bluetooth configured."
info "To pair a gamepad, run: ./setup/bluetooth_pair.sh"

# ─── Step 6: Python Virtual Environment + Dependencies ──────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Step 6/6: Python Environment"
echo "═══════════════════════════════════════════════════════"

VENV_DIR="$PROJECT_DIR/venv"

if [[ -d "$VENV_DIR" ]]; then
    warn "Virtual environment already exists at $VENV_DIR"
    info "Upgrading packages..."
else
    info "Creating virtual environment at $VENV_DIR..."
    sudo -u "$REAL_USER" python3 -m venv "$VENV_DIR"
    ok "Virtual environment created."
fi

info "Installing Python packages..."
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --upgrade pip
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

ok "Python packages installed."

# ─── Verification ────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Verification"
echo "═══════════════════════════════════════════════════════"

PASS=0
TOTAL=0

check() {
    TOTAL=$((TOTAL + 1))
    if eval "$2" &>/dev/null; then
        ok "$1"
        PASS=$((PASS + 1))
    else
        fail "$1"
    fi
}

check "Python 3 installed"            "python3 --version"
check "pip installed"                 "$VENV_DIR/bin/pip --version"
check "I2C enabled"                   "raspi-config nonint get_i2c | grep -q 0"
check "i2c-dev module loaded"         "lsmod | grep -q i2c_dev"
check "pigpiod running"               "systemctl is-active pigpiod"
check "Bluetooth running"             "systemctl is-active bluetooth"
check "smbus2 importable"             "$VENV_DIR/bin/python3 -c 'import smbus2'"
check "adafruit_servokit importable"  "$VENV_DIR/bin/python3 -c 'from adafruit_servokit import ServoKit'"
check "pigpio importable"             "$VENV_DIR/bin/python3 -c 'import pigpio'"
check "evdev importable"              "$VENV_DIR/bin/python3 -c 'import evdev'"
check "RPi.GPIO importable"           "$VENV_DIR/bin/python3 -c 'import RPi.GPIO'"

echo ""
echo "─────────────────────────────────────────────────────────"
echo "  Results: $PASS / $TOTAL checks passed"
echo "─────────────────────────────────────────────────────────"

if [[ $PASS -eq $TOTAL ]]; then
    ok "All checks passed! Setup complete."
else
    warn "Some checks failed. See output above."
fi

# ─── Post-Install Notes ─────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Next Steps"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  1. Log out and back in (for group changes to take effect)"
echo ""
echo "  2. Activate the virtual environment:"
echo "       cd $PROJECT_DIR"
echo "       source venv/bin/activate"
echo ""
echo "  3. Run the test suite:"
echo "       python3 combined_test.py"
echo ""
echo "  4. To pair a Bluetooth gamepad:"
echo "       ./setup/bluetooth_pair.sh"
echo ""
echo "  5. To run individual tests:"
echo "       python3 servo_test.py"
echo "       python3 motor_test.py"
echo "       python3 controller_test.py"
echo ""
echo "═══════════════════════════════════════════════════════"
