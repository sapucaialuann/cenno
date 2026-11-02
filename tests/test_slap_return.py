"""Tests for the slap (Space switch) gestures.

A natural slap is not a clean swipe in the middle of the frame:

  - the hand often starts partly outside the frame and sweeps in,
  - it crosses the face box on the way,
  - the stroke that brings the hand back must not switch Spaces again,
  - the fingers bunch up in the middle of a slap, which must not open
    Spotlight.

Builds synthetic MediaPipe landmarks and drives GestureEngine with them, so
no camera, mouse or keyboard is involved.  Run:

    python tests/test_slap_return.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
from tests.test_face_zone import open_hand       # noqa: E402
import test_slap_wave as sw                      # noqa: E402

FPS = 30.0
W, H = 640, 480

# A face box in the middle of the frame, big enough for the hand below to
# move around inside it without leaving.
FACE_BOX = (150.0, 120.0, 490.0, 440.0)


# --- synthetic hands -------------------------------------------------------

def hand_at(cx, cy, scale=1.0):
    """The open hand, with its wrist at (cx, cy)."""
    return open_hand(cx=cx, cy=cy, scale=scale)


def bunched_hand(cx, cy, scale=1.0):
    """An open hand whose fingertips are pulled together: the gather pose
    that opens Spotlight, but only when the hand is not moving."""
    pts = open_hand(cx=cx, cy=cy, scale=scale)
    tips = (4, 8, 12, 16, 20)
    tx = sum(pts[i][0] for i in tips) / len(tips)
    ty = sum(pts[i][1] for i in tips) / len(tips)
    for i in tips:
        pts[i] = (tx, ty)
    return pts


# --- driving the engine ----------------------------------------------------

def names(log):
    return [n for _, n in log]


def spaces(log):
    return [n for _, n in log if n in ("space_left", "space_right")]


def launchers(log):
    return [n for _, n in log if n == "launcher"]


def feed(engine, pts, t, log, face=None):
    """One frame; append (time, action) to `log`."""
    for name, _ in engine.update(pts, W, H, t, face=face):
        log.append((t, name))
    return t + 1.0 / FPS


def hold(engine, cx, cy, seconds, t, log, face=None):
    """Keep the hand still at (cx, cy)."""
    end = t + seconds
    while t < end - 1e-9:
        t = feed(engine, hand_at(cx, cy), t, log, face=face)
    return t


def stroke(engine, x0, x1, seconds, t, log, cy=300.0, face=None):
    """Move the hand sideways from x0 to x1, in `seconds`."""
    end = t + seconds
    start = end - seconds
    while t < end - 1e-9:
        k = (t - start) / seconds
        t = feed(engine, hand_at(x0 + (x1 - x0) * k, cy), t, log, face=face)
    return t


def stroke_outside(engine, x0, x1, seconds, t, log, cy=300.0):
    """Move the hand sideways, but keep it half outside the frame.

    The hand is placed so that part of it hangs over the left edge of the
    frame, the way a hand does when it sweeps in from the side.
    """
    end = t + seconds
    start = end - seconds
    while t < end - 1e-9:
        k = (t - start) / seconds
        x = x0 + (x1 - x0) * k
        # The wrist sits left of the frame, so the fingertips are outside.
        t = feed(engine, hand_at(x, cy), t, log)
    return t


# --- the tests -------------------------------------------------------------

def test_a_fast_sweep_from_outside_the_frame_switches_spaces():
    """The hand comes in from the edge of the frame in one fast stroke: it
    is not warmed up yet, but it is a slap going by."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    # The hand starts outside the frame and sweeps right into it.
    t = stroke_outside(eng, -40.0, 480.0, 0.30, t, log)
    assert spaces(log), log
    assert spaces(log)[0] == "space_left", log


def test_a_slow_hand_entering_the_frame_does_not_switch_spaces():
    """The same entry, but slow: that is the hand coming into view, not a
    slap, so nothing happens."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = stroke_outside(eng, -40.0, 480.0, 2.0, t, log)
    assert not spaces(log), log


def test_a_slap_then_an_immediate_return_switches_once():
    """One slap, then the hand comes straight back: one Space switch, not
    two."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = hold(eng, 320.0, 300.0, 0.4, t, log)
    t = stroke(eng, 150.0, 490.0, 0.25, t, log)      # the slap, to the right
    t = hold(eng, 490.0, 300.0, 0.05, t, log)       # barely a pause
    t = stroke(eng, 490.0, 150.0, 0.25, t, log)      # the return, to the left
    assert spaces(log) == ["space_left"], log


def test_a_fast_slap_across_a_face_box_switches_spaces():
    """On a laptop webcam the face is in the middle of the frame, so a real
    slap crosses the face box.  It must still switch Spaces."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = hold(eng, 320.0, 300.0, 0.4, t, log, face=FACE_BOX)
    t = stroke(eng, 150.0, 490.0, 0.25, t, log, face=FACE_BOX)
    assert spaces(log) == ["space_left"], log


def test_slow_movement_at_the_face_does_nothing():
    """Scratching your face looks like a swipe, so slow movement there is
    still ignored."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = hold(eng, 320.0, 300.0, 0.4, t, log, face=FACE_BOX)
    t = stroke(eng, 200.0, 440.0, 1.2, t, log, face=FACE_BOX)
    assert not spaces(log), log
    assert "lock" not in names(log), log


def test_an_open_hand_sweeping_fast_does_not_open_spotlight():
    """The fingers bunch up in the middle of a slap.  That must not open
    Spotlight while the hand is still moving."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = hold(eng, 320.0, 300.0, 0.4, t, log)
    # The hand sweeps to the right and the fingers bunch up on the way.
    end = t + 0.30
    start = end - 0.30
    while t < end - 1e-9:
        k = (t - start) / 0.30
        x = 200.0 + 300.0 * k
        t = feed(eng, bunched_hand(x, 300.0), t, log)
    assert not launchers(log), log


def test_a_still_open_hand_then_gather_still_opens_spotlight():
    """The normal Spotlight gesture: an open hand that stands still and
    then bunches its fingertips together."""
    eng, log = core.GestureEngine(), []
    t = 0.0
    t = hold(eng, 320.0, 300.0, 0.5, t, log)
    end = t + 0.7
    while t < end - 1e-9:
        t = feed(eng, bunched_hand(320.0, 300.0), t, log)
    assert launchers(log), log


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
