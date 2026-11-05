"""Tests for the Windows side of the welcome tour (#40).  Run:

    python tests/test_onboarding_win.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding                       # noqa: E402
import onboarding_win                   # noqa: E402


def test_hint_for_the_gesture_steps():
    assert onboarding_win.hint_for("first_win") == onboarding.HINTS["first_win"]
    assert onboarding_win.hint_for("pause") == onboarding.HINTS["pause"]
    for choice in onboarding.SECOND_GESTURE_CHOICES:
        hint = onboarding_win.hint_for("second_gesture", choice)
        assert hint == onboarding.HINTS["second_gesture"][choice]


def test_no_hint_for_the_other_steps():
    assert onboarding_win.hint_for("welcome") == ""
    assert onboarding_win.hint_for("camera") == ""
    assert onboarding_win.hint_for("second_gesture") == ""


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


def test_the_gesture_steps_are_the_ones_that_wait_for_a_gesture():
    assert onboarding_win.GESTURE_STEPS == ("first_win", "pause", "second_gesture")
    for step in onboarding_win.GESTURE_STEPS:
        assert onboarding_win.STEP_DONE[step]


def test_the_second_gesture_buttons_are_choices_the_tour_knows():
    keys = [key for key, _label in onboarding_win.SECOND_CHOICES]
    assert keys == list(onboarding.SECOND_GESTURE_CHOICES)
    ob = onboarding.Onboarding("windows")
    for key in keys:
        assert ob.choose_second(key) is True


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
