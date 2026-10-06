"""System tray icon via the StatusNotifierItem D-Bus protocol.

Ubuntu's GNOME session ships the AppIndicator extension, which shows these
icons in the top bar. We talk D-Bus directly (through Gio) because the usual
AppIndicator library is GTK3-only and can't live in a GTK4 process.

GNOME's extension only shows items that have a real menu (it ignores the
"/NO_DBUSMENU" convention), so we also serve a tiny com.canonical.dbusmenu menu:
"Show brightness controls" and "Quit". A plain click on the icon still calls
`Activate`, which toggles the window.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
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

_MENU_INTROSPECTION = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
  </interface>
</node>
"""

MENU_SHOW, MENU_QUIT = 1, 2
_MENU_ITEMS = {  # id -> dbusmenu properties
    MENU_SHOW: {"label": "Show brightness controls"},
    MENU_QUIT: {"label": "Quit"},
}
_MENU_ROOT = {"children-display": "submenu"}


def _props(d: dict[str, str]) -> dict[str, GLib.Variant]:
    return {k: GLib.Variant("s", v) for k, v in d.items()}


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
    "Menu": lambda title: GLib.Variant("o", MENU_PATH),
}


class Tray:
    def __init__(self, on_activate: Callable[[], None], on_show: Callable[[], None],
                 on_quit: Callable[[], None], on_registered: Callable[[], None],
                 title: str = "Monitor Brightness"):
        self._on_activate = on_activate
        self._on_show = on_show
        self._on_quit = on_quit
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
            menu = Gio.DBusNodeInfo.new_for_xml(_MENU_INTROSPECTION)
            self._conn.register_object(
                MENU_PATH, menu.interfaces[0], self._menu_method_call, self._menu_get_property, None
            )
        except GLib.Error as e:
            log.debug("tray: no session bus or registration failed: %s", e)
            return  # no session bus: the app will just show its window instead
        log.debug("tray: serving %s and %s as %s", ITEM_PATH, MENU_PATH, self._name)
        Gio.bus_own_name_on_connection(
            self._conn, self._name, Gio.BusNameOwnerFlags.NONE, self._name_acquired, None
        )
        Gio.bus_watch_name_on_connection(
            self._conn, WATCHER, Gio.BusNameWatcherFlags.NONE, self._watcher_appeared, self._watcher_vanished
        )

    def _name_acquired(self, conn, name) -> None:
        log.debug("tray: acquired bus name %s", name)
        self._have_name = True
        self._register()

    def _watcher_appeared(self, conn, name, owner) -> None:
        log.debug("tray: StatusNotifierWatcher is on the bus (%s)", owner)
        self._watcher_up = True
        self._register()

    def _watcher_vanished(self, conn, name) -> None:
        log.debug("tray: no StatusNotifierWatcher on the bus")
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
        except GLib.Error as e:
            log.debug("tray: RegisterStatusNotifierItem failed: %s", e)
            self._registered = False
            return
        log.debug("tray: registered with the watcher")
        self._on_registered()

    def _method_call(self, conn, sender, path, interface, method, params, invocation) -> None:
        log.debug("tray: item method %s", method)
        if method in ("Activate", "SecondaryActivate"):
            self._on_activate()
        invocation.return_value(None)

    def _get_property(self, conn, sender, path, interface, prop):
        make = _PROPERTIES.get(prop)
        log.debug("tray: item property %s", prop)
        return make(self._title) if make else None

    # com.canonical.dbusmenu: a flat menu with two items, never changes.
    def _layout(self, parent: int, depth: int):
        if parent == 0:
            children = []
            if depth != 0:
                children = [GLib.Variant("(ia{sv}av)", (i, _props(p), [])) for i, p in _MENU_ITEMS.items()]
            return (0, _props(_MENU_ROOT), children)
        return (parent, _props(_MENU_ITEMS.get(parent, {})), [])

    def _menu_method_call(self, conn, sender, path, interface, method, params, invocation) -> None:
        args = params.unpack()
        log.debug("tray: menu method %s%s", method, args)
        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, self._layout(args[0], args[1]))))
        elif method == "GetGroupProperties":
            ids = args[0] or [0, *_MENU_ITEMS]
            reply = [(i, _props(_MENU_ROOT if i == 0 else _MENU_ITEMS.get(i, {}))) for i in ids]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (reply,)))
        elif method == "GetProperty":
            value = (_MENU_ROOT if args[0] == 0 else _MENU_ITEMS.get(args[0], {})).get(args[1], "")
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", value),)))
        elif method == "Event":
            self._menu_event(args[0], args[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event, _data, _ts in args[0]:
                self._menu_event(item_id, event)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _menu_event(self, item_id: int, event: str) -> None:
        if event != "clicked":
            return
        if item_id == MENU_SHOW:
            self._on_show()
        elif item_id == MENU_QUIT:
            self._on_quit()

    def _menu_get_property(self, conn, sender, path, interface, prop):
        values = {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return values.get(prop)
