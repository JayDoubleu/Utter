from utter.formatting import (
    apply_dictionary,
    apply_spoken_punctuation,
    describe_trigger,
    format_transcript,
    tail_preview,
    tidy,
)


def test_spoken_punctuation_basic():
    assert apply_spoken_punctuation("hello comma world period") == "hello, world."


def test_spoken_punctuation_when_recogniser_added_a_mark():
    assert apply_spoken_punctuation("Hello comma, world period.") == "Hello, world."


def test_spoken_punctuation_multiword_and_newline():
    text = "first line new line second line question mark"
    assert apply_spoken_punctuation(text) == "first line\nsecond line?"


def test_spoken_punctuation_quotes_and_parens():
    text = "he said open quote hi close quote open paren yes close paren"
    assert apply_spoken_punctuation(text) == "he said “hi” (yes)"


def test_spoken_punctuation_does_not_touch_inner_words():
    assert apply_spoken_punctuation("the commandos") == "the commandos"


def test_dictionary_case_insensitive_word_boundary():
    out = apply_dictionary("send it to jay double you now", ["jay double you=JayDoubleu"])
    assert out == "send it to JayDoubleu now"
    assert apply_dictionary("kubernetes", ["kube=k8s"]) == "kubernetes"


def test_tidy_capitalises_sentences_and_fixes_spacing():
    out = tidy("  hello .this is a test .ok  ", auto_capitalise=True)
    assert out == "Hello. This is a test. Ok"


def test_tidy_keeps_case_when_disabled():
    assert tidy("hello world", auto_capitalise=False) == "hello world"


def test_full_pipeline():
    out = format_transcript(
        "um send the invoice comma please new paragraph thanks period",
        spoken_punctuation=True,
        auto_capitalise=True,
        dictionary=["um=", "invoice=Invoice #42"],
    )
    assert out == "Send the Invoice #42, please\n\nThanks."


def test_describe_trigger_gnome_form():
    assert describe_trigger("Press <Control><Alt>space") == "Ctrl+Alt+Space"


def test_describe_trigger_two_accelerators():
    text = "Press <Super>d or <Shift><Control>Page_Up"
    assert describe_trigger(text) == "Super+D or Shift+Ctrl+Page Up"


def test_describe_trigger_plain_label_unchanged():
    assert describe_trigger("Ctrl+Alt+Space") == "Ctrl+Alt+Space"


def test_describe_trigger_empty():
    assert describe_trigger("") == ""


def test_tail_preview_keeps_short_text():
    assert tail_preview("hello  world\nagain") == "hello world again"


def test_tail_preview_cuts_at_a_word():
    text = " ".join(f"word{i}" for i in range(100))
    preview = tail_preview(text, limit=30)
    assert preview.startswith("…word")
    assert preview.endswith("word99")
    assert len(preview) <= 31


def test_tail_preview_without_spaces():
    assert tail_preview("x" * 50, limit=10) == "…" + "x" * 10
