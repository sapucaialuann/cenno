"""Tests for the face zone as a user option (#43).

The zone is off by default: the face never blocks a click, a scroll or a
swipe.  Turned on, it brings back the old blocking of #9, #25 and #26.
Synthetic landmarks, no camera.  Run:

    python tests/test_face_zone_option.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

# The shared fixtures: hands and a face box from the face zone tests.
from tests.test_face_zone import (               # noqa: E402
    FACE_BOX, names, pinch_hand, point_hand, run, two_hand)
from tests.test_face_zone_size import swipe_up   # noqa: E402

# The tilted hand comes from the tilt tests, which set core.SCROLL_MODE.
_SCROLL_MODE = core.SCROLL_MODE
from tests.test_scroll_tilt import two_hand as tilted_hand   # noqa: E402
core.SCROLL_MODE = _SCROLL_MODE

# The laptop webcam face box: the hand sits right over the face.
LAPTOP_FACE_BOX = (245.0, 60.0, 395.0, 250.0)


def engine(**kw):
    """A fresh engine with the given settings."""
    eng = core.GestureEngine()
    for key, value in kw.items():
        setattr(eng, key, value)
    return eng


# --- the default ------------------------------------------------------------

def test_the_face_zone_is_off_by_default():
    assert core.FACE_ZONE_DEFAULT is False
    assert core.GestureEngine().face_zone is False


# --- clicking ---------------------------------------------------------------

def test_pinch_over_the_face_clicks_with_the_zone_off():
    """The face does not stop a click any more (#43)."""
    eng, log = core.GestureEngine(), []
    t = run(eng, point_hand(), 0.3, 0.0, log, face=FACE_BOX)
    t = run(eng, pinch_hand(), 0.2, t, log, face=FACE_BOX)
    run(eng, point_hand(), 0.3, t, log, face=FACE_BOX)
    assert "click" in names(log), log


def test_pinch_on_the_face_is_refused_with_the_zone_on():
    """Turned on, the old blocking of #9 and #25 is back."""
    eng, log = engine(face_zone=True), []
    t = run(eng, point_hand(), 0.3, 0.0, log, face=FACE_BOX)
    t = run(eng, pinch_hand(), 0.2, t, log, face=FACE_BOX)
    run(eng, point_hand(), 0.3, t, log, face=FACE_BOX)
    assert "click" not in names(log), log
    assert "mouse_down" not in names(log), log


# --- scrolling --------------------------------------------------------------

def test_tilt_scroll_in_front_of_the_face_scrolls_with_the_zone_off():
    """The tilt scroll (#22) works in front of the face."""
    eng, log = engine(scroll_mode="tilt"), []
    run(eng, tilted_hand(70), 1.0, 0.0, log, face=FACE_BOX)
    assert "scroll_drag" in names(log), log


def test_joystick_scroll_in_front_of_the_face_scrolls_with_the_zone_off():
    """The gas pedal scrolls in front of the face too (the Mac default)."""
    eng, log = engine(scroll_mode="joystick"), []
    t = run(eng, two_hand(), 0.6, 0.0, log, face=FACE_BOX)   # neutral
    mpalm = eng.debug["mpalm"]
    run(eng, two_hand(cy=300.0 + mpalm), 0.8, t, log, face=FACE_BOX)
    assert "scroll_drag" in names(log), log


def test_joystick_scroll_at_the_face_is_blocked_with_the_zone_on():
    eng, log = engine(face_zone=True, scroll_mode="joystick"), []
    t = run(eng, two_hand(), 0.6, 0.0, log, face=FACE_BOX)
    mpalm = eng.debug["mpalm"]
    run(eng, two_hand(cy=300.0 + mpalm), 0.8, t, log, face=FACE_BOX)
    assert "scroll_drag" not in names(log), log


# --- swiping ----------------------------------------------------------------

def test_swipe_into_the_face_fires_with_the_zone_off():
    """A swipe that ends over the face is a swipe, not a reach for the face."""
    eng, log = core.GestureEngine(), []
    swipe_up(eng, log, cx=320.0, face=LAPTOP_FACE_BOX)
    assert "overview" in names(log), log


def test_swipe_into_the_face_is_blocked_with_the_zone_on():
    eng, log = engine(face_zone=True), []
    swipe_up(eng, log, cx=320.0, face=LAPTOP_FACE_BOX)
    assert "overview" not in names(log), log


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
