"""Model install state with GObject signals. Wraps the pure functions in models.py."""

from __future__ import annotations

import threading
from pathlib import Path

from gi.repository import GObject

from .mainthread import run_on_main
from .models import CATALOGUE, ModelSpec, install_model, is_installed, remove_model


class ModelStore(GObject.Object):
    __gsignals__ = {
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (str, float, str)),
        "installed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "removed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "failed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._active: set[str] = set()
        self._progress: dict[str, tuple[str, float]] = {}

    def is_installed(self, spec: ModelSpec) -> bool:
        return is_installed(self.root, spec)

    def is_downloading(self, spec: ModelSpec) -> bool:
        return spec.id in self._active

    def progress_of(self, spec: ModelSpec) -> tuple[str, float] | None:
        return self._progress.get(spec.id)

    def installed_specs(self) -> list[ModelSpec]:
        return [spec for spec in CATALOGUE if self.is_installed(spec)]

    def download(self, spec: ModelSpec) -> None:
        if spec.id in self._active:
            return
        self._active.add(spec.id)
        self._progress[spec.id] = ("downloading", 0.0)
        threading.Thread(
            target=self._worker, args=(spec,), daemon=True, name="model-download"
        ).start()

    def remove(self, spec: ModelSpec) -> None:
        remove_model(self.root, spec)
        self.emit("removed", spec.id)

    def _worker(self, spec: ModelSpec) -> None:
        def progress(phase: str, fraction: float) -> None:
            run_on_main(self._on_progress, spec.id, fraction, phase)

        try:
            install_model(self.root, spec, progress)
        except Exception as error:  # network, disk or archive errors
            run_on_main(self._on_done, spec.id, str(error))
            return
        run_on_main(self._on_done, spec.id, None)

    def _on_progress(self, model_id: str, fraction: float, phase: str) -> None:
        self._progress[model_id] = (phase, fraction)
        self.emit("progress", model_id, fraction, phase)

    def _on_done(self, model_id: str, error: str | None) -> None:
        self._active.discard(model_id)
        self._progress.pop(model_id, None)
        if error is None:
            self.emit("installed", model_id)
        else:
            self.emit("failed", model_id, error)
