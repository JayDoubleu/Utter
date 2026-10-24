"""D-Bus feed for the Utter Overlay GNOME Shell extension.

GNOME does not let an application place a window or keep it above other windows, and a new
window takes the keyboard focus from the app that gets the text. So the extension draws the
dictation panel, and this object sends it the state, the microphone level and the live text.
"""

from __future__ import annotations

import math
import time

from gi.repository import Gio, GLib

from .config import APP_ID
from .dictation import Dictation
from .formatting import tail_preview

OBJECT_PATH = "/" + APP_ID.replace(".", "/") + "/Overlay"
INTERFACE = f"{APP_ID}.Overlay"

INTERFACE_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetState">
      <arg type="s" name="state" direction="out"/>
      <arg type="s" name="text" direction="out"/>
    </method>
    <method name="Cancel"/>
    <method name="SetTargetApp">
      <arg type="s" name="app_id" direction="in"/>
    </method>
    <signal name="StateChanged">
      <arg type="s" name="state"/>
    </signal>
    <signal name="Level">
      <arg type="d" name="level"/>
    </signal>
    <signal name="Partial">
      <arg type="s" name="text"/>
    </signal>
  </interface>
</node>
"""

# FluidVoice sends the level about every 50 ms. The microphone gives a block every 10 ms.
LEVEL_INTERVAL = 0.05
# FluidVoice shows the last 150 characters of the live text.
PREVIEW_LIMIT = 150


def level_fraction(rms: float) -> float:
    """Map microphone RMS, which is small, to 0..1 with a soft curve."""
    return min(1.0, math.sqrt(min(max(rms, 0.0), 0.15) / 0.15))


class OverlayFeed:
    def __init__(self, connection: Gio.DBusConnection, dictation: Dictation) -> None:
        self._connection = connection
        self._dictation = dictation
        self._state = dictation.state
        self._text = ""
        self._peak = 0.0
        self._last_level = 0.0
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        self._registration = connection.register_object(
            OBJECT_PATH, node.interfaces[0], self._on_method_call, None, None
        )
        dictation.connect("state-changed", self._on_state_changed)
        dictation.connect("level", self._on_level)
        dictation.connect("partial", self._on_partial)

    def close(self) -> None:
        if self._registration:
            self._connection.unregister_object(self._registration)
            self._registration = 0

    def _emit(self, name: str, value: GLib.Variant) -> None:
        try:
            self._connection.emit_signal(None, OBJECT_PATH, INTERFACE, name, value)
        except GLib.Error:
            pass  # The bus is gone during shutdown. The overlay is optional.

    def _on_method_call(
        self, _connection, _sender, _path, _interface, method, params, invocation
    ) -> None:
        if method == "GetState":
            invocation.return_value(GLib.Variant("(ss)", (self._state, self._text)))
        elif method == "Cancel":
            # The extension calls this when the user presses Escape during a dictation.
            self._dictation.cancel()
            invocation.return_value(None)
        elif method == "SetTargetApp":
            # The extension sends the focused app during a dictation. Terminals get a paste.
            self._dictation.target_app = params.unpack()[0]
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod", f"No method {method}"
            )

    def _on_state_changed(self, _dictation, state: str) -> None:
        self._state = state
        if state == "idle":
            # The text stays while it is processed. The next dictation starts empty.
            self._text = ""
        self._emit("StateChanged", GLib.Variant("(s)", (state,)))

    def _on_level(self, _dictation, rms: float) -> None:
        self._peak = max(self._peak, level_fraction(rms))
        now = time.monotonic()
        if now - self._last_level < LEVEL_INTERVAL:
            return
        self._last_level = now
        peak, self._peak = self._peak, 0.0
        self._emit("Level", GLib.Variant("(d)", (peak,)))

    def _on_partial(self, _dictation, text: str) -> None:
        self._text = tail_preview(text, PREVIEW_LIMIT)
        self._emit("Partial", GLib.Variant("(s)", (self._text,)))
