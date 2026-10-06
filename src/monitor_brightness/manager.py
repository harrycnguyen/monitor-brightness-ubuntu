"""Find every controllable display."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from . import backlight, ddc, xrandr
from .display import BrightnessError, Display


@dataclass
class Discovery:
    displays: list[Display] = field(default_factory=list)
    #: human-readable problems and limitations worth showing to the user
    notes: list[str] = field(default_factory=list)


def discover(env: Mapping[str, str] | None = None) -> Discovery:
    env = os.environ if env is None else env
    result = Discovery()

    panels = backlight.detect()
    result.displays.extend(panels)

    ddc_infos: list[ddc.DdcInfo] = []
    try:
        ddc_infos = ddc.detect()
    except FileNotFoundError:
        result.notes.append("ddcutil is not installed (sudo apt install ddcutil), so external monitors can't be controlled.")
    except BrightnessError as e:
        result.notes.append(f"ddcutil failed: {e}")
    result.displays.extend(ddc.DdcDisplay(i) for i in ddc_infos)

    wayland = env.get("XDG_SESSION_TYPE") == "wayland"
    if wayland:
        result.notes.append("Monitors without DDC support can't be dimmed on Wayland yet.")
    elif env.get("DISPLAY"):
        _add_software(result, ddc_infos, has_panel=bool(panels))
    return result


def _add_software(result: Discovery, ddc_infos: list[ddc.DdcInfo], has_panel: bool) -> None:
    if any(i.drm_connector is None for i in ddc_infos):
        result.notes.append("Cannot match DDC monitors to X outputs, so software dimming is off.")
        return
    claimed = {xrandr.normalize_connector(i.drm_connector) for i in ddc_infos}
    try:
        outputs = xrandr.detect()
    except FileNotFoundError:
        return
    for d in outputs:
        is_panel = d.output.startswith(("eDP", "LVDS", "DSI"))
        if d.output in claimed or (is_panel and has_panel):
            continue
        result.displays.append(d)


def select(displays: list[Display], selector: str) -> list[Display]:
    """Pick displays by 1-based index, id, or case-insensitive name substring."""
    if selector.isdigit():
        i = int(selector)
        return [displays[i - 1]] if 1 <= i <= len(displays) else []
    exact = [d for d in displays if d.id == selector]
    if exact:
        return exact
    return [d for d in displays if selector.lower() in d.name.lower()]
