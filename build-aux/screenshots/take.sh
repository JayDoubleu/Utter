#!/bin/sh
# Makes the screenshots in docs/screenshots.
#
# Run this on the host, not in a toolbox, after you install the Utter Flatpak. It needs
# gnome-shell 50, gnome-text-editor, ffmpeg and the Parakeet TDT 0.6B v2 model in your
# Utter data folder. Each part starts a private headless GNOME Shell with its own home, bus
# and runtime folder, so the screenshots do not show your history or your desktop. A private
# XDG_RUNTIME_DIR is necessary: else the private session replaces the document portal mount
# of your real session.
set -e
HERE=$(dirname "$(readlink -f "$0")")
REPO=$(dirname "$(dirname "$HERE")")
OUT=${OUT:-$HOME/.cache/utter-screenshots}
SIZE=1440x900
REAL_HOME=$HOME
MODEL=sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8
export HERE REPO OUT SIZE

# Starts a private headless shell with the Utter Overlay and the shot helper extensions,
# then runs the command in $1 in that session.
session() {
    home=$1
    command=$2
    rm -rf "$home"
    mkdir -p "$home/.local/share/gnome-shell/extensions" "$home/.config" "$home/.cache"
    cp -r "$REPO/gnome-shell-extension/utter-overlay@jaydoubleu.github.io" "$HERE/shot-helper@local" \
        "$home/.local/share/gnome-shell/extensions/"
    run=$(mktemp -d /tmp/utrun.XXXXXX)
    env -u WAYLAND_DISPLAY -u DISPLAY HOME="$home" XDG_RUNTIME_DIR="$run" \
        XDG_DATA_HOME="$home/.local/share" XDG_CONFIG_HOME="$home/.config" \
        XDG_CACHE_HOME="$home/.cache" FLATPAK_USER_DIR="$REAL_HOME/.local/share/flatpak" \
        COMMAND="$command" dbus-run-session -- sh -c '
        gsettings set org.gnome.shell disable-user-extensions false
        gsettings set org.gnome.shell enabled-extensions "[\"utter-overlay@jaydoubleu.github.io\", \"shot-helper@local\"]"
        gsettings set org.gnome.shell welcome-dialog-last-shown-version "999"
        gnome-shell --headless --virtual-monitor $SIZE --wayland --no-x11 --wayland-display=wayland-0 \
            > "$OUT/shell.log" 2>&1 &
        shell=$!
        for i in $(seq 1 60); do
            gdbus introspect --session --dest org.utter.TestShot --object-path /org/utter/TestShot \
                > /dev/null 2>&1 && break
            sleep 0.5
        done
        gdbus call --session --dest org.utter.TestShot --object-path /org/utter/TestShot \
            --method org.utter.TestShot.HideOverview > /dev/null
        export WAYLAND_DISPLAY=wayland-0
        eval "$COMMAND" || echo "The screenshot step failed. See $OUT."
        kill $shell
    '
    # The document portal and gvfs of the private session leave FUSE mounts behind.
    for mount in "$run/doc" "$run/gvfs"; do
        fusermount -u "$mount" 2> /dev/null || true
    done
    rm -rf "$run" 2> /dev/null || true
}

rm -rf "$OUT"
mkdir -p "$OUT/frames"

# Part 1: the real app with demo settings and history.
APPHOME=$REAL_HOME/.cache/utter-screenshots-home
APPDIR=$APPHOME/.var/app/io.github.jaydoubleu.Utter
app_steps='
    mkdir -p "$APPDIR/data/utter/models"
    cp -al "$REAL_HOME/.var/app/io.github.jaydoubleu.Utter/data/utter/models/$MODEL" "$APPDIR/data/utter/models/"
    cp "$HERE/seed.py" "$HERE/driver.py" "$APPDIR/"
    flatpak run --command=python3 io.github.jaydoubleu.Utter "$APPDIR/seed.py" "$APPDIR/data/utter/history.db"
    flatpak run --talk-name=org.utter.TestShot --filesystem="$OUT" --command=python3 \
        io.github.jaydoubleu.Utter "$APPDIR/driver.py" "$OUT" > "$OUT/app.log" 2>&1
'
export APPDIR REAL_HOME MODEL
session "$APPHOME" "$app_steps"

# Part 2: the overlay over a text editor. A fake Utter sends the D-Bus signals.
EDITHOME=$REAL_HOME/.cache/utter-screenshots-overlay
overlay_steps='
    printf "Hi Sam,\n\n" > "$HOME/Email to Sam.txt"
    gsettings set org.gnome.TextEditor restore-session false
    gnome-text-editor --standalone "$HOME/Email to Sam.txt" > "$OUT/editor.log" 2>&1 &
    sleep 4
    python3 "$HERE/overlay_play.py" "$OUT" stills
    python3 "$HERE/overlay_play.py" "$OUT" frames
'
session "$EDITHOME" "$overlay_steps"
# Services of the private session can still write here for a moment.
sleep 2
rm -rf "$APPHOME" "$EDITHOME" 2> /dev/null || true

# The frames come at about 16 per second. The crop leaves out the editor above the panel.
DEST=$REPO/docs/screenshots
mkdir -p "$DEST"
ffmpeg -loglevel error -y -framerate 16 -i "$OUT/frames/%04d.png" \
    -vf "crop=460:145:0:45,split[a][b];[a]palettegen=stats_mode=diff:max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    -loop 0 "$DEST/overlay.gif"
cp "$OUT/main.png" "$DEST/main-window.png"
cp "$OUT/overlay-desktop.png" "$DEST/overlay-desktop.png"
for page in general voice cleanup text; do
    cp "$OUT/preferences-$page.png" "$DEST/preferences-$page.png"
done
echo "The screenshots are in $DEST."
