"""Helpers that move work from worker threads to the GLib main loop."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import GLib


def _call_once(fn: Callable, args: tuple) -> bool:
    fn(*args)
    return GLib.SOURCE_REMOVE


def run_on_main(fn: Callable, *args) -> None:
    """Schedule fn(*args) on the main loop and return at once."""
    GLib.idle_add(_call_once, fn, args)
