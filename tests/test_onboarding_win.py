"""Tests for the Windows side of the welcome tour (#40).  Run:

    python tests/test_onboarding_win.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding                       # noqa: E402
import onboarding_win                   # noqa: E402


def test_every_step_has_a_title_and_a_body():
    for step in onboarding.STEPS_WINDOWS:
        assert onboarding_win.STEP_TITLE[step]
        assert onboarding_win.STEP_BODY[step]


def test_the_window_knows_exactly_the_windows_steps():
    assert set(onboarding_win.STEP_TITLE) == set(onboarding.STEPS_WINDOWS)
    assert set(onboarding_win.STEP_BODY) == set(onboarding.STEPS_WINDOWS)


def test_windows_has_no_accessibility_step():
    # Only macOS asks for the Accessibility permission.
    assert "accessibility" not in onboarding.STEPS_WINDOWS


def test_the_gesture_steps_have_a_line_for_when_they_work():
    for step in onboarding.GESTURE_STEPS:
        assert onboarding_win.STEP_DONE[step]


def test_the_pc_says_its_own_line_for_the_first_gesture():
    # The PC moves between windows, the Mac between Spaces.
    assert "PC" in onboarding_win.STEP_DONE["first_win"]
    assert "Mac" not in onboarding_win.STEP_DONE["first_win"]


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
