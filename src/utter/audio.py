"""Microphone capture with GStreamer. Produces 16 kHz mono float32 samples."""

from __future__ import annotations

import threading

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import GLib, GObject, Gst  # noqa: E402

from .mainthread import run_on_main  # noqa: E402

SAMPLE_RATE = 16000
CAPS = f"audio/x-raw,format=F32LE,rate={SAMPLE_RATE},channels=1,layout=interleaved"


class AudioError(Exception):
    pass


def ensure_gst() -> None:
    if not Gst.is_initialized():
        Gst.init(None)


def list_input_devices() -> list[tuple[str, str]]:
    """Return (pulse source name, display name) for every microphone."""
    ensure_gst()
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Audio/Source", None)
    monitor.start()
    devices = monitor.get_devices() or []
    monitor.stop()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for device in devices:
        element = device.create_element(None)
        if element is None or element.find_property("device") is None:
            continue
        name = element.get_property("device")
        if not name or name.endswith(".monitor") or name in seen:
            continue
        seen.add(name)
        out.append((name, device.get_display_name()))
    return out


class AudioCapture(GObject.Object):
    __gsignals__ = {
        "level": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        ensure_gst()
        self._pipeline: Gst.Pipeline | None = None
        self._bus: Gst.Bus | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._pipeline is not None

    def start(self, device: str = "") -> None:
        if self._pipeline is not None:
            return
        pipeline = self._build("pulsesrc", device) or self._build("autoaudiosrc", "")
        if pipeline is None:
            raise AudioError("GStreamer has no usable audio source element.")
        sink = pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_sample)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_bus_error)
        with self._lock:
            self._chunks = []
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            bus.remove_signal_watch()
            pipeline.set_state(Gst.State.NULL)
            raise AudioError("Cannot open the microphone.")
        self._pipeline = pipeline
        self._bus = bus

    def stop(self) -> np.ndarray:
        """Stop capture and return every sample recorded since start."""
        pipeline, bus = self._pipeline, self._bus
        self._pipeline, self._bus = None, None
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        if bus is not None:
            bus.remove_signal_watch()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def _build(self, source: str, device: str) -> Gst.Pipeline | None:
        description = (
            f"{source} name=src ! queue ! audioconvert ! audioresample ! {CAPS} "
            "! appsink name=sink emit-signals=true sync=false max-buffers=256 drop=false"
        )
        try:
            pipeline = Gst.parse_launch(description)
        except GLib.Error:
            return None
        src = pipeline.get_by_name("src")
        if device and src is not None and src.find_property("device") is not None:
            src.set_property("device", device)
        return pipeline

    def _on_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            data = np.frombuffer(info.data, dtype=np.float32).copy()
        finally:
            buffer.unmap(info)
        if data.size:
            with self._lock:
                self._chunks.append(data)
            level = float(np.sqrt(np.mean(np.square(data))))
            run_on_main(self.emit, "level", level)
        return Gst.FlowReturn.OK

    def _on_bus_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        error, _debug = message.parse_error()
        run_on_main(self.emit, "error", error.message)
