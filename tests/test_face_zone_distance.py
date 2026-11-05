"""Tests for the face zone and the hand's distance from the face (#41).

The face is in the middle of the frame on a laptop camera, so the hand
points, clicks and scrolls right through it.  Only a hand that is at the
face's distance from the camera (its palm looks about as wide as the face)
is really at the face: that is the hand that scratches, and that one must
not click and must not scroll.

Builds synthetic MediaPipe landmarks and drives GestureEngine with them, so
no camera, mouse or keyboard is involved.  Run:

    python tests/test_face_zone_distance.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
from test_face_zone import (                     # noqa: E402
    names, pinch_hand, point_hand, run, two_hand, vertical_stroke)

FPS = 30.0

# The laptop webcam face box (tests/test_face_zone_size.py): 150 px wide.
FACE_BOX = (245.0, 60.0, 395.0, 250.0)

# A hand at the face's distance from the camera.
ON_FACE_SCALE = 1.0
# A hand closer to the camera: it looks bigger next to the face.
CLOSE_SCALE = 1.6


def ratio(pts, face=FACE_BOX):
    """How wide the hand looks next to the face."""
    return core.face_ratio(core.palm_size(pts), face)


# The hand at the face: it overlaps the face box and is at its distance.
def on_face_point():
    return point_hand(cx=320.0, cy=170.0, scale=ON_FACE_SCALE)


def on_face_pinch():
    return pinch_hand(cy=170.0, scale=ON_FACE_SCALE)


# The hand in front of the face: bigger (closer to the camera).  Its palm
# is over the face, so the old rule blocked the click there.
def close_point():
    return point_hand(cx=320.0, cy=120.0, scale=CLOSE_SCALE)


def close_pinch():
    return pinch_hand(cy=120.0, scale=CLOSE_SCALE)


# The hand in front of the face, with the pinch fingers on the face box:
# the old rule blocked the click there too (the fingers on the face).
def close_pinch_on_face():
    """The pinch hand moved to the right, so the thumb tip is on the face."""
    pts = pinch_hand(cy=200.0, scale=CLOSE_SCALE)
    return [(x + 150.0, y) for x, y in pts]


# --- the rule itself --------------------------------------------------------

def test_a_hand_in_front_of_the_face_is_not_at_the_face():
    pts = close_point()
    assert core.near_face(pts, FACE_BOX), "the hand does not overlap the face"
    assert ratio(pts) > core.FACE_REST_PALM_RATIO
    assert not core.at_face(pts, FACE_BOX, core.palm_size(pts))


def test_a_hand_at_the_face_is_at_the_face():
    pts = on_face_point()
    assert core.near_face(pts, FACE_BOX)
    assert ratio(pts) <= core.FACE_REST_PALM_RATIO
    assert core.at_face(pts, FACE_BOX, core.palm_size(pts))


def test_no_face_is_never_at_the_face():
    pts = close_point()
    assert not core.at_face(pts, None, core.palm_size(pts))


def test_face_ratio_without_a_face():
    assert core.face_ratio(100.0, None) == 0.0
    assert core.face_ratio(100.0, (0.0, 0.0, 0.0, 0.0)) == 0.0


def test_face_ratio_is_the_palm_over_the_face_width():
    assert abs(core.face_ratio(50.0, (0.0, 0.0, 100.0, 100.0)) - 0.5) < 1e-9


# --- the click in front of the face -----------------------------------------

def test_a_pinch_in_front_of_the_face_clicks():
    """The cursor moves in front of the face (#9), so the click has to work
    there too: on a laptop camera that is where the hand is."""
    eng, log = core.GestureEngine(), []
    t = run(eng, close_point(), 0.3, 0.0, log, face=FACE_BOX)
    t = run(eng, close_pinch(), 0.2, t, log, face=FACE_BOX)
    run(eng, close_point(), 0.3, t, log, face=FACE_BOX)
    assert "click" in names(log), log


def test_a_pinch_with_the_fingers_on_the_face_clicks_when_it_is_closer():
    """The pinch fingers on the face box, but the hand is closer to the
    camera than the face: that is a click in front of the face."""
    eng, log = core.GestureEngine(), []
    point = [(x + 150.0, y) for x, y in
             point_hand(cx=320.0, cy=200.0, scale=CLOSE_SCALE)]
    pinch = close_pinch_on_face()
    assert core.pinch_at_face(pinch, FACE_BOX), "the fingers are not on the face"
    t = run(eng, point, 0.3, 0.0, log, face=FACE_BOX)
    t = run(eng, pinch, 0.2, t, log, face=FACE_BOX)
    run(eng, point, 0.3, t, log, face=FACE_BOX)
    assert "click" in names(log), log


def test_a_pinch_at_the_face_does_not_click():
    """The scratch that looks like a pinch: the hand is on the face."""
    eng, log = core.GestureEngine(), []
    t = run(eng, on_face_point(), 0.3, 0.0, log, face=FACE_BOX)
    t = run(eng, on_face_pinch(), 0.2, t, log, face=FACE_BOX)
    run(eng, on_face_point(), 0.3, t, log, face=FACE_BOX)
    assert "click" not in names(log), log
    assert "mouse_down" not in names(log), log


def test_a_hand_in_front_of_the_face_still_moves_the_pointer():
    eng, log = core.GestureEngine(), []
    run(eng, close_point(), 0.5, 0.0, log, face=FACE_BOX)
    assert "pointer_move" in names(log), log


# --- the gestures in front of the face --------------------------------------

def test_a_scroll_in_front_of_the_face_scrolls():
    """The hand scrolls in front of the face: that is a real gesture."""
    eng, log = core.GestureEngine(), []
    vertical_stroke(eng, log,
                    lambda cx, cy: two_hand(cx=cx, cy=cy, scale=CLOSE_SCALE),
                    FACE_BOX, y0=120.0)
    assert "scroll_drag" in names(log), log


def test_a_scroll_at_the_face_does_not_scroll():
    eng, log = core.GestureEngine(), []
    vertical_stroke(eng, log, lambda cx, cy: two_hand(cx=320.0, cy=200.0), FACE_BOX)
    assert "scroll_drag" not in names(log), log


# --- the flag itself --------------------------------------------------------

def test_the_engine_reports_the_hand_at_the_face():
    eng = core.GestureEngine()
    eng.update(on_face_point(), 640, 480, 0.0, face=FACE_BOX)
    assert eng.at_face is True
    assert eng.debug["at_face"] is True
    eng.update(close_point(), 640, 480, 0.1, face=FACE_BOX)
    assert eng.at_face is False
    assert eng.debug["at_face"] is False
    assert eng.debug["face_ratio"] > core.FACE_REST_PALM_RATIO


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
