"""Software dimming fallback for X11 sessions, using xrandr gamma scaling.

This only works on X11. GNOME on Wayland ignores it, so the manager does not
offer software displays there (a GNOME Shell extension is needed for that).
"""

from __future__ import annotations

import re

from . import proc
from .display import BrightnessError, Display, clamp_percent

MIN_SOFTWARE = 10  # percent; below this the screen is unreadable


def parse_outputs(text: str) -> dict[str, float]:
    """Parse `xrandr --verbose` into {output name: current brightness 0.0-1.0+}."""
    outputs: dict[str, float] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^(\S+) connected", line)
        if m:
            current = m.group(1)
            outputs[current] = 1.0
            continue
        if line and not line[0].isspace():
            current = None
            continue
        b = re.match(r"^\s+Brightness:\s*([0-9.]+)", line)
        if b and current:
            outputs[current] = float(b.group(1))
    return outputs


def normalize_connector(name: str) -> str:
    """Make DRM ("card1-HDMI-A-1") and xrandr ("HDMI-1") connector names comparable."""
    name = re.sub(r"^card\d+-", "", name)
    return re.sub(r"-A-(\d+)$", r"-\1", name)


class SoftwareDisplay(Display):
    kind = "software"

    def __init__(self, output: str, brightness: float = 1.0):
        self.output = output
        self.id = f"software:{output}"
        self.name = f"{output} (software dimming)"
        self._initial = brightness

    def get_percent(self) -> int:
        return clamp_percent(self._initial * 100)

    def set_percent(self, percent: int) -> None:
        value = max(MIN_SOFTWARE, clamp_percent(percent)) / 100
        r = proc.run(["xrandr", "--output", self.output, "--brightness", f"{value:.2f}"])
        if r.returncode != 0:
            raise BrightnessError(r.stderr.strip() or "xrandr failed")
        self._initial = value


def detect() -> list[SoftwareDisplay]:
    r = proc.run(["xrandr", "--verbose"])
    if r.returncode != 0:
        return []
    return [SoftwareDisplay(o, b) for o, b in parse_outputs(r.stdout).items()]
