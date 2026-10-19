"""Runs Utter in the sandbox and takes window screenshots through the shot helper extension.

take.sh runs this inside the Flatpak in a private GNOME Shell session. The private session
has no global shortcut binding and no keyring, so the script shows demo values for them.
"""

import sys
import time

sys.path.insert(1, "/app/share/utter")

import gi  # noqa: E402

gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from utter import main as utter_main  # noqa: E402
from utter import preferences as utter_preferences  # noqa: E402
from utter.shortcuts import GlobalShortcuts  # noqa: E402

OUT = sys.argv[1]
SHOT = ("org.utter.TestShot", "/org/utter/TestShot", "org.utter.TestShot")


def fake_shortcut(self, parent=""):
    self.trigger = "Super+Space"
    self._set_state("ready")


GlobalShortcuts.start = fake_shortcut
utter_main.UtterApplication.request_background = lambda self, *args, **kwargs: None
# A keyring lookup in the private session waits for a time-out.
utter_preferences.load_secret = lambda purpose: "demo-key-not-real"
utter_preferences.store_secret = lambda purpose, value: None

dialogs = []


class KeptPreferences(utter_main.PreferencesDialog):
    def __init__(self, app):
        super().__init__(app)
        dialogs.append(self)


utter_main.PreferencesDialog = KeptPreferences
app = utter_main.UtterApplication()
bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def shot(method, *args):
    """The shell waits for a new frame of the window, so the app must not block here."""
    signature = "(" + "".join("s" if isinstance(a, str) else "i" for a in args) + ")"
    replies = []
    bus.call(
        *SHOT,
        method,
        GLib.Variant(signature, args) if args else None,
        None,
        Gio.DBusCallFlags.NONE,
        10000,
        None,
        lambda connection, result: replies.append(connection.call_finish(result)),
    )
    context = GLib.MainContext.default()
    while not replies:
        context.iteration(True)


def wait(seconds):
    context = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.01)


def preference_pages(widget):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Adw.PreferencesPage):
            found.append(child)
        found.extend(preference_pages(child))
        child = child.get_next_sibling()
    return found


def run():
    shot("HideOverview")
    wait(6)  # The model loads.
    shot("ShotWindow", f"{OUT}/main.png")
    app.injector.state = "ready"
    app.injector.session = "/demo"
    app.injector.clipboard_enabled = True
    app.window.set_default_size(720, 760)
    wait(1)
    app.show_preferences()
    wait(1.5)
    dialog = dialogs[-1]
    pages = {page.get_title(): page for page in preference_pages(dialog)}
    for title in ("General", "Voice", "Cleanup", "Text"):
        dialog.set_visible_page(pages[title])
        wait(0.8)
        shot("ShotWindow", f"{OUT}/preferences-{title.lower()}.png")
    app.quit()
    return GLib.SOURCE_REMOVE


started = []


def on_activate(_app):
    # show_preferences() activates the app again.
    if not started:
        started.append(True)
        GLib.timeout_add(500, run)


app.connect("activate", on_activate)
app.run([])
