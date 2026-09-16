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

        def finish(*_args) -> None:
            pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()
            self._active.discard(pipeline)

        bus.connect("message::eos", finish)
        bus.connect("message::error", finish)
        self._active.add(pipeline)
        pipeline.set_state(Gst.State.PLAYING)

    def start(self) -> None:
        self.play(880)

    def stop(self) -> None:
        self.play(660)

    def error(self) -> None:
        self.play(330, 160)
