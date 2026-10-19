// Test only. Takes screenshots on request over D-Bus, for build-aux/screenshots/take.sh.
// GNOME Shell does not let other clients use its own screenshot interface.
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const XML = `<node><interface name="org.utter.TestShot">
  <method name="Shot"><arg type="s" name="path" direction="in"/></method>
  <method name="ShotWindow"><arg type="s" name="path" direction="in"/></method>
  <method name="ShotArea">
    <arg type="s" name="path" direction="in"/>
    <arg type="i" name="x" direction="in"/><arg type="i" name="y" direction="in"/>
    <arg type="i" name="width" direction="in"/><arg type="i" name="height" direction="in"/>
  </method>
  <method name="HideOverview"/>
</interface></node>`;

// Runs one Shell.Screenshot method into a PNG file and answers the D-Bus call.
function shoot(path, invocation, method, finish, args) {
    const file = Gio.File.new_for_path(path);
    const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
    const shooter = new Shell.Screenshot();
    shooter[method](...args, stream, (_shooter, result) => {
        try {
            shooter[finish](result);
            stream.close(null);
            invocation.return_value(null);
        } catch (e) {
            invocation.return_error_literal(Gio.DBusError, Gio.DBusError.FAILED, `${e}`);
        }
    });
}

export default class ShotHelper extends Extension {
    enable() {
        this._impl = Gio.DBusExportedObject.wrapJSObject(XML, {
            ShotAsync: ([path], invocation) =>
                shoot(path, invocation, 'screenshot', 'screenshot_finish', [false]),
            ShotWindowAsync: ([path], invocation) =>
                shoot(path, invocation, 'screenshot_window', 'screenshot_window_finish', [true, false]),
            ShotAreaAsync: ([path, x, y, width, height], invocation) =>
                shoot(path, invocation, 'screenshot_area', 'screenshot_area_finish', [x, y, width, height]),
            HideOverview: () => Main.overview.hide(),
        });
        this._impl.export(Gio.DBus.session, '/org/utter/TestShot');
        this._owner = Gio.bus_own_name(Gio.BusType.SESSION, 'org.utter.TestShot',
            Gio.BusNameOwnerFlags.NONE, null, null, null);
    }

    disable() {
        this._impl.unexport();
        Gio.bus_unown_name(this._owner);
    }
}
