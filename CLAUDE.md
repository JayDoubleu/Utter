# Utter

GNOME voice dictation app. Python 3.13, GTK 4, libadwaita, GStreamer, sherpa-onnx. Packaged as a Flatpak on the `org.gnome.Platform//50` runtime.

## Layout

- `src/utter/` application package. Pure modules with no GTK imports: `formatting.py`, `models.py`, `enhance.py`, `history.py`, `live.py`, `recognizer.py`. GObject modules: `audio.py`, `sounds.py`, `portal.py`, `shortcuts.py`, `injector.py`, `modelstore.py`, `dictation.py`, `overlay.py`, `window.py`, `preferences.py`, `main.py`.
- `gnome-shell-extension/utter-overlay@jaydoubleu.github.io/` the Utter Overlay GNOME Shell extension (GJS, ESM, GNOME Shell 50).
- `data/` desktop file, metainfo, GSettings schema, D-Bus service, icons.
- `build-aux/flatpak/` manifest and pinned Python wheels.
- `tests/` pytest for the pure modules.

## Key design points

- `dictation.py` is the state machine: idle, loading, listening, transcribing, enhancing, typing. Worker threads report back with `mainthread.run_on_main`.
- Models have a `kind`: `transducer`, `whisper` and `streaming`. `Recognizer.start_live()` gives the live session for the loaded model, or None for Whisper. `streaming` (Nemotron 3.5, 320 ms chunks) uses a `StreamingSession` on `OnlineRecognizer` that decodes each chunk once. `transducer` (Parakeet) uses a `RedecodeSession` that decodes the recording again with `OfflineRecognizer`: first after 1 s, then every 0.6 s (the FluidVoice timings). Parakeet needs about 55 ms per second of audio on 4 threads, so the preview decodes in 15 s segments and the text of a full segment stays fixed. `live.py` polls `AudioCapture.read_new()` every 100 ms, feeds the session and reports the text through the `partial` signal. At the stop, `LiveDecode.finish()` gives the session the samples that it did not read yet. `RedecodeSession.finish()` decodes the full recording once, so the final text does not depend on the segments. Then the usual format, enhance and deliver steps run. The app types the text after the stop only.
- `overlay.py` exports `io.github.jaydoubleu.Utter.Overlay` on `/io/github/jaydoubleu/Utter/Overlay` on the app's bus connection. Signals: `StateChanged(s)`, `Level(d)` (0..1, at most every 50 ms), `Partial(s)` (last 150 characters). Method: `GetState() -> (ss)`. The Utter Overlay extension draws the panel from these. GNOME gives a new app window the keyboard focus (tested on GNOME 50), so the panel must not be an app window.
- The extension ports the FluidVoice "medium" panel: 340 px wide, 50 px above the bottom of the monitor, 8 bars driven by a spring (stiffness 260, damping 21), a shimmer while Utter processes. St draws the `box-shadow` of a gradient background without the rounded corners, so the panel background is one colour. GNOME 50 `addTopChrome()` takes no `affectsInputRegion` option. The panel is not reactive, so clicks go to the window below. To test it without a new login, run `gnome-shell --headless --virtual-monitor 1280x720 --wayland --no-x11` on the host inside `dbus-run-session`, with `XDG_DATA_HOME`, `XDG_CONFIG_HOME` and `XDG_RUNTIME_DIR` in a temporary directory. Without a private `XDG_RUNTIME_DIR`, the private session starts a document portal that replaces the FUSE mount at `/run/user/1000/doc`, and Flatpak apps fail with "bwrap: Can't find source path" until `systemctl --user restart xdg-document-portal`.
- `enhance.py`: each `Provider` has an `api`. `openai` uses `urllib` and `/chat/completions`. `anthropic` uses the official `anthropic` SDK (imported late) with `claude-haiku-5-5` by default, effort `low`, and treats the `refusal` and `max_tokens` stop reasons as errors. Every provider gets the FluidVoice default prompt and the transcript as `{"transcript": ...}` JSON. The Flatpak installs the SDK and its 15 dependencies from pinned wheels in `python3-deps.yaml`.
- `StreamingSession.finish()` adds 0.66 s of silence before `input_finished()`. A shorter tail loses the last word. Greedy search makes the partial text append-only. In `auto` language mode the text has a double space where sherpa-onnx removes the language tag, and `tidy()` collapses it.
- The `language` key holds one code from `LANGUAGES` in `models.py`. `language_choices(spec)` gives the codes that a model accepts, and the Language row in Preferences shows only those. `recognizer_language(spec, language)` gives the string for sherpa-onnx: Whisper gets the base code, `""` for `auto` and `no` for `nb`. sherpa-onnx exits the process when Whisper gets an unknown code. Nemotron accepts locale codes such as `en-GB` and uses `auto` for an unknown code. `en` means `en-US`. In tests, `en-GB` did not give British spelling.
- The Language row must not call `set_model()` inside its own `notify::selected` signal. That crashes GTK. `_language_busy` prevents it.
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
