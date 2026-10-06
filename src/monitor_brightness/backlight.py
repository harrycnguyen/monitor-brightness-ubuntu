"""Built-in laptop panels via /sys/class/backlight."""

from __future__ import annotations

import os
from pathlib import Path

from . import proc
from .display import BrightnessError, Display, clamp_percent

SYSFS = Path("/sys/class/backlight")


class BacklightDisplay(Display):
    kind = "backlight"

    def __init__(self, device: str, root: Path = SYSFS):
        self.device = device
        self.root = root
        self.id = f"backlight:{device}"
        self.name = "Built-in display"

    def _read(self, attr: str) -> int:
        try:
            return int((self.root / self.device / attr).read_text())
        except (OSError, ValueError) as e:
            raise BrightnessError(f"cannot read {attr} of {self.device}: {e}") from e

    def get_percent(self) -> int:
        return clamp_percent(self._read("brightness") * 100 / (self._read("max_brightness") or 1))

    def set_percent(self, percent: int) -> None:
        maximum = self._read("max_brightness")
        # Never go fully dark: on many panels raw 0 turns the backlight off.
        raw = max(1, round(clamp_percent(percent) * maximum / 100))
        # logind lets an ordinary user do this without root; fall back to sysfs.
        try:
            r = proc.run(
                ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                 "org.freedesktop.login1.Session", "SetBrightness", "ssu",
                 "backlight", self.device, str(raw)]
            )
            if r.returncode == 0:
                return
        except FileNotFoundError:
            pass
        try:
            (self.root / self.device / "brightness").write_text(str(raw))
        except OSError as e:
            raise BrightnessError(f"cannot set brightness of {self.device}: {e}") from e


def detect(root: Path = SYSFS) -> list[BacklightDisplay]:
    if not root.is_dir():
        return []
    return [BacklightDisplay(name, root) for name in sorted(os.listdir(root))]
