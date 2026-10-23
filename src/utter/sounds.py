"""Short feedback tones through GStreamer."""

from __future__ import annotations

from gi.repository import GLib, Gst

from .audio import ensure_gst


class Sounds:
    def __init__(self) -> None:
        ensure_gst()
        self._active: set[Gst.Pipeline] = set()

    def play(self, frequency: int, duration_ms: int = 90, volume: float = 0.1) -> None:
        buffers = max(1, duration_ms // 10)
        description = (
            f"audiotestsrc freq={frequency} volume={volume} wave=sine samplesperbuffer=441 "
            f"num-buffers={buffers} ! audioconvert ! audioresample ! autoaudiosink"
        )
        try:
            pipeline = Gst.parse_launch(description)
        except GLib.Error:
            return
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        handlers: list[int] = []

        def finish(*_args) -> None:
            if not handlers:
                return
            pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()
            # The bus holds this closure and the closure holds the pipeline. Python cannot
            # free that cycle, so each tone kept its pipeline and its file descriptors.
            for handler in handlers:
                bus.disconnect(handler)
            handlers.clear()
            self._active.discard(pipeline)

        handlers.append(bus.connect("message::eos", finish))
        handlers.append(bus.connect("message::error", finish))
        self._active.add(pipeline)
        pipeline.set_state(Gst.State.PLAYING)

    def start(self) -> None:
        self.play(880)

    def stop(self) -> None:
        self.play(660)

    def error(self) -> None:
        self.play(330, 160)
