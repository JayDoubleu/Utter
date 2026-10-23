import queue
import threading
from pathlib import Path

from utter.recognizer import PROVIDER, ModelLoader, RecognizerError


class FakeMainLoop:
    """Collects the calls that the worker posts, like run_on_main, and runs them on request."""

    def __init__(self) -> None:
        self.calls: queue.Queue = queue.Queue()

    def post(self, fn, *args) -> None:
        self.calls.put((fn, args))

    def run_next(self) -> None:
        fn, args = self.calls.get(timeout=5)
        fn(*args)


class BlockingLoad:
    """A model load that waits until the test releases it."""

    def __init__(self, error: str | None = None) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple] = []
        self.error = error

    def __call__(self, *args) -> None:
        self.calls.append(args)
        self.started.set()
        self.release.wait(timeout=5)
        if self.error is not None:
            raise RecognizerError(self.error)


def test_request_during_preload_gets_the_result():
    load = BlockingLoad()
    main = FakeMainLoop()
    loader = ModelLoader(load, main.post)
    results = []

    loader.request(("model",))  # the preload at startup has no callback
    assert load.started.wait(timeout=5)
    loader.request(("model",), results.append)  # the user starts a dictation
    load.release.set()
    main.run_next()

    assert results == [True]
    assert load.calls == [("model",)]
    assert not loader.busy


def test_every_waiting_callback_gets_the_error():
    load = BlockingLoad(error="Cannot load the model")
    main = FakeMainLoop()
    errors = []
    loader = ModelLoader(load, main.post, errors.append)
    results = []

    loader.request(("model",), results.append)
    assert load.started.wait(timeout=5)
    loader.request(("model",), results.append)
    load.release.set()
    main.run_next()

    assert results == [False, False]
    assert errors == ["Cannot load the model"]


def test_request_after_a_load_starts_a_new_load():
    load = BlockingLoad()
    load.release.set()
    main = FakeMainLoop()
    loader = ModelLoader(load, main.post)
    results = []

    loader.request(("first",), results.append)
    main.run_next()
    loader.request(("second",), results.append)
    main.run_next()

    assert results == [True, True]
    assert load.calls == [("first",), ("second",)]


def test_provider_config_turns_off_the_memory_arena():
    name, _, config = PROVIDER.partition(":")
    assert name == "cpu"
    assert "EnableCpuMemArena=0" in Path(config).read_text().splitlines()
