"""Tests for the Windows parts of the gesture check tool.

The settings path and the "is the app running" probe depend on the OS, so
they are checked here with the platform and the shell calls faked.  No
camera, no cv2, no mediapipe.  Run:

    python3 tests/test_gesture_check_windows.py
"""

import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

import gesture_check                              # noqa: E402


class FakeResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_settings_path_on_windows():
    with tempfile.TemporaryDirectory() as appdata:
        with patch.dict(os.environ, {"APPDATA": appdata}):
            path = gesture_check.settings_path("win32")
    assert path.startswith(appdata), path
    assert path.endswith(os.path.join("Cenno", "settings.json")), path


def test_settings_path_on_macos():
    path = gesture_check.settings_path("darwin")
    assert path.endswith(os.path.join("Library", "Application Support",
                                      "Cenno", "settings.json")), path


def test_app_running_on_windows():
    with patch("subprocess.run", return_value=FakeResult(
            stdout="Cenno.exe   1234 Console   1  10,000 K")):
        assert gesture_check.app_running("win32") is True
    with patch("subprocess.run", return_value=FakeResult(
            stdout="INFO: No tasks are running which match the specified criteria.")):
        assert gesture_check.app_running("win32") is False


def test_app_running_on_macos():
    with patch("subprocess.run", return_value=FakeResult(returncode=0)):
        assert gesture_check.app_running("darwin") is True
    with patch("subprocess.run", return_value=FakeResult(returncode=1)):
        assert gesture_check.app_running("darwin") is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print("ok")
