import numpy as np

from utter.recognizer import SAMPLE_RATE, RedecodeSession


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeDecoder:
    """Returns one word for each full second of audio, and records each call."""

    def __init__(self, words: dict[int, str] | None = None) -> None:
        self.calls: list[int] = []
        self.words = words or {}

    def __call__(self, audio: np.ndarray) -> str:
        self.calls.append(len(audio))
        seconds = len(audio) // SAMPLE_RATE
        return " ".join(self.words.get(i, f"w{i}") for i in range(seconds)).strip()


def seconds(value: float) -> np.ndarray:
    return np.zeros(int(value * SAMPLE_RATE), dtype=np.float32)


def make_session(decoder, clock, segment: float = 15.0) -> RedecodeSession:
    return RedecodeSession(decoder, min_audio=1.0, interval=0.6, segment=segment, clock=clock)


def test_no_decode_before_the_first_second():
    decoder, clock = FakeDecoder(), FakeClock()
    session = make_session(decoder, clock)
    assert session.feed(seconds(0.9)) == ""
    assert decoder.calls == []
    assert session.feed(seconds(0.1)) == "w0"
    assert decoder.calls == [SAMPLE_RATE]


def test_decodes_again_only_after_the_interval():
    decoder, clock = FakeDecoder(), FakeClock()
    session = make_session(decoder, clock)
    session.feed(seconds(1.0))
    clock.now = 0.5
    assert session.feed(seconds(1.0)) == "w0"
    assert len(decoder.calls) == 1
    clock.now = 0.6
    assert session.feed(seconds(0.0)) == "w0 w1"
    assert decoder.calls == [SAMPLE_RATE, 2 * SAMPLE_RATE]


def test_empty_decode_keeps_the_previous_preview():
    decoder, clock = FakeDecoder(), FakeClock()
    session = make_session(decoder, clock)
    session.feed(seconds(2.0))
    decoder.words = {0: "", 1: ""}
    clock.now = 1.0
    assert session.feed(seconds(0.5)) == "w0 w1"


def test_full_segment_is_fixed_and_not_decoded_again():
    decoder, clock = FakeDecoder(), FakeClock()
    session = make_session(decoder, clock, segment=3.0)
    session.feed(seconds(2.0))
    clock.now = 1.0
    assert session.feed(seconds(2.0)) == "w0 w1 w2"
    assert decoder.calls[-1] == 3 * SAMPLE_RATE
    clock.now = 2.0
    assert session.feed(seconds(1.5)) == "w0 w1 w2 w0 w1"
    assert decoder.calls[-1] == int(2.5 * SAMPLE_RATE)


def test_finish_decodes_the_complete_recording_once():
    decoder, clock = FakeDecoder(), FakeClock()
    session = make_session(decoder, clock, segment=3.0)
    session.feed(seconds(4.0))
    decoder.calls.clear()
    assert session.finish(seconds(1.0)) == "w0 w1 w2 w3 w4"
    assert decoder.calls == [5 * SAMPLE_RATE]
