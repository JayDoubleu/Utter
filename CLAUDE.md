# Utter

GNOME voice dictation app. Python 3.13, GTK 4, libadwaita, GStreamer, sherpa-onnx. Packaged as a Flatpak on the `org.gnome.Platform//50` runtime.

## Layout

- `src/utter/` application package. Pure modules with no GTK imports: `formatting.py`, `models.py`, `enhance.py`, `history.py`, `recognizer.py`. GObject modules: `audio.py`, `sounds.py`, `portal.py`, `shortcuts.py`, `injector.py`, `modelstore.py`, `dictation.py`, `window.py`, `preferences.py`, `main.py`.
- `data/` desktop file, metainfo, GSettings schema, D-Bus service, icons.
- `build-aux/flatpak/` manifest and pinned Python wheels.
- `tests/` pytest for the pure modules.

## Key design points

- `dictation.py` is the state machine: idle, loading, listening, transcribing, enhancing, typing. Worker threads report back with `mainthread.run_on_main`.
- `portal.py` wraps GDBus portal calls. `request()` subscribes to the Request Response signal before it calls the method. `subscribe()` filters session signals with `MATCH_ARG0_PATH` because the session handle is an object path, and a plain arg0 match never fires.
- `shortcuts.py` uses `org.freedesktop.portal.GlobalShortcuts`. Activated starts, Deactivated stops in push-to-talk mode. `ConfigureShortcuts` needs interface version 2. GNOME 50 answers version 1, so `main.py` shows a dialog and opens Settings › Apps › Utter over `org.gnome.Settings` instead (`--talk-name` in the manifest).
- `injector.py` uses `org.freedesktop.portal.RemoteDesktop` with `persist_mode=2` and stores the restore token in GSettings. Typing sends one keysym per character. Paste mode uses the Clipboard portal and Ctrl+V. `_send_keys()` sends one key event at a time and waits for each reply. xdg-desktop-portal 1.22 handles each method call in its own thread, so events that are sent together can change places. Mutter then logs `Received multiple virtual 0x.. key releases (ignoring)`, a key or the Shift for a capital letter stays down, and only a new login clears it.
- Audio is captured with `pulsesrc` at 16 kHz mono float32. sherpa-onnx resamples other rates itself.
- The version lives in `src/utter/config.py`. Meson reads it from there.

## Commands

```bash
.venv/bin/python -m pytest              # unit tests
.venv/bin/ruff check src tests          # lint
meson setup _build && meson test -C _build   # validates desktop, metainfo and schema
flatpak run org.flatpak.Builder --user --install --force-clean flatpak-build build-aux/flatpak/io.github.jaydoubleu.Utter.yaml
flatpak run io.github.jaydoubleu.Utter
```

## Conventions

- British spelling in prose and UI strings. Code identifiers keep upstream spelling.
- No em-dashes anywhere.
- Keep GTK-free modules GTK-free so tests run in a plain venv.
