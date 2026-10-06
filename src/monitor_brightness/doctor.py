"""Check the machine is set up for DDC/CI and say how to fix what isn't."""

from __future__ import annotations

import glob
import os
import shutil


def check() -> list[str]:
    """Return a list of problems; empty means DDC should work."""
    problems = []
    if shutil.which("ddcutil") is None:
        problems.append("ddcutil is not installed. Fix: sudo apt install ddcutil")
    buses = sorted(glob.glob("/dev/i2c-*"))
    if not buses:
        problems.append(
            "No /dev/i2c-* devices. Fix: sudo modprobe i2c-dev "
            "(persist with: echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf)"
        )
    elif not any(os.access(b, os.R_OK | os.W_OK) for b in buses):
        problems.append(
            "You can't access /dev/i2c-*. Fix: sudo usermod -aG i2c $USER "
            "(create the group first if missing: sudo groupadd --system i2c), then log out and back in. "
            "ddcutil's udev rule file 60-ddcutil-i2c.rules gives the i2c group access."
        )
    return problems
