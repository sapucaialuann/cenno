"""Tests for the face zone: motion gestures are ignored while the hand is
at the user's face, but hold poses (shaka, thumbs up, ...) still work.

Builds synthetic MediaPipe landmarks and drives GestureEngine with them, so
no camera, mouse or keyboard is involved.  Run:

    python tests/test_face_zone.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

FPS = 30.0

# A face box in the middle of the frame, big enough for the hands below to
# move around inside it without leaving.
FACE_BOX = (150.0, 120.0, 490.0, 440.0)
# A face box far away in the corner: the hand is nowhere near it.
FAR_FACE_BOX = (0.0, 0.0, 60.0, 60.0)


# --- synthetic hands -------------------------------------------------------

def open_hand(cx=320, cy=300, scale=1.0):
    """Four fingers spread and up: the swipe / wave hand."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy + 100 * scale)                       # wrist
    pts[1] = (cx - 60 * scale, cy + 70 * scale)
    pts[2] = (cx - 90 * scale, cy + 40 * scale)
    pts[3] = (cx - 110 * scale, cy + 10 * scale)
    pts[4] = (cx - 130 * scale, cy - 20 * scale)           # thumb out
    for mcp, dx in ((5, -70), (9, -30), (13, 10), (17, 50)):
        x = cx + dx * scale
        pts[mcp] = (x, cy + 70 * scale)
        pts[mcp + 1] = (x, cy + 30 * scale)
        pts[mcp + 2] = (x, cy - 10 * scale)
        pts[mcp + 3] = (x, cy - 50 * scale)                 # tip
    return pts


def two_hand(cx=320, cy=300, scale=1.0):
    """Index and middle up, ring and pinky curled: the scroll hand."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy + 100 * scale)
    pts[1] = (cx - 60 * scale, cy + 70 * scale)
    pts[2] = (cx - 85 * scale, cy + 45 * scale)
    pts[3] = (cx - 95 * scale, cy + 20 * scale)
    pts[4] = (cx - 105 * scale, cy - 5 * scale)
    for mcp, x in ((5, cx - 50 * scale), (9, cx - 10 * scale)):
        pts[mcp] = (x, cy + 70 * scale)
        pts[mcp + 1] = (x, cy + 30 * scale)
        pts[mcp + 2] = (x, cy - 10 * scale)
        pts[mcp + 3] = (x, cy - 50 * scale)
    for mcp, x in ((13, cx + 25 * scale), (17, cx + 60 * scale)):
        pts[mcp] = (x, cy + 70 * scale)
        pts[mcp + 1] = (x, cy + 30 * scale)
        pts[mcp + 2] = (x, cy + 60 * scale)
        pts[mcp + 3] = (x, cy + 80 * scale)
    return pts


def point_hand(cx=320, cy=300, scale=1.0):
    """Index up, the rest curled: the pointer hand."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy + 100 * scale)
    pts[1] = (cx - 60 * scale, cy + 70 * scale)
    pts[2] = (cx - 90 * scale, cy + 45 * scale)
    pts[3] = (cx - 105 * scale, cy + 15 * scale)
    pts[4] = (cx - 115 * scale, cy - 15 * scale)
    pts[5] = (cx - 40 * scale, cy + 70 * scale)
    pts[6] = (cx - 40 * scale, cy + 30 * scale)
    pts[7] = (cx - 40 * scale, cy - 10 * scale)
    pts[8] = (cx - 40 * scale, cy - 50 * scale)
    for mcp, x in ((9, cx), (13, cx + 35 * scale), (17, cx + 70 * scale)):
        pts[mcp] = (x, cy + 70 * scale)
        pts[mcp + 1] = (x, cy + 30 * scale)
        pts[mcp + 2] = (x, cy + 60 * scale)
        pts[mcp + 3] = (x, cy + 80 * scale)
    return pts


def shaka_hand(cx=320, cy=300, scale=1.0):
    """Thumb and pinky out, the three middle fingers curled: hang loose."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy + 100 * scale)
    pts[1] = (cx - 60 * scale, cy + 70 * scale)
    pts[2] = (cx - 95 * scale, cy + 45 * scale)
    pts[3] = (cx - 120 * scale, cy + 15 * scale)
    pts[4] = (cx - 145 * scale, cy - 20 * scale)            # thumb out
    for mcp, x in ((5, cx - 40 * scale), (9, cx), (13, cx + 35 * scale)):
        pts[mcp] = (x, cy + 70 * scale)
        pts[mcp + 1] = (x, cy + 30 * scale)
        pts[mcp + 2] = (x, cy + 60 * scale)
        pts[mcp + 3] = (x, cy + 80 * scale)
    pts[17] = (cx + 70 * scale, cy + 70 * scale)
    pts[18] = (cx + 70 * scale, cy + 20 * scale)
    pts[19] = (cx + 70 * scale, cy - 30 * scale)
    pts[20] = (cx + 70 * scale, cy - 80 * scale)            # pinky up high
    return pts


def fist(thumb="up", cx=300, cy=400):
    """A fist with the thumb pointing `thumb` (see test_thumb_arrows.py)."""
    tips = {
        "tucked": ((278, 335), (268, 345)),
        "up": ((250, 230), (252, 290)),
        "down": ((250, 480), (252, 420)),
        "left": ((170, 350), (212, 352)),
        "right": ((440, 350), (350, 352)),
    }
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy)
    pts[1], pts[2] = (cx - 35, cy - 15), (cx - 45, cy - 45)
    pts[3], pts[4] = tips[thumb][1], tips[thumb][0]
    for mcp, x, y in ((5, cx - 30, cy - 100), (9, cx, cy - 105),
                      (13, cx + 30, cy - 100), (17, cx + 55, cy - 90)):
        pts[mcp] = (x, y)
        pts[mcp + 1] = (x, y - 45)
        pts[mcp + 2] = (x, y - 40)
        pts[mcp + 3] = (x, y - 10)
    return pts


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


# --- driving the engine ----------------------------------------------------

def run(engine, pts, seconds, t, log, face=None):
    """Feed `pts` at 30 fps for `seconds`; append (time, action) to `log`."""
    end = t + seconds
    while t < end - 1e-9:
        for name, _ in engine.update(pts, 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    return t


def names(log):
    return [n for _, n in log]


def sweep(engine, log, maker, face, seconds=0.25, dx=220.0, t=0.0,
          x0=150.0, cy=300.0, hold=0.35):
    """A fast horizontal sweep: the hand crosses `dx` pixels in `seconds`.

    The hand is held still first, so the entry warm-up is over and the
    sweep itself is what the engine sees.
    """
    end = t + hold
    while t < end - 1e-9:
        for name, _ in engine.update(maker(cx=x0, cy=cy), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    steps = int(seconds * FPS)
    for i in range(steps + 1):
        pts = maker(cx=x0 + dx * i / steps, cy=cy)
        for name, _ in engine.update(pts, 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    return t


def vertical_stroke(engine, log, maker, face, seconds=0.25, dy=140.0, t=0.0,
                    cx=320.0, y0=210.0, hold=0.35):
    """A fast vertical stroke with two fingers: the scroll gesture."""
    end = t + hold
    while t < end - 1e-9:
        for name, _ in engine.update(maker(cx=cx, cy=y0), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    steps = int(seconds * FPS)
    for i in range(steps + 1):
        pts = maker(cx=cx, cy=y0 + dy * i / steps)
        for name, _ in engine.update(pts, 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    return t


# --- the fixtures themselves must be sane ----------------------------------

def test_fixtures_classify():
    assert pose_of(open_hand()) == "open"
    assert pose_of(two_hand()) == "two"
    assert pose_of(point_hand()) == "point"
    assert pose_of(shaka_hand()) == "shaka"
    assert pose_of(fist("up")) == "thumbs_up"


def test_hands_sit_inside_the_face_box():
    for maker in (open_hand, two_hand, point_hand, shaka_hand):
        assert core.near_face(maker(), FACE_BOX), maker.__name__
        assert not core.near_face(maker(), FAR_FACE_BOX), maker.__name__
        assert not core.near_face(maker(), None), maker.__name__


# --- 1. shaka (dictation) still works at the face --------------------------

def test_shaka_at_the_face_starts_dictation_once():
    eng, log = core.GestureEngine(), []
    run(eng, shaka_hand(), 1.0, 0.0, log, face=FACE_BOX)
    assert names(log).count("dictation") == 1, log


def test_shaka_outside_the_face_also_starts_dictation():
    eng, log = core.GestureEngine(), []
    run(eng, shaka_hand(), 1.0, 0.0, log, face=None)
    assert names(log).count("dictation") == 1, log


# --- 2. thumbs up (play / pause) still works at the face -------------------

def test_thumbs_up_at_the_face_fires_play_pause():
    eng, log = core.GestureEngine(), []
    run(eng, fist("up"), 1.0, 0.0, log, face=FACE_BOX)
    assert names(log).count("play_pause") == 1, log


def test_thumb_left_at_the_face_fires_arrow():
    eng, log = core.GestureEngine(), []
    run(eng, fist("left"), 0.5, 0.0, log, face=FACE_BOX)
    assert names(log).count("arrow_left") == 1, log


# --- 3. swipes at the face do nothing --------------------------------------

def test_sweep_at_the_face_does_not_switch_spaces():
    eng, log = core.GestureEngine(), []
    sweep(eng, log, open_hand, FACE_BOX)
    assert not [n for n in names(log) if n.startswith("space_")], log
    assert "lock" not in names(log), log


def test_sweep_without_a_face_switches_spaces():
    eng, log = core.GestureEngine(), []
    sweep(eng, log, open_hand, None)
    fired = [n for n in names(log) if n.startswith("space_")]
    assert fired, log
    assert fired[0] in ("space_left", "space_right"), log


def test_sweep_with_a_far_away_face_switches_spaces():
    eng, log = core.GestureEngine(), []
    sweep(eng, log, open_hand, FAR_FACE_BOX)
    fired = [n for n in names(log) if n.startswith("space_")]
    assert fired, log


def wave(engine, log, face, seconds=1.4, cx=320.0, cy=300.0, t=0.0):
    """Side to side, the way you wave hello."""
    end = t + seconds
    i = 0
    while t < end - 1e-9:
        x = cx + (70 if (i // 3) % 2 else -70)
        for name, _ in engine.update(open_hand(cx=x, cy=cy), 640, 480, t, face=face):
            log.append((t, name))
        i += 1
        t += 1.0 / FPS
    return t


def test_wave_at_the_face_does_not_lock():
    eng, log = core.GestureEngine(), []
    wave(eng, log, FACE_BOX)
    assert "lock" not in names(log), log


def test_wave_without_a_face_locks():
    eng, log = core.GestureEngine(), []
    wave(eng, log, None)
    assert "lock" in names(log), log


# --- 4. the hand works again as soon as it leaves the face -----------------

def test_sweep_right_after_leaving_the_face_fires():
    eng, log = core.GestureEngine(), []
    t = sweep(eng, log, open_hand, FACE_BOX)     # at the face: nothing
    assert not [n for n in names(log) if n.startswith("space_")], log
    sweep(eng, log, open_hand, None, t=t)        # same sweep, no face
    fired = [n for n in names(log) if n.startswith("space_")]
    assert fired, log


# --- 5. two-finger scrolling at the face does nothing ---------------------

def test_two_finger_stroke_at_the_face_does_not_scroll():
    eng, log = core.GestureEngine(), []
    vertical_stroke(eng, log, two_hand, FACE_BOX)
    assert "scroll_drag" not in names(log), log
    assert "scroll_fling" not in names(log), log


def test_two_finger_stroke_without_a_face_scrolls():
    eng, log = core.GestureEngine(), []
    vertical_stroke(eng, log, two_hand, None)
    assert "scroll_drag" in names(log), log


# --- 6. the pointer at the face does nothing -------------------------------

def test_point_at_the_face_does_not_move_the_pointer():
    eng, log = core.GestureEngine(), []
    run(eng, point_hand(), 0.5, 0.0, log, face=FACE_BOX)
    assert "pointer_move" not in names(log), log
    assert "click" not in names(log), log


def test_point_without_a_face_moves_the_pointer():
    eng, log = core.GestureEngine(), []
    run(eng, point_hand(), 0.5, 0.0, log, face=None)
    assert "pointer_move" in names(log), log


def test_pointer_ends_cleanly_when_the_hand_reaches_the_face():
    eng, log = core.GestureEngine(), []
    run(eng, point_hand(), 0.3, 0.0, log, face=None)
    assert "pointer_move" in names(log), log
    mark = len(log)
    run(eng, point_hand(), 0.3, 0.3, log, face=FACE_BOX)
    tail = [n for _, n in log[mark:]]
    assert "pointer_end" in tail, tail
    assert "pointer_move" not in tail, tail


# --- the flag itself -------------------------------------------------------

def test_near_face_flag_and_debug():
    eng = core.GestureEngine()
    eng.update(open_hand(), 640, 480, 0.0, face=FACE_BOX)
    assert eng.near_face is True
    assert eng.debug["face"] is True
    eng.update(open_hand(), 640, 480, 0.1, face=None)
    assert eng.near_face is False
    assert eng.debug["face"] is False


def test_face_box_is_grown_by_the_margin():
    # A hand just outside the raw box but inside the grown one counts.
    x0, y0, x1, y1 = 200.0, 200.0, 300.0, 300.0
    mx = core.FACE_MARGIN * (x1 - x0)
    hand = [(x1 + mx - 1.0, y1 + my - 1.0) for my in (0.0,)] * 21
    assert core.near_face(hand, (x0, y0, x1, y1))
    far = [(x1 + mx + 20.0, y1)] * 21
    assert not core.near_face(far, (x0, y0, x1, y1))


def test_hand_share_threshold():
    # 12 of 21 landmarks inside is below the 60% share (and palm center outside) -> not at the face.
    box = (0.0, 0.0, 100.0, 100.0)
    hand = [(10.0, 10.0)] * 12 + [(500.0, 500.0)] * 9
    assert not core.near_face(hand, box)
    # 13 of 21 landmarks inside is >= 60% share -> at the face.
    hand = [(10.0, 10.0)] * 13 + [(500.0, 500.0)] * 8
    assert core.near_face(hand, box)


def test_palm_centre_inside_face_box():
    # Palm centre inside the box triggers near_face even below the landmark share.
    box = (0.0, 0.0, 100.0, 100.0)
    # Only 5 palm landmarks inside (5/21 = 24% < 60%), but palm centre is at (50, 50).
    hand = [(500.0, 500.0)] * 21
    for i in core.FACE_PALM_INDICES:
        hand[i] = (50.0, 50.0)
    assert core.near_face(hand, box)


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
