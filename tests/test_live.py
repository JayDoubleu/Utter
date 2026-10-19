import threading

from utter.live import LiveDecode


class FakeSession:
    def __init__(self, fail_on_feed: bool = False) -> None:
        self.fed: list[float] = []
        self.finished = False
        self.fail_on_feed = fail_on_feed

    def feed(self, samples) -> str:
        if self.fail_on_feed:
            raise RuntimeError("decode failed")
        self.fed.extend(samples)
        return f"{len(self.fed)} samples"

    def finish(self) -> str:
        self.finished = True
        return f"final {len(self.fed)}"


class FakeMicrophone:
    """Hands out the recording in blocks, like AudioCapture.read_new."""

    def __init__(self, recording: list[float], block: int) -> None:
        self.recording = recording
        self.block = block
        self.position = 0
        self.lock = threading.Lock()

    def read_new(self) -> list[float]:
        with self.lock:
            start = self.position
            self.position = min(len(self.recording), start + self.block)
            return self.recording[start : self.position]


def test_finish_decodes_every_sample_once():
    recording = [float(i) for i in range(1000)]
    microphone = FakeMicrophone(recording, block=90)
    session = FakeSession()
    partials: list[str] = []
    finals: list[str] = []
    errors: list[str] = []
    seen_some = threading.Event()

    def on_partial(text: str) -> None:
        partials.append(text)
        if len(partials) >= 3:
            seen_some.set()

    live = LiveDecode(session, microphone.read_new, on_partial, errors.append, poll_interval=0.001)
    live.start()
    assert seen_some.wait(5)
    live.finish(recording, finals.append)
    live.join(5)
    assert session.fed == recording
    assert session.finished
    assert finals == ["final 1000"]
    assert errors == []
    assert partials == sorted(set(partials), key=partials.index)


def test_cancel_reports_nothing():
    microphone = FakeMicrophone([0.0] * 100, block=10)
    session = FakeSession()
    errors: list[str] = []
    live = LiveDecode(session, microphone.read_new, lambda _text: None, errors.append, 0.001)
    live.start()
    live.cancel()
    live.join(5)
    assert not session.finished
    assert errors == []


def test_feed_error_is_reported_once():
    microphone = FakeMicrophone([0.0] * 100, block=10)
    errors: list[str] = []
    reported = threading.Event()

    def on_error(message: str) -> None:
        errors.append(message)
        reported.set()

    live = LiveDecode(
        FakeSession(fail_on_feed=True), microphone.read_new, lambda _text: None, on_error, 0.001
    )
    live.start()
    assert reported.wait(5)
    live.join(5)
    assert errors == ["decode failed"]
