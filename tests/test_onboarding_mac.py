"""Tests for the macOS side of the welcome tour (#40).  Run:

    python tests/test_onboarding_mac.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding                       # noqa: E402
import onboarding_mac                   # noqa: E402


def test_space_shortcuts_are_on_by_default():
    # No entry means the default shortcut, which is on.
    assert onboarding_mac.space_shortcuts_off({}) == []


def test_space_shortcuts_off_is_found():
    off = onboarding_mac.space_shortcuts_off({
        "79": {"enabled": False, "value": {"parameters": [65535, 123, 8650752]}},
        "81": {"enabled": True, "value": {"parameters": [65535, 124, 8650752]}}})
    assert off == ["Move left a space"]


def test_space_shortcuts_off_is_found_in_a_plist_number():
    # macOS writes the flag as a number, so 0 has to count as off.
    off = onboarding_mac.space_shortcuts_off({"81": {"enabled": 0}})
    assert off == ["Move right a space"]


def test_space_shortcuts_both_off():
    off = onboarding_mac.space_shortcuts_off({"79": {"enabled": False},
                                              "81": {"enabled": False}})
    assert off == ["Move left a space", "Move right a space"]


def test_space_shortcuts_on_when_enabled():
    hotkeys = {"79": {"enabled": True}, "81": {"enabled": True}}
    assert onboarding_mac.space_shortcuts_off(hotkeys) == []


def test_the_accessibility_step_moves_on_when_all_is_ready():
    # Access granted and the Mission Control shortcuts on: the step can
    # move on by itself.
    assert onboarding_mac.should_leave_accessibility(True, []) is True


def test_the_accessibility_step_waits_for_the_permission():
    assert onboarding_mac.should_leave_accessibility(False, []) is False


def test_the_accessibility_step_waits_when_the_space_shortcuts_are_off():
    # The warning about the Mission Control shortcuts has to be read, so
    # the step waits for the user instead of flashing past.
    off = ["Move left a space"]
    assert onboarding_mac.should_leave_accessibility(True, off) is False
    assert onboarding_mac.should_leave_accessibility(False, off) is False


def test_every_step_has_a_title_and_a_body():
    for step in onboarding.STEPS_MACOS:
        assert onboarding_mac.STEP_TITLE[step]
        assert onboarding_mac.STEP_BODY[step]


def test_the_mac_says_its_own_line_for_the_first_gesture():
    # The Mac moves between Spaces, the PC between windows.
    assert "Mac" in onboarding_mac.STEP_DONE["first_win"]
    assert "PC" not in onboarding_mac.STEP_DONE["first_win"]


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
    print("all good" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
