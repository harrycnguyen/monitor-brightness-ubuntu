"""Background writes that only ever send the latest requested value.

DDC writes take 50-500 ms. While a slider is being dragged we must not queue
every intermediate value, so each display gets a worker that writes whatever
the newest request is and skips the rest.
"""

from __future__ import annotations

import threading
from typing import Callable

from .display import BrightnessError, Display


class _Slot:
    def __init__(self) -> None:
        self.cv = threading.Condition()
        self.pending: int | None = None
        self.busy = False


class CoalescingWriter:
    def __init__(self, on_error: Callable[[Display, Exception], None] | None = None):
        self._on_error = on_error
        self._slots: dict[str, _Slot] = {}
        self._lock = threading.Lock()

    def request(self, display: Display, percent: int) -> None:
        with self._lock:
            slot = self._slots.get(display.id)
            if slot is None:
                slot = self._slots[display.id] = _Slot()
        with slot.cv:
            slot.pending = percent
            if slot.busy:
                return
            slot.busy = True
        threading.Thread(target=self._drain, args=(display, slot), daemon=True).start()

    def _drain(self, display: Display, slot: _Slot) -> None:
        while True:
            with slot.cv:
                value = slot.pending
                slot.pending = None
                if value is None:
                    slot.busy = False
                    slot.cv.notify_all()
                    return
            try:
                display.set_percent(value)
            except (BrightnessError, OSError) as e:
                if self._on_error:
                    self._on_error(display, e)

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until all queued writes finished (used by tests and the CLI)."""
        with self._lock:
            slots = list(self._slots.values())
        for slot in slots:
            with slot.cv:
                if not slot.cv.wait_for(lambda: not slot.busy and slot.pending is None, timeout):
                    return False
        return True
