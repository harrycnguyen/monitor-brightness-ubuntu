"""Common display interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BrightnessError(Exception):
    """Reading or writing a display's brightness failed."""


def clamp_percent(value: float) -> int:
    return max(0, min(100, int(round(value))))


class Display(ABC):
    #: stable identifier such as "ddc:1", "backlight:intel_backlight", "software:HDMI-1"
    id: str
    name: str
    #: "ddc", "backlight" or "software"
    kind: str

    @abstractmethod
    def get_percent(self) -> int:
        """Current brightness, 0-100."""

    @abstractmethod
    def set_percent(self, percent: int) -> None:
        """Set brightness, 0-100."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} {self.name!r}>"
