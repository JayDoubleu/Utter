"""Shared Gio.Settings instance."""

from __future__ import annotations

from gi.repository import Gio

from .config import APP_ID

_settings: Gio.Settings | None = None


def get_settings() -> Gio.Settings:
    global _settings
    if _settings is None:
        _settings = Gio.Settings.new(APP_ID)
    return _settings
