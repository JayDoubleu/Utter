"""Delivers text to the focused application through the RemoteDesktop portal."""

from __future__ import annotations

import os
from collections.abc import Callable

from gi.repository import Gdk, Gio, GLib, GObject

from .portal import PORTAL_BUS, PORTAL_PATH, RESPONSE_OK, Portal

REMOTE_DESKTOP = "org.freedesktop.portal.RemoteDesktop"
CLIPBOARD = "org.freedesktop.portal.Clipboard"

DEVICE_KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2

KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_V = 47

KEYSYM_RETURN = 0xFF0D
KEYSYM_TAB = 0xFF09

TEXT_MIME_TYPES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "TEXT", "STRING"]

DoneCallback = Callable[[bool, str], None]


def keysym_for(char: str) -> int | None:
    code = ord(char)
    if char == "\n":
        return KEYSYM_RETURN
    if char == "\t":
        return KEYSYM_TAB
    if code < 0x20 or 0x7F <= code < 0xA0:
        return None
    if code <= 0xFF:
        return code
    return 0x01000000 | code


class TextInjector(GObject.Object):
    """States: idle, connecting, ready, denied, unavailable."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, portal: Portal, settings: Gio.Settings) -> None:
        super().__init__()
        self.portal = portal
        self.settings = settings
        self.session: str | None = None
        self.state = "idle"
        self.message = ""
        self.clipboard_enabled = False
        self._waiters: list[Callable[[bool], None]] = []
        self._subscriptions: list[int] = []
        self._selection: bytes = b""

    @property
    def is_ready(self) -> bool:
        return self.state == "ready" and self.session is not None

    # ---- session -------------------------------------------------------------------------

    def connect_session(
        self, on_ready: Callable[[bool], None] | None = None, parent: str = ""
    ) -> None:
        if self.is_ready:
            if on_ready is not None:
                on_ready(True)
            return
        if on_ready is not None:
            self._waiters.append(on_ready)
        if self.state == "connecting":
            return
        if not self.portal.has_interface(REMOTE_DESKTOP):
            self._finish(False, "unavailable", "The RemoteDesktop portal is not available.")
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
            REMOTE_DESKTOP,
            "CreateSession",
            params,
            lambda code, results: self._on_session(code, results, parent),
        )

    def _on_session(self, code: int, results: dict, parent: str) -> None:
        if code != RESPONSE_OK or "session_handle" not in results:
            self._finish(
                False, "unavailable", results.get("error", "The portal refused the session.")
            )
            return
        self.session = results["session_handle"]
        self._subscriptions = [
            self.portal.watch_session_closed(self.session, self._on_closed),
            self.portal.subscribe(
                CLIPBOARD, "SelectionTransfer", self._on_selection_transfer, arg0=self.session
            ),
        ]

        def params(handle_token: str) -> GLib.Variant:
            options = {
                "handle_token": GLib.Variant("s", handle_token),
                "types": GLib.Variant("u", DEVICE_KEYBOARD),
                "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
            }
            token = self.settings.get_string("remote-desktop-token")
            if token:
                options["restore_token"] = GLib.Variant("s", token)
            return GLib.Variant("(oa{sv})", (self.session, options))

        self.portal.request(
            REMOTE_DESKTOP,
            "SelectDevices",
            params,
            lambda code, results: self._on_devices(code, results, parent),
        )

    def _on_devices(self, code: int, results: dict, parent: str) -> None:
        if code != RESPONSE_OK:
            self._finish(False, "denied", "Keyboard access was not granted.")
            return
        # Ask for clipboard access before Start. Older portals do not have this interface.
        self.portal.call(
            CLIPBOARD,
            "RequestClipboard",
            GLib.Variant("(oa{sv})", (self.session, {})),
            lambda _value, _error: self._start(parent),
        )

    def _start(self, parent: str) -> None:
        def params(handle_token: str) -> GLib.Variant:
            options = {"handle_token": GLib.Variant("s", handle_token)}
            return GLib.Variant("(osa{sv})", (self.session, parent, options))

        self.portal.request(REMOTE_DESKTOP, "Start", params, self._on_started)

    def _on_started(self, code: int, results: dict) -> None:
        if code != RESPONSE_OK:
            self._finish(False, "denied", "Keyboard access was not granted.")
            return
        token = results.get("restore_token")
        if isinstance(token, str) and token:
            self.settings.set_string("remote-desktop-token", token)
        self.clipboard_enabled = bool(results.get("clipboard_enabled", False))
        self._finish(True, "ready")

    def _finish(self, ok: bool, state: str, message: str = "") -> None:
        if not ok:
            self._drop_session()
        self._set_state(state, message)
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            waiter(ok)

    def _drop_session(self) -> None:
        for subscription in self._subscriptions:
            self.portal.unsubscribe(subscription)
        self._subscriptions = []
        self.session = None
        self.clipboard_enabled = False

    def _on_closed(self) -> None:
        self._drop_session()
        self._set_state("idle", "The typing session was closed.")

    def _set_state(self, state: str, message: str = "") -> None:
        self.state = state
        self.message = message
        self.emit("changed")

    # ---- delivery ------------------------------------------------------------------------

    def deliver(self, text: str, mode: str, use_shift: bool, on_done: DoneCallback) -> None:
        """Type or paste text into the focused app. on_done(ok, notice)."""
        if not text:
            on_done(True, "")
            return

        def go(ok: bool) -> None:
            if not ok:
                self.copy_with_gdk(text)
                on_done(
                    False,
                    "Copied to the clipboard. " + (self.message or "Typing is not available."),
                )
            elif mode == "paste":
                self._paste(text, use_shift, on_done)
            else:
                self._type(text, on_done)

        self.connect_session(go)

    def _type(self, text: str, on_done: DoneCallback) -> None:
        session = self.session
        keysyms = [k for k in (keysym_for(ch) for ch in text) if k is not None]
        if not keysyms or session is None:
            on_done(True, "")
            return
        events = [(k, state) for k in keysyms for state in (1, 0)]
        last = len(events) - 1
        for index, (keysym, state) in enumerate(events):
            params = GLib.Variant("(oa{sv}iu)", (session, {}, keysym, state))
            if index == last:
                self.portal.call(
                    REMOTE_DESKTOP,
                    "NotifyKeyboardKeysym",
                    params,
                    lambda _v, error: on_done(error is None, error or ""),
                )
            else:
                self.portal.call(REMOTE_DESKTOP, "NotifyKeyboardKeysym", params)

    def _paste(self, text: str, use_shift: bool, on_done: DoneCallback) -> None:
        self._selection = text.encode("utf-8")
        if self.clipboard_enabled and self.session is not None:
            options = {"mime_types": GLib.Variant("as", TEXT_MIME_TYPES)}

            def after_selection(_value, error) -> None:
                if error:
                    self.copy_with_gdk(text)
                GLib.timeout_add(80, self._send_paste, use_shift, on_done)

            self.portal.call(
                CLIPBOARD,
                "SetSelection",
                GLib.Variant("(oa{sv})", (self.session, options)),
                after_selection,
            )
        else:
            self.copy_with_gdk(text)
            GLib.timeout_add(80, self._send_paste, use_shift, on_done)

    def _send_paste(self, use_shift: bool, on_done: DoneCallback) -> bool:
        keys = [KEY_LEFTCTRL] + ([KEY_LEFTSHIFT] if use_shift else []) + [KEY_V]
        events = [(k, 1) for k in keys] + [(k, 0) for k in reversed(keys)]
        session = self.session
        if session is None:
            on_done(False, "Copied to the clipboard. The typing session was closed.")
            return GLib.SOURCE_REMOVE
        last = len(events) - 1
        for index, (keycode, state) in enumerate(events):
            params = GLib.Variant("(oa{sv}iu)", (session, {}, keycode, state))
            if index == last:
                self.portal.call(
                    REMOTE_DESKTOP,
                    "NotifyKeyboardKeycode",
                    params,
                    lambda _v, error: on_done(error is None, error or ""),
                )
            else:
                self.portal.call(REMOTE_DESKTOP, "NotifyKeyboardKeycode", params)
        return GLib.SOURCE_REMOVE

    def _on_selection_transfer(self, params: tuple) -> None:
        _session, _mime_type, serial = params
        if self.session is None:
            return
        success = False
        try:
            reply, fd_list = self.portal.bus.call_with_unix_fd_list_sync(
                PORTAL_BUS,
                PORTAL_PATH,
                CLIPBOARD,
                "SelectionWrite",
                GLib.Variant("(ou)", (self.session, serial)),
                GLib.VariantType("(h)"),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                None,
            )
            fd = fd_list.get(reply.unpack()[0])
            try:
                data = self._selection
                while data:
                    written = os.write(fd, data)
                    data = data[written:]
                success = True
            finally:
                os.close(fd)
        except (GLib.Error, OSError):
            success = False
        self.portal.call(
            CLIPBOARD, "SelectionWriteDone", GLib.Variant("(oub)", (self.session, serial, success))
        )

    @staticmethod
    def copy_with_gdk(text: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain;charset=utf-8", GLib.Bytes.new(text.encode("utf-8"))
        )
        display.get_clipboard().set_content(provider)
