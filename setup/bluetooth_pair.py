#!/usr/bin/env python3
"""
bluetooth_pair.py — Interactive Bluetooth Gamepad Pairing for ARES RPi4.

Guides you through discovering, pairing, and trusting a Bluetooth gamepad.
Supports PS4/PS5 DualShock/DualSense, Xbox, 8BitDo, and generic gamepads.

Usage:
    python3 bluetooth_pair.py                # Interactive scan + pair
    python3 bluetooth_pair.py AA:BB:CC:DD    # Pair a known MAC address

Controller prep (put your controller in pairing mode first):
    PS4 DualShock 4:  Hold Share + PS button until light bar flashes rapidly
    PS5 DualSense:    Hold Create + PS button until light bar flashes
    Xbox controller:  Hold the pairing button (top) until Xbox logo flashes
    8BitDo:           Hold Start + pair button (varies by model, check manual)
    Generic:          Usually hold power/home until LED blinks fast
"""

import os
import sys
import time
import subprocess
import shutil
import re
from pathlib import Path


# ─── Colors ──────────────────────────────────────────────────────────────────

class C:
    RED    = "\033[0;31m"
    GREEN  = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN   = "\033[0;36m"
    BOLD   = "\033[1m"
    NC     = "\033[0m"


def info(msg):  print(f"{C.CYAN}[INFO]{C.NC}  {msg}")
def ok(msg):    print(f"{C.GREEN}[OK]{C.NC}    {msg}")
def warn(msg):  print(f"{C.YELLOW}[WARN]{C.NC}  {msg}")
def fail(msg):  print(f"{C.RED}[FAIL]{C.NC}  {msg}")


def bt(cmd):
    """Run a bluetoothctl command and return (success, stdout)."""
    try:
        result = subprocess.run(
            ["bluetoothctl", "--", cmd] if isinstance(cmd, str) else ["bluetoothctl", "--"] + cmd,
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, ""


def bt_must(cmd):
    """Run a bluetoothctl command, ignoring errors (best-effort)."""
    try:
        subprocess.run(
            ["bluetoothctl", "--", cmd] if isinstance(cmd, str) else ["bluetoothctl", "--"] + cmd,
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


# ─── Checks ──────────────────────────────────────────────────────────────────

def preflight():
    """Verify bluetoothctl is available and bluetooth service is running."""
    if not shutil.which("bluetoothctl"):
        fail("bluetoothctl not found. Install: sudo apt install bluez")
        sys.exit(1)

    result = subprocess.run(
        ["systemctl", "is-active", "bluetooth"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        warn("Bluetooth service not running. Starting it...")
        subprocess.run(["sudo", "systemctl", "start", "bluetooth"], check=False)


# ─── Pair a Known MAC ────────────────────────────────────────────────────────

def pair_direct(mac):
    """Pair, trust, and connect to a known MAC address."""
    info(f"Pairing with MAC: {mac}")

    bt_must("power on")
    bt_must("agent on")
    bt_must("default-agent")

    info("Attempting to pair...")
    success, _ = bt(["pair", mac])
    if success:
        ok(f"Paired with {mac}")
    else:
        fail("Pairing failed. Is the controller in pairing mode?")
        sys.exit(1)

    info("Trusting device...")
    bt_must(["trust", mac])

    info("Connecting...")
    success, _ = bt(["connect", mac])
    if success:
        ok(f"Connected to {mac}")
    else:
        warn("Connect failed — some controllers connect automatically after trust.")

    print()
    ok("Done! Run 'python3 controller_test.py' to test.")


# ─── Scan for Devices ────────────────────────────────────────────────────────

def scan_devices(duration=15):
    """Scan for Bluetooth devices and return a list of (mac, name) tuples."""
    bt_must("power on")

    info(f"Scanning for Bluetooth devices ({duration} seconds)...")
    print("  Look for your controller name below.")
    print()

    # Start scan in the background
    try:
        proc = subprocess.Popen(
            ["bluetoothctl", "--", "scan", "on"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Show new devices as they appear
        start = time.monotonic()
        while time.monotonic() - start < duration:
            if proc.poll() is not None:
                break
            line = ""
            try:
                # Non-blocking-ish read with a short timeout
                import select
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if ready:
                    line = proc.stdout.readline()
            except (ImportError, OSError):
                time.sleep(1)
                continue

            if line and "NEW" in line.upper():
                # Extract device info from output like "[NEW] Device AA:BB:CC:DD:EE:FF Name"
                match = re.search(r"Device\s+([\dA-F:]{17})\s+(.*)", line, re.IGNORECASE)
                if match:
                    print(f"  Found: {match.group(2).strip()}  [{match.group(1)}]")

        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        pass

    # Stop scanning
    bt_must("scan off")

    # Get the full device list
    success, output = bt("devices")
    if not success or not output.strip():
        return []

    devices = []
    for line in output.splitlines():
        match = re.match(r"Device\s+([\dA-F:]{17})\s+(.*)", line, re.IGNORECASE)
        if match:
            devices.append((match.group(1), match.group(2).strip()))

    return devices


# ─── Interactive Pairing ─────────────────────────────────────────────────────

def pair_interactive():
    """Interactive scan, select, pair flow."""
    print(f"\n{C.BOLD}Step 1: Put your controller in pairing mode NOW{C.NC}")
    print()
    print("  PS4:    Hold Share + PS button (light bar flashes)")
    print("  PS5:    Hold Create + PS button (light bar flashes)")
    print("  Xbox:   Hold pairing button on top (logo flashes)")
    print("  8BitDo: Hold Start + pair button")
    print()
    input("Press Enter when your controller is in pairing mode...")

    # Scan
    devices = scan_devices(duration=15)

    print()
    print("-" * 55)

    if not devices:
        fail("No devices found. Make sure your controller is in pairing mode and try again.")
        sys.exit(1)

    # Display numbered list
    info("Discovered devices:")
    print()
    for i, (mac, name) in enumerate(devices, 1):
        print(f"  {i}) {name}  [{mac}]")

    print()
    choice = input("Enter the number of your controller (or 'q' to quit): ").strip()

    if choice.lower() == "q":
        info("Cancelled.")
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(devices):
            raise ValueError
    except ValueError:
        fail("Invalid selection.")
        sys.exit(1)

    selected_mac, selected_name = devices[idx]
    info(f"Selected: {selected_name} [{selected_mac}]")

    # Pair
    print(f"\n{C.BOLD}Step 2: Pairing...{C.NC}")
    bt_must("agent on")
    bt_must("default-agent")

    success, _ = bt(["pair", selected_mac])
    if success:
        ok("Paired successfully.")
    else:
        warn("Pairing command returned an error (may already be paired).")

    # Trust
    print(f"\n{C.BOLD}Step 3: Trusting (auto-reconnect on boot)...{C.NC}")
    bt_must(["trust", selected_mac])
    ok("Device trusted.")

    # Connect
    print(f"\n{C.BOLD}Step 4: Connecting...{C.NC}")
    success, _ = bt(["connect", selected_mac])
    if success:
        ok("Connected!")
    else:
        warn("Connection attempt returned an error.")
        warn("Some controllers connect automatically — check if it's active.")

    # Verify input devices
    print()
    print("-" * 55)
    time.sleep(2)

    input_dir = Path("/dev/input")
    events = sorted(input_dir.glob("event*")) if input_dir.exists() else []
    if events:
        info("Input devices detected:")
        for ev in events:
            name_path = Path(f"/sys/class/input/{ev.name}/device/name")
            try:
                name = name_path.read_text().strip()
            except (OSError, IOError):
                name = "unknown"
            print(f"  {ev}: {name}")
    else:
        warn("No input events found. The controller may need a moment to initialize.")

    print()
    ok("Bluetooth pairing complete!")
    print()
    print("  Next steps:")
    print("    source venv/bin/activate")
    print("    python3 controller_test.py")
    print()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 55)
    print("  ARES RPi4 — Bluetooth Gamepad Pairing")
    print("=" * 55)
    print()

    preflight()

    # Direct MAC pairing if argument provided
    if len(sys.argv) > 1:
        mac = sys.argv[1]
        if re.match(r"^[\dA-Fa-f]{2}(:[\dA-Fa-f]{2}){5}$", mac):
            pair_direct(mac)
        else:
            fail(f"Invalid MAC address: {mac}")
            print("  Expected format: AA:BB:CC:DD:EE:FF")
            sys.exit(1)
    else:
        pair_interactive()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
