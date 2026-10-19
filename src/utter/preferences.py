"""Preferences dialog."""

from __future__ import annotations

import threading

from gi.repository import Adw, Gio, GLib, Gtk

from .audio import list_input_devices
from .enhance import DEFAULT_PROMPT, PROVIDERS, EnhanceError, enhance, find_provider, list_models
from .mainthread import run_on_main
from .models import CATALOGUE, effective_language, find_spec, language_choices
from .secrets import load_secret, store_secret

ACTIVATION_MODES = (
    ("toggle", "Press to start, press again to stop"),
    ("push-to-talk", "Hold to talk, release to stop"),
)
INJECTION_MODES = (("type", "Type each character"), ("paste", "Paste with the clipboard"))


def _combo(title: str, subtitle: str, labels: list[str]) -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, subtitle=subtitle)
    row.set_model(Gtk.StringList.new(labels))
    return row


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, app) -> None:
        super().__init__(title="Preferences")
        self.app = app
        self.settings: Gio.Settings = app.settings
        self.store = app.store
        self.set_search_enabled(False)
        self.add(self._general_page())
        self.add(self._voice_page())
        self.add(self._enhance_page())
        self.add(self._text_page())

    # ---- General ---------------------------------------------------------------------------

    def _general_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")

        group = Adw.PreferencesGroup(title="Activation")
        page.add(group)
        modes = _combo("Shortcut behaviour", "", [label for _id, label in ACTIVATION_MODES])
        self._bind_choice(modes, "activation-mode", [m for m, _ in ACTIVATION_MODES])
        group.add(modes)

        self.shortcut_row = Adw.ActionRow(title="Global shortcut")
        change = Gtk.Button(label="Change", valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda *_: self.app.configure_shortcut())
        self.shortcut_row.add_suffix(change)
        group.add(self.shortcut_row)
        self.app.shortcuts.connect("changed", lambda *_: self._refresh_shortcut_row())
        self._refresh_shortcut_row()

        group = Adw.PreferencesGroup(title="Output")
        page.add(group)
        injection = _combo("Insert text by", "", [label for _id, label in INJECTION_MODES])
        self._bind_choice(injection, "injection-mode", [m for m, _ in INJECTION_MODES])
        group.add(injection)
        shift = Adw.SwitchRow(
            title="Paste with Ctrl+Shift+V", subtitle="Terminals use this combination"
        )
        self.settings.bind("paste-uses-shift", shift, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(shift)

        def sync_shift(*_args) -> None:
            shift.set_sensitive(self.settings.get_string("injection-mode") == "paste")

        self.settings.connect("changed::injection-mode", sync_shift)
        sync_shift()
        sounds = Adw.SwitchRow(
            title="Play sounds", subtitle="A short tone when listening starts and stops"
        )
        self.settings.bind("play-sounds", sounds, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(sounds)

        self.typing_row = Adw.ActionRow(title="Typing permission")
        grant = Gtk.Button(label="Grant", valign=Gtk.Align.CENTER)
        grant.connect("clicked", lambda *_: self.app.injector.connect_session())
        self.typing_row.add_suffix(grant)
        group.add(self.typing_row)
        self.app.injector.connect("changed", lambda *_: self._refresh_typing_row())
        self._refresh_typing_row()

        group = Adw.PreferencesGroup(title="Background")
        page.add(group)
        background = Adw.SwitchRow(
            title="Keep running when the window is closed",
            subtitle="The global shortcut keeps working",
        )
        self.settings.bind("run-in-background", background, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(background)
        autostart = Adw.SwitchRow(
            title="Start at login", subtitle="Starts hidden in the background"
        )
        self.settings.bind("autostart", autostart, "active", Gio.SettingsBindFlags.DEFAULT)
        autostart.connect("notify::active", lambda *_: self.app.request_background())
        group.add(autostart)
        return page

    def _refresh_shortcut_row(self) -> None:
        shortcuts = self.app.shortcuts
        if shortcuts.is_ready:
            self.shortcut_row.set_subtitle(shortcuts.trigger or "Bound, no trigger set")
        elif shortcuts.state == "connecting":
            self.shortcut_row.set_subtitle("Connecting to the portal")
        else:
            self.shortcut_row.set_subtitle(
                (shortcuts.message or "Not available.")
                + " Fallback: bind “flatpak run io.github.jaydoubleu.Utter --toggle” in Settings."
            )

    def _refresh_typing_row(self) -> None:
        injector = self.app.injector
        if injector.is_ready:
            clip = (
                "with clipboard access"
                if injector.clipboard_enabled
                else "without clipboard access"
            )
            self.typing_row.set_subtitle(f"Granted {clip}")
        elif injector.state == "connecting":
            self.typing_row.set_subtitle("Waiting for permission")
        else:
            self.typing_row.set_subtitle(injector.message or "Asked on first dictation")

    # ---- Voice -----------------------------------------------------------------------------

    def _voice_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Voice", icon_name="audio-input-microphone-symbolic")

        group = Adw.PreferencesGroup(
            title="Speech model", description="Models run on this computer. Nothing is uploaded."
        )
        page.add(group)
        self.model_row = _combo("Model", "", [spec.name for spec in CATALOGUE])
        self._bind_choice(self.model_row, "model-id", [spec.id for spec in CATALOGUE])
        group.add(self.model_row)

        self.model_status = Adw.ActionRow(title="Status")
        self.model_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.model_button.connect("clicked", self._on_model_button)
        self.model_status.add_suffix(self.model_button)
        group.add(self.model_status)
        self.model_progress = Gtk.ProgressBar(margin_top=6, visible=False)
        group.add(self.model_progress)

        self.settings.connect("changed::model-id", lambda *_: self._refresh_model_status())
        for signal in ("installed", "removed", "failed"):
            self.store.connect(signal, lambda *_: self._refresh_model_status())
        self.store.connect("progress", lambda *_: self._refresh_model_status())
        self._refresh_model_status()

        group = Adw.PreferencesGroup(title="Recognition")
        page.add(group)
        self.language_row = Adw.ComboRow(title="Language", enable_search=True)
        self.language_row.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        )
        self._language_codes: list[str] = []
        self._language_busy = False
        self.language_row.connect("notify::selected", self._on_language_selected)
        for key in ("model-id", "language"):
            self.settings.connect(f"changed::{key}", lambda *_: self._refresh_language_row())
        self._refresh_language_row()
        group.add(self.language_row)
        threads = Adw.SpinRow.new_with_range(1, 32, 1)
        threads.set_title("CPU threads")
        self.settings.bind("num-threads", threads, "value", Gio.SettingsBindFlags.DEFAULT)
        group.add(threads)

        devices = [("", "System default")] + list_input_devices()
        current = self.settings.get_string("audio-device")
        if current and current not in [name for name, _ in devices]:
            devices.append((current, f"{current} (not connected)"))
        microphone = _combo("Microphone", "", [label for _name, label in devices])
        self._bind_choice(microphone, "audio-device", [name for name, _ in devices])
        group.add(microphone)
        return page

    def _refresh_language_row(self) -> None:
        """Show the languages of the selected model and the language that it will use."""
        if self._language_busy:
            return
        spec = find_spec(self.settings.get_string("model-id")) or CATALOGUE[0]
        choices = language_choices(spec)
        if choices:
            subtitle = "“Detect automatically” lets the model find the language"
        elif spec.multilingual:
            choices = (("auto", "Detected by the model"),)
            subtitle = f"{spec.name} detects the language itself"
        else:
            choices = (("en", "English"),)
            subtitle = f"{spec.name} supports English only"
        codes = [code for code, _name in choices]
        current = effective_language(spec, self.settings.get_string("language"))
        self._language_busy = True
        if codes != self._language_codes:
            self._language_codes = codes
            self.language_row.set_model(Gtk.StringList.new([name for _code, name in choices]))
        if current in codes:
            self.language_row.set_selected(codes.index(current))
        self._language_busy = False
        self.language_row.set_subtitle(subtitle)
        self.language_row.set_sensitive(len(choices) > 1)

    def _on_language_selected(self, *_args) -> None:
        if self._language_busy:
            return
        index = self.language_row.get_selected()
        if 0 <= index < len(self._language_codes):
            code = self._language_codes[index]
            if self.settings.get_string("language") != code:
                # The row must not rebuild its model inside its own selection signal.
                self._language_busy = True
                self.settings.set_string("language", code)
                self._language_busy = False

    def _refresh_model_status(self) -> None:
        spec = find_spec(self.settings.get_string("model-id")) or CATALOGUE[0]
        self.model_row.set_subtitle(f"{spec.summary} {spec.languages}.")
        progress = self.store.progress_of(spec)
        if progress is not None:
            phase, fraction = progress
            self.model_status.set_subtitle(
                "Extracting" if phase == "extracting" else f"Downloading {int(fraction * 100)}%"
            )
            self.model_progress.set_visible(True)
            self.model_progress.set_fraction(fraction)
            self.model_button.set_visible(False)
            return
        self.model_progress.set_visible(False)
        self.model_button.set_visible(True)
        if self.store.is_installed(spec):
            self.model_status.set_subtitle("Installed")
            self.model_button.set_label("Remove")
            self.model_button.remove_css_class("suggested-action")
        else:
            self.model_status.set_subtitle(f"Not downloaded. {spec.size_mb} MB.")
            self.model_button.set_label("Download")
            self.model_button.add_css_class("suggested-action")

    def _on_model_button(self, *_args) -> None:
        spec = find_spec(self.settings.get_string("model-id")) or CATALOGUE[0]
        if self.store.is_installed(spec):
            self.store.remove(spec)
        else:
            self.store.download(spec)
        self._refresh_model_status()

    # ---- Enhancement -----------------------------------------------------------------------

    def _enhance_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Cleanup", icon_name="document-edit-symbolic")

        group = Adw.PreferencesGroup(
            title="AI cleanup",
            description="Send the transcript to a chat model that fixes punctuation and "
            "removes filler words. Local providers keep the text on this computer.",
        )
        page.add(group)
        enabled = Adw.SwitchRow(title="Clean up transcripts")
        self.settings.bind("enhance-enabled", enabled, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(enabled)

        provider = _combo("Provider", "", [p.name for p in PROVIDERS])
        self._bind_choice(provider, "enhance-provider", [p.id for p in PROVIDERS])
        group.add(provider)

        self.base_url = Adw.EntryRow(title="Base URL")
        self.settings.bind("enhance-base-url", self.base_url, "text", Gio.SettingsBindFlags.DEFAULT)
        group.add(self.base_url)

        self.model_entry = Adw.EntryRow(title="Model")
        self.settings.bind("enhance-model", self.model_entry, "text", Gio.SettingsBindFlags.DEFAULT)
        browse = Gtk.MenuButton(
            icon_name="view-list-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="List models from the provider",
        )
        browse.add_css_class("flat")
        self.model_popover = Gtk.Popover()
        browse.set_popover(self.model_popover)
        browse.connect("notify::active", self._on_browse_models)
        self.model_entry.add_suffix(browse)
        group.add(self.model_entry)

        self.api_key = Adw.PasswordEntryRow(title="API key")
        self.api_key.set_text(load_secret("enhance-api-key"))
        self.api_key.connect("apply", lambda row: store_secret("enhance-api-key", row.get_text()))
        self.api_key.set_show_apply_button(True)
        group.add(self.api_key)

        def on_provider_changed(*_args) -> None:
            spec = find_provider(self.settings.get_string("enhance-provider"))
            if spec.base_url:
                self.settings.set_string("enhance-base-url", spec.base_url)
            self.api_key.set_sensitive(spec.needs_key)

        self.settings.connect("changed::enhance-provider", on_provider_changed)
        self.api_key.set_sensitive(
            find_provider(self.settings.get_string("enhance-provider")).needs_key
        )

        timeout = Adw.SpinRow.new_with_range(5, 300, 5)
        timeout.set_title("Timeout")
        timeout.set_subtitle("Seconds. The raw transcript is used when the model is slower.")
        self.settings.bind("enhance-timeout", timeout, "value", Gio.SettingsBindFlags.DEFAULT)
        group.add(timeout)

        group = Adw.PreferencesGroup(title="Instructions")
        page.add(group)
        frame = Gtk.Frame()
        self.prompt_view = Gtk.TextView(
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=8,
            bottom_margin=8,
            left_margin=8,
            right_margin=8,
        )
        self.prompt_view.set_size_request(-1, 160)
        frame.set_child(self.prompt_view)
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(self.settings.get_string("enhance-prompt") or DEFAULT_PROMPT)
        buffer.connect("changed", self._on_prompt_changed)
        group.add(frame)
        reset = Adw.ButtonRow(title="Reset to the built-in instructions")
        reset.connect("activated", lambda *_: buffer.set_text(DEFAULT_PROMPT))
        group.add(reset)
        test = Adw.ButtonRow(title="Test with sample text")
        test.connect("activated", self._on_test_enhance)
        group.add(test)
        return page

    def _on_prompt_changed(self, buffer: Gtk.TextBuffer) -> None:
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        self.settings.set_string(
            "enhance-prompt", "" if text.strip() == DEFAULT_PROMPT.strip() else text
        )

    def _on_browse_models(self, button: Gtk.MenuButton, _pspec) -> None:
        if not button.get_active():
            return
        spinner = Adw.Spinner() if hasattr(Adw, "Spinner") else Gtk.Spinner(spinning=True)
        self.model_popover.set_child(spinner)
        base_url = self.settings.get_string("enhance-base-url")
        api_key = self.api_key.get_text()

        def worker() -> None:
            try:
                models = list_models(base_url, api_key)
            except EnhanceError as error:
                run_on_main(self._show_models, None, str(error))
                return
            run_on_main(self._show_models, models, "")

        threading.Thread(target=worker, daemon=True).start()

    def _show_models(self, models: list[str] | None, error: str) -> None:
        if models is None:
            self.model_popover.set_child(
                Gtk.Label(
                    label=error,
                    wrap=True,
                    max_width_chars=40,
                    margin_top=8,
                    margin_bottom=8,
                    margin_start=8,
                    margin_end=8,
                )
            )
            return
        if not models:
            self.model_popover.set_child(Gtk.Label(label="No models found"))
            return
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("navigation-sidebar")
        for name in models[:80]:
            row = Gtk.ListBoxRow(child=Gtk.Label(label=name, xalign=0))
            row.model_name = name
            box.append(row)

        def on_activated(_box, row) -> None:
            self.settings.set_string("enhance-model", row.model_name)
            self.model_popover.popdown()

        box.connect("row-activated", on_activated)
        scroller = Gtk.ScrolledWindow(
            propagate_natural_height=True, propagate_natural_width=True, max_content_height=320
        )
        scroller.set_child(box)
        self.model_popover.set_child(scroller)

    def _on_test_enhance(self, *_args) -> None:
        sample = "um so this is a test of the the cleanup feature can you hear me okay"
        settings = self.settings

        def worker() -> None:
            try:
                result = enhance(
                    sample,
                    base_url=settings.get_string("enhance-base-url"),
                    model=settings.get_string("enhance-model"),
                    api_key=load_secret("enhance-api-key"),
                    prompt=settings.get_string("enhance-prompt"),
                    timeout=settings.get_int("enhance-timeout"),
                )
            except EnhanceError as error:
                run_on_main(self.add_toast, Adw.Toast(title=f"Failed: {error}", timeout=6))
                return
            run_on_main(self.add_toast, Adw.Toast(title=f"Result: {result}", timeout=8))

        self.add_toast(Adw.Toast(title="Testing", timeout=2))
        threading.Thread(target=worker, daemon=True).start()

    # ---- Text ------------------------------------------------------------------------------

    def _text_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Text", icon_name="format-text-bold-symbolic")

        group = Adw.PreferencesGroup(title="Formatting")
        page.add(group)
        spoken = Adw.SwitchRow(
            title="Spoken punctuation", subtitle="Say “comma”, “full stop” or “new line”"
        )
        self.settings.bind("spoken-punctuation", spoken, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(spoken)
        capitalise = Adw.SwitchRow(title="Capitalise sentences")
        self.settings.bind("auto-capitalise", capitalise, "active", Gio.SettingsBindFlags.DEFAULT)
        group.add(capitalise)

        self.dictionary_group = Adw.PreferencesGroup(
            title="Dictionary",
            description="Replace words the recogniser gets wrong. Names, jargon, abbreviations.",
        )
        page.add(self.dictionary_group)
        self.spoken_entry = Adw.EntryRow(title="Spoken form")
        self.replacement_entry = Adw.EntryRow(title="Replacement")
        add = Adw.ButtonRow(title="Add replacement")
        add.connect("activated", self._on_add_dictionary)
        self.dictionary_group.add(self.spoken_entry)
        self.dictionary_group.add(self.replacement_entry)
        self.dictionary_group.add(add)
        self._dictionary_rows: list[Adw.ActionRow] = []
        self._rebuild_dictionary()
        return page

    def _rebuild_dictionary(self) -> None:
        for row in self._dictionary_rows:
            self.dictionary_group.remove(row)
        self._dictionary_rows = []
        for entry in self.settings.get_strv("dictionary"):
            spoken, _sep, replacement = entry.partition("=")
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(spoken),
                subtitle=GLib.markup_escape_text(replacement or "(remove)"),
            )
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove.add_css_class("flat")
            remove.connect("clicked", lambda _b, e=entry: self._remove_dictionary(e))
            row.add_suffix(remove)
            self.dictionary_group.add(row)
            self._dictionary_rows.append(row)

    def _on_add_dictionary(self, *_args) -> None:
        spoken = self.spoken_entry.get_text().strip()
        replacement = self.replacement_entry.get_text().strip()
        if not spoken:
            return
        entries = [
            e
            for e in self.settings.get_strv("dictionary")
            if e.split("=", 1)[0].lower() != spoken.lower()
        ]
        entries.append(f"{spoken}={replacement}")
        self.settings.set_strv("dictionary", entries)
        self.spoken_entry.set_text("")
        self.replacement_entry.set_text("")
        self._rebuild_dictionary()

    def _remove_dictionary(self, entry: str) -> None:
        entries = [e for e in self.settings.get_strv("dictionary") if e != entry]
        self.settings.set_strv("dictionary", entries)
        self._rebuild_dictionary()

    # ---- helpers ---------------------------------------------------------------------------

    def _bind_choice(self, row: Adw.ComboRow, key: str, values: list[str]) -> None:
        """Two-way binding between a string GSettings key and a ComboRow index."""
        current = self.settings.get_string(key)
        row.set_selected(values.index(current) if current in values else 0)
        guard = {"busy": False}

        def on_selected(*_args) -> None:
            if guard["busy"]:
                return
            index = row.get_selected()
            if 0 <= index < len(values) and self.settings.get_string(key) != values[index]:
                self.settings.set_string(key, values[index])

        def on_changed(*_args) -> None:
            value = self.settings.get_string(key)
            if value in values and row.get_selected() != values.index(value):
                guard["busy"] = True
                row.set_selected(values.index(value))
                guard["busy"] = False

        row.connect("notify::selected", on_selected)
        self.settings.connect(f"changed::{key}", on_changed)
