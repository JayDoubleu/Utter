"""Key events for typed text, and the terminal apps that need a paste. No GTK imports here."""

from __future__ import annotations

KEYSYM_RETURN = 0xFF0D
KEYSYM_TAB = 0xFF09
KEYSYM_SHIFT_L = 0xFFE1

# Return sends a message in chat apps and in Claude Code. Shift+Return makes a new line.
LINE_BREAK = [(KEYSYM_SHIFT_L, 1), (KEYSYM_RETURN, 1), (KEYSYM_RETURN, 0), (KEYSYM_SHIFT_L, 0)]

# Desktop file ids without ".desktop", in lower case. A terminal pastes with Ctrl+Shift+V.
TERMINALS = frozenset(
    {
        "alacritty",
        "app.devsuite.ptyxis",
        "com.gexperts.tilix",
        "com.mitchellh.ghostty",
        "com.raggesilver.blackbox",
        "dev.warp.warp",
        "foot",
        "footclient",
        "io.elementary.terminal",
        "kitty",
        "org.alacritty.alacritty",
        "org.contourterminal.contour",
        "org.gnome.console",
        "org.gnome.ptyxis",
        "org.gnome.terminal",
        "org.kde.konsole",
        "org.wezfurlong.wezterm",
        "org.xfce.terminal",
        "xterm",
    }
)


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


def key_events(text: str) -> list[tuple[int, int]]:
    """Return the (keysym, pressed) events that type the text."""
    events: list[tuple[int, int]] = []
    for char in text:
        if char == "\n":
            events.extend(LINE_BREAK)
            continue
        keysym = keysym_for(char)
        if keysym is not None:
            events.extend(((keysym, 1), (keysym, 0)))
    return events


def is_terminal(app_id: str) -> bool:
    """True if the desktop file id belongs to a terminal emulator."""
    name = app_id.lower().removesuffix(".desktop")
    return name in TERMINALS or "terminal" in name


def delivery(text: str, mode: str, use_shift: bool, app_id: str) -> tuple[str, bool]:
    """Return the mode ("type" or "paste") and the Shift setting for a paste into the app.

    A typed line break is Shift+Return, which a shell runs as Return. So a terminal gets a
    paste for text with line breaks, and keeps the lines in one block until the user presses
    Return. A terminal pastes with Ctrl+Shift+V.
    """
    if not is_terminal(app_id):
        return mode, use_shift
    return ("paste" if "\n" in text else mode), True
