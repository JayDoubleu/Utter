"""Pure text formatting: spoken punctuation, tidy up, dictionary, shortcut labels."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Longest phrases first so "exclamation mark" wins over a shorter overlap.
SPOKEN_PUNCTUATION: tuple[tuple[str, str], ...] = (
    ("exclamation point", "!"),
    ("exclamation mark", "!"),
    ("question mark", "?"),
    ("new paragraph", "\n\n"),
    ("full stop", "."),
    ("new line", "\n"),
    ("newline", "\n"),
    ("open quote", "“"),
    ("close quote", "”"),
    ("open parenthesis", "("),
    ("close parenthesis", ")"),
    ("open paren", "("),
    ("close paren", ")"),
    ("open bracket", "["),
    ("close bracket", "]"),
    ("percent sign", "%"),
    ("at sign", "@"),
    ("semicolon", ";"),
    ("ellipsis", "..."),
    ("ampersand", "&"),
    ("underscore", "_"),
    ("asterisk", "*"),
    ("hashtag", "#"),
    ("period", "."),
    ("comma", ","),
    ("colon", ":"),
    ("hyphen", "-"),
)

_CLOSING = ".,?!:;)]”"
_OPENING = "([“"


def _compile_spoken() -> list[tuple[re.Pattern[str], str]]:
    out = []
    for phrase, symbol in SPOKEN_PUNCTUATION:
        words = r"\s+".join(re.escape(w) for w in phrase.split())
        # The recogniser may already put a punctuation mark after the spoken word.
        pattern = re.compile(rf"(?<![\w'])(?:{words})(?![\w'])[.,!?]?", re.IGNORECASE)
        out.append((pattern, symbol))
    return out


_SPOKEN_PATTERNS = _compile_spoken()


def apply_spoken_punctuation(text: str) -> str:
    """Replace spoken punctuation words with the symbols."""
    for pattern, symbol in _SPOKEN_PATTERNS:
        text = pattern.sub(lambda _m, s=symbol: f"\x00{s}\x00", text)
    # Remove the space before a closing mark and after an opening mark.
    text = re.sub(rf"[ \t]*\x00([{re.escape(_CLOSING)}]+)\x00", r"\1", text)
    text = re.sub(rf"\x00([{re.escape(_OPENING)}])\x00[ \t]*", r"\1", text)
    text = re.sub(r"[ \t]*\x00(\n+)\x00[ \t]*", r"\1", text)
    text = re.sub(r"\x00([^\x00]*)\x00", r"\1", text)
    return text


def apply_dictionary(text: str, entries: Iterable[str]) -> str:
    """Apply "spoken=replacement" entries with word boundaries, case-insensitive."""
    for entry in entries:
        if "=" not in entry:
            continue
        spoken, replacement = entry.split("=", 1)
        spoken = spoken.strip()
        replacement = replacement.strip()
        if not spoken:
            continue
        words = r"\s+".join(re.escape(w) for w in spoken.split())
        pattern = re.compile(rf"(?<!\w)(?:{words})(?!\w)", re.IGNORECASE)
        text = pattern.sub(lambda _m, r=replacement: r, text)
    return text


def _capitalise_sentences(text: str) -> str:
    def upper_first(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"^(\s*)(\w)", upper_first, text)
    text = re.sub(r"([.!?]\s+|\n+\s*)(\w)", upper_first, text)
    return text


def tidy(text: str, *, auto_capitalise: bool = True) -> str:
    """Normalise spacing and capitalisation."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(rf" +([{re.escape(_CLOSING)}])", r"\1", text)
    text = re.sub(rf"([{re.escape(_OPENING)}]) +", r"\1", text)
    text = re.sub(r"([.!?,;:])(?=[A-Za-zÀ-ɏ])", r"\1 ", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = text.strip()
    if auto_capitalise:
        text = _capitalise_sentences(text)
    return text


def format_transcript(
    text: str,
    *,
    spoken_punctuation: bool = True,
    auto_capitalise: bool = True,
    dictionary: Iterable[str] = (),
) -> str:
    """Run the full formatting pipeline on a raw transcript."""
    if spoken_punctuation:
        text = apply_spoken_punctuation(text)
    text = apply_dictionary(text, dictionary)
    return tidy(text, auto_capitalise=auto_capitalise)


# ---- global shortcut labels -------------------------------------------------------------

MODIFIER_LABELS = {
    "control": "Ctrl",
    "primary": "Ctrl",
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "super": "Super",
    "meta": "Meta",
    "hyper": "Hyper",
}

# A GTK accelerator such as <Control><Alt>space inside a longer sentence.
_ACCELERATOR = re.compile(r"(?:<[A-Za-z0-9]+>)+[^\s<>]+")
_LEADING_VERB = re.compile(r"^(?:Press|Hold)\s+", re.IGNORECASE)


def describe_trigger(description: str) -> str:
    """Turn a portal trigger_description into a short label such as "Ctrl+Alt+Space".

    GNOME answers with "Press <Control><Alt>space". The verb goes because the UI adds
    its own, and each accelerator becomes a readable label. Other desktops answer
    with a plain label, which comes back unchanged.
    """
    text = _LEADING_VERB.sub("", description.strip())
    return _ACCELERATOR.sub(lambda match: _accelerator_label(match.group(0)), text)


def _accelerator_label(accelerator: str) -> str:
    parts: list[str] = []
    rest = accelerator
    while rest.startswith("<"):
        end = rest.index(">")
        name = rest[1:end]
        parts.append(MODIFIER_LABELS.get(name.lower(), name.capitalize()))
        rest = rest[end + 1 :]
    parts.append(_key_label(rest))
    return "+".join(parts)


def _key_label(key: str) -> str:
    key = key.replace("_", " ")
    return key[:1].upper() + key[1:]
