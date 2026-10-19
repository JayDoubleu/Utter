"""Dictation state machine: record, recognise, format, enhance, deliver."""

from __future__ import annotations

import threading
import time

import numpy as np
from gi.repository import Gio, GObject

from .audio import SAMPLE_RATE, AudioCapture, AudioError
from .enhance import EnhanceError, enhance, find_provider
from .formatting import format_transcript
from .history import History
from .injector import TextInjector
from .live import LiveDecode
from .mainthread import run_on_main
from .models import DEFAULT_MODEL_ID, ModelSpec, find_spec
from .modelstore import ModelStore
from .recognizer import Recognizer, RecognizerError
from .secrets import load_api_key
from .sounds import Sounds

MIN_DURATION = 0.35

STATE_LABELS = {
    "idle": "Ready",
    "loading": "Loading the speech model",
    "listening": "Listening",
    "transcribing": "Transcribing",
    "enhancing": "Cleaning up",
    "typing": "Typing",
}


class Dictation(GObject.Object):
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "level": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "partial": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "transcribed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "notice": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(
        self,
        settings: Gio.Settings,
        store: ModelStore,
        recognizer: Recognizer,
        audio: AudioCapture,
        injector: TextInjector,
        history: History,
        sounds: Sounds,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.store = store
        self.recognizer = recognizer
        self.audio = audio
        self.injector = injector
        self.history = history
        self.sounds = sounds
        self._state = "idle"
        self._cancel_pending_start = False
        self._loading = False
        self._live: LiveDecode | None = None
        self.audio.connect("level", lambda _audio, level: self.emit("level", level))
        self.audio.connect("error", self._on_audio_error)
        for key in ("model-id", "language", "num-threads"):
            self.settings.connect(f"changed::{key}", lambda *_: self._on_model_setting_changed())

    # ---- state ---------------------------------------------------------------------------

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_busy(self) -> bool:
        return self._state not in ("idle", "listening")

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.emit("state-changed", state)

    def current_spec(self) -> ModelSpec:
        return find_spec(self.settings.get_string("model-id")) or find_spec(DEFAULT_MODEL_ID)

    def model_installed(self) -> bool:
        return self.store.is_installed(self.current_spec())

    def _model_params(self) -> tuple[ModelSpec, str, int]:
        return (
            self.current_spec(),
            self.settings.get_string("language"),
            self.settings.get_int("num-threads"),
        )

    # ---- model loading -------------------------------------------------------------------

    def preload(self) -> None:
        """Load the selected model in the background when it is installed."""
        spec, language, threads = self._model_params()
        if not self.store.is_installed(spec) or self.recognizer.is_loaded(spec, language, threads):
            return
        self._load_async(spec, language, threads, on_done=None)

    def _load_async(self, spec, language, threads, on_done) -> None:
        if self._loading:
            return
        self._loading = True

        def worker() -> None:
            try:
                self.recognizer.load(spec, self.store.root, language, threads)
            except RecognizerError as error:
                run_on_main(self._on_loaded, str(error), on_done)
                return
            run_on_main(self._on_loaded, None, on_done)

        threading.Thread(target=worker, daemon=True, name="model-load").start()

    def _on_loaded(self, error: str | None, on_done) -> None:
        self._loading = False
        if error is not None:
            self.emit("error", error)
        if on_done is not None:
            on_done(error is None)

    def _on_model_setting_changed(self) -> None:
        if self._state == "idle":
            self.recognizer.unload()
            self.preload()

    # ---- control -------------------------------------------------------------------------

    def toggle(self) -> None:
        if self._state == "listening":
            self.stop()
        elif self._state == "idle":
            self.start()

    def start(self) -> None:
        if self._state != "idle":
            return
        spec, language, threads = self._model_params()
        if not self.store.is_installed(spec):
            self.emit("error", f"Download the {spec.name} model in Preferences first.")
            return
        if self.recognizer.is_loaded(spec, language, threads):
            self._begin_listening()
            return
        self._cancel_pending_start = False
        self._set_state("loading")

        def after_load(ok: bool) -> None:
            if not ok or self._cancel_pending_start:
                self._set_state("idle")
                return
            self._begin_listening()

        self._load_async(spec, language, threads, after_load)

    def _begin_listening(self) -> None:
        live = None
        try:
            session = self.recognizer.start_live()
            if session is not None:
                live = LiveDecode(
                    session,
                    self.audio.read_new,
                    on_partial=lambda text: run_on_main(self._on_live_partial, live, text),
                    on_error=lambda message: run_on_main(self._on_live_error, message),
                )
            self.audio.start(self.settings.get_string("audio-device"))
        except (AudioError, RecognizerError) as error:
            self.emit("error", str(error))
            self._set_state("idle")
            return
        self._live = live
        if live is not None:
            live.start()
        self._set_state("listening")
        if self.settings.get_boolean("play-sounds"):
            self.sounds.start()

    def stop(self) -> None:
        if self._state == "loading":
            self._cancel_pending_start = True
            return
        if self._state != "listening":
            return
        samples = self.audio.stop()
        live, self._live = self._live, None
        duration = samples.size / SAMPLE_RATE
        if self.settings.get_boolean("play-sounds"):
            self.sounds.stop()
        if duration < MIN_DURATION:
            if live is not None:
                live.cancel()
            self._set_state("idle")
            return
        self._set_state("transcribing")
        if live is not None:
            # The live session decodes the samples that it did not read yet, then the final text.
            started = time.monotonic()
            live.finish(samples, lambda raw: self._postprocess(raw, duration, started))
            return
        threading.Thread(
            target=self._process, args=(samples, duration), daemon=True, name="transcribe"
        ).start()

    def cancel(self) -> None:
        if self._state == "listening":
            self._drop_live()
            self.audio.stop()
            self._set_state("idle")
        elif self._state == "loading":
            self._cancel_pending_start = True

    # ---- pipeline ------------------------------------------------------------------------

    def _process(self, samples: np.ndarray, duration: float) -> None:
        started = time.monotonic()
        try:
            raw = self.recognizer.transcribe(samples)
        except RecognizerError as error:
            run_on_main(self._fail, str(error))
            return
        self._postprocess(raw, duration, started)

    def _format(self, raw: str) -> str:
        return format_transcript(
            raw,
            spoken_punctuation=self.settings.get_boolean("spoken-punctuation"),
            auto_capitalise=self.settings.get_boolean("auto-capitalise"),
            dictionary=self.settings.get_strv("dictionary"),
        )

    def _postprocess(self, raw: str, duration: float, started: float) -> None:
        """Format, enhance and deliver. Runs on a worker thread."""
        text = self._format(raw)
        if not text:
            run_on_main(self._fail, "No speech was recognised.")
            return
        if self.settings.get_boolean("enhance-enabled"):
            run_on_main(self._set_state, "enhancing")
            spec = find_provider(self.settings.get_string("enhance-provider"))
            model = self.settings.get_string("enhance-model")
            try:
                text = enhance(
                    text,
                    base_url=self.settings.get_string("enhance-base-url"),
                    model=model,
                    api_key=load_api_key(spec.id),
                    prompt=self.settings.get_string("enhance-prompt"),
                    timeout=self.settings.get_int("enhance-timeout"),
                    api=spec.api,
                    options=spec.request_options(model),
                )
            except EnhanceError as error:
                run_on_main(self.emit, "notice", f"Enhancement skipped: {error}")
        elapsed = time.monotonic() - started
        run_on_main(self._deliver, raw, text, duration, elapsed)

    def _fail(self, message: str) -> None:
        self.emit("error", message)
        if self.settings.get_boolean("play-sounds"):
            self.sounds.error()
        self._set_state("idle")

    def _deliver(self, raw: str, text: str, duration: float, elapsed: float) -> None:
        self._set_state("typing")
        spec = self.current_spec()
        mode = self.settings.get_string("injection-mode")
        use_shift = self.settings.get_boolean("paste-uses-shift")

        def done(_ok: bool, notice: str) -> None:
            entry = self.history.add(
                text, raw, spec.id, duration, limit=self.settings.get_int("max-history")
            )
            self.emit("transcribed", entry)
            if notice:
                self.emit("notice", notice)
            self._set_state("idle")

        self.injector.deliver(text, mode, use_shift, done)

    def _on_audio_error(self, _audio: AudioCapture, message: str) -> None:
        if self._state == "listening":
            self._drop_live()
            self.audio.stop()
            self._fail(f"Microphone error: {message}")

    # ---- live decode ---------------------------------------------------------------------

    def _drop_live(self) -> None:
        live, self._live = self._live, None
        if live is not None:
            live.cancel()

    def _on_live_partial(self, live: LiveDecode, raw: str) -> None:
        if self._live is live and self._state == "listening":
            self.emit("partial", self._format(raw))

    def _on_live_error(self, message: str) -> None:
        # A cancelled live decode reports nothing, so the error belongs to this dictation.
        if self._state == "listening":
            self._live = None
            self.audio.stop()
        elif self._state != "transcribing":
            return
        self._fail(message)
