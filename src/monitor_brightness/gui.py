"""GTK4 / libadwaita window with one brightness slider per display."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import manager  # noqa: E402
from .display import BrightnessError, Display  # noqa: E402
from .writer import CoalescingWriter  # noqa: E402

APP_ID = "io.github.harrycnguyen.MonitorBrightness"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Monitor Brightness", default_width=420, default_height=300)
        self._writer = CoalescingWriter(on_error=self._write_failed)
        self._scales: dict[str, Gtk.Scale] = {}
        self._syncing = False

        self._toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()
        self._spinner = Gtk.Spinner(spinning=True)
        header.pack_end(self._spinner)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._notes = Gtk.Label(wrap=True, xalign=0)
        self._notes.add_css_class("dim-label")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(self._list)
        box.append(self._notes)
        self._toasts.set_child(box)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self._toasts)
        self.set_content(view)

        threading.Thread(target=self._load, daemon=True).start()

    # Discovery and the first read are slow (DDC), so they run off the UI thread.
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
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        for d in found.displays:
            if d.id in levels:
                self._add_row(d, levels[d.id])
        notes = list(found.notes)
        if not found.displays:
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
        self._scales[display.id] = scale

    def _on_changed(self, scale: Gtk.Scale, display: Display) -> None:
        self._writer.request(display, int(scale.get_value()))

    def _write_failed(self, display: Display, error: Exception) -> None:
        GLib.idle_add(lambda: self._toasts.add_toast(Adw.Toast(title=f"{display.name}: {error}")) or False)


def run() -> int:
    app = Adw.Application(application_id=APP_ID)
    app.connect("activate", lambda a: MainWindow(a).present())
    return app.run(None)
