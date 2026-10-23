// Utter Overlay: the dictation panel of the Utter app, drawn by GNOME Shell.
//
// Utter sends its state, the microphone level and the live text over D-Bus. The panel shows
// them at the bottom centre of the screen, above all windows, and never takes the keyboard
// focus. The look and the waveform follow the "medium" panel of FluidVoice
// (GPL-3.0, https://github.com/altic-dev/FluidVoice).

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Pango from 'gi://Pango';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.jaydoubleu.Utter';
const OBJECT_PATH = '/io/github/jaydoubleu/Utter/Overlay';
const INTERFACE = 'io.github.jaydoubleu.Utter.Overlay';

const BOTTOM_OFFSET = 50;
const ICON_SIZE = 18;
const SHOW_DURATION = 220;
const HIDE_DURATION = 180;

const PROCESSING_STATES = new Set(['transcribing', 'enhancing', 'typing']);
// Escape cancels the dictation in these states. Utter cannot stop the typing after it starts.
const CANCEL_STATES = new Set(['loading', 'listening', 'transcribing', 'enhancing']);

// Waveform of the medium panel.
const BAR_COUNT = 8;
const BAR_WIDTH = 3.5;
const BAR_GAP = 4.5;
const BAR_MIN = 6;
const BAR_MAX = 28;
const WAVE_WIDTH = 130;
const WAVE_HEIGHT = 32;
const NOISE_THRESHOLD = 0.05;
const HISTORY = 32;
const SHIMMER_PERIOD = 1.05;

/** Bar heights that follow the voice with a spring. A port of the FluidVoice simulation. */
class Waveform {
    constructor() {
        this.reset();
    }

    reset() {
        this.heights = new Array(BAR_COUNT).fill(BAR_MIN);
        this.velocities = new Array(BAR_COUNT).fill(0);
        this.history = new Array(HISTORY).fill(0);
        this.index = 0;
        this.energy = 0;
        this.clock = 0;
    }

    step(dt, level, idleWave) {
        dt = Math.min(Math.max(dt, 0), 1 / 30);
        if (dt <= 0)
            return;
        this.clock += dt;
        const adjusted = Math.min(Math.max((level - NOISE_THRESHOLD) / (1 - NOISE_THRESHOLD), 0), 1);
        const gate = Math.sqrt(adjusted);
        // The level arrives about every 50 ms. Glide to it, so the ripple has no steps.
        this.energy += (gate - this.energy) * Math.min(dt * 18, 1);
        this.index = (this.index + 1) % HISTORY;
        this.history[this.index] = this.energy;

        const half = Math.max((BAR_COUNT - 1) / 2, 1);
        const range = BAR_MAX - BAR_MIN;
        for (let i = 0; i < BAR_COUNT; i++) {
            const distance = Math.abs(i - half) / half;
            // The outer bars hear the voice about 90 ms after the centre bars.
            const delayFrames = Math.min(Math.round(distance * 0.09 / dt), HISTORY - 1);
            const delayed = this.history[(this.index - delayFrames + HISTORY) % HISTORY];
            const envelope = 0.34 + 0.66 * Math.cos(distance * Math.PI / 2);
            // FluidVoice takes a spectrum band here. A slow pseudo band gives a similar motion.
            const band = 0.5 + 0.5 * Math.sin(this.clock * 3.1 + i * 1.7);
            const wobble = 0.9 + 0.1 * Math.sin(this.clock * 9 + i * 2.1);
            const voice = delayed * (0.5 + 0.5 * band) * wobble * envelope;
            const idle = idleWave
                ? (1 - this.energy) * 0.13 * (0.5 + 0.5 * Math.sin(this.clock * 2.4 - i * 0.75))
                : 0;
            const target = BAR_MIN + range * Math.min(voice + idle, 1);
            // A slightly underdamped spring: lively on the way up, no buzz when it settles.
            const acceleration = 260 * (target - this.heights[i]) - 21 * this.velocities[i];
            this.velocities[i] += acceleration * dt;
            this.heights[i] = Math.min(BAR_MAX, Math.max(BAR_MIN, this.heights[i] + this.velocities[i] * dt));
        }
    }
}

export default class UtterOverlayExtension extends Extension {
    enable() {
        this._state = 'idle';
        this._level = 0;
        this._waveform = new Waveform();
        this._buildPanel();
        this._subscriptions = [];
        this._connection = null;
        this._owner = null;
        this._escapeAction = Meta.KeyBindingAction.NONE;
        this._targetApp = null;
        this._focusId = Shell.WindowTracker.get_default().connect('notify::focus-app',
            () => this._reportTarget());
        this._acceleratorId = global.display.connect('accelerator-activated',
            (_display, action) => {
                if (action === this._escapeAction)
                    this._cancel();
            });
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            (connection, _name, owner) => this._onAppeared(connection, owner),
            () => this._onVanished());
    }

    disable() {
        Gio.bus_unwatch_name(this._watchId);
        this._unsubscribe();
        this._releaseEscape();
        global.display.disconnect(this._acceleratorId);
        Shell.WindowTracker.get_default().disconnect(this._focusId);
        this._timeline.stop();
        this._timeline = null;
        Main.layoutManager.removeChrome(this._panel);
        this._panel.destroy();
        this._panel = null;
        this._label = null;
        this._scroll = null;
        this._area = null;
        this._iconBin = null;
        this._loadingLabel = null;
        this._waveform = null;
    }

    // ---- panel --------------------------------------------------------------------------

    _buildPanel() {
        this._panel = new St.BoxLayout({
            style_class: 'utter-overlay',
            orientation: Clutter.Orientation.VERTICAL,
            visible: false,
            opacity: 0,
        });

        this._label = new St.Label({style_class: 'utter-overlay-text', x_expand: true});
        const text = this._label.clutter_text;
        text.line_wrap = true;
        text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
        text.ellipsize = Pango.EllipsizeMode.NONE;
        const textBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true});
        textBox.add_child(this._label);
        this._scroll = new St.ScrollView({
            style_class: 'utter-overlay-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.EXTERNAL,
            x_expand: true,
            visible: false,
        });
        this._scroll.child = textBox;
        // Keep the newest line in view, like the FluidVoice preview.
        const adjustment = this._scroll.vadjustment;
        adjustment.connect('changed', () => {
            adjustment.value = adjustment.upper - adjustment.page_size;
        });
        this._panel.add_child(this._scroll);

        const row = new St.BoxLayout({style_class: 'utter-overlay-row', x_expand: true});
        this._iconBin = new St.Bin({y_align: Clutter.ActorAlign.CENTER});
        row.add_child(this._iconBin);
        this._area = new St.DrawingArea({
            width: WAVE_WIDTH,
            height: WAVE_HEIGHT,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._area.connect('repaint', area => this._drawBars(area));
        row.add_child(this._area);
        const labels = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            y_align: Clutter.ActorAlign.CENTER,
        });
        labels.add_child(new St.Label({style_class: 'utter-overlay-mode', text: 'Dictate'}));
        this._loadingLabel = new St.Label({
            style_class: 'utter-overlay-loading',
            text: 'Loading model…',
            visible: false,
        });
        labels.add_child(this._loadingLabel);
        row.add_child(labels);
        this._panel.add_child(row);

        // The panel is not reactive, so pointer events go through it to the window below.
        Main.layoutManager.addTopChrome(this._panel);
        this._panel.connect('notify::height', () => this._place());
        this._panel.connect('notify::width', () => this._place());

        this._lastFrame = 0;
        this._timeline = new Clutter.Timeline({actor: this._area, duration: 1000, repeat_count: -1});
        this._timeline.connect('new-frame', () => this._onFrame());
    }

    _place() {
        const monitor = Main.layoutManager.currentMonitor ?? Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        // The work area leaves out panels and docks, like the visible frame in FluidVoice.
        const area = Main.layoutManager.getWorkAreaForMonitor(monitor.index);
        const [width, height] = this._panel.get_size();
        this._panel.set_position(
            Math.round(area.x + (area.width - width) / 2),
            Math.round(area.y + area.height - BOTTOM_OFFSET - height));
    }

    _show() {
        if (this._shown)
            return;
        this._shown = true;
        this._waveform.reset();
        this._setAppIcon();
        this._place();
        this._panel.remove_all_transitions();
        this._panel.visible = true;
        this._panel.translation_y = 12;
        this._panel.ease({
            opacity: 255,
            translation_y: 0,
            duration: SHOW_DURATION,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        this._lastFrame = 0;
        this._timeline.start();
    }

    _hide() {
        if (!this._shown)
            return;
        this._shown = false;
        this._panel.remove_all_transitions();
        this._panel.ease({
            opacity: 0,
            translation_y: 8,
            duration: HIDE_DURATION,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onStopped: () => {
                if (this._shown || !this._panel)
                    return;
                this._panel.visible = false;
                this._timeline.stop();
                this._setText('');
            },
        });
    }

    _setAppIcon() {
        const app = Shell.WindowTracker.get_default().focus_app;
        this._iconBin.child = app ? app.create_icon_texture(ICON_SIZE) : null;
        this._iconBin.visible = app !== null;
    }

    _setText(text) {
        this._label.text = text;
        this._scroll.visible = text.length > 0;
    }

    // ---- waveform -----------------------------------------------------------------------

    _onFrame() {
        const now = GLib.get_monotonic_time() / 1e6;
        const dt = this._lastFrame ? now - this._lastFrame : 0;
        this._lastFrame = now;
        if (this._state === 'listening')
            this._waveform.step(dt, this._level, true);
        else
            this._waveform.clock += dt; // The shimmer runs on the same clock.
        this._area.queue_repaint();
    }

    _drawBars(area) {
        const cr = area.get_context();
        const [width, height] = area.get_surface_size();
        const processing = PROCESSING_STATES.has(this._state);
        const heights = processing || this._state !== 'listening'
            ? new Array(BAR_COUNT).fill(BAR_MIN)
            : this._waveform.heights;
        const total = BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP;
        const left = (width - total) / 2;

        const barsPath = () => {
            for (let i = 0; i < BAR_COUNT; i++) {
                const h = heights[i];
                const x = left + i * (BAR_WIDTH + BAR_GAP);
                const y = (height - h) / 2;
                const r = BAR_WIDTH / 2;
                cr.newSubPath();
                cr.arc(x + r, y + r, r, Math.PI, 0);
                cr.arc(x + r, y + h - r, r, 0, Math.PI);
                cr.closePath();
            }
        };

        // Dictate mode colour: white at 85 %. Dim while the model loads and while Utter works.
        let alpha = 0.85;
        if (processing)
            alpha = 0.85 * 0.16;
        else if (this._state === 'loading')
            alpha = 0.85 * 0.45;
        cr.setSourceRGBA(1, 1, 1, alpha);
        barsPath();
        cr.fill();

        if (processing) {
            // A light band that sweeps across the bars: the only "working" cue, as in FluidVoice.
            const phase = (this._waveform.clock % SHIMMER_PERIOD) / SHIMMER_PERIOD;
            const centre = left - 30 + phase * (total + 60);
            const gradient = new Cairo.LinearGradient(centre - 30, 0, centre + 30, 0);
            gradient.addColorStopRGBA(0, 1, 1, 1, 0);
            gradient.addColorStopRGBA(0.5, 1, 1, 1, 0.9);
            gradient.addColorStopRGBA(1, 1, 1, 1, 0);
            cr.setSource(gradient);
            barsPath();
            cr.fill();
        }
        cr.$dispose();
    }

    // ---- D-Bus --------------------------------------------------------------------------

    _onAppeared(connection, owner) {
        this._unsubscribe();
        this._connection = connection;
        this._owner = owner;
        const subscribe = (member, handler) => {
            const id = connection.signal_subscribe(
                owner, INTERFACE, member, OBJECT_PATH, null, Gio.DBusSignalFlags.NONE,
                (_connection, _sender, _path, _interface, _signal, params) =>
                    handler(params.deepUnpack()));
            this._subscriptions.push([connection, id]);
        };
        subscribe('StateChanged', ([state]) => this._setState(state));
        subscribe('Level', ([level]) => {
            this._level = level;
        });
        subscribe('Partial', ([text]) => this._setText(text));

        // Catch up when GNOME Shell starts during a dictation.
        connection.call(
            owner, OBJECT_PATH, INTERFACE, 'GetState', null, new GLib.VariantType('(ss)'),
            Gio.DBusCallFlags.NONE, -1, null,
            (conn, result) => {
                try {
                    const [state, text] = conn.call_finish(result).deepUnpack();
                    if (!this._panel)
                        return;
                    this._setState(state);
                    this._setText(text);
                } catch {
                    // An older Utter has no overlay feed. Nothing to show.
                }
            });
    }

    _onVanished() {
        this._unsubscribe();
        this._connection = null;
        this._owner = null;
        if (this._panel)
            this._setState('idle');
    }

    _unsubscribe() {
        for (const [connection, id] of this._subscriptions)
            connection.signal_unsubscribe(id);
        this._subscriptions = [];
    }

    // ---- Escape -------------------------------------------------------------------------

    // Utter cannot see the keyboard while a different app has the focus. So the shell takes
    // Escape during a dictation only, and Escape goes to the focused app at all other times.
    _grabEscape() {
        if (this._escapeAction !== Meta.KeyBindingAction.NONE)
            return;
        const action = global.display.grab_accelerator('Escape', Meta.KeyBindingFlags.NONE);
        if (action === Meta.KeyBindingAction.NONE)
            return;
        // In the overview, in a dialog and on the lock screen, Escape keeps its usual job.
        Main.wm.allowKeybinding(Meta.external_binding_name_for_action(action), Shell.ActionMode.NORMAL);
        this._escapeAction = action;
    }

    _releaseEscape() {
        if (this._escapeAction === Meta.KeyBindingAction.NONE)
            return;
        const action = this._escapeAction;
        this._escapeAction = Meta.KeyBindingAction.NONE;
        Main.wm.allowKeybinding(Meta.external_binding_name_for_action(action), Shell.ActionMode.NONE);
        global.display.ungrab_accelerator(action);
    }

    // Utter types into the focused app. A terminal gets a paste, so a line break does not run
    // the line. Utter cannot see the focused app on Wayland, so the shell tells it.
    _reportTarget() {
        if (!this._connection || this._state === 'idle')
            return;
        const app = Shell.WindowTracker.get_default().focus_app;
        const id = app?.get_id() ?? '';
        if (id === this._targetApp)
            return;
        this._targetApp = id;
        this._call('SetTargetApp', new GLib.Variant('(s)', [id]));
    }

    _cancel() {
        this._call('Cancel', null);
    }

    _call(method, params) {
        if (!this._connection)
            return;
        this._connection.call(
            this._owner, OBJECT_PATH, INTERFACE, method, params, null,
            Gio.DBusCallFlags.NONE, -1, null,
            (conn, result) => {
                try {
                    conn.call_finish(result);
                } catch (e) {
                    // An older Utter does not have this method.
                    console.warn(`Utter Overlay: ${method} failed: ${e.message}`);
                }
            });
    }

    _setState(state) {
        const previous = this._state;
        this._state = state;
        if (CANCEL_STATES.has(state))
            this._grabEscape();
        else
            this._releaseEscape();
        if (state === 'idle')
            this._targetApp = null;
        else if (previous === 'idle')
            this._reportTarget();
        this._loadingLabel.visible = state === 'loading';
        if (state === 'idle') {
            this._hide();
            return;
        }
        if (state === 'listening' && previous !== 'listening') {
            this._level = 0;
            if (!PROCESSING_STATES.has(previous))
                this._setText('');
        }
        this._show();
    }
}
