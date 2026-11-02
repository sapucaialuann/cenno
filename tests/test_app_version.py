"""Tests for app_version.py: the app reads the version from the VERSION file.

No camera, no app.  Run:

    python tests/test_app_version.py
"""

import os
import re
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_version  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reads_the_repo_version_file():
    """The version the app shows is the one in the repo's VERSION file."""
    expected = open(os.path.join(REPO, "VERSION"), encoding="utf-8").read().strip()
    assert app_version.read_version() == expected


def test_reads_a_given_base():
    assert app_version.read_version(base=_dir_with_version("9.8.7\n")) == "9.8.7"


def test_missing_version_file_is_unknown():
    """Without a VERSION file the app must still start, with "unknown"."""
    with tempfile.TemporaryDirectory() as tmp:
        assert app_version.read_version(base=tmp) == "unknown"


def test_empty_version_file_is_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("")
        assert app_version.read_version(base=tmp) == "unknown"


def test_frozen_app_reads_the_bundle_root():
    """A frozen app looks for VERSION in the bundle (sys._MEIPASS)."""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("1.2.3")
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", tmp, create=True):
            assert app_version.read_version() == "1.2.3"


def test_apps_do_not_hard_code_the_version():
    """No app may keep its own copy of the version."""
    pattern = re.compile(r'^VERSION = "')
    for name in ("cenno_app.py", "cenno_app_win.py"):
        path = os.path.join(REPO, name)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                assert not pattern.search(line), f"{name}: {line.strip()}"


def _dir_with_version(text):
    """A temp dir holding a VERSION file with the given text."""
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, "VERSION"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return tmp


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    print("ok" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
