#!/usr/bin/env python3
"""Version and release notes for a release.

release.py bump VERSION --note TEXT [--note TEXT ...] [--date YYYY-MM-DD]
    Sets VERSION in src/utter/config.py and adds a <release> entry at the top of the
    metainfo file. One note becomes a paragraph, more notes become a list.
release.py notes VERSION
    Prints the notes of VERSION from the metainfo file as Markdown.
release.py check TAG
    Fails unless TAG is "v" + the version in config.py and the metainfo has an entry.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

SOURCE_DIR = Path(__file__).resolve().parents[2]
CONFIG = SOURCE_DIR / "src" / "utter" / "config.py"
METAINFO = SOURCE_DIR / "data" / "io.github.jaydoubleu.Utter.metainfo.xml.in"

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_CONFIG_VERSION = re.compile(r'^VERSION = "([^"]+)"$', re.MULTILINE)


class ReleaseError(Exception):
    pass


def parse_version(version: str) -> tuple[int, ...]:
    if not _VERSION.match(version):
        raise ReleaseError(f"{version} is not a version such as 1.2.3.")
    return tuple(int(part) for part in version.split("."))


def current_version(config: str) -> str:
    match = _CONFIG_VERSION.search(config)
    if not match:
        raise ReleaseError("config.py has no VERSION line.")
    return match[1]


def set_version(config: str, version: str) -> str:
    return _CONFIG_VERSION.sub(f'VERSION = "{version}"', config, count=1)


def release_versions(metainfo: str) -> list[str]:
    root = ET.fromstring(metainfo)
    return [release.get("version", "") for release in root.iter("release")]


def release_entry(version: str, date: str, notes: list[str]) -> str:
    if not notes:
        raise ReleaseError("Give at least one note.")
    if len(notes) == 1:
        body = f"        <p>{escape(notes[0])}</p>\n"
    else:
        items = "".join(f"          <li>{escape(note)}</li>\n" for note in notes)
        body = f"        <ul>\n{items}        </ul>\n"
    return (
        f'    <release version="{version}" date="{date}">\n'
        f"      <description>\n{body}      </description>\n"
        f"    </release>\n"
    )


def add_release(metainfo: str, version: str, date: str, notes: list[str]) -> str:
    versions = release_versions(metainfo)
    if version in versions:
        raise ReleaseError(f"The metainfo already has release {version}.")
    if versions and parse_version(version) <= parse_version(versions[0]):
        raise ReleaseError(f"{version} is not newer than {versions[0]}.")
    marker = "  <releases>\n"
    if marker not in metainfo:
        raise ReleaseError("The metainfo has no <releases> element.")
    return metainfo.replace(marker, marker + release_entry(version, date, notes), 1)


def notes_markdown(metainfo: str, version: str) -> str:
    root = ET.fromstring(metainfo)
    for release in root.iter("release"):
        if release.get("version") != version:
            continue
        lines = []
        description = release.find("description")
        for element in [] if description is None else list(description):
            if element.tag == "p":
                lines += ["".join(element.itertext()).strip(), ""]
            elif element.tag in ("ul", "ol"):
                lines += [f"- {''.join(li.itertext()).strip()}" for li in element.iter("li")]
                lines.append("")
        return "\n".join(lines).strip() + "\n"
    raise ReleaseError(f"The metainfo has no release {version}.")


def bump(version: str, notes: list[str], date: str) -> None:
    parse_version(version)
    config = CONFIG.read_text()
    if parse_version(version) <= parse_version(current_version(config)):
        raise ReleaseError(f"{version} is not newer than {current_version(config)}.")
    metainfo = add_release(METAINFO.read_text(), version, date, notes)
    CONFIG.write_text(set_version(config, version))
    METAINFO.write_text(metainfo)
    print(f"Version {version}. Commit, then run: git tag v{version} && git push origin v{version}")


def check(tag: str) -> None:
    version = current_version(CONFIG.read_text())
    if tag != f"v{version}":
        raise ReleaseError(f"The tag {tag} does not match the version {version} in config.py.")
    if version not in release_versions(METAINFO.read_text()):
        raise ReleaseError(f"The metainfo has no release {version}.")
    print(f"Tag {tag} matches the version and the metainfo.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    bump_parser = commands.add_parser("bump")
    bump_parser.add_argument("version")
    bump_parser.add_argument("--note", action="append", default=[], required=True)
    bump_parser.add_argument("--date", default=datetime.date.today().isoformat())
    notes_parser = commands.add_parser("notes")
    notes_parser.add_argument("version")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("tag")
    args = parser.parse_args(argv)
    try:
        if args.command == "bump":
            bump(args.version, args.note, args.date)
        elif args.command == "notes":
            print(notes_markdown(METAINFO.read_text(), args.version), end="")
        else:
            check(args.tag)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
