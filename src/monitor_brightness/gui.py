"""GTK4 / libadwaita app: a tray icon that toggles a window of per-display sliders.

Only widgets available since libadwaita 1.0 are used, so this runs on Ubuntu 22.04 too.
"""

from __future__ import annotations

import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import manager  # noqa: E402
from .display import BrightnessError, Display  # noqa: E402
from .tray import Tray  # noqa: E402
from .writer import CoalescingWriter  # noqa: E402

APP_ID = "io.github.harrycnguyen.MonitorBrightness"
RELOAD_AFTER = 60  # seconds before reopening the window re-detects monitors


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Monitor Brightness", default_width=420, default_height=240)
        self._writer = CoalescingWriter(on_error=self._write_failed)
        self._loading = False
        self._loaded_at = 0.0

        header = Adw.HeaderBar()
        quit_button = Gtk.Button(icon_name="application-exit-symbolic", tooltip_text="Quit")
        quit_button.connect("clicked", lambda _b: app.quit())
        header.pack_end(quit_button)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Detect monitors again")
        refresh.connect("clicked", lambda _b: self.reload())
        header.pack_start(refresh)
        self._spinner = Gtk.Spinner()
        header.pack_end(self._spinner)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._notes = Gtk.Label(wrap=True, xalign=0)
        self._notes.add_css_class("dim-label")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(self._list)
        box.append(self._notes)
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_vexpand(True)
        self._toasts.set_child(box)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(header)
        outer.append(self._toasts)
        self.set_content(outer)

        self.connect("close-request", self._on_close_request)
        self.reload()

    # Showing and hiding: the app lives in the tray, so closing only hides.
    def _on_close_request(self, _window) -> bool:
        self.set_visible(False)
        return True

    def show_window(self) -> None:
        self.present()
        if time.monotonic() - self._loaded_at > RELOAD_AFTER:
            self.reload()

    def toggle(self) -> None:
        if self.get_visible():
            self.set_visible(False)
        else:
            self.show_window()

    # Detection and the first read are slow (DDC), so they run off the UI thread.
    def reload(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._spinner.start()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        found = manager.discover()
        levels: dict[str, int] = {}
        for d in found.displays:
            try:
                levels[d.id] = d.get_percent()
            except BrightnessError as e:
                found.notes.append(f"{d.name}: {e}")
        GLib.idle_add(self._populate, found, levels)

    def _populate(self, found: manager.Discovery, levels: dict[str, int]) -> bool:
        self._loading = False
        self._loaded_at = time.monotonic()
        self._spinner.stop()
        child = self._list.get_first_child()
        while child is not None:
            self._list.remove(child)
            child = self._list.get_first_child()
        for d in found.displays:
            if d.id in levels:
                self._add_row(d, levels[d.id])
        notes = list(found.notes)
        if not levels:
            notes.insert(0, "No controllable displays found.")
        self._notes.set_text("\n".join(notes))
        return False

    def _add_row(self, display: Display, level: int) -> None:
        row = Adw.ActionRow(title=display.name, subtitle=display.kind.replace("ddc", "DDC/CI"))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_value(level)
        scale.set_hexpand(True)
        scale.set_size_request(200, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_draw_value(True)
        scale.connect("value-changed", self._on_changed, display)
        row.add_suffix(scale)
        self._list.append(row)

    def _on_changed(self, scale: Gtk.Scale, display: Display) -> None:
        self._writer.request(display, int(scale.get_value()))

    def _write_failed(self, display: Display, error: Exception) -> None:
        GLib.idle_add(lambda: self._toasts.add_toast(Adw.Toast(title=f"{display.name}: {error}")) or False)


class App(Adw.Application):
    def __init__(self, background: bool = False):
        super().__init__(application_id=APP_ID)
        self._background = background
        self._window: MainWindow | None = None
        self._tray: Tray | None = None
        self._tray_ready = False

    def do_activate(self) -> None:
        if self._window is not None:  # launched again: bring the window up
            self._window.show_window()
            return
        self.hold()  # stay alive in the tray while the window is hidden
        self._window = MainWindow(self)
        self._tray = Tray(
            on_activate=self._window.toggle,
            on_show=self._window.show_window,
            on_quit=self.quit,
            on_registered=self._on_tray_registered,
        )
        self._tray.start()
        if self._background:
            # Without a tray host (extension off, non-GNOME desktop) the app would be
            # invisible, so fall back to showing the window.
            GLib.timeout_add_seconds(3, self._tray_fallback)
        else:
            self._window.show_window()

    def _on_tray_registered(self) -> None:
        self._tray_ready = True

    def _tray_fallback(self) -> bool:
        if not self._tray_ready and self._window is not None:
            self._window.show_window()
        return False


def run(background: bool = False) -> int:
    return App(background).run([sys.argv[0]])
