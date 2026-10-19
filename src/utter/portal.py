"""Small GDBus helper for XDG desktop portals."""

from __future__ import annotations

import secrets
from collections.abc import Callable

from gi.repository import Gio, GLib

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

RESPONSE_OK = 0
RESPONSE_CANCELLED = 1

ResponseCallback = Callable[[int, dict], None]


class Portal:
    def __init__(self) -> None:
        self.bus: Gio.DBusConnection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        unique = self.bus.get_unique_name() or ":0"
        self.sender = unique.lstrip(":").replace(".", "_")

    @staticmethod
    def new_token() -> str:
        return "utter_" + secrets.token_hex(6)

    def request_path(self, token: str) -> str:
        return f"{PORTAL_PATH}/request/{self.sender}/{token}"

    def interface_version(self, interface: str) -> int:
        """The version property of a portal interface. 0 when the interface is absent."""
        try:
            result = self.bus.call_sync(
                PORTAL_BUS,
                PORTAL_PATH,
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", (interface, "version")),
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        except GLib.Error:
            return 0
        (value,) = result.unpack()
        return int(value)

    def has_interface(self, interface: str) -> bool:
        return self.interface_version(interface) > 0

    def request(
        self,
        interface: str,
        method: str,
        build_params: Callable[[str], GLib.Variant],
        on_response: ResponseCallback,
    ) -> None:
        """Call a portal method that answers through a Request object.

        build_params receives the handle token and must put it into the options dict.
        on_response receives (response code, results). Code -1 means the call failed.
        """
        token = self.new_token()
        path = self.request_path(token)
        subscription = {"id": 0}

        def on_signal(_bus, _sender, _path, _iface, _signal, params) -> None:
            self.bus.signal_unsubscribe(subscription["id"])
            code, results = params.unpack()
            on_response(int(code), results)

        subscription["id"] = self.bus.signal_subscribe(
            PORTAL_BUS,
            REQUEST_IFACE,
            "Response",
            path,
            None,
            Gio.DBusSignalFlags.NO_MATCH_RULE,
            on_signal,
        )

        def on_called(bus: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
            try:
                bus.call_finish(result)
            except GLib.Error as error:
                self.bus.signal_unsubscribe(subscription["id"])
                on_response(-1, {"error": error.message})

        self.bus.call(
            PORTAL_BUS,
            PORTAL_PATH,
            interface,
            method,
            build_params(token),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            on_called,
        )

    def call(
        self,
        interface: str,
        method: str,
        params: GLib.Variant,
        on_done: Callable[[GLib.Variant | None, str | None], None] | None = None,
    ) -> None:
        """Plain asynchronous call. on_done(result, error_message) when given."""

        def on_called(bus: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
            try:
                value = bus.call_finish(result)
            except GLib.Error as error:
                if on_done is not None:
                    on_done(None, error.message)
                return
            if on_done is not None:
                on_done(value, None)

        self.bus.call(
            PORTAL_BUS,
            PORTAL_PATH,
            interface,
            method,
            params,
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            on_called,
        )

    def subscribe(
        self,
        interface: str,
        signal: str,
        callback: Callable[[tuple], None],
        session: str | None = None,
    ) -> int:
        """Listen for a portal signal, limited to one session when given.

        Session signals carry the session handle as an object path in the first
        argument. A plain arg0 match only compares string arguments and never fires,
        so the filter uses MATCH_ARG0_PATH.
        """
        flags = Gio.DBusSignalFlags.NONE
        if session is not None:
            flags = Gio.DBusSignalFlags.MATCH_ARG0_PATH

        def on_signal(_bus, _sender, _path, _iface, _signal, params) -> None:
            callback(params.unpack())

        return self.bus.signal_subscribe(
            PORTAL_BUS,
            interface,
            signal,
            PORTAL_PATH,
            session,
            flags,
            on_signal,
        )

    def watch_session_closed(self, session: str, callback: Callable[[], None]) -> int:
        def on_signal(*_args) -> None:
            callback()

        return self.bus.signal_subscribe(
            PORTAL_BUS,
            SESSION_IFACE,
            "Closed",
            session,
            None,
            Gio.DBusSignalFlags.NONE,
            on_signal,
        )

    def unsubscribe(self, subscription_id: int) -> None:
        if subscription_id:
            self.bus.signal_unsubscribe(subscription_id)


def export_window_handle(window, callback: Callable[[str], None]) -> None:
    """Resolve the portal parent_window string for a GTK window. Empty when unknown."""
    surface = window.get_surface() if window is not None else None
    if surface is None:
        callback("")
        return
    try:
        from gi.repository import GdkWayland  # type: ignore

        if isinstance(surface, GdkWayland.WaylandToplevel):
            if surface.export_handle(lambda _s, handle: callback(f"wayland:{handle}")):
                return
    except (ImportError, ValueError, AttributeError):
        pass
    try:
        from gi.repository import GdkX11  # type: ignore

        if isinstance(surface, GdkX11.X11Surface):
            callback(f"x11:{surface.get_xid():x}")
            return
    except (ImportError, ValueError, AttributeError):
        pass
    callback("")
