"""Tests for the thumb-sideways ("hitchhiker") Left / Right arrow gesture.

Builds synthetic MediaPipe landmarks for a fist and drives GestureEngine with
them, so no camera, mouse or keyboard is involved.  Run:

    python tests/test_thumb_arrows.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

FPS = 30.0

# Thumb tip (pt 4) and the joint before it (pt 3), per direction.  The thumb
# base (pts 1, 2) is fixed on the left of the palm.
THUMB_TIPS = {
    "tucked": ((278, 335), (268, 345)),
    "up": ((250, 230), (252, 290)),
    "down": ((250, 480), (252, 420)),
    "left": ((170, 350), (212, 352)),
    "right": ((440, 350), (350, 352)),
}


def make_fist(thumb="tucked", dx=0.0, dy=0.0):
    """21 pixel landmarks (y grows downward): a fist with every fingertip
    folded back below its PIP joint, and the thumb pointing `thumb`."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (300, 400)                              # wrist
    pts[1], pts[2] = (265, 385), (255, 355)          # thumb base
    pts[3], pts[4] = THUMB_TIPS[thumb][1], THUMB_TIPS[thumb][0]
    for mcp, x, y in ((5, 270, 300), (9, 300, 295), (13, 330, 300),
                      (17, 355, 310)):
        pts[mcp] = (x, y)
        pts[mcp + 1] = (x, y - 45)                   # PIP, straight up
        pts[mcp + 2] = (x, y - 40)                   # DIP, folding back
        pts[mcp + 3] = (x, y - 10)                   # tip, tucked into palm
    return [(x + dx, y + dy) for x, y in pts]


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


def run(engine, pts, seconds, t, log):
    """Feed `pts` at 30 fps for `seconds`; append (time, action) to `log`."""
    end = t + seconds
    while t < end - 1e-9:
        for name, _ in engine.update(pts, 640, 480, t):
            log.append((t, name))
        t += 1.0 / FPS
    return t


def arrows(log, name="arrow_left"):
    return [t for t, n in log if n == name]


def test_fixture_is_sane():
    pts = make_fist("tucked")
    for f in core.FINGERS:
        assert core.finger_ratio(pts, f) <= core.CURLED_RATIO, f
    assert pose_of(pts) == "fist"
    assert pose_of(make_fist("up")) == "thumbs_up"


def test_classify_thumb_poses():
    assert pose_of(make_fist("left")) == "thumb_left"
    assert pose_of(make_fist("right")) == "thumb_right"
    assert pose_of(make_fist("up")) == "thumbs_up"
    assert pose_of(make_fist("down")) == "thumbs_down"
    assert pose_of(make_fist("tucked")) == "fist"


def test_slight_sideways_thumb_is_still_a_fist():
    # Inside THUMB_SIDE_MARGIN: out past the knuckles, but not far enough.
    for side, tip in (("left", (240, 292)), ("right", (372, 350))):
        pts = make_fist("tucked")
        pts[4] = tip
        palm = core.palm_size(pts)
        assert core.dist(pts[4], pts[2]) / palm >= core.THUMB_UP_MIN_LEN
        assert pose_of(pts) not in ("thumb_left", "thumb_right"), side


def test_fires_once_then_repeats_while_held():
    eng, log = core.GestureEngine(), []
    run(eng, make_fist("left", 200, 100), 2.2, 0.0, log)
    ts = arrows(log)
    assert ts, "no arrow_left at all"
    assert ts[0] < 0.15, ts
    gaps = [round(b - a, 2) for a, b in zip(ts, ts[1:])]
    assert gaps[0] >= core.ARROW_REPEAT_DELAY - 1e-6, gaps
    assert gaps[0] <= core.ARROW_REPEAT_DELAY + 1 / FPS + 1e-6, gaps
    for g in gaps[1:]:
        assert core.ARROW_REPEAT_INTERVAL - 1e-6 <= g <= (
            core.ARROW_REPEAT_INTERVAL + 1 / FPS + 1e-6), gaps
    assert len(ts) == 4, ts
    assert not arrows(log, "arrow_right")


def test_thumb_right_sends_arrow_right():
    eng, log = core.GestureEngine(), []
    run(eng, make_fist("right", 100, 100), 0.5, 0.0, log)
    assert len(arrows(log, "arrow_right")) == 1, log
    assert not arrows(log, "arrow_left")


def test_releasing_and_repeating_fires_immediately():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_fist("left", 200, 100), 0.5, 0.0, log)
    assert len(arrows(log)) == 1
    t = run(eng, make_fist("tucked", 200, 100), 0.3, t, log)
    mark = t
    run(eng, make_fist("left", 200, 100), 0.3, t, log)
    ts = arrows(log)
    assert len(ts) == 2, ts
    assert ts[1] - mark < 0.15, (ts, mark)


def test_no_arrows_while_paused():
    eng, log = core.GestureEngine(), []
    eng.paused = True
    run(eng, make_fist("left", 200, 100), 1.5, 0.0, log)
    assert not [n for _, n in log if n.startswith("arrow")], log


def test_key_bindings():
    for os_name in ("Darwin", "Windows", "Linux"):
        keys = core.KEY_BINDINGS[os_name]
        assert keys["arrow_left"] == ("left",), os_name
        assert keys["arrow_right"] == ("right",), os_name
    for labels in (core.ACTION_LABELS_MAC, core.ACTION_LABELS_WIN):
        assert "arrow_left" in labels and "arrow_right" in labels


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
