from utter.keys import (
    KEYSYM_RETURN,
    KEYSYM_SHIFT_L,
    delivery,
    is_terminal,
    key_events,
)


def test_a_line_break_is_shift_return():
    assert key_events("a\nb") == [
        (ord("a"), 1),
        (ord("a"), 0),
        (KEYSYM_SHIFT_L, 1),
        (KEYSYM_RETURN, 1),
        (KEYSYM_RETURN, 0),
        (KEYSYM_SHIFT_L, 0),
        (ord("b"), 1),
        (ord("b"), 0),
    ]


def test_control_characters_are_left_out():
    assert key_events("a\x07") == [(ord("a"), 1), (ord("a"), 0)]
    assert key_events("€") == [(0x010020AC, 1), (0x010020AC, 0)]


def test_terminals():
    assert is_terminal("com.mitchellh.ghostty.desktop")
    assert is_terminal("org.gnome.Ptyxis.desktop")
    assert is_terminal("org.gnome.Terminal.desktop")
    assert is_terminal("kitty")
    assert is_terminal("org.codeberg.dnkl.foot.desktop")
    assert is_terminal("org.gnome.Ptyxis.Devel.desktop")
    assert is_terminal("terminator.desktop")
    assert is_terminal("com.github.amezin.ddterm")
    assert not is_terminal("window:12")
    assert not is_terminal("org.gnome.TextEditor.desktop")
    assert not is_terminal("")


def test_a_terminal_gets_a_paste_for_lines():
    ghostty = "com.mitchellh.ghostty.desktop"
    assert delivery("1. One\n2. Two", "type", False, ghostty) == ("paste", True)
    assert delivery("One line", "type", False, ghostty) == ("type", True)
    assert delivery("One line", "paste", False, ghostty) == ("paste", True)


def test_other_apps_keep_the_settings():
    editor = "org.gnome.TextEditor.desktop"
    assert delivery("1. One\n2. Two", "type", False, editor) == ("type", False)
    assert delivery("1. One\n2. Two", "paste", True, "") == ("paste", True)
