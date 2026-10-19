"""Plays one dictation over the Utter Overlay D-Bus interface and takes screenshots.

take.sh runs this in a private GNOME Shell session in place of Utter. The "stills" mode takes
the desktop and panel screenshots. The "frames" mode saves about 16 frames per second of the
panel for the animation.
"""

import math
import sys
import time

from gi.repository import Gio, GLib

OUT, MODE = sys.argv[1], sys.argv[2]
PATH = "/io/github/jaydoubleu/Utter/Overlay"
IFACE = "io.github.jaydoubleu.Utter.Overlay"
XML = f"""<node><interface name="{IFACE}">
<method name="GetState"><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<signal name="StateChanged"><arg type="s"/></signal><signal name="Level"><arg type="d"/></signal>
<signal name="Partial"><arg type="s"/></signal></interface></node>"""

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
state = ["idle", ""]
bus.register_object(
    PATH,
    Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
    lambda *a: a[-1].return_value(GLib.Variant("(ss)", tuple(state))),
    None,
    None,
)
bus.call_sync(
    "org.freedesktop.DBus",
    "/org/freedesktop/DBus",
    "org.freedesktop.DBus",
    "RequestName",
    GLib.Variant("(su)", ("io.github.jaydoubleu.Utter", 0)),
    None,
    0,
    -1,
    None,
)
ctx = GLib.MainContext.default()
W, H = 1440, 900
AREA = (W // 2 - 230, H - 210, 460, 190)
frames = [0]


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.004)


def emit(name, sig, value):
    bus.emit_signal(None, PATH, IFACE, name, GLib.Variant(sig, (value,)))


def set_state(s):
    state[0] = s
    emit("StateChanged", "(s)", s)


def shoot(method, path, *area):
    sig = "(s" + "i" * len(area) + ")"
    bus.call_sync(
        "org.utter.TestShot",
        "/org/utter/TestShot",
        "org.utter.TestShot",
        method,
        GLib.Variant(sig, (path, *area)),
        None,
        0,
        10000,
        None,
    )


def full(name):
    shoot("Shot", f"{OUT}/{name}.png")


def frame():
    if MODE == "frames":
        frames[0] += 1
        shoot("ShotArea", f"{OUT}/frames/{frames[0]:04d}.png", *AREA)


t = [0.0]


def speak(seconds, loud=True):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        t[0] += 0.05
        level = 0.5 + 0.45 * math.sin(t[0] * 6.3) * math.sin(t[0] * 1.7) if loud else 0.05
        emit("Level", "(d)", max(0.0, level))
        pump(0.035)
        frame()


pump(1.0)
set_state("listening")
speak(0.7)
words = (
    "Thanks for sending the notes from Tuesday. I read them on the train this morning, "
    "and I think the new release plan works well. Can we move the review to Thursday "
    "afternoon so that Priya can join us?"
).split()
text = ""
for i, w in enumerate(words):
    text = f"{text} {w}".strip()
    if i % 3 == 2 or i == len(words) - 1:
        state[1] = text[-150:] if len(text) <= 150 else "…" + text[-149:].lstrip()
        emit("Partial", "(s)", state[1])
    speak(0.16)
    if MODE == "stills" and i == 24:
        full("overlay-desktop")
speak(0.4)
if MODE == "stills":
    shoot("ShotArea", f"{OUT}/overlay-listening.png", *AREA)
set_state("enhancing")
speak(1.4, loud=False)
if MODE == "stills":
    shoot("ShotArea", f"{OUT}/overlay-enhancing.png", *AREA)
set_state("typing")
speak(0.2, loud=False)
set_state("idle")
speak(0.8, loud=False)
