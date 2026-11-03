"""Tests for tilt scrolling (#22): index and middle held together, the angle
they point at sets the scroll speed.  Synthetic landmarks, no camera.
Run:

    python tests/test_scroll_tilt.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

core.SCROLL_MODE = "tilt"     # the Windows app's default; every engine here tilts

FPS = 30.0
W, H = 640, 480
WRIST = (320.0, 300.0)


def two_hand(angle_deg, spread=0.0, dx=0.0, mirror=False):
    """Two-finger hand pointing `angle_deg` above level (negative = below),
    toward image-right (or image-left with `mirror`).  Index and middle are
    together; `spread` pushes their tips apart into a V (pixels)."""
    up = [(0.0, 0.0)] * 21          # pointing straight up, wrist at origin
    up[1], up[2], up[3], up[4] = (-38, -12), (-50, -38), (-54, -70), (-57, -94)
    for mcp, x in ((5, -12), (9, 12)):
        tip_x = x * 0.4 + (-spread / 2 if mcp == 5 else spread / 2)
        up[mcp] = (x, -100)
        up[mcp + 1] = (x * 0.8, -148)
        up[mcp + 2] = ((x + tip_x) / 2, -178)
        up[mcp + 3] = (tip_x, -208)
    for mcp, x in ((13, 34), (17, 56)):
        up[mcp] = (x, -94)
        up[mcp + 1] = (x, -140)
        up[mcp + 2] = (x, -135)
        up[mcp + 3] = (x, -104)
    # Rotate from "up" (90 deg) to the angle wanted; y grows downward.
    turn = math.radians(angle_deg - 90)
    if mirror:
        turn = math.radians(90 - angle_deg)
    c, s = math.cos(turn), math.sin(turn)
    pts = []
    for x, y in up:
        mx, my = x * c - (-y) * s, x * s + (-y) * c
        pts.append((WRIST[0] + mx + dx, WRIST[1] - my))
    return pts


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


def run(engine, pts_at, seconds, t, log, face=None):
    """Feed pts_at(i) (or a fixed hand) at 30 fps; log (time, name, value)."""
    n = int(round(seconds * FPS))
    for i in range(n):
        pts = pts_at(i) if callable(pts_at) else pts_at
        for name, v in engine.update(pts, W, H, t, face=face):
            log.append((t, name, v))
        t += 1.0 / FPS
    return t


def scroll_after(angle_deg, warmup=0.5, hold=0.5, **kw):
    """Mean scroll_drag per frame while holding a hand at `angle_deg`."""
    eng, log = core.GestureEngine(), []
    t = run(eng, two_hand(angle_deg, **kw), warmup, 0.0, log)
    start = t
    run(eng, two_hand(angle_deg, **kw), hold, t, log)
    ds = [v for tt, name, v in log if name == "scroll_drag" and tt >= start]
    return sum(ds) / max(len(ds), 1), len(ds)


def test_fixtures_are_two_fingers():
    for angle in (-90, -45, 0, 30, 60, 90):
        for mirror in (False, True):
            assert pose_of(two_hand(angle, mirror=mirror)) == "two", (angle, mirror)
    assert pose_of(two_hand(45, spread=80)) == "two"


def test_level_does_not_scroll():
    for angle in (0, 10, -10):
        mean, n = scroll_after(angle)
        assert n == 0, (angle, mean, n)


def test_pointing_up_scrolls_up_and_down_scrolls_down():
    up, n_up = scroll_after(60)
    down, n_down = scroll_after(-60)
    assert n_up and up > 0, up
    assert n_down and down < 0, down
    assert abs(abs(up) - abs(down)) < abs(up) * 0.01, (up, down)


def test_steeper_is_faster():
    speeds = [scroll_after(a)[0] for a in (35, 55, 75, 90)]
    assert all(b > a for a, b in zip(speeds, speeds[1:])), speeds


def test_top_speed_straight_up():
    mean, _ = scroll_after(90)
    want = core.TILT_MAX_PX_S / FPS / core.SCROLL_PX_PER_PALM
    assert abs(mean - want) < want * 0.02, (mean, want)


def test_left_and_right_hand_match():
    right, _ = scroll_after(50)
    left, _ = scroll_after(50, mirror=True)
    assert abs(right - left) < abs(right) * 0.01, (right, left)


def test_spread_v_does_not_scroll():
    mean, n = scroll_after(70, spread=80)
    assert n == 0, (mean, n)


def test_hand_position_does_not_matter():
    a, _ = scroll_after(60)
    b, _ = scroll_after(60, dx=-150)
    assert abs(a - b) < abs(a) * 0.01, (a, b)


def test_works_beside_the_face():
    face = (250, 150, 410, 330)            # a face box around the hand
    eng, log = core.GestureEngine(), []
    run(eng, two_hand(70), 1.0, 0.0, log, face=face)
    assert [e for e in log if e[1] == "scroll_drag"], log


def test_no_glide_when_the_pose_ends():
    eng, log = core.GestureEngine(), []
    t = run(eng, two_hand(80), 0.6, 0.0, log)
    assert [e for e in log if e[1] == "scroll_drag"], "it never scrolled"
    gone = eng.no_hand(t + 1.0)          # past the hand-lost grace time
    assert not [e for e in gone if e[0] == "scroll_fling"], gone


def test_back_forward_swipe_still_fires_with_a_tilted_hand():
    for sign in (1, -1):
        eng, log = core.GestureEngine(), []
        t = run(eng, two_hand(40, dx=-sign * 150), 0.6, 0.0, log)
        # a fast horizontal sweep, about 3 palms in 0.2 s
        run(eng, lambda i: two_hand(40, dx=-sign * 150 + sign * 50 * i), 0.2, t, log)
        t = run(eng, two_hand(40, dx=sign * 150), 0.4, t + 0.2, log)
        names = {e[1] for e in log}
        assert names & {"back", "forward"}, (sign, sorted(names))


def swipe(eng, log, angle, sign, t):
    """Hold, then a fast sideways sweep, as in Back / Forward."""
    t = run(eng, two_hand(angle, dx=-sign * 150), 0.6, t, log)
    return run(eng, lambda i: two_hand(angle, dx=-sign * 150 + sign * 50 * i), 0.2, t, log)


def drags_since(log, t):
    return [e for e in log if e[1] == "scroll_drag" and e[0] >= t]


def test_no_scroll_while_sweeping_sideways():
    eng, log = core.GestureEngine(), []
    t = run(eng, two_hand(50, dx=-150), 0.6, 0.0, log)
    start = t
    run(eng, lambda i: two_hand(50, dx=-150 + 50 * i), 0.2, t, log)
    # (the smoothed hand lags one frame behind, so the first one may scroll)
    assert len(drags_since(log, start)) <= 1, drags_since(log, start)


def test_no_scroll_after_a_swipe_until_the_fingers_come_level():
    eng, log = core.GestureEngine(), []
    t = swipe(eng, log, 50, 1, 0.0)
    assert {"back", "forward"} & {e[1] for e in log}, log
    start = t
    # still tilted after the swipe: blocked
    t = run(eng, two_hand(50, dx=150), 1.0, t, log)
    assert not drags_since(log, start), drags_since(log, start)
    # level, then tilt again: scrolls (dx=50 keeps level fingers in frame)
    t = run(eng, two_hand(0, dx=50), 0.5, t, log)
    start = t
    run(eng, two_hand(50, dx=50), 0.8, t, log)
    assert drags_since(log, start), "no scroll after levelling"


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    if failed:
        print(f"{failed} failed")
        sys.exit(1)
    print("all good")
