"""Tests for the natural gesture check scoring.

Builds synthetic recordings in memory, so no camera is needed.  Run:

    python3 tests/test_natural_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

import gesture_check                              # noqa: E402
from test_face_zone import open_hand               # noqa: E402

FPS = 30.0
W, H = 640, 480
# The hand travels across this part of the frame, so the swipe is long
# enough for the engine to treat it as a slap.
X0, X1 = 90.0, 550.0


def frame(t, rep=None, pts=None, handed=None):
    return dict(t=round(t, 4), lead=False, rep=rep, w=W, h=H,
                pts=[[round(x, 1), round(y, 1)] for x, y in pts] if pts else None,
                face=None, handed=handed)


def add_frames(frames, t, rep, pts, handed="Right", seconds=None):
    """Add frames of one hand position (or no hand) for `seconds`."""
    end = t + (seconds if seconds is not None else 1.0 / FPS)
    while t < end - 1e-9:
        frames.append(frame(t, rep=rep, pts=pts,
                            handed=[handed, 0.99] if pts else None))
        t += 1.0 / FPS
    return t


def add_gone(frames, t, seconds=0.3):
    """A gap with no hand in view, so the engine forgets the last motion."""
    return add_frames(frames, t, None, None, seconds=seconds)


def add_still(frames, t, rep, seconds=0.6, hand="Right"):
    """A still hand, used to fill a window."""
    return add_frames(frames, t, rep, open_hand(X0, 300), hand, seconds=seconds)


def add_sweep(frames, t, rep, fast=True, hand="Right"):
    """A sideways sweep; the fast one must switch Space.

    The hand starts at the left of the frame and moves to the right.
    """
    t = add_frames(frames, t, rep, open_hand(X0, 300), hand, seconds=0.4)
    if fast:
        # A quick sweep across most of the frame.
        steps = 4
        for i in range(steps + 1):
            x = X0 + (X1 - X0) * i / steps
            t = add_frames(frames, t, rep, open_hand(x, 300), hand)
        # The hand rests at the end, so the swipe buffer sees the travel.
        t = add_frames(frames, t, rep, open_hand(X1, 300), hand, seconds=0.3)
    else:
        # A slow drift across the frame must not fire.
        steps = 20
        for i in range(steps + 1):
            x = X0 + (X1 - X0) * i / steps
            t = add_frames(frames, t, rep, open_hand(x, 300), hand)
    # The hand leaves the frame, so the engine forgets the motion.
    return add_gone(frames, t, seconds=0.4)


def add_window(frames, t, rep, fast=None, hand="Right"):
    """One full GO window: a still hand, then the sweep if asked for."""
    t = add_still(frames, t, rep, seconds=0.6, hand=hand)
    if fast is not None:
        t = add_sweep(frames, t, rep, fast=fast, hand=hand)
        t = add_still(frames, t, rep, seconds=0.6, hand=hand)
    else:
        t = add_still(frames, t, rep, seconds=1.5, hand=hand)
    return t


def add_window_with_gap(frames, t, rep, fast=None, hand="Right", gap=1.5):
    """A GO window followed by a rest gap, so the next window starts clean."""
    t = add_window(frames, t, rep, fast=fast, hand=hand)
    t = add_gone(frames, t, seconds=0.4)
    t = add_frames(frames, t, None, open_hand(X0, 300), seconds=gap)
    return t


def natural_step(step_id, hand, frames, reps=3, window=3.0):
    return dict(id=step_id, hand=hand, prompt="test", reps=reps,
                window=window, rest=1.5, skipped=False, result="done",
                frames=frames)


def test_synthetic_slaps_score_two_hits_one_miss():
    frames = []
    t = 0.0
    t = add_window_with_gap(frames, t, 1, fast=True)
    t = add_window_with_gap(frames, t, 2, fast=False)
    t = add_window(frames, t, 3, fast=True)
    rec = dict(mode="natural", w=W, h=H, steps=[
        natural_step("slap_right", "right", frames)])
    scored = gesture_check.score_natural(rec)
    assert len(scored) == 1, scored
    item = scored[0]
    assert item["hits"] == 2, item
    assert item["misses"] == 1, item
    assert item["wrong"] == 0, item
    assert item["wrong_hand"] == 0, item


def test_negative_still_hand_fires_nothing():
    frames = []
    t = 0.0
    t = add_still(frames, t, 0, seconds=3.0)
    rec = dict(mode="natural", w=W, h=H, steps=[
        natural_step("scratch_face", "right", frames, reps=1, window=10.0)])
    item = gesture_check.score_natural(rec)[0]
    assert item["wrong"] == 0, item
    assert item["hits"] == 0, item
    assert item["misses"] == 0, item


def test_negative_window_counts_a_slap_as_wrong():
    frames = []
    t = 0.0
    t = add_still(frames, t, 0, seconds=0.6)
    t = add_sweep(frames, t, 0, fast=True)
    rec = dict(mode="natural", w=W, h=H, steps=[
        natural_step("scratch_face", "right", frames, reps=1, window=10.0)])
    item = gesture_check.score_natural(rec)[0]
    assert item["wrong"] == 1, item
    assert item["wrong_events"] == ["space_left"], item
    assert item["hits"] == 0, item


def test_hands_are_reported_separately():
    right_frames = []
    t = 0.0
    t = add_window(right_frames, t, 1, fast=True, hand="Right")
    left_frames = []
    t = 0.0
    t = add_window(left_frames, t, 1, fast=True, hand="Left")
    rec = dict(mode="natural", w=W, h=H, steps=[
        natural_step("slap_right", "right", right_frames, reps=1),
        natural_step("slap_right", "left", left_frames, reps=1)])
    scored = gesture_check.score_natural(rec)
    assert len(scored) == 2, scored
    assert [(x["id"], x["hand"], x["hits"]) for x in scored] == [
        ("slap_right", "right", 1), ("slap_right", "left", 1)], scored


def test_mismatched_handedness_is_flagged():
    frames = []
    t = 0.0
    t = add_window(frames, t, 1, fast=True, hand="Left")
    rec = dict(mode="natural", w=W, h=H, steps=[
        natural_step("slap_right", "right", frames, reps=1)])
    item = gesture_check.score_natural(rec)[0]
    assert item["hits"] == 1, item
    assert item["wrong_hand"] == 1, item
    assert item["wrong_hand_reps"] == [1], item


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print("all natural check tests passed")
