#!/usr/bin/env python3
"""
setup.py — Full Raspberry Pi 4B Setup for ARES Robot Platform.

Installs all system packages, Python dependencies, enables hardware
interfaces (I2C, Bluetooth), and configures services (pigpiod).

Usage:
    sudo python3 setup.py
    sudo python3 setup.py /path/to/ares_rpi4   # Custom project path

What this script does:
    1. Updates the OS and installs system packages
    2. Enables I2C interface via raspi-config
    3. Installs and enables the pigpio daemon (encoder feedback)
    4. Configures Bluetooth for gamepad support
    5. Creates a Python virtual environment with all dependencies
    6. Verifies the installation

Tested on: Raspberry Pi OS (Bookworm) — 64-bit and 32-bit
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


# ─── Colors ──────────────────────────────────────────────────────────────────

class C:
    """ANSI color codes."""
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


def run(cmd, check=True, capture=False, **kwargs):
    """Run a shell command. Returns CompletedProcess."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        **kwargs,
    )


def run_quiet(cmd):
    """Run a command, return True if it succeeds, False otherwise."""
    try:
        subprocess.run(
            cmd if isinstance(cmd, list) else cmd.split(),
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def banner(title):
    print()
    print("=" * 55)
    print(f"  {title}")
    print("=" * 55)


# ─── Root Check ──────────────────────────────────────────────────────────────

def check_root():
    if os.geteuid() != 0:
        fail("This script must be run as root.")
        print("  Usage: sudo python3 setup.py")
        sys.exit(1)


def get_real_user():
    """Get the actual user who ran sudo (not root)."""
    user = os.environ.get("SUDO_USER", os.environ.get("USER", "pi"))
    home = Path(f"/home/{user}")
    if not home.exists():
        home = Path.home()
    return user, home


# ─── Step 1: System Update ──────────────────────────────────────────────────

def step_system_update():
    banner("Step 1/6: System Update")

    info("Updating package lists...")
    run("apt-get update -y")

    info("Upgrading installed packages...")
    run("apt-get upgrade -y")

    ok("System updated.")


# ─── Step 2: System Packages ────────────────────────────────────────────────

PACKAGES = [
    # Python
    "python3", "python3-pip", "python3-venv", "python3-dev",

    # Build tools (native extensions)
    "build-essential", "libffi-dev", "libssl-dev",

    # I2C tools
    "i2c-tools", "python3-smbus",

    # GPIO
    "python3-rpi.gpio", "libgpiod2",

    # pigpio (daemon + Python bindings)
    "pigpio", "python3-pigpio",

    # Bluetooth (gamepad support)
    "bluetooth", "bluez", "bluez-tools",

    # Git
    "git",
]


def step_system_packages():
    banner("Step 2/6: System Packages")

    info("Installing system packages...")
    run(["apt-get", "install", "-y"] + PACKAGES)

    ok("System packages installed.")


# ─── Step 3: Enable I2C ─────────────────────────────────────────────────────

def step_enable_i2c(real_user):
    banner("Step 3/6: Enable I2C Interface")

    # Check if I2C is already enabled (raspi-config returns 0 = enabled, 1 = disabled)
    result = run("raspi-config nonint get_i2c", capture=True, check=False)
    if result.stdout.strip() == "1":
        info("Enabling I2C interface...")
        run("raspi-config nonint do_i2c 0")
        ok("I2C enabled.")
    else:
        ok("I2C already enabled.")

    # Ensure i2c-dev kernel module loads on boot
    modules_file = Path("/etc/modules")
    modules_text = modules_file.read_text() if modules_file.exists() else ""
    if "i2c-dev" not in modules_text:
        with open(modules_file, "a") as f:
            f.write("i2c-dev\n")
        info("Added i2c-dev to /etc/modules.")

    # Load it now if not already loaded
    result = run("lsmod", capture=True)
    if "i2c_dev" not in result.stdout:
        run("modprobe i2c-dev")
        info("Loaded i2c-dev kernel module.")

    # Add user to i2c group
    result = run(["groups", real_user], capture=True, check=False)
    if "i2c" not in result.stdout.split():
        run(["usermod", "-aG", "i2c", real_user])
        info(f"Added {real_user} to 'i2c' group.")

    ok("I2C configured.")


# ─── Step 4: pigpio Daemon ──────────────────────────────────────────────────

def step_pigpio():
    banner("Step 4/6: pigpio Daemon (Encoder Feedback)")

    # Enable on boot
    if run_quiet("systemctl is-enabled pigpiod"):
        ok("pigpiod already enabled on boot.")
    else:
        run("systemctl enable pigpiod")
        ok("pigpiod enabled on boot.")

    # Start now
    if run_quiet("systemctl is-active pigpiod"):
        ok("pigpiod is running.")
    else:
        run("systemctl start pigpiod")
        ok("pigpiod started.")


# ─── Step 5: Bluetooth Setup ────────────────────────────────────────────────

def step_bluetooth(real_user):
    banner("Step 5/6: Bluetooth (Gamepad Support)")

    # Enable service
    if run_quiet("systemctl is-enabled bluetooth"):
        ok("Bluetooth service already enabled.")
    else:
        run("systemctl enable bluetooth")
        ok("Bluetooth service enabled.")

    if run_quiet("systemctl is-active bluetooth"):
        ok("Bluetooth service is running.")
    else:
        run("systemctl start bluetooth")
        ok("Bluetooth service started.")

    # Add user to bluetooth and input groups
    result = run(["groups", real_user], capture=True, check=False)
    current_groups = result.stdout if result.returncode == 0 else ""

    for grp in ("bluetooth", "input"):
        if grp not in current_groups.split():
            run(["usermod", "-aG", grp, real_user])
            info(f"Added {real_user} to '{grp}' group.")

    ok("Bluetooth configured.")
    info("To pair a gamepad, run: python3 setup/bluetooth_pair.py")


# ─── Step 6: Python Virtual Environment ─────────────────────────────────────

def step_python_env(project_dir, real_user):
    banner("Step 6/6: Python Environment")

    venv_dir = project_dir / "venv"
    venv_pip = venv_dir / "bin" / "pip"
    requirements = project_dir / "requirements.txt"

    if venv_dir.exists():
        warn(f"Virtual environment already exists at {venv_dir}")
        info("Upgrading packages...")
    else:
        info(f"Creating virtual environment at {venv_dir}...")
        run(["sudo", "-u", real_user, "python3", "-m", "venv", str(venv_dir)])
        ok("Virtual environment created.")

    info("Installing Python packages...")
    run(["sudo", "-u", real_user, str(venv_pip), "install", "--upgrade", "pip"])
    run(["sudo", "-u", real_user, str(venv_pip), "install", "-r", str(requirements)])

    ok("Python packages installed.")
    return venv_dir


# ─── Verification ────────────────────────────────────────────────────────────

def step_verify(venv_dir):
    banner("Verification")

    venv_python = venv_dir / "bin" / "python3"
    venv_pip = venv_dir / "bin" / "pip"

    checks = [
        ("Python 3 installed",           ["python3", "--version"]),
        ("pip installed",                 [str(venv_pip), "--version"]),
        ("I2C enabled",                   ["bash", "-c", "raspi-config nonint get_i2c | grep -q 0"]),
        ("i2c-dev module loaded",         ["bash", "-c", "lsmod | grep -q i2c_dev"]),
        ("pigpiod running",              ["systemctl", "is-active", "pigpiod"]),
        ("Bluetooth running",            ["systemctl", "is-active", "bluetooth"]),
        ("smbus2 importable",            [str(venv_python), "-c", "import smbus2"]),
        ("adafruit_servokit importable", [str(venv_python), "-c", "from adafruit_servokit import ServoKit"]),
        ("pigpio importable",            [str(venv_python), "-c", "import pigpio"]),
        ("evdev importable",             [str(venv_python), "-c", "import evdev"]),
        ("RPi.GPIO importable",          [str(venv_python), "-c", "import RPi.GPIO"]),
    ]

    passed = 0
    total = len(checks)

    for label, cmd in checks:
        if run_quiet(cmd):
            ok(label)
            passed += 1
        else:
            fail(label)

    print()
    print("-" * 55)
    print(f"  Results: {passed} / {total} checks passed")
    print("-" * 55)

    if passed == total:
        ok("All checks passed! Setup complete.")
    else:
        warn("Some checks failed. See output above.")

    return passed, total


# ─── Next Steps ──────────────────────────────────────────────────────────────

def print_next_steps(project_dir):
    banner("Next Steps")
    print(f"""
  1. Log out and back in (for group changes to take effect)

  2. Activate the virtual environment:
       cd {project_dir}
       source venv/bin/activate

  3. Run the test suite:
       python3 combined_test.py

  4. To pair a Bluetooth gamepad:
       python3 setup/bluetooth_pair.py

  5. To run individual tests:
       python3 servo_test.py
       python3 motor_test.py
       python3 controller_test.py
""")
    print("=" * 55)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    check_root()

    real_user, real_home = get_real_user()

    # Determine project directory
    if len(sys.argv) > 1:
        project_dir = Path(sys.argv[1]).resolve()
    else:
        # Default: same directory as this script's parent
        project_dir = Path(__file__).resolve().parent.parent

    requirements = project_dir / "requirements.txt"
    if not requirements.exists():
        fail(f"Project not found at {project_dir}")
        print("  Clone the repo first:")
        print("    git clone https://github.com/ExtendoN64/ares_rpi4.git")
        print("  Or pass the project path:")
        print("    sudo python3 setup.py /path/to/ares_rpi4")
        sys.exit(1)

    info(f"Project directory: {project_dir}")
    info(f"User: {real_user}")

    try:
        step_system_update()
        step_system_packages()
        step_enable_i2c(real_user)
        step_pigpio()
        step_bluetooth(real_user)
        venv_dir = step_python_env(project_dir, real_user)
        step_verify(venv_dir)
        print_next_steps(project_dir)

    except subprocess.CalledProcessError as e:
        fail(f"Command failed: {e.cmd}")
        if e.stderr:
            print(f"  {e.stderr.strip()}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nSetup interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
