"""Tests for the slap (sideways sweep -> change Space) and the wave
(short strokes back and forth -> lock screen).

Builds synthetic MediaPipe landmarks for a flat hand, an open hand and the
other poses, and drives GestureEngine with them, so no camera, mouse or
keyboard is involved.  Run:

    python tests/test_slap_wave.py
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

FPS = 30.0
W, H = 640, 480

# A hand in the frame: the landmarks below are in "hand units", where the
# palm (wrist to middle knuckle) is 1.0 unit long, and the whole hand is
# scaled up by HAND_SCALE to pixels.  The four fingers point up (-y).
HAND_SCALE = 110.0

# Palm facing the camera, fingers up: knuckle row, then the three joints of
# each finger.  The fingertips almost touch (fingers held together) and the
# fingers lean in towards each other, like a flat hand used to chop.  The
# thumb lies along the index finger, so the tips form one tight cluster.
FLAT_HAND = {
    0: (0.00, 0.00),        # wrist
    1: (-0.18, -0.15),      # thumb CMC
    2: (-0.35, -0.42),      # thumb MCP
    3: (-0.42, -0.90),      # thumb IP
    4: (-0.40, -1.55),      # thumb tip
    5: (-0.35, -0.92),      # index MCP
    6: (-0.32, -1.45),      # index PIP
    7: (-0.15, -1.90),      # index DIP
    8: (0.02, -2.30),       # index tip
    9: (0.00, -1.00),       # middle MCP
    10: (0.00, -1.55),      # middle PIP
    11: (-0.04, -2.08),     # middle DIP
    12: (0.03, -2.42),      # middle tip
    13: (0.30, -0.95),      # ring MCP
    14: (0.28, -1.45),      # ring PIP
    15: (0.20, -1.98),      # ring DIP
    16: (0.10, -2.28),      # ring tip
    17: (0.58, -0.72),      # pinky MCP
    18: (0.55, -1.10),      # pinky PIP
    19: (0.42, -1.48),      # pinky DIP
    20: (0.22, -1.92),      # pinky tip
}

# The same hand with the fingers spread wide: an "open" hand.
OPEN_HAND = dict(FLAT_HAND)
OPEN_HAND.update({
    8: (-1.05, -2.20),      # index tip
    12: (-0.20, -2.60),     # middle tip
    16: (0.60, -2.40),      # ring tip
    20: (1.20, -1.90),      # pinky tip
})

# Index and middle up, ring and pinky curled: the "two" pose.
TWO_HAND = dict(FLAT_HAND)
TWO_HAND.update({
    14: (0.30, -1.05),      # ring PIP, folded
    15: (0.30, -1.00),      # ring DIP
    16: (0.30, -0.95),      # ring tip
    18: (0.58, -0.85),      # pinky PIP, folded
    19: (0.58, -0.80),      # pinky DIP
    20: (0.58, -0.75),      # pinky tip
})

# Index up, the other three curled: the "point" pose.
POINT_HAND = dict(TWO_HAND)
POINT_HAND.update({
    10: (0.00, -1.10),      # middle PIP, folded
    11: (0.00, -1.05),      # middle DIP
    12: (0.00, -1.00),      # middle tip
})

# All four fingers curled: a fist.
FIST_HAND = dict(FLAT_HAND)
for mcp, pip, dip, tip in ((5, (-0.30, -0.95), (-0.12, -0.82), (-0.02, -0.72)),
                            (9, (0.02, -0.98), (0.12, -0.85), (0.18, -0.75)),
                            (13, (0.30, -0.95), (0.34, -0.82), (0.36, -0.72)),
                            (17, (0.56, -0.78), (0.56, -0.68), (0.56, -0.60))):
    FIST_HAND[mcp + 1] = pip
    FIST_HAND[mcp + 2] = dip
    FIST_HAND[mcp + 3] = tip
# The thumb is tucked against the palm, so the hand reads as a fist.
FIST_HAND.update({
    1: (-0.20, -0.18),      # thumb CMC
    2: (-0.34, -0.38),      # thumb MCP
    3: (-0.36, -0.60),      # thumb IP
    4: (-0.30, -0.78),      # thumb tip
})

# Thumb and pinky out, the three middle fingers curled: hang loose (shaka).
SHAKA_HAND = dict(FLAT_HAND)
SHAKA_HAND.update({
    6: (-0.32, -1.05),      # index PIP, folded
    7: (-0.30, -1.02),      # index DIP
    8: (-0.28, -1.00),      # index tip
    10: (0.00, -1.10),      # middle PIP, folded
    11: (0.02, -1.05),      # middle DIP
    12: (0.04, -1.00),      # middle tip
    14: (0.28, -1.05),      # ring PIP, folded
    15: (0.30, -1.00),      # ring DIP
    16: (0.32, -0.95),      # ring tip
    4: (-1.05, -1.60),      # thumb tip, out
})


def hand(template, x, y, mirror=False, scale=None):
    """21 pixel landmarks of `template` with the wrist at (x, y).  With
    mirror the hand is flipped left/right, which is what the camera sees
    for the other hand or the back of the hand."""
    if scale is None:
        scale = HAND_SCALE
    pts = []
    for i in range(21):
        px, py = template[i]
        if mirror:
            px = -px
        pts.append((x + px * scale, y + py * scale))
    return pts


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


def feed(engine, pts, t, log, w=W, h=H):
    """One frame; append (time, action) to `log`."""
    for name, _ in engine.update(pts, w, h, t):
        log.append((t, name))
    return t + 1.0 / FPS


def hold(engine, template, x, y, seconds, t, log, mirror=False, scale=None):
    """Keep the hand still at (x, y)."""
    end = t + seconds
    while t < end - 1e-9:
        t = feed(engine, hand(template, x, y, mirror, scale), t, log)
    return t


def sweep(engine, template, x0, x1, seconds, t, log, mirror=False, y=300.0,
          scale=None):
    """Move the hand sideways from x0 to x1, in `seconds`."""
    end = t + seconds
    while t < end - 1e-9:
        k = (t - (end - seconds)) / seconds
        x = x0 + (x1 - x0) * k
        t = feed(engine, hand(template, x, y, mirror, scale), t, log)
    return t


def spaces(log):
    return [name for _, name in log if name in ("space_left", "space_right")]


def locks(log):
    return [name for _, name in log if name == "lock"]


def test_flat_hand_is_classified_flat():
    pts = hand(FLAT_HAND, 320, 300)
    assert pose_of(pts) == "flat", pose_of(pts)
    # ... and the mirrored hand (other hand / back of the hand) too.
    assert pose_of(hand(FLAT_HAND, 320, 300, mirror=True)) == "flat"


def test_the_other_poses_are_unchanged():
    assert pose_of(hand(OPEN_HAND, 320, 300)) == "open"
    assert pose_of(hand(SHAKA_HAND, 320, 300)) == "shaka", pose_of(hand(SHAKA_HAND, 320, 300))
    assert pose_of(hand(TWO_HAND, 320, 300)) == "two", pose_of(hand(TWO_HAND, 320, 300))
    assert pose_of(hand(POINT_HAND, 320, 300)) == "point", pose_of(hand(POINT_HAND, 320, 300))
    assert pose_of(hand(FIST_HAND, 320, 300)) == "fist", pose_of(hand(FIST_HAND, 320, 300))


def test_flat_hand_does_not_open_the_gather_launcher():
    # The gather (Spotlight) launcher only follows an "open" hand, and a
    # flat hand must not feed it.
    eng, log = core.GestureEngine(), []
    hold(eng, FLAT_HAND, 320, 300, 0.6, 0.0, log)
    assert eng.last_open_time == -1e9, eng.last_open_time


def test_flat_slap_right_and_left_change_space():
    for mirror in (False, True):
        eng, log = core.GestureEngine(), []
        t = hold(eng, FLAT_HAND, 120, 300, 0.5, 0.0, log, mirror)
        t = sweep(eng, FLAT_HAND, 120, 350, 0.18, t, log, mirror)
        t = hold(eng, FLAT_HAND, 350, 300, 0.6, t, log, mirror)
        assert len(spaces(log)) == 1, (mirror, log)
        assert not locks(log), (mirror, log)
        first = spaces(log)[0]

        eng, log = core.GestureEngine(), []
        t = hold(eng, FLAT_HAND, 520, 300, 0.5, 0.0, log, mirror)
        t = sweep(eng, FLAT_HAND, 520, 290, 0.18, t, log, mirror)
        t = hold(eng, FLAT_HAND, 290, 300, 0.6, t, log, mirror)
        assert len(spaces(log)) == 1, (mirror, log)
        assert not locks(log), (mirror, log)
        assert spaces(log)[0] != first, (mirror, log)


def test_the_slap_direction_follows_natural_swipe():
    # A hand moving to the right is the previous Space when NATURAL_SWIPE
    # is on (the hand pushes the screen), and the next one when it is off.
    right, left = ("space_left", "space_right") if core.NATURAL_SWIPE else (
        "space_right", "space_left")
    for mirror in (False, True):
        eng, log = core.GestureEngine(), []
        t = hold(eng, FLAT_HAND, 120, 300, 0.5, 0.0, log, mirror)
        t = sweep(eng, FLAT_HAND, 120, 350, 0.18, t, log, mirror)
        assert spaces(log) == [right], (mirror, log)

        eng, log = core.GestureEngine(), []
        t = hold(eng, FLAT_HAND, 520, 300, 0.5, 0.0, log, mirror)
        t = sweep(eng, FLAT_HAND, 520, 290, 0.18, t, log, mirror)
        assert spaces(log) == [left], (mirror, log)


def test_open_hand_slap_still_fires():
    eng, log = core.GestureEngine(), []
    t = hold(eng, OPEN_HAND, 120, 300, 0.5, 0.0, log)
    t = sweep(eng, OPEN_HAND, 120, 350, 0.18, t, log)
    t = hold(eng, OPEN_HAND, 350, 300, 0.6, t, log)
    assert len(spaces(log)) == 1, log
    assert not locks(log), log


def test_wave_locks_and_does_not_change_space():
    for template in (OPEN_HAND, FLAT_HAND):
        eng, log = core.GestureEngine(), []
        t = hold(eng, template, 320, 300, 0.5, 0.0, log)
        # Four short strokes back and forth, well inside the wave window.
        x = 320.0
        for i in range(4):
            x = 320.0 + (34.0 if i % 2 == 0 else -34.0)
            t = sweep(eng, template, 320.0, x, 0.16, t, log)
            t = sweep(eng, template, x, 320.0, 0.16, t, log)
        t = hold(eng, template, 320, 300, 0.6, t, log)
        assert len(locks(log)) == 1, (template, log)
        assert not spaces(log), (template, log)


def test_slap_back_and_forth_never_locks():
    eng, log = core.GestureEngine(), []
    t = hold(eng, FLAT_HAND, 120, 300, 0.5, 0.0, log)
    for i in range(2):
        t = sweep(eng, FLAT_HAND, 120, 520, 0.18, t, log)
        t = hold(eng, FLAT_HAND, 520, 300, 0.3, t, log)
        t = sweep(eng, FLAT_HAND, 520, 120, 0.18, t, log)
        t = hold(eng, FLAT_HAND, 120, 300, 1.0, t, log)
    assert len(spaces(log)) == 2, log
    assert not locks(log), log


def test_a_short_move_passes_the_palm_check_but_not_the_travel_check():
    # A small hand (palm 45 px) makes 1.8 palms only ~81 px, so a 130 px
    # sweep is far enough for the palm distance check.  It is still shorter
    # than SLAP_MIN_TRAVEL_FRAC of the frame, so it must not switch Space.
    small = 45.0
    eng, log = core.GestureEngine(), []
    t = hold(eng, FLAT_HAND, 250, 300, 0.5, 0.0, log, scale=small)
    t = sweep(eng, FLAT_HAND, 250, 380, 0.18, t, log, scale=small)
    t = hold(eng, FLAT_HAND, 380, 300, 0.6, t, log, scale=small)
    assert not spaces(log), log
    assert not locks(log), log


def test_a_slap_resets_the_wave_tracker():
    # A slap is a sweep, not a wave: after it the tracker must start over,
    # so the strokes that follow cannot add up to a lock.
    eng, log = core.GestureEngine(), []
    t = hold(eng, FLAT_HAND, 120, 300, 0.5, 0.0, log)
    t = sweep(eng, FLAT_HAND, 120, 350, 0.18, t, log)
    assert len(spaces(log)) == 1, log
    assert eng.wave_flips == deque(), eng.wave_flips
    assert eng.wave_anchor is None, eng.wave_anchor


def test_a_long_stroke_never_counts_as_a_wave():
    # One long stroke (a sweep) must not leave the wave tracker half way
    # through a stroke: the stroke is longer than WAVE_MAX_STROKE_PALMS.
    eng = core.GestureEngine()
    eng.pose = "open"
    assert eng._wave_step(0.0, 0.0) is False
    assert eng._wave_step(3.0, 0.1) is False        # a long sweep
    assert eng.wave_anchor is None, eng.wave_anchor
    assert eng.wave_flips == deque(), eng.wave_flips


def test_small_sideways_move_does_nothing():
    eng, log = core.GestureEngine(), []
    t = hold(eng, FLAT_HAND, 300, 300, 0.5, 0.0, log)
    t = sweep(eng, FLAT_HAND, 300, 364, 0.18, t, log)
    t = hold(eng, FLAT_HAND, 364, 300, 0.6, t, log)
    assert not spaces(log), log
    assert not locks(log), log


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
