"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .audio import AudioCapture
from .config import APP_ID, APP_NAME, HOMEPAGE, ISSUES, VERSION
from .dictation import Dictation
from .history import History
from .injector import TextInjector
from .modelstore import ModelStore
from .overlay import OverlayFeed
from .portal import RESPONSE_OK, Portal, export_window_handle
from .preferences import PreferencesDialog
from .recognizer import Recognizer
from .secrets import migrate_api_key
from .settings import get_settings
from .shortcuts import GlobalShortcuts
from .sounds import Sounds
from .window import UtterWindow

CSS = """
.record-button {
  min-width: 88px;
  min-height: 88px;
  padding: 0;
  -gtk-icon-size: 36px;
}
"""


class UtterApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.add_main_option(
            "toggle",
            ord("t"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Start or stop dictation in the running instance",
            None,
        )
        self.add_main_option(
            "background",
            ord("b"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Start without showing the window",
            None,
        )
        self.add_main_option(
            "version",
            ord("v"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Print the version and exit",
            None,
        )
        self.connect("handle-local-options", self._on_local_options)
        self.window: UtterWindow | None = None
        self._start_hidden = False
        self._pending_toggle = False
        self._held = False

    # ---- lifecycle -----------------------------------------------------------------------

    def _on_local_options(self, _app, options: GLib.VariantDict) -> int:
        if options.contains("version"):
            print(f"{APP_NAME} {VERSION}")
            return 0
        if options.contains("background"):
            self._start_hidden = True
        if options.contains("toggle"):
            try:
                self.register(None)
            except GLib.Error as error:
                print(f"Cannot register: {error.message}", file=sys.stderr)
                return 1
            if self.get_is_remote():
                self.activate_action("toggle", None)
                return 0
            self._start_hidden = True
            self._pending_toggle = True
        return -1

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.settings = get_settings()
        migrate_api_key(self.settings.get_string("enhance-provider"))
        data_dir = Path(GLib.get_user_data_dir()) / "utter"
        self.portal = Portal()
        self.shortcuts = GlobalShortcuts(self.portal)
        self.injector = TextInjector(self.portal, self.settings)
        self.store = ModelStore(data_dir / "models")
        self.history = History(data_dir / "history.db")
        self.recognizer = Recognizer()
        self.audio = AudioCapture()
        self.sounds = Sounds()
        self.dictation = Dictation(
            self.settings,
            self.store,
            self.recognizer,
            self.audio,
            self.injector,
            self.history,
            self.sounds,
        )
        connection = self.get_dbus_connection()
        self.overlay_feed = OverlayFeed(connection, self.dictation) if connection else None

        for name, callback in (
            ("toggle", lambda *_: self.dictation.toggle()),
            ("start", lambda *_: self.dictation.start()),
            ("stop", lambda *_: self.dictation.stop()),
            ("cancel", lambda *_: self.dictation.cancel()),
            ("show", lambda *_: self.activate()),
            ("preferences", lambda *_: self.show_preferences()),
            ("configure-shortcut", lambda *_: self.configure_shortcut()),
            ("about", lambda *_: self.show_about()),
            ("quit", lambda *_: self.quit_now()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.preferences", ["<primary>comma"])
        self.set_accels_for_action("app.quit", ["<primary>q"])
        self.set_accels_for_action("window.close", ["<primary>w"])
        self.set_accels_for_action("app.toggle", ["<primary>d"])
        self.set_accels_for_action("app.cancel", ["Escape"])

        self.shortcuts.connect("activated", self._on_shortcut_activated)
        self.shortcuts.connect("deactivated", self._on_shortcut_deactivated)
        self.shortcuts.connect("configure-failed", self._on_configure_failed)
        self.dictation.connect("error", self._on_error)
        self.dictation.connect("transcribed", self._on_transcribed)
        self.settings.connect("changed::run-in-background", lambda *_: self._sync_hold())
        self._sync_hold()

        self.shortcuts.start()
        self.dictation.preload()
        if self.settings.get_boolean("run-in-background"):
            self.request_background()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = UtterWindow(self, self.dictation, self.store, self.history, self.settings)
            self.window.set_hide_on_close(self.settings.get_boolean("run-in-background"))
            self.settings.connect(
                "changed::run-in-background",
                lambda *_: self.window.set_hide_on_close(
                    self.settings.get_boolean("run-in-background")
                ),
            )
        if self._pending_toggle:
            self._pending_toggle = False
            self.dictation.toggle()
        if self._start_hidden:
            self._start_hidden = False
            return
        self.window.present()

    def do_shutdown(self) -> None:
        if self.dictation.state == "listening":
            self.audio.stop()
        if self.overlay_feed is not None:
            self.overlay_feed.close()
        self.history.close()
        Adw.Application.do_shutdown(self)

    def _sync_hold(self) -> None:
        wanted = self.settings.get_boolean("run-in-background")
        if wanted and not self._held:
            self.hold()
            self._held = True
        elif not wanted and self._held:
            self.release()
            self._held = False

    def quit_now(self) -> None:
        if self._held:
            self.release()
            self._held = False
        self.quit()

    # ---- shortcut events -----------------------------------------------------------------

    def _on_shortcut_activated(self, *_args) -> None:
        if self.settings.get_string("activation-mode") == "push-to-talk":
            self.dictation.start()
        else:
            self.dictation.toggle()

    def _on_shortcut_deactivated(self, *_args) -> None:
        if self.settings.get_string("activation-mode") == "push-to-talk":
            self.dictation.stop()

    # ---- feedback ------------------------------------------------------------------------

    def _window_visible(self) -> bool:
        return self.window is not None and self.window.get_visible() and self.window.is_active()

    def _on_error(self, _dictation, message: str) -> None:
        if not self._window_visible():
            self.notify_user("utter-error", "Dictation failed", message)

    def _on_transcribed(self, _dictation, entry) -> None:
        if not self._window_visible() and self.injector.state != "ready":
            self.notify_user("utter-copied", "Copied to the clipboard", entry.text)

    def notify_user(self, notification_id: str, title: str, body: str) -> None:
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        notification.set_default_action("app.show")
        self.send_notification(notification_id, notification)

    # ---- dialogs and portals -------------------------------------------------------------

    def show_preferences(self) -> None:
        self.activate()
        PreferencesDialog(self).present(self.window)

    def configure_shortcut(self) -> None:
        def with_handle(handle: str) -> None:
            self.shortcuts.configure(handle)

        export_window_handle(self.window, with_handle)

    def _on_configure_failed(self, _shortcuts, message: str) -> None:
        """The portal has no ConfigureShortcuts. Send the user to Settings instead."""
        self.activate()
        dialog = Adw.AlertDialog(
            heading="Change the shortcut in Settings",
            body=f"{message} Open Settings › Apps › {APP_NAME} › Global Shortcuts "
            "to change the binding.",
        )
        dialog.add_response("close", "Close")
        dialog.add_response("settings", "Open Settings")
        dialog.set_response_appearance("settings", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("settings")

        def on_response(_dialog, response: str) -> None:
            if response == "settings":
                self.open_app_settings()

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def open_app_settings(self) -> None:
        """Ask GNOME Settings for this app's page over D-Bus. Silent on other desktops."""
        desktop_id = GLib.Variant("s", f"{APP_ID}.desktop")
        panel = GLib.Variant("(sav)", ("applications", [desktop_id]))
        self.portal.bus.call(
            "org.gnome.Settings",
            "/org/gnome/Settings",
            "org.gtk.Actions",
            "Activate",
            GLib.Variant("(sava{sv})", ("launch-panel", [panel], {})),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
        )

    def show_about(self) -> None:
        self.activate()
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="Jay W",
            version=VERSION,
            website=HOMEPAGE,
            issue_url=ISSUES,
            license_type=Gtk.License.GPL_3_0,
            comments="Dictate into any app. Speech recognition runs on this computer with "
            "sherpa-onnx and NVIDIA Parakeet or OpenAI Whisper models.",
        )
        about.present(self.window)

    def request_background(self) -> None:
        """Ask the Background portal to allow running hidden and, when set, autostart."""
        autostart = self.settings.get_boolean("autostart")

        def params(handle_token: str) -> GLib.Variant:
            options = {
                "handle_token": GLib.Variant("s", handle_token),
                "reason": GLib.Variant("s", "Utter listens for the dictation shortcut"),
                "autostart": GLib.Variant("b", autostart),
                "commandline": GLib.Variant("as", ["utter", "--background"]),
                "dbus-activatable": GLib.Variant("b", False),
            }
            return GLib.Variant("(sa{sv})", ("", options))

        def on_response(code: int, results: dict) -> None:
            if code != RESPONSE_OK:
                return
            if autostart and not results.get("autostart", False):
                self.settings.set_boolean("autostart", False)
                if self.window is not None:
                    self.window.toast("Autostart was not allowed by the desktop.")

        self.portal.request(
            "org.freedesktop.portal.Background", "RequestBackground", params, on_response
        )


def main(argv: list[str]) -> int:
    app = UtterApplication()
    return app.run(argv)
