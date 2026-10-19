"""API key storage. Uses the secret service when present, else a private file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from gi.repository import GLib

from .config import APP_ID

try:
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    _SCHEMA = Secret.Schema.new(
        APP_ID, Secret.SchemaFlags.NONE, {"purpose": Secret.SchemaAttributeType.STRING}
    )
except (ImportError, ValueError):
    Secret = None
    _SCHEMA = None


def _fallback_path() -> Path:
    return Path(GLib.get_user_config_dir()) / "utter" / "secrets.json"


def _read_fallback() -> dict[str, str]:
    try:
        return json.loads(_fallback_path().read_text())
    except (OSError, ValueError):
        return {}


def _write_fallback(data: dict[str, str]) -> None:
    path = _fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)


def store_secret(purpose: str, value: str) -> None:
    """Store the value. An empty value removes the secret from both stores."""
    if Secret is not None:
        try:
            if value:
                Secret.password_store_sync(
                    _SCHEMA,
                    {"purpose": purpose},
                    Secret.COLLECTION_DEFAULT,
                    f"Utter {purpose}",
                    value,
                    None,
                )
                return
            Secret.password_clear_sync(_SCHEMA, {"purpose": purpose}, None)
        except GLib.Error:
            pass
    data = _read_fallback()
    if value:
        data[purpose] = value
    elif purpose in data:
        # An older version can have put the secret in the file when the keyring failed.
        del data[purpose]
    else:
        return
    _write_fallback(data)


def load_secret(purpose: str) -> str:
    if Secret is not None:
        try:
            value = Secret.password_lookup_sync(_SCHEMA, {"purpose": purpose}, None)
            if value:
                return value
        except GLib.Error:
            pass
    return _read_fallback().get(purpose, "")


def _api_key_purpose(provider_id: str) -> str:
    return f"enhance-api-key-{provider_id}"


def store_api_key(provider_id: str, value: str) -> None:
    store_secret(_api_key_purpose(provider_id), value)


def load_api_key(provider_id: str) -> str:
    return load_secret(_api_key_purpose(provider_id))


def migrate_api_key(provider_id: str) -> None:
    """Give the shared key of older versions to the selected provider, then remove it.

    The key of one provider must not go to the host of a different provider, so the
    caller runs this one time only.
    """
    legacy = load_secret("enhance-api-key")
    if not legacy:
        return
    if not load_api_key(provider_id):
        store_api_key(provider_id, legacy)
    store_secret("enhance-api-key", "")
