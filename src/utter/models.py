"""Speech model catalogue, download and install. No GTK imports here."""

from __future__ import annotations

import shutil
import tarfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

RELEASE_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
USER_AGENT = "Utter (https://github.com/JayDoubleu/Utter)"

# Every language that the Language preference can hold. A code with a region is a Nemotron locale.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("auto", "Detect automatically"),
    ("en", "English"),
    ("en-GB", "English (United Kingdom)"),
    ("de", "German"),
    ("fr", "French"),
    ("fr-CA", "French (Canada)"),
    ("es", "Spanish"),
    ("es-ES", "Spanish (Spain)"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("pt-BR", "Portuguese (Brazil)"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("nb", "Norwegian"),
    ("fi", "Finnish"),
    ("et", "Estonian"),
    ("cs", "Czech"),
    ("sk", "Slovak"),
    ("hu", "Hungarian"),
    ("ro", "Romanian"),
    ("bg", "Bulgarian"),
    ("hr", "Croatian"),
    ("uk", "Ukrainian"),
    ("ru", "Russian"),
    ("el", "Greek"),
    ("tr", "Turkish"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("vi", "Vietnamese"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
)

# Nemotron 3.5 transcribes these languages without fine-tuning. Greek is not one of them.
_NEMOTRON_UNSUPPORTED = frozenset({"el"})

# Whisper names Norwegian "no". sherpa-onnx exits the process on a code that Whisper does not know.
_WHISPER_CODES = {"nb": "no"}


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    summary: str
    kind: str  # "transducer", "whisper" or "streaming"
    dirname: str
    files: dict[str, str]
    size_mb: int
    languages: str
    multilingual: bool = False
    url: str | None = field(default=None)

    @property
    def is_streaming(self) -> bool:
        """A streaming model decodes while the microphone records."""
        return self.kind == "streaming"

    @property
    def download_url(self) -> str:
        return self.url or f"{RELEASE_BASE}{self.dirname}.tar.bz2"


CATALOGUE: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="parakeet-tdt-0.6b-v3",
        name="Parakeet TDT 0.6B v3",
        summary="Fast and accurate. Punctuation and capitalisation. Recommended.",
        kind="transducer",
        dirname="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        files={
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
        size_mb=487,
        languages="25 European languages",
        multilingual=True,
    ),
    ModelSpec(
        id="parakeet-tdt-0.6b-v2",
        name="Parakeet TDT 0.6B v2",
        summary="Fast and accurate. English only.",
        kind="transducer",
        dirname="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        files={
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
        size_mb=482,
        languages="English",
    ),
    ModelSpec(
        id="nemotron-3.5-streaming",
        name="Nemotron 3.5 Streaming",
        summary="Shows the text while you speak. Lowest delay after you stop.",
        kind="streaming",
        dirname="sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-320ms-int8-2026-06-11",
        files={
            "encoder": "encoder.int8.onnx",
            "decoder": "decoder.int8.onnx",
            "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt",
        },
        size_mb=453,
        languages="40 languages",
        multilingual=True,
    ),
    ModelSpec(
        id="whisper-base.en",
        name="Whisper Base (English)",
        summary="Small and quick. Dictations up to 30 seconds.",
        kind="whisper",
        dirname="sherpa-onnx-whisper-base.en",
        files={
            "encoder": "base.en-encoder.int8.onnx",
            "decoder": "base.en-decoder.int8.onnx",
            "tokens": "base.en-tokens.txt",
        },
        size_mb=209,
        languages="English",
    ),
    ModelSpec(
        id="whisper-small",
        name="Whisper Small",
        summary="Multilingual. Dictations up to 30 seconds.",
        kind="whisper",
        dirname="sherpa-onnx-whisper-small",
        files={
            "encoder": "small-encoder.int8.onnx",
            "decoder": "small-decoder.int8.onnx",
            "tokens": "small-tokens.txt",
        },
        size_mb=639,
        languages="99 languages",
        multilingual=True,
    ),
    ModelSpec(
        id="whisper-turbo",
        name="Whisper Turbo",
        summary="Large-v3 Turbo. Best Whisper accuracy, slower. Dictations up to 30 seconds.",
        kind="whisper",
        dirname="sherpa-onnx-whisper-turbo",
        files={
            "encoder": "turbo-encoder.int8.onnx",
            "decoder": "turbo-decoder.int8.onnx",
            "tokens": "turbo-tokens.txt",
        },
        size_mb=564,
        languages="99 languages",
        multilingual=True,
    ),
)

DEFAULT_MODEL_ID = CATALOGUE[0].id


def find_spec(model_id: str) -> ModelSpec | None:
    for spec in CATALOGUE:
        if spec.id == model_id:
            return spec
    return None


def language_choices(spec: ModelSpec) -> tuple[tuple[str, str], ...]:
    """Return the (code, name) pairs that spec accepts. Empty when spec takes no language."""
    if not spec.multilingual:
        return ()
    if spec.kind == "whisper":
        return tuple(item for item in LANGUAGES if "-" not in item[0])
    if spec.kind == "streaming":
        return tuple(item for item in LANGUAGES if item[0] not in _NEMOTRON_UNSUPPORTED)
    return ()


def effective_language(spec: ModelSpec, language: str) -> str:
    """Return the choice of spec that is nearest to the Language preference."""
    codes = [code for code, _name in language_choices(spec)]
    if language in codes:
        return language
    base = language.partition("-")[0]
    return base if base in codes else "auto"


def recognizer_language(spec: ModelSpec, language: str) -> str:
    """Return the language string that sherpa-onnx accepts for spec."""
    if spec.kind == "whisper":
        if not spec.multilingual:
            return "en"
        code = effective_language(spec, language)
        return "" if code == "auto" else _WHISPER_CODES.get(code, code)
    return effective_language(spec, language)


def model_directory(root: Path, spec: ModelSpec) -> Path:
    return root / spec.dirname


def model_files(root: Path, spec: ModelSpec) -> dict[str, Path]:
    directory = model_directory(root, spec)
    return {key: directory / name for key, name in spec.files.items()}


def is_installed(root: Path, spec: ModelSpec) -> bool:
    return all(path.is_file() for path in model_files(root, spec).values())


def remove_model(root: Path, spec: ModelSpec) -> None:
    directory = model_directory(root, spec)
    if directory.is_dir():
        shutil.rmtree(directory)


ProgressCallback = Callable[[str, float], None]
"""Called with (phase, fraction). Phase is "downloading" or "extracting"."""


class ModelInstallError(Exception):
    pass


def install_model(root: Path, spec: ModelSpec, progress: ProgressCallback | None = None) -> Path:
    """Download and extract a model archive into root. Blocks. Returns the model directory."""
    root.mkdir(parents=True, exist_ok=True)
    archive = root / f"{spec.dirname}.tar.bz2.part"
    staging = root / f"{spec.dirname}.extracting"
    target = model_directory(root, spec)

    def report(phase: str, fraction: float) -> None:
        if progress is not None:
            progress(phase, max(0.0, min(1.0, fraction)))

    try:
        _download(spec.download_url, archive, report)
        report("extracting", 0.0)
        if staging.exists():
            shutil.rmtree(staging)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(staging, filter="data")
        extracted = staging / spec.dirname
        if not extracted.is_dir():
            children = [p for p in staging.iterdir() if p.is_dir()]
            if len(children) != 1:
                raise ModelInstallError("The archive does not contain a single model directory.")
            extracted = children[0]
        if target.exists():
            shutil.rmtree(target)
        extracted.rename(target)
        missing = [name for name, path in model_files(root, spec).items() if not path.is_file()]
        if missing:
            raise ModelInstallError(f"The archive is missing files: {', '.join(missing)}")
        report("extracting", 1.0)
        return target
    finally:
        archive.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _download(url: str, destination: Path, report: Callable[[str, float], None]) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_reported = -1.0
        report("downloading", 0.0)
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                fraction = done / total
                if fraction - last_reported >= 0.005:
                    last_reported = fraction
                    report("downloading", fraction)
        report("downloading", 1.0)
