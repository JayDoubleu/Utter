# Utter

Dictate into any app on the Linux desktop. Utter records while you hold or toggle a global shortcut, recognises the speech on your computer, and types the text into the focused window.

It is a GNOME-native, Flatpak-packaged alternative to macOS dictation apps such as FluidVoice.

## Features

- On-device speech recognition with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx). Models: NVIDIA Parakeet TDT 0.6B v3 (25 languages) and v2 (English), NVIDIA Nemotron 3.5 Streaming (40 languages), OpenAI Whisper Base, Small and Turbo.
- Live dictation with the Nemotron 3.5 Streaming model. The window shows the text while you speak, and the text is ready when you stop.
- Global shortcut through the XDG GlobalShortcuts portal. Toggle or push-to-talk.
- Types into the focused app through the XDG RemoteDesktop portal, or pastes through the clipboard portal. Works on Wayland and X11 from inside the sandbox.
- Spoken punctuation ("comma", "full stop", "new line"), sentence capitalisation, and a personal dictionary.
- Optional cleanup with any OpenAI-compatible chat model: Ollama, LM Studio, OpenAI, Groq, OpenRouter.
- Dictation history with copy and delete.
- Runs in the background and can start at login.

## Requirements

- A desktop that implements the GlobalShortcuts and RemoteDesktop portals. GNOME 48 or later and KDE Plasma 6 do. The app still works without them: click the button in the window, and bind `flatpak run io.github.jaydoubleu.Utter --toggle` to a key in your desktop settings.
- Flatpak with the `org.gnome.Platform//50` runtime.

## Build and install

```bash
flatpak install flathub org.gnome.Sdk//50 org.gnome.Platform//50 org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install --force-clean flatpak-build build-aux/flatpak/io.github.jaydoubleu.Utter.yaml
flatpak run io.github.jaydoubleu.Utter
```

The first start asks you to confirm the global shortcut. The first dictation asks for permission to control the keyboard. Both permissions are remembered.

Download a speech model from the banner in the main window or from Preferences. Parakeet TDT 0.6B v3 is 487 MB and is the recommended model.

## Command line

```bash
flatpak run io.github.jaydoubleu.Utter --toggle      # start or stop dictation in the running instance
flatpak run io.github.jaydoubleu.Utter --background  # start hidden
```

## Development

Pure Python modules (formatting, models, enhance, history, live, recognizer) have unit tests that run without GTK:

```bash
uv venv -p 3.13 .venv
uv pip install -p .venv/bin/python sherpa-onnx numpy pytest ruff
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
```

To run the GTK app outside Flatpak you need PyGObject, GTK 4, libadwaita 1.6+, GStreamer with the pulse plugin, and the compiled GSettings schema:

```bash
meson setup _build --prefix ~/.local
meson install -C _build
utter
```

## Files

- `~/.var/app/io.github.jaydoubleu.Utter/data/utter/models/` downloaded speech models
- `~/.var/app/io.github.jaydoubleu.Utter/data/utter/history.db` dictation history
- API keys go to the secret service (GNOME Keyring) when it is available.

## Licence

GPL-3.0-or-later. See `LICENSE`.
