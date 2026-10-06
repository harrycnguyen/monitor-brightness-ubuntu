"""System tray icon via the StatusNotifierItem D-Bus protocol.

Ubuntu's GNOME session ships the AppIndicator extension, which shows these
icons in the top bar. We talk D-Bus directly (through Gio) because the usual
AppIndicator library is GTK3-only and can't live in a GTK4 process.

The icon has no menu, so a click calls `Activate`; the app answers by toggling
its window. Quitting is done from the window.
"""

from __future__ import annotations

import os
from typing import Callable

from gi.repository import Gio, GLib

ITEM_PATH = "/StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
ICON = "display-brightness-symbolic"

_INTROSPECTION = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg type="s"/></signal>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
  </interface>
</node>
"""

_PROPERTIES = {
    "Category": lambda title: GLib.Variant("s", "Hardware"),
    "Id": lambda title: GLib.Variant("s", "monitor-brightness"),
    "Title": lambda title: GLib.Variant("s", title),
    "Status": lambda title: GLib.Variant("s", "Active"),
    "WindowId": lambda title: GLib.Variant("u", 0),
    "IconName": lambda title: GLib.Variant("s", ICON),
    "IconPixmap": lambda title: GLib.Variant("a(iiay)", []),
    "OverlayIconName": lambda title: GLib.Variant("s", ""),
    "OverlayIconPixmap": lambda title: GLib.Variant("a(iiay)", []),
    "AttentionIconName": lambda title: GLib.Variant("s", ""),
    "AttentionIconPixmap": lambda title: GLib.Variant("a(iiay)", []),
    "AttentionMovieName": lambda title: GLib.Variant("s", ""),
    "ToolTip": lambda title: GLib.Variant("(sa(iiay)ss)", ("", [], title, "")),
    "ItemIsMenu": lambda title: GLib.Variant("b", False),
    # "No menu" convention, so shells deliver a click as Activate.
    "Menu": lambda title: GLib.Variant("o", "/NO_DBUSMENU"),
}


class Tray:
    def __init__(self, on_activate: Callable[[], None], on_registered: Callable[[], None],
                 title: str = "Monitor Brightness"):
        self._on_activate = on_activate
        self._on_registered = on_registered
        self._title = title
        self._conn: Gio.DBusConnection | None = None
        self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._have_name = False
        self._watcher_up = False
        self._registered = False

    def start(self) -> None:
        try:
            self._conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION)
            self._conn.register_object(
                ITEM_PATH, node.interfaces[0], self._method_call, self._get_property, None
            )
        except GLib.Error:
            return  # no session bus: the app will just show its window instead
        Gio.bus_own_name_on_connection(
            self._conn, self._name, Gio.BusNameOwnerFlags.NONE, self._name_acquired, None
        )
        Gio.bus_watch_name_on_connection(
            self._conn, WATCHER, Gio.BusNameWatcherFlags.NONE, self._watcher_appeared, self._watcher_vanished
        )

    def _name_acquired(self, conn, name) -> None:
        self._have_name = True
        self._register()

    def _watcher_appeared(self, conn, name, owner) -> None:
        self._watcher_up = True
        self._register()

    def _watcher_vanished(self, conn, name) -> None:
        # Panel/extension restarted: register again when it comes back.
        self._watcher_up = False
        self._registered = False

    def _register(self) -> None:
        if not (self._have_name and self._watcher_up) or self._registered:
            return
        self._registered = True
        self._conn.call(
            WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._name,)), None, Gio.DBusCallFlags.NONE, -1, None, self._register_done,
        )

    def _register_done(self, conn, result) -> None:
        try:
            conn.call_finish(result)
        except GLib.Error:
            self._registered = False
            return
        self._on_registered()

    def _method_call(self, conn, sender, path, interface, method, params, invocation) -> None:
        if method in ("Activate", "SecondaryActivate"):
            self._on_activate()
        invocation.return_value(None)

    def _get_property(self, conn, sender, path, interface, prop):
        make = _PROPERTIES.get(prop)
        return make(self._title) if make else None
