"""Level bars that animate while the microphone is open."""

from __future__ import annotations

import math
from collections import deque

from gi.repository import Adw, Gdk, Gtk


class Waveform(Gtk.DrawingArea):
    def __init__(self, bars: int = 36) -> None:
        super().__init__()
        self.set_content_height(64)
        self.set_hexpand(True)
        self._levels: deque[float] = deque([0.0] * bars, maxlen=bars)
        self._active = False
        self.set_draw_func(self._draw)

    def push(self, level: float) -> None:
        # Microphone RMS is small. Map 0..0.15 to 0..1 with a soft curve.
        value = min(1.0, math.sqrt(min(level, 0.15) / 0.15))
        self._levels.append(value)
        self.queue_draw()

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._levels.extend([0.0] * self._levels.maxlen)
        self.queue_draw()

    def _colour(self) -> Gdk.RGBA:
        try:
            return Adw.StyleManager.get_default().get_accent_color_rgba()
        except AttributeError:
            return self.get_color()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        colour = self._colour()
        alpha = 1.0 if self._active else 0.35
        cr.set_source_rgba(colour.red, colour.green, colour.blue, alpha)
        count = len(self._levels)
        gap = 3.0
        bar_width = max(2.0, (width - gap * (count - 1)) / count)
        minimum = 4.0
        for index, level in enumerate(self._levels):
            bar_height = max(minimum, level * height)
            x = index * (bar_width + gap)
            y = (height - bar_height) / 2
            radius = bar_width / 2
            cr.new_sub_path()
            cr.arc(x + radius, y + radius, radius, math.pi, 0)
            cr.arc(x + radius, y + bar_height - radius, radius, 0, math.pi)
            cr.close_path()
            cr.fill()
