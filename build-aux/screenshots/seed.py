"""Writes demo settings and a demo history for the screenshots. take.sh runs it in the Flatpak."""

import sys
import time

sys.path.insert(1, "/app/share/utter")

from gi.repository import Gio  # noqa: E402

from utter.history import History  # noqa: E402

MODEL = "parakeet-tdt-0.6b-v2"
# (age in seconds, text, duration in seconds)
DICTATIONS = [
    (
        26 * 3600,
        "Can you send me the slides from this morning? I want to add the new numbers "
        "before Friday.",
        9,
    ),
    (5 * 3600, "Remind the team that the release branch freezes on Thursday at noon.", 6),
    (
        2 * 3600,
        "Thanks for the quick review. I fixed the typo in the README and pushed a new commit.",
        8,
    ),
    (40 * 60, "Let's meet at 3 pm in the small room. I'll bring the printed plan.", 6),
    (
        3 * 60,
        "The build passed on all three platforms, so I think we can tag the release today.",
        7,
    ),
]

settings = Gio.Settings.new("io.github.jaydoubleu.Utter")
settings.set_string("model-id", MODEL)
settings.set_string("language", "en")
settings.set_boolean("enhance-enabled", True)
settings.set_string("enhance-provider", "anthropic")
settings.set_string("enhance-base-url", "https://api.anthropic.com")
settings.set_string("enhance-model", "claude-haiku-5-5")
settings.set_boolean("run-in-background", False)
settings.set_strv("dictionary", ["flat pack=Flatpak", "gnome=GNOME", "k eights=k8s"])
settings.set_int("window-height", 720)
Gio.Settings.sync()

history = History(sys.argv[1])
now = time.time()
for age, text, duration in DICTATIONS:
    entry = history.add(text, text.lower().rstrip("."), MODEL, duration)
    history._db.execute("UPDATE entries SET created_at=? WHERE id=?", (now - age, entry.id))
history._db.commit()
