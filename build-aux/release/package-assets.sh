#!/usr/bin/env bash
# Makes the files for a GitHub release.
#
# Usage: package-assets.sh REPO_DIR OUT_DIR
#
# Utter-VERSION.flatpak          a single-file bundle. It knows the repository URL, so an
#                                install from the bundle also gets updates.
# utter-overlay@...shell-extension.zip   the GNOME Shell extension, for gnome-extensions install
# SHA256SUMS
set -euo pipefail
# shellcheck source=build-aux/release/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

REPO="${1:?usage: package-assets.sh REPO_DIR OUT_DIR}"
OUT="${2:?usage: package-assets.sh REPO_DIR OUT_DIR}"
VERSION="$(app_version)"
EXTENSION="utter-overlay@jaydoubleu.github.io"

rm -rf "$OUT"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

bundle_args=(--repo-url="$PAGES_URL/repo/" --runtime-repo="$RUNTIME_REPO")
# A bundle from an unsigned test build must not ask for signatures at the next update.
if [[ -s "$REPO/summary.sig" ]]; then
    bundle_args+=(--gpg-keys="$PUBLIC_KEY")
fi
flatpak build-bundle "${bundle_args[@]}" "$REPO" "$OUT/Utter-$VERSION.flatpak" "$APP_ID" "$BRANCH"

(cd "$SOURCE_DIR/gnome-shell-extension/$EXTENSION" && zip -qr "$OUT/$EXTENSION.shell-extension.zip" .)

(cd "$OUT" && sha256sum -- * > SHA256SUMS)
ls -la "$OUT"
