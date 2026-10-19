"""Speech recognition with sherpa-onnx. Offline models and streaming models."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .models import ModelSpec, model_files

SAMPLE_RATE = 16000

# Silence that flushes the last chunk of a streaming model. A shorter tail loses the last word.
TAIL_PADDING = 0.66


class RecognizerError(Exception):
    pass


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

    def finish(self) -> str:
        """Flush the last chunk and return the final text. Do not use the session again."""
        try:
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


class Recognizer:
    """Holds one loaded sherpa-onnx recogniser. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._recognizer = None
        self._key: tuple | None = None
        self._streaming = False
        self._language = "auto"

    @property
    def loaded_key(self) -> tuple | None:
        return self._key

    @property
    def is_streaming(self) -> bool:
        """True when the loaded model decodes while the microphone records."""
        return self._streaming

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
                    sample_rate=SAMPLE_RATE,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    model_type="nemo_transducer",
                )
            elif spec.kind == "whisper":
                if spec.multilingual:
                    whisper_language = "" if language == "auto" else language
                else:
                    whisper_language = "en"
                recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    tokens=paths["tokens"],
                    language=whisper_language,
                    task="transcribe",
                    num_threads=threads,
                )
            elif spec.kind == "streaming":
                recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    joiner=paths["joiner"],
                    tokens=paths["tokens"],
                    num_threads=threads,
                    sample_rate=SAMPLE_RATE,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    provider="cpu",
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
            self._language = language

    def unload(self) -> None:
        with self._lock:
            self._recognizer = None
            self._key = None
            self._streaming = False

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
            session = self.start_stream()
            session.feed(samples)
            return session.finish()
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
