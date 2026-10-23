# Utter

Dictate into any app on the Linux desktop. Utter records while you hold or toggle a global shortcut, recognises the speech on your computer, and types the text into the focused window.

Utter is a GNOME app in a Flatpak. It is an alternative to macOS dictation apps such as [FluidVoice](https://github.com/altic-dev/FluidVoice), and its live text, overlay panel and cleanup prompt follow FluidVoice.

<p align="center">
  <img src="docs/screenshots/overlay.gif" alt="The Utter overlay panel shows the live text and a waveform while you speak" width="460">
</p>

## Features

- **On-device speech recognition** with [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx). No audio leaves your computer.
- **Live text while you speak.** Parakeet models decode the recording again every 0.6 s. Nemotron 3.5 Streaming decodes each chunk once. At the stop, Utter decodes the full recording once more, so the final text is as accurate as an offline decode.
- **An overlay panel** at the bottom of the screen, from the optional Utter Overlay GNOME Shell extension. It shows the live text, a waveform and the processing state. It stays above all windows and does not take the keyboard focus.
- **Global shortcut** through the XDG GlobalShortcuts portal, with toggle or push-to-talk.
- **Types into the focused app** through the XDG RemoteDesktop portal, or pastes through the Clipboard portal. This works on Wayland and X11 from inside the sandbox.
- **Spoken punctuation** ("comma", "full stop", "new line"), sentence capitalisation and a personal dictionary.
- **Optional cleanup with a chat model.** Use Anthropic (Claude Haiku 5.5 by default) or an OpenAI-compatible provider such as Ollama, LM Studio, OpenAI, Cerebras, Groq, Google Gemini or OpenRouter. Cerebras and Groq use `gpt-oss-120b` by default and clean a dictation in about 0.3 s. Each provider keeps its own API key. The model removes filler words and corrects punctuation.
- **Dictation history** with copy and delete.
- **Runs in the background** and can start at login.

## Screenshots

<p align="center">
  <img src="docs/screenshots/overlay-desktop.png" alt="A text editor with the Utter overlay panel below it, while the user dictates an email" width="820">
</p>

<table>
  <tr>
    <td align="center"><img src="docs/screenshots/main-window.png" alt="The Utter main window with the record button and the recent dictations" width="300"></td>
    <td align="center"><img src="docs/screenshots/preferences-voice.png" alt="The Voice page of Preferences, with the speech model and the language" width="420"></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshots/preferences-general.png" alt="The General page of Preferences, with the shortcut and the output settings" width="420"></td>
    <td align="center"><img src="docs/screenshots/preferences-cleanup.png" alt="The Cleanup page of Preferences, with the Cerebras provider and gpt-oss-120b" width="420"></td>
  </tr>
</table>

## Speech models

Download a model from the banner in the main window or from Preferences › Voice. The models run on the CPU.

| Model | Languages | Size | Live text |
|---|---|---|---|
| NVIDIA Parakeet TDT 0.6B v3 (recommended) | 25 European languages | 487 MB | Yes, decoded again every 0.6 s |
| NVIDIA Parakeet TDT 0.6B v2 | English | 482 MB | Yes, decoded again every 0.6 s |
| NVIDIA Nemotron 3.5 Streaming | 40 languages | 453 MB | Yes, streaming |
| OpenAI Whisper Base (English) | English | 209 MB | No |
| OpenAI Whisper Small | 99 languages | 639 MB | No |
| OpenAI Whisper Turbo | 99 languages | 564 MB | No |

Whisper models accept dictations of up to 30 seconds.

## Requirements

- A desktop that implements the GlobalShortcuts and RemoteDesktop portals. GNOME 48 or later and KDE Plasma 6 do. Without them, you can click the button in the window, and bind `flatpak run io.github.jaydoubleu.Utter --toggle` to a key in your desktop settings.
- Flatpak with the `org.gnome.Platform//50` runtime.
- GNOME Shell 50 for the overlay panel. The overlay is optional.

## Install

Utter has its own signed Flatpak repository on GitHub Pages. This command adds the repository and installs Utter:

```bash
flatpak install --user --from https://jaydoubleu.github.io/Utter/io.github.jaydoubleu.Utter.flatpakref
flatpak run io.github.jaydoubleu.Utter
```

The GNOME 50 runtime comes from Flathub. GNOME Software and `flatpak update` get new versions of Utter from the repository.

To add the repository without an install:

```bash
flatpak remote-add --user --if-not-exists utter https://jaydoubleu.github.io/Utter/utter.flatpakrepo
flatpak install --user utter io.github.jaydoubleu.Utter
```

Each [GitHub release](https://github.com/JayDoubleu/Utter/releases) also has a `.flatpak` bundle. An install from the bundle adds the same repository, so it also gets updates. The repository is signed with the key in [`build-aux/release/signing-key.asc`](build-aux/release/signing-key.asc) (`0AB8199B524EEF94`).

If you built Utter from source before, remove that build first. It has the same app ID:

```bash
flatpak uninstall --user io.github.jaydoubleu.Utter
```

At the first start, GNOME asks you to confirm the global shortcut. At the first dictation, GNOME asks for permission to control the keyboard. GNOME remembers both permissions.

GNOME shows a remote control icon in the top bar while Utter types. Utter closes the typing session 3 seconds after each dictation, and then the icon goes away.

## Build from source

```bash
git clone https://github.com/JayDoubleu/Utter.git
cd Utter
flatpak install flathub org.gnome.Sdk//50 org.gnome.Platform//50 org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install --force-clean flatpak-build build-aux/flatpak/io.github.jaydoubleu.Utter.yaml
flatpak run io.github.jaydoubleu.Utter
```

## Overlay panel (GNOME Shell extension)

GNOME does not let an app place a window or keep it above other windows. Also, a new window takes the keyboard focus from the app that gets the text. So a GNOME Shell extension draws the dictation panel. Utter sends the state, the microphone level and the live text to the extension over D-Bus (`io.github.jaydoubleu.Utter.Overlay` on `/io/github/jaydoubleu/Utter/Overlay`).

To install the extension, download `utter-overlay@jaydoubleu.github.io.shell-extension.zip` from the [latest release](https://github.com/JayDoubleu/Utter/releases/latest):

```bash
gnome-extensions install utter-overlay@jaydoubleu.github.io.shell-extension.zip
```

Or copy it from a clone of this repository:

```bash
cp -r gnome-shell-extension/utter-overlay@jaydoubleu.github.io ~/.local/share/gnome-shell/extensions/
```

Log out and log in again, then enable the extension:

```bash
gnome-extensions enable utter-overlay@jaydoubleu.github.io
```

Utter works without the extension. Then the main window shows the live text.

## Cleanup with a chat model

Utter can send each transcript to a chat model before it types the text. Turn this on in Preferences › Cleanup.

- **Anthropic** uses the official `anthropic` Python SDK. The default model is `claude-haiku-5-5` with low effort. Get an API key in the [Claude Console](https://console.anthropic.com/).
- **Cerebras and Groq** run models on fast inference hardware. The default model is `gpt-oss-120b` with low reasoning effort. Get an API key from [Cerebras](https://cloud.cerebras.ai/) or [Groq](https://console.groq.com/keys).
- **Google Gemini** uses its OpenAI-compatible endpoint. The default model is `gemini-3.5-flash-lite`. Utter sends no reasoning effort to Gemini, so the model selects its own thinking. Get an API key in [Google AI Studio](https://aistudio.google.com/apikey).
- **OpenAI-compatible providers** use the `/chat/completions` endpoint. Ollama and LM Studio run on your computer, so the text stays on your computer.

Each provider keeps its own API key. If you paste a key from a different provider, Preferences tells you.

### Speed of the cloud providers

The cleanup adds its time to each dictation before Utter types the text. In October 2026, each setup cleaned three sample dictations 30 times in total, with the built-in instructions of Utter 0.2.0:

| Provider and model | Median time | Slowest 10 % | Correct | Notes |
|---|---|---|---|---|
| Cerebras `gpt-oss-120b` (default) | 0.3 s | 0.4 s | 26 of 30 | The fastest steady result. It sometimes keeps a spoken correction such as "Thursday no wait Friday". |
| Groq `openai/gpt-oss-120b` (default) | 0.3 to 0.4 s | 0.4 to 0.6 s | 29 of 30 | The best text from a fast provider. |
| Groq `qwen/qwen3.8-27b` | 0.2 s | 0.3 s | 20 of 30 | The fastest, but in long dictations it types spoken punctuation such as "comma" as a word. |
| Cerebras `qwen-3.8-27b` | 0.3 to 0.7 s | up to 2.1 s | 21 of 30 | The same punctuation errors, and slow peaks. |
| Google `gemini-3.5-flash-lite` (default) | 0.7 s | 1.2 s | 30 of 30 | Accurate, and the fastest Gemini model. |
| Google `gemini-3.1-flash-lite` | 1.0 s | 1.3 s | 30 of 30 | Accurate, but slower than 3.5 Flash-Lite. |
| Google `gemini-3.8-flash` | 1.6 s | 2.1 to 2.4 s | 30 of 30 | Accurate, but slow for dictation. |
| Anthropic `claude-haiku-5-5` (default) | 0.8 to 0.9 s | 1.0 to 1.3 s | 30 of 30 | Accurate, but about 3 times slower than Cerebras and Groq. |

"Correct" means that the text has no filler words, the speaker's correction replaces the earlier phrase, and spoken punctuation becomes symbols. The times include the network. They change with your connection and with the load on the provider.

The built-in instructions are the default dictation prompt of FluidVoice. Utter sends the instructions and the transcript in one message, as FluidVoice does. You can change them in Preferences. Put `${transcript}` in your instructions to set the place of the transcript. Without it, the transcript goes at the end. If the model does not answer before the time-out, Utter types the raw transcript.

## Command line

```bash
flatpak run io.github.jaydoubleu.Utter --toggle      # start or stop dictation in the running instance
flatpak run io.github.jaydoubleu.Utter --background  # start hidden
```

## Privacy

- Speech recognition runs on your computer. Utter never sends audio to a server.
- If you turn on cleanup with a cloud provider, Utter sends the text of each dictation to that provider.
- API keys go to the secret service (GNOME Keyring) when it is available.
- Utter downloads the speech models from the [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases) on GitHub.

## Files

- `~/.var/app/io.github.jaydoubleu.Utter/data/utter/models/` downloaded speech models
- `~/.var/app/io.github.jaydoubleu.Utter/data/utter/history.db` dictation history

## Development

The pure Python modules (formatting, models, enhance, history, live, recognizer) have unit tests that run without GTK:

```bash
uv venv -p 3.13 .venv
uv pip install -p .venv/bin/python sherpa-onnx numpy anthropic pytest ruff
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
```

To run the GTK app outside Flatpak, you need PyGObject, GTK 4, libadwaita 1.6 or later, GStreamer with the pulse plugin, and the compiled GSettings schema:

```bash
meson setup _build --prefix ~/.local
meson install -C _build
utter
```

`CLAUDE.md` has notes on the design and on the GNOME 50 workarounds.

## Releases

A tag `vX.Y.Z` starts the release workflow. The workflow builds a signed Flatpak repository, deploys it to GitHub Pages, makes the GitHub release, and installs Utter from the live repository to test it.

1. Set the version and the release notes. The notes go into the metainfo file, so GNOME Software shows them:

   ```bash
   python3 build-aux/release/release.py bump 0.2.0 --note "Cerebras and Gemini cleanup." --note "A signed Flatpak repository."
   ```

2. Commit the change and merge it to `main`.
3. Tag the commit and push the tag:

   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

The workflow fails if the tag does not match the version in `src/utter/config.py`.

Each release continues the live repository. The new commit has the previous release as its parent, so `flatpak update` downloads a static delta. The repository keeps the last 3 commits.

To test the release process on your computer, run the scripts in the CI image with podman. Use a separate Flatpak user folder for the test install:

```bash
export PAGES_URL=http://127.0.0.1:8765 GPG_PRIVATE_KEY_FILE=~/.local/share/utter-release/private.asc
build-aux/release/in-container.sh build-aux/release/build-repo.sh _release/repo --no-mirror
build-aux/release/in-container.sh build-aux/release/stage-site.sh _release/repo _release/site
python3 -m http.server 8765 --bind 127.0.0.1 --directory _release/site &
CONTAINER_ARGS="--network=host --env FLATPAK_USER_DIR=$PWD/_release/flatpak-user" \
    build-aux/release/in-container.sh build-aux/release/verify-install.sh 0.1.0
```

Without the private key, use `--unsigned`. The CI workflow builds an unsigned bundle for each pull request.

### Signing key

The workflow reads the private key from the `GPG_PRIVATE_KEY` Actions secret. The public key is `build-aux/release/signing-key.asc`. Keep an offline copy of the private key. If you lose it, you must make a new key. Then each user must import the new key with `flatpak remote-modify --user --gpg-import=signing-key.asc utter`.

## Acknowledgements

- [FluidVoice](https://github.com/altic-dev/FluidVoice) by altic-dev (GPL-3.0). Utter uses its default dictation prompt, the timings of its live re-decode, and the design and waveform animation of its overlay panel.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) by k2-fsa (Apache-2.0) runs the speech models.
- [NVIDIA Parakeet TDT](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) and NVIDIA Nemotron speech models. See each model card for its licence.
- [OpenAI Whisper](https://github.com/openai/whisper) (MIT).
- The [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) (MIT).
- [github-pages-flatpak-repo](https://github.com/sirredbeard/github-pages-flatpak-repo) by sirredbeard (MIT). The release scripts follow its layout and its signing order.
- GTK, libadwaita and GNOME Shell.

## Licence

Utter is free software under the GNU General Public License, version 3 or later. See [`LICENSE`](LICENSE).
