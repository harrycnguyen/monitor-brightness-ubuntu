"""External monitors over DDC/CI, using the ddcutil command line tool."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import proc
from .display import BrightnessError, Display, clamp_percent

VCP_BRIGHTNESS = "10"


@dataclass
class DdcInfo:
    number: int
    name: str
    drm_connector: str | None  # e.g. "card1-DP-2"


def parse_detect(text: str) -> list[DdcInfo]:
    """Parse `ddcutil detect` output. Invalid/phantom displays are skipped."""
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)

    found = []
    for block in blocks:
        m = re.fullmatch(r"Display (\d+)", block[0].strip())
        if not m:
            continue
        number = int(m.group(1))
        body = "\n".join(block[1:])
        model = re.search(r"^\s*Model:\s*(.+?)\s*$", body, re.M)
        drm = re.search(r"^\s*DRM[_ ]connector:\s*(\S+)", body, re.M)
        found.append(
            DdcInfo(
                number=number,
                name=model.group(1) if model and model.group(1) else f"Display {number}",
                drm_connector=drm.group(1) if drm else None,
            )
        )
    return found


def parse_getvcp(text: str) -> tuple[int, int]:
    """Parse `ddcutil getvcp 10 --brief` into (current, maximum)."""
    m = re.search(r"VCP\s+10\s+C\s+(\d+)\s+(\d+)", text)
    if not m:
        raise BrightnessError(f"unexpected ddcutil output: {text.strip()!r}")
    return int(m.group(1)), int(m.group(2))


def detect() -> list[DdcInfo]:
    result = proc.run(["ddcutil", "detect"], timeout=60)
    if result.returncode != 0 and not result.stdout:
        raise BrightnessError(result.stderr.strip() or "ddcutil detect failed")
    return parse_detect(result.stdout)


class DdcDisplay(Display):
    kind = "ddc"

    def __init__(self, info: DdcInfo):
        self.info = info
        self.id = f"ddc:{info.number}"
        self.name = info.name
        self._max: int | None = None

    def _run(self, args: list[str]) -> proc.Result:
        result = proc.run(["ddcutil", *args, "--display", str(self.info.number)])
        if result.returncode != 0:
            raise BrightnessError(result.stderr.strip() or result.stdout.strip() or "ddcutil failed")
        return result

    def get_percent(self) -> int:
        current, maximum = parse_getvcp(self._run(["getvcp", VCP_BRIGHTNESS, "--brief"]).stdout)
        self._max = maximum or 100
        return clamp_percent(current * 100 / self._max)

    def set_percent(self, percent: int) -> None:
        if self._max is None:
            self.get_percent()
        raw = round(clamp_percent(percent) * self._max / 100)
        self._run(["setvcp", VCP_BRIGHTNESS, str(raw), "--noverify"])
