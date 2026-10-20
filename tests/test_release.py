import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "build-aux" / "release" / "release.py"
spec = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

METAINFO = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <releases>
    <release version="0.1.0" date="2026-09-16">
      <description>
        <p>First release.</p>
      </description>
    </release>
  </releases>
</component>
"""


def test_add_release_puts_the_new_entry_first():
    out = release.add_release(METAINFO, "0.2.0", "2026-10-20", ["One & two", "Three"])
    assert release.release_versions(out) == ["0.2.0", "0.1.0"]
    assert "<li>One &amp; two</li>" in out
    assert release.notes_markdown(out, "0.2.0") == "- One & two\n- Three\n"
    assert release.notes_markdown(out, "0.1.0") == "First release.\n"


def test_add_release_refuses_an_old_or_known_version():
    with pytest.raises(release.ReleaseError):
        release.add_release(METAINFO, "0.1.0", "2026-10-20", ["x"])
    with pytest.raises(release.ReleaseError):
        release.add_release(METAINFO, "0.0.9", "2026-10-20", ["x"])
    with pytest.raises(release.ReleaseError):
        release.add_release(METAINFO, "0.2", "2026-10-20", ["x"])
    with pytest.raises(release.ReleaseError):
        release.add_release(METAINFO, "0.2.0", "2026-10-20", [])


def test_versions_compare_as_numbers():
    out = release.add_release(METAINFO, "0.10.0", "2026-10-20", ["x"])
    with pytest.raises(release.ReleaseError):
        release.add_release(out, "0.9.0", "2026-10-21", ["x"])


def test_set_version():
    config = 'APP_ID = "x"\nVERSION = "0.1.0"\n'
    assert release.current_version(release.set_version(config, "0.2.0")) == "0.2.0"


def test_the_real_files_agree():
    version = release.current_version(release.CONFIG.read_text())
    assert version in release.release_versions(release.METAINFO.read_text())
