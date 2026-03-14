#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# bluetooth_pair.sh — Interactive Bluetooth Gamepad Pairing for ARES RPi4
#
# Guides you through discovering, pairing, and trusting a Bluetooth gamepad.
# Supports PS4/PS5 DualShock/DualSense, Xbox, 8BitDo, and generic gamepads.
#
# Usage:
#   ./bluetooth_pair.sh              # Interactive scan + pair
#   ./bluetooth_pair.sh AA:BB:CC:DD  # Pair a known MAC address directly
#
# Controller prep (put your controller in pairing mode first):
#   PS4 DualShock 4:   Hold Share + PS button until light bar flashes rapidly
#   PS5 DualSense:     Hold Create + PS button until light bar flashes
#   Xbox controller:   Hold the pairing button (top) until Xbox logo flashes
#   8BitDo:            Hold Start + pair button (varies by model, check manual)
#   Generic:           Usually hold power/home until LED blinks fast
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ─── Checks ─────────────────────────────────────────────────────────────────

if ! command -v bluetoothctl &>/dev/null; then
    fail "bluetoothctl not found. Install: sudo apt install bluez"
    exit 1
fi

if ! systemctl is-active bluetooth &>/dev/null; then
    warn "Bluetooth service not running. Starting it..."
    sudo systemctl start bluetooth
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ARES RPi4 — Bluetooth Gamepad Pairing"
echo "═══════════════════════════════════════════════════════"
echo ""

# ─── Direct MAC Pairing ─────────────────────────────────────────────────────

if [[ -n "${1:-}" ]]; then
    MAC="$1"
    info "Pairing with MAC: $MAC"

    bluetoothctl -- power on
    bluetoothctl -- agent on
    bluetoothctl -- default-agent

    info "Attempting to pair..."
    if bluetoothctl -- pair "$MAC"; then
        ok "Paired with $MAC"
    else
        fail "Pairing failed. Is the controller in pairing mode?"
        exit 1
    fi

    info "Trusting device..."
    bluetoothctl -- trust "$MAC"

    info "Connecting..."
    if bluetoothctl -- connect "$MAC"; then
        ok "Connected to $MAC"
    else
        warn "Connect failed — some controllers connect automatically after trust."
    fi

    echo ""
    ok "Done! Run 'python3 controller_test.py' to test."
    exit 0
fi

# ─── Interactive Scan ────────────────────────────────────────────────────────

echo -e "${BOLD}Step 1: Put your controller in pairing mode NOW${NC}"
echo ""
echo "  PS4:   Hold Share + PS button (light bar flashes)"
echo "  PS5:   Hold Create + PS button (light bar flashes)"
echo "  Xbox:  Hold pairing button on top (logo flashes)"
echo "  8BitDo: Hold Start + pair button"
echo ""
read -rp "Press Enter when your controller is in pairing mode..."

# Power on the Bluetooth adapter
bluetoothctl -- power on &>/dev/null

echo ""
info "Scanning for Bluetooth devices (15 seconds)..."
echo "  Look for your controller name below."
echo ""

# Scan with a timeout — capture output
SCAN_FILE=$(mktemp)
timeout 15 bluetoothctl -- scan on &>"$SCAN_FILE" &
SCAN_PID=$!

# Show scan output in real time, filtered to NEW devices
sleep 1
tail -f "$SCAN_FILE" 2>/dev/null | grep --line-buffered -i "NEW\|Device" &
TAIL_PID=$!

# Wait for scan to finish
wait "$SCAN_PID" 2>/dev/null || true
kill "$TAIL_PID" 2>/dev/null || true

echo ""
echo "─────────────────────────────────────────────────────────"

# List discovered devices
info "Discovered devices:"
echo ""

DEVICES=$(bluetoothctl -- devices 2>/dev/null | grep "^Device" || true)

if [[ -z "$DEVICES" ]]; then
    fail "No devices found. Make sure your controller is in pairing mode and try again."
    rm -f "$SCAN_FILE"
    exit 1
fi

# Number the devices for easy selection
IDX=0
declare -A DEVICE_MAP
while IFS= read -r line; do
    MAC=$(echo "$line" | awk '{print $2}')
    NAME=$(echo "$line" | cut -d' ' -f3-)
    IDX=$((IDX + 1))
    DEVICE_MAP[$IDX]="$MAC"
    echo "  $IDX) $NAME  [$MAC]"
done <<< "$DEVICES"

echo ""
read -rp "Enter the number of your controller (or 'q' to quit): " CHOICE

if [[ "$CHOICE" == "q" ]]; then
    info "Cancelled."
    rm -f "$SCAN_FILE"
    exit 0
fi

SELECTED_MAC="${DEVICE_MAP[$CHOICE]:-}"
if [[ -z "$SELECTED_MAC" ]]; then
    fail "Invalid selection."
    rm -f "$SCAN_FILE"
    exit 1
fi

info "Selected: $SELECTED_MAC"

# ─── Pair, Trust, Connect ────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Step 2: Pairing...${NC}"

bluetoothctl -- agent on &>/dev/null
bluetoothctl -- default-agent &>/dev/null

if bluetoothctl -- pair "$SELECTED_MAC" 2>/dev/null; then
    ok "Paired successfully."
else
    warn "Pairing command returned an error (may already be paired)."
fi

echo ""
echo -e "${BOLD}Step 3: Trusting (auto-reconnect on boot)...${NC}"
bluetoothctl -- trust "$SELECTED_MAC" 2>/dev/null
ok "Device trusted."

echo ""
echo -e "${BOLD}Step 4: Connecting...${NC}"
if bluetoothctl -- connect "$SELECTED_MAC" 2>/dev/null; then
    ok "Connected!"
else
    warn "Connection attempt returned an error."
    warn "Some controllers connect automatically — check if it's active."
fi

# ─── Verify ──────────────────────────────────────────────────────────────────

echo ""
echo "─────────────────────────────────────────────────────────"

# Check if the controller shows up as an input device
sleep 2
if ls /dev/input/event* &>/dev/null; then
    info "Input devices detected:"
    for ev in /dev/input/event*; do
        name=$(cat "/sys/class/input/$(basename "$ev")/device/name" 2>/dev/null || echo "unknown")
        echo "  $ev: $name"
    done
else
    warn "No input events found. The controller may need a moment to initialize."
fi

echo ""
ok "Bluetooth pairing complete!"
echo ""
echo "  Next steps:"
echo "    cd $(dirname "$(dirname "$(readlink -f "$0")")")"
echo "    source venv/bin/activate"
echo "    python3 controller_test.py"
echo ""

# Cleanup
rm -f "$SCAN_FILE"
