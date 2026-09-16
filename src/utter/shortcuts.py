"""Global hotkey through the GlobalShortcuts portal."""

from __future__ import annotations

from gi.repository import GLib, GObject

from .portal import RESPONSE_OK, Portal

IFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "toggle"
DEFAULT_TRIGGER = "CTRL+ALT+space"


class GlobalShortcuts(GObject.Object):
    """States: idle, connecting, ready, unavailable."""

    __gsignals__ = {
        "activated": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "deactivated": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, portal: Portal) -> None:
        super().__init__()
        self.portal = portal
        self.session: str | None = None
        self.state = "idle"
        self.trigger = ""
        self.message = ""
        self._subscriptions: list[int] = []

    @property
    def is_ready(self) -> bool:
        return self.state == "ready"

    def start(self, parent: str = "") -> None:
        if self.session is not None or self.state == "connecting":
            return
        if not self.portal.has_interface(IFACE):
            self._set_state("unavailable", "The GlobalShortcuts portal is not available.")
            return
        self._set_state("connecting")
        session_token = self.portal.new_token()

        def params(handle_token: str) -> GLib.Variant:
            options = {
                "handle_token": GLib.Variant("s", handle_token),
                "session_handle_token": GLib.Variant("s", session_token),
            }
            return GLib.Variant("(a{sv})", (options,))

        self.portal.request(
            IFACE,
            "CreateSession",
            params,
            lambda code, results: self._on_session(code, results, parent),
        )

    def _on_session(self, code: int, results: dict, parent: str) -> None:
        if code != RESPONSE_OK or "session_handle" not in results:
            self._set_state("unavailable", results.get("error", "The portal refused the session."))
            return
        self.session = results["session_handle"]
        self._subscriptions = [
            self.portal.subscribe(IFACE, "Activated", self._on_activated, arg0=self.session),
            self.portal.subscribe(IFACE, "Deactivated", self._on_deactivated, arg0=self.session),
            self.portal.subscribe(
                IFACE, "ShortcutsChanged", self._on_shortcuts_changed, arg0=self.session
            ),
            self.portal.watch_session_closed(self.session, self._on_closed),
        ]
        self._bind(parent)

    def _bind(self, parent: str) -> None:
        shortcuts = [
            (
                SHORTCUT_ID,
                {
                    "description": GLib.Variant("s", "Start or stop dictation"),
                    "preferred_trigger": GLib.Variant("s", DEFAULT_TRIGGER),
                },
            )
        ]

        def params(handle_token: str) -> GLib.Variant:
            options = {"handle_token": GLib.Variant("s", handle_token)}
            return GLib.Variant("(oa(sa{sv})sa{sv})", (self.session, shortcuts, parent, options))

        self.portal.request(IFACE, "BindShortcuts", params, self._on_bound)

    def _on_bound(self, code: int, results: dict) -> None:
        if code != RESPONSE_OK:
            self._set_state("unavailable", "The shortcut binding was cancelled.")
            return
        self._read_shortcuts(results.get("shortcuts", []))
        self._set_state("ready")

    def _read_shortcuts(self, shortcuts) -> None:
        for shortcut_id, props in shortcuts:
            if shortcut_id == SHORTCUT_ID:
                self.trigger = str(props.get("trigger_description", "") or "")

    def refresh(self) -> None:
        if self.session is None:
            return

        def params(handle_token: str) -> GLib.Variant:
            return GLib.Variant(
                "(oa{sv})", (self.session, {"handle_token": GLib.Variant("s", handle_token)})
            )

        def on_list(code: int, results: dict) -> None:
            if code == RESPONSE_OK:
                self._read_shortcuts(results.get("shortcuts", []))
                self.emit("changed")

        self.portal.request(IFACE, "ListShortcuts", params, on_list)

    def configure(self, parent: str = "") -> None:
        """Open the desktop's dialog to change the binding."""
        if self.session is None:
            self.start(parent)
            return
        self.portal.call(
            IFACE, "ConfigureShortcuts", GLib.Variant("(osa{sv})", (self.session, parent, {}))
        )

    def _on_activated(self, params: tuple) -> None:
        _session, shortcut_id, _timestamp, _options = params
        if shortcut_id == SHORTCUT_ID:
            self.emit("activated")

    def _on_deactivated(self, params: tuple) -> None:
        _session, shortcut_id, _timestamp, _options = params
        if shortcut_id == SHORTCUT_ID:
            self.emit("deactivated")

    def _on_shortcuts_changed(self, params: tuple) -> None:
        _session, shortcuts = params
        self._read_shortcuts(shortcuts)
        self.emit("changed")

    def _on_closed(self) -> None:
        for subscription in self._subscriptions:
            self.portal.unsubscribe(subscription)
        self._subscriptions = []
        self.session = None
        self._set_state("idle", "The shortcut session was closed.")

    def _set_state(self, state: str, message: str = "") -> None:
        self.state = state
        self.message = message
        self.emit("changed")
