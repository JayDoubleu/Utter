# shellcheck shell=bash
# shellcheck disable=SC2034  # The scripts that source this file use these variables.
# Settings and helpers for the release scripts. Source this file, do not run it.
#
# The Flatpak repository is an OSTree repository on GitHub Pages. The layout and the
# signing order follow https://github.com/sirredbeard/github-pages-flatpak-repo (MIT).

RELEASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$RELEASE_DIR/../.." && pwd)"

APP_ID="io.github.jaydoubleu.Utter"
APP_TITLE="Utter"
MANIFEST="$SOURCE_DIR/build-aux/flatpak/$APP_ID.yaml"
BRANCH="stable"
REMOTE_NAME="utter"
PAGES_URL="${PAGES_URL:-https://jaydoubleu.github.io/Utter}"
PAGES_URL="${PAGES_URL%/}"
HOMEPAGE="https://github.com/JayDoubleu/Utter"
RUNTIME_REPO="https://dl.flathub.org/repo/flathub.flatpakrepo"
PUBLIC_KEY="$RELEASE_DIR/signing-key.asc"
# Old commits that the repository keeps, so clients can update with static deltas.
HISTORY_DEPTH="${HISTORY_DEPTH:-3}"

die() {
    echo "error: $*" >&2
    exit 1
}

app_version() {
    python3 -c 'import re, sys; print(re.search(r"VERSION = \"([^\"]+)\"", open(sys.argv[1]).read())[1])' \
        "$SOURCE_DIR/src/utter/config.py"
}

key_id() {
    gpg --with-colons --show-keys "$PUBLIC_KEY" | awk -F: '/^pub/ {print $5; exit}'
}

# Sets GNUPGHOME to a keyring with the private signing key. The key comes from
# GPG_PRIVATE_KEY (CI secret), GPG_PRIVATE_KEY_FILE, or an existing GNUPGHOME.
import_signing_key() {
    local id
    id="$(key_id)"
    if [[ -n "${GPG_PRIVATE_KEY:-}" || -n "${GPG_PRIVATE_KEY_FILE:-}" ]]; then
        GNUPGHOME="$(mktemp -d)"
        export GNUPGHOME
        chmod 700 "$GNUPGHOME"
        if [[ -n "${GPG_PRIVATE_KEY:-}" ]]; then
            printf '%s\n' "$GPG_PRIVATE_KEY" | gpg --batch --quiet --import
        else
            gpg --batch --quiet --import "$GPG_PRIVATE_KEY_FILE"
        fi
    fi
    gpg --list-secret-keys "$id" > /dev/null 2>&1 \
        || die "no private key for $id. Set GPG_PRIVATE_KEY, GPG_PRIVATE_KEY_FILE or GNUPGHOME."
    GPG_ARGS=(--gpg-sign="$id" --gpg-homedir="$GNUPGHOME")
}

# The key as one line of base64, for GPGKey= in .flatpakref and .flatpakrepo files.
key_base64() {
    gpg --dearmor < "$PUBLIC_KEY" | base64 -w0
}
