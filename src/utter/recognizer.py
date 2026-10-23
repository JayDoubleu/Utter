"""Speech recognition with sherpa-onnx. Offline models and streaming models."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .models import ModelSpec, model_files, recognizer_language

SAMPLE_RATE = 16000

# Silence that flushes the last chunk of a streaming model. A shorter tail loses the last word.
TAIL_PADDING = 0.66

# FluidVoice timings for offline models: the first preview after 1 s, then one every 0.6 s.
REDECODE_MIN_AUDIO = 1.0
REDECODE_INTERVAL = 0.6
# Parakeet needs about 55 ms per second of audio on 4 threads. Segments keep each tick short.
REDECODE_SEGMENT = 15.0


# The CPU provider with the session options in onnx-cpu.cfg. The options turn off the memory
# arena, which kept up to 2 GB after long dictations.
PROVIDER = f"cpu:{Path(__file__).with_name('onnx-cpu.cfg')}"


class RecognizerError(Exception):
    pass


class ModelLoader:
    """Runs one model load at a time in a worker thread.

    A request during a load does not start a second load. Its callback waits, and each waiting
    callback gets the result of the load in progress. `post` moves the result to the main loop.
    """

    def __init__(
        self,
        load: Callable[..., None],
        post: Callable[..., None],
        on_finished: Callable[[str | None], None] | None = None,
    ) -> None:
        self._load = load
        self._post = post
        self._on_finished = on_finished
        self._waiters: list[Callable[[bool], None]] = []
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def request(self, args: tuple, on_done: Callable[[bool], None] | None = None) -> None:
        if on_done is not None:
            self._waiters.append(on_done)
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, args=args, daemon=True, name="model-load").start()

    def _work(self, *args) -> None:
        error = None
        try:
            self._load(*args)
        except RecognizerError as exc:
            error = str(exc)
        self._post(self._finish, error)

    def _finish(self, error: str | None) -> None:
        self._busy = False
        waiters, self._waiters = self._waiters, []
        if self._on_finished is not None:
            self._on_finished(error)
        for on_done in waiters:
            on_done(error is None)


class StreamingSession:
    """One live decode with a streaming model. Use each session from one thread only."""

    def __init__(self, recognizer, decode_lock: threading.Lock, language: str) -> None:
        self._recognizer = recognizer
        self._decode_lock = decode_lock
        self._stream = recognizer.create_stream()
        self._stream.set_option("language", language)

    def feed(self, samples: np.ndarray) -> str:
        """Decode more float32 mono samples. Returns the text so far. The text only grows."""
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        try:
            self._stream.accept_waveform(SAMPLE_RATE, samples)
            return self._decode()
        except Exception as error:  # sherpa raises plain RuntimeError
            raise RecognizerError(f"Live recognition failed: {error}") from error

    def finish(self, samples: np.ndarray | None = None) -> str:
        """Add the last samples, flush and return the final text. Do not use the session again."""
        try:
            if samples is not None and len(samples):
                self._stream.accept_waveform(SAMPLE_RATE, np.asarray(samples, dtype=np.float32))
            tail = np.zeros(int(TAIL_PADDING * SAMPLE_RATE), dtype=np.float32)
            self._stream.accept_waveform(SAMPLE_RATE, tail)
            self._stream.input_finished()
            return self._decode()
        except Exception as error:
            raise RecognizerError(f"Live recognition failed: {error}") from error

    def _decode(self) -> str:
        with self._decode_lock:
            while self._recognizer.is_ready(self._stream):
                self._recognizer.decode_stream(self._stream)
            return self._recognizer.get_result(self._stream).strip()


class RedecodeSession:
    """Live preview for an offline model. Decodes the recording again at intervals.

    The preview decodes the recording in segments of REDECODE_SEGMENT seconds. The text of a
    full segment stays fixed, so a tick never decodes more than one segment. finish() decodes
    the complete recording once, so the final text does not depend on the segments.
    """

    def __init__(
        self,
        transcribe: Callable[[np.ndarray], str],
        min_audio: float = REDECODE_MIN_AUDIO,
        interval: float = REDECODE_INTERVAL,
        segment: float = REDECODE_SEGMENT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transcribe = transcribe
        self._min_samples = int(min_audio * SAMPLE_RATE)
        self._interval = interval
        self._segment_samples = int(segment * SAMPLE_RATE)
        self._clock = clock
        self._chunks: list[np.ndarray] = []
        self._total = 0
        self._segment_start = 0
        self._committed = ""
        self._current = ""
        self._last_decode: float | None = None

    def feed(self, samples) -> str:
        """Add samples. Decodes when the interval has passed. Returns the preview text."""
        if len(samples):
            self._chunks.append(np.asarray(samples, dtype=np.float32))
            self._total += len(samples)
        if self._total < self._min_samples:
            return self._text()
        if self._last_decode is not None and self._clock() - self._last_decode < self._interval:
            return self._text()
        audio = self._audio()
        end = min(self._total, self._segment_start + self._segment_samples)
        text = self._transcribe(audio[self._segment_start : end])
        if end - self._segment_start >= self._segment_samples:
            self._committed = _join(self._committed, text)
            self._current = ""
            self._segment_start = end
        elif text:
            # FluidVoice keeps the previous preview when a decode gives no text.
            self._current = text
        self._last_decode = self._clock()
        return self._text()

    def finish(self, samples=None) -> str:
        """Add the last samples and decode the complete recording."""
        if samples is not None and len(samples):
            self._chunks.append(np.asarray(samples, dtype=np.float32))
        return self._transcribe(self._audio())

    def _audio(self) -> np.ndarray:
        if len(self._chunks) > 1:
            self._chunks = [np.concatenate(self._chunks)]
        return self._chunks[0] if self._chunks else np.zeros(0, dtype=np.float32)

    def _text(self) -> str:
        return _join(self._committed, self._current)


def _join(first: str, second: str) -> str:
    return f"{first} {second}".strip()


class Recognizer:
    """Holds one loaded sherpa-onnx recogniser. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._recognizer = None
        self._key: tuple | None = None
        self._streaming = False
        self._kind = ""
        self._language = "auto"

    @property
    def loaded_key(self) -> tuple | None:
        return self._key

    def is_loaded(self, spec: ModelSpec, language: str, num_threads: int) -> bool:
        return self._key == self._make_key(spec, language, num_threads)

    @staticmethod
    def _make_key(spec: ModelSpec, language: str, num_threads: int) -> tuple:
        return (spec.id, language, num_threads)

    def load(self, spec: ModelSpec, root: Path, language: str, num_threads: int) -> None:
        """Load the model. Blocks for several seconds. Safe to call from a worker thread."""
        key = self._make_key(spec, language, num_threads)
        if self._key == key and self._recognizer is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as error:
            raise RecognizerError("The sherpa-onnx package is not installed.") from error

        paths = {name: str(path) for name, path in model_files(root, spec).items()}
        threads = max(1, int(num_threads))
        try:
            if spec.kind == "transducer":
                recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    joiner=paths["joiner"],
                    tokens=paths["tokens"],
                    num_threads=threads,
                    provider=PROVIDER,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    model_type="nemo_transducer",
                )
            elif spec.kind == "whisper":
                recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    tokens=paths["tokens"],
                    language=recognizer_language(spec, language),
                    task="transcribe",
                    num_threads=threads,
                    provider=PROVIDER,
                )
            elif spec.kind == "streaming":
                recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    joiner=paths["joiner"],
                    tokens=paths["tokens"],
                    num_threads=threads,
                    provider=PROVIDER,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=80,
                    decoding_method="greedy_search",
                )
            else:
                raise RecognizerError(f"Unknown model kind: {spec.kind}")
        except RecognizerError:
            raise
        except Exception as error:  # sherpa raises plain RuntimeError
            raise RecognizerError(f"Cannot load {spec.name}: {error}") from error

        with self._lock:
            self._recognizer = recognizer
            self._key = key
            self._streaming = spec.is_streaming
            self._kind = spec.kind
            self._language = recognizer_language(spec, language)

    def unload(self) -> None:
        with self._lock:
            self._recognizer = None
            self._key = None
            self._streaming = False
            self._kind = ""

    def start_live(self) -> StreamingSession | RedecodeSession | None:
        """Open a live decode on the loaded model. None when the model has no live preview.

        A streaming model decodes each chunk once. A transducer model decodes the recording
        again at intervals. Whisper models stop at 30 seconds and have no live preview.
        """
        with self._lock:
            recognizer, kind = self._recognizer, self._kind
        if recognizer is None:
            raise RecognizerError("No speech model is loaded.")
        if kind == "transducer":
            return RedecodeSession(self.transcribe)
        if kind == "streaming":
            return self.start_stream()
        return None

    def start_stream(self) -> StreamingSession:
        """Open a live decode on the loaded streaming model."""
        with self._lock:
            recognizer, streaming, language = self._recognizer, self._streaming, self._language
        if recognizer is None or not streaming:
            raise RecognizerError("No streaming speech model is loaded.")
        try:
            return StreamingSession(recognizer, self._decode_lock, language)
        except Exception as error:
            raise RecognizerError(f"Cannot start live recognition: {error}") from error

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        """Decode float32 mono samples in [-1, 1]. Blocks."""
        with self._lock:
            recognizer, streaming = self._recognizer, self._streaming
        if recognizer is None:
            raise RecognizerError("No speech model is loaded.")
        if streaming:
            return self.start_stream().finish(samples)
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
