"""Offline speech recognition with sherpa-onnx."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .models import ModelSpec, model_files

SAMPLE_RATE = 16000


class RecognizerError(Exception):
    pass


class Recognizer:
    """Holds one loaded sherpa-onnx offline recogniser. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recognizer = None
        self._key: tuple | None = None

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
            else:
                raise RecognizerError(f"Unknown model kind: {spec.kind}")
        except RecognizerError:
            raise
        except Exception as error:  # sherpa raises plain RuntimeError
            raise RecognizerError(f"Cannot load {spec.name}: {error}") from error

        with self._lock:
            self._recognizer = recognizer
            self._key = key

    def unload(self) -> None:
        with self._lock:
            self._recognizer = None
            self._key = None

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        """Decode float32 mono samples in [-1, 1]. Blocks."""
        with self._lock:
            recognizer = self._recognizer
        if recognizer is None:
            raise RecognizerError("No speech model is loaded.")
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
