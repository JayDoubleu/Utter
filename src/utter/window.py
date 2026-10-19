"""Main window."""

from __future__ import annotations

from datetime import datetime

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .dictation import STATE_LABELS, Dictation
from .formatting import tail_preview
from .history import Entry, History
from .modelstore import ModelStore
from .waveform import Waveform

RECENT_LIMIT = 50


class UtterWindow(Adw.ApplicationWindow):
    def __init__(
        self, app, dictation: Dictation, store: ModelStore, history: History, settings: Gio.Settings
    ) -> None:
        super().__init__(application=app, title="Utter")
        self.app = app
        self.dictation = dictation
        self.store = store
        self.history = history
        self.settings = settings
        self.set_default_size(settings.get_int("window-width"), settings.get_int("window-height"))
        self.set_size_request(360, 420)
        self.connect("close-request", self._on_close_request)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        view = Adw.ToolbarView()
        self.toasts.set_child(view)

        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcut", "app.configure-shortcut")
        menu.append("About Utter", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main menu", primary=True
        )
        header.pack_end(menu_button)
        view.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        view.set_content(content)

        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", self._on_banner_clicked)
        content.append(self.banner)

        hero = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
            margin_top=28,
            margin_bottom=20,
            margin_start=24,
            margin_end=24,
        )
        self.waveform = Waveform()
        hero.append(self.waveform)

        self.record_button = Gtk.Button(
            icon_name="audio-input-microphone-symbolic",
            halign=Gtk.Align.CENTER,
            tooltip_text="Start or stop dictation",
        )
        self.record_button.add_css_class("circular")
        self.record_button.add_css_class("record-button")
        self.record_button.add_css_class("suggested-action")
        self.record_button.connect("clicked", lambda *_: self.dictation.toggle())
        hero.append(self.record_button)

        self.status_label = Gtk.Label(label=STATE_LABELS["idle"])
        self.status_label.add_css_class("title-3")
        hero.append(self.status_label)

        self.preview_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, visible=False)
        hero.append(self.preview_label)

        self.hint_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.hint_label.add_css_class("dim-label")
        self.hint_label.add_css_class("caption")
        hero.append(self.hint_label)
        content.append(hero)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content.append(scroller)
        clamp = Adw.Clamp(maximum_size=720, margin_start=16, margin_end=16, margin_bottom=16)
        scroller.set_child(clamp)

        self.recent_group = Adw.PreferencesGroup(title="Recent")
        clear_button = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        clear_button.add_css_class("flat")
        clear_button.connect("clicked", self._on_clear_clicked)
        self.recent_group.set_header_suffix(clear_button)
        clamp.set_child(self.recent_group)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.recent_group.add(self.list)

        self.empty_row = Adw.ActionRow(
            title="Nothing dictated yet", subtitle="Your last dictations appear here."
        )
        self.empty_row.set_sensitive(False)
        self.list.append(self.empty_row)
        self._rows: dict[int, Gtk.ListBoxRow] = {}

        for entry in reversed(self.history.recent(RECENT_LIMIT)):
            self._add_entry(entry)

        self.dictation.connect("state-changed", self._on_state_changed)
        self.dictation.connect("level", lambda _d, level: self.waveform.push(level))
        self.dictation.connect("partial", self._on_partial)
        self.dictation.connect("transcribed", lambda _d, entry: self._add_entry(entry))
        self.dictation.connect("error", lambda _d, message: self.toast(message))
        self.dictation.connect("notice", lambda _d, message: self.toast(message))
        for signal in ("installed", "removed"):
            self.store.connect(signal, lambda *_: self._refresh_banner())
        self.store.connect("progress", self._on_progress)
        self.store.connect(
            "failed", lambda _s, _id, message: self.toast(f"Download failed: {message}")
        )
        self.settings.connect("changed::model-id", lambda *_: self._refresh_banner())
        self.app.shortcuts.connect("changed", lambda *_: self._refresh_hint())
        self._refresh_banner()
        self._refresh_hint()

    # ---- helpers -------------------------------------------------------------------------

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message, timeout=4))

    def _on_close_request(self, *_args) -> bool:
        width, height = self.get_default_size()
        self.settings.set_int("window-width", width)
        self.settings.set_int("window-height", height)
        return False

    def _refresh_hint(self) -> None:
        shortcuts = self.app.shortcuts
        mode = self.settings.get_string("activation-mode")
        if shortcuts.is_ready and shortcuts.trigger:
            action = "Hold" if mode == "push-to-talk" else "Press"
            self.hint_label.set_label(f"{action} {shortcuts.trigger} or click the button.")
        elif shortcuts.state == "connecting":
            self.hint_label.set_label("Setting up the global shortcut.")
        else:
            self.hint_label.set_label(
                "No global shortcut. Bind “utter --toggle” in Settings › Keyboard, "
                "or use Keyboard Shortcut in the menu."
            )

    def _refresh_banner(self) -> None:
        spec = self.dictation.current_spec()
        if self.store.is_installed(spec):
            self.banner.set_revealed(False)
            return
        progress = self.store.progress_of(spec)
        if progress is not None:
            phase, fraction = progress
            label = "Extracting" if phase == "extracting" else f"Downloading {int(fraction * 100)}%"
            self.banner.set_title(f"{label} {spec.name}")
            self.banner.set_button_label(None)
        else:
            self.banner.set_title(f"{spec.name} is not downloaded ({spec.size_mb} MB)")
            self.banner.set_button_label("Download")
        self.banner.set_revealed(True)

    def _on_progress(self, _store, model_id: str, _fraction: float, _phase: str) -> None:
        if model_id == self.dictation.current_spec().id:
            self._refresh_banner()

    def _on_banner_clicked(self, *_args) -> None:
        spec = self.dictation.current_spec()
        self.store.download(spec)
        self._refresh_banner()

    def _on_state_changed(self, _dictation, state: str) -> None:
        self.status_label.set_label(STATE_LABELS.get(state, state))
        listening = state == "listening"
        self.waveform.set_active(listening)
        self.record_button.set_sensitive(state in ("idle", "listening"))
        if state not in ("listening", "transcribing", "enhancing"):
            self.preview_label.set_visible(False)
            self.preview_label.set_label("")
        if listening:
            self.record_button.set_icon_name("media-playback-stop-symbolic")
            self.record_button.remove_css_class("suggested-action")
            self.record_button.add_css_class("destructive-action")
        else:
            self.record_button.set_icon_name("audio-input-microphone-symbolic")
            self.record_button.remove_css_class("destructive-action")
            self.record_button.add_css_class("suggested-action")

    def _on_partial(self, _dictation, text: str) -> None:
        self.preview_label.set_label(tail_preview(text))
        self.preview_label.set_visible(bool(text))

    # ---- history rows --------------------------------------------------------------------

    def _add_entry(self, entry: Entry) -> None:
        self.empty_row.set_visible(False)
        when = datetime.fromtimestamp(entry.created_at).strftime("%-d %b %H:%M")
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(entry.text),
            subtitle=f"{when} · {entry.duration:.0f} s · {entry.model}",
        )
        row.set_title_lines(3)
        row.set_tooltip_text(entry.text)
        copy_button = Gtk.Button(
            icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy"
        )
        copy_button.add_css_class("flat")
        copy_button.connect("clicked", lambda *_: self._copy(entry.text))
        row.add_suffix(copy_button)
        delete_button = Gtk.Button(
            icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Delete"
        )
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", lambda *_: self._delete(entry.id))
        row.add_suffix(delete_button)
        self.list.insert(row, 0)
        self._rows[entry.id] = row
        while len(self._rows) > RECENT_LIMIT:
            oldest_id = next(iter(self._rows))
            self.list.remove(self._rows.pop(oldest_id))

    def _copy(self, text: str) -> None:
        provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain;charset=utf-8", GLib.Bytes.new(text.encode("utf-8"))
        )
        self.get_clipboard().set_content(provider)
        self.toast("Copied")

    def _delete(self, entry_id: int) -> None:
        self.history.delete(entry_id)
        row = self._rows.pop(entry_id, None)
        if row is not None:
            self.list.remove(row)
        if not self._rows:
            self.empty_row.set_visible(True)

    def _on_clear_clicked(self, *_args) -> None:
        if not self._rows:
            return
        dialog = Adw.AlertDialog(
            heading="Clear history?", body="This removes every dictation from the history."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response != "clear":
                return
            self.history.clear()
            for row in self._rows.values():
                self.list.remove(row)
            self._rows.clear()
            self.empty_row.set_visible(True)

        dialog.connect("response", on_response)
        dialog.present(self)
