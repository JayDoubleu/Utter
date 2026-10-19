"""Live decode loop for streaming models. No GTK imports here."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

POLL_INTERVAL = 0.1


class LiveDecode:
    """Feeds new microphone samples to a streaming session on one worker thread.

    finish() hands over the complete recording. The worker decodes the samples that it did
    not read yet and then reports the final text. cancel() drops the session without a report.
    The callbacks run on the worker thread.
    """

    def __init__(
        self,
        session,
        read_new: Callable[[], Sequence[float]],
        on_partial: Callable[[str], None],
        on_error: Callable[[str], None],
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self._session = session
        self._read_new = read_new
        self._on_partial = on_partial
        self._on_error = on_error
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._recording: Sequence[float] | None = None
        self._on_final: Callable[[str], None] | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="live-decode")

    def start(self) -> None:
        self._thread.start()

    def finish(self, recording: Sequence[float], on_final: Callable[[str], None]) -> None:
        """Stop the loop. recording holds every sample since the start of the capture."""
        self._recording = recording
        self._on_final = on_final
        self._stop.set()

    def cancel(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def _run(self) -> None:
        consumed = 0
        text = ""
        try:
            while not self._stop.wait(self._poll_interval):
                samples = self._read_new()
                if not len(samples):
                    continue
                consumed += len(samples)
                latest = self._session.feed(samples)
                if latest != text and not self._stop.is_set():
                    text = latest
                    self._on_partial(text)
            on_final, recording = self._on_final, self._recording
            if on_final is None or recording is None:
                return
            rest = recording[consumed:]
            if len(rest):
                self._session.feed(rest)
            final = self._session.finish()
        except Exception as error:  # thread boundary: an escaped error leaves the app stuck
            if self._on_final is not None or not self._stop.is_set():
                self._on_error(str(error))
            return
        on_final(final)
