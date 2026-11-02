"""Tests for the "gas pedal" (joystick) two-finger scrolling.

Builds synthetic MediaPipe landmarks for a two-finger hand and drives
GestureEngine with them, so no camera, mouse or keyboard is involved.
Run:

    python tests/test_scroll_joystick.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

core.SCROLL_MODE = "joystick"     # the default is tilt; every engine here is a gas pedal

FPS = 30.0
W, H = 640, 480


def make_two(dx=0.0, dy=0.0):
    """21 pixel landmarks (y grows downward): index + middle up, ring and
    pinky folded into the palm, thumb tucked to the side."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (300, 400)                              # wrist
    pts[1], pts[2] = (262, 388), (250, 362)          # thumb base
    pts[3], pts[4] = (246, 330), (243, 306)          # thumb tip
    # index and middle straight up
    pts[5], pts[6], pts[7], pts[8] = (272, 300), (272, 252), (272, 222), (272, 192)
    pts[9], pts[10], pts[11], pts[12] = (308, 294), (308, 246), (308, 216), (308, 186)
    # ring and pinky folded down into the palm
    for mcp, x, y in ((13, 340, 300), (17, 366, 310)):
        pts[mcp] = (x, y)
        pts[mcp + 1] = (x, y - 46)                   # PIP, straight up
        pts[mcp + 2] = (x, y - 41)                   # DIP, folding back
        pts[mcp + 3] = (x, y - 10)                   # tip, tucked into the palm
    return [(x + dx, y + dy) for x, y in pts]


def make_fist(dx=0.0, dy=0.0):
    """Every finger folded: the two-finger pose is over."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (300, 400)
    pts[1], pts[2] = (262, 388), (250, 362)
    pts[3], pts[4] = (246, 330), (243, 306)
    for mcp, x, y in ((5, 272, 300), (9, 308, 294), (13, 340, 300), (17, 366, 310)):
        pts[mcp] = (x, y)
        pts[mcp + 1] = (x, y - 46)
        pts[mcp + 2] = (x, y - 41)
        pts[mcp + 3] = (x, y - 10)
    return [(x + dx, y + dy) for x, y in pts]


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


def run(engine, pts, seconds, t, log, frames=None):
    """Feed `pts` at 30 fps for `seconds`; append (time, name, value) to
    `log` and the frame timestamps to `frames` (if given)."""
    end = t + seconds
    while t < end - 1e-9:
        if frames is not None:
            frames.append(t)
        for name, n in engine.update(pts, W, H, t):
            log.append((t, name, n))
        t += 1.0 / FPS
    return t


def drags(log, since=None):
    """The scroll_drag events, as (time, value) pairs."""
    return [(t, n) for t, name, n in log
            if name == "scroll_drag" and (since is None or t >= since)]


def steady(ds, n=8):
    """The last `n` values of a phase: by then the smoothed hand position
    has caught up with the real one, so the speed has settled."""
    return [v for _, v in ds[-n:]]


def expected_travel(offset_palms):
    """How much scroll_drag one frame should carry for a hand `offset`
    palms away from neutral."""
    reach = abs(offset_palms) - core.JOY_DEADZONE_PALMS
    if reach <= 0:
        return 0.0
    speed = min(core.JOY_MAX_PX_S, core.JOY_PX_S_PER_PALM * reach ** core.JOY_EXPONENT)
    return speed / FPS / core.SCROLL_PX_PER_PALM


def test_fixture_is_sane():
    pts = make_two()
    for f in ("index", "middle"):
        assert core.finger_ratio(pts, f) >= core.EXTENDED_RATIO, f
    for f in ("ring", "pinky"):
        assert core.finger_ratio(pts, f) <= core.CURLED_RATIO, f
    assert pose_of(pts) == "two"
    assert pose_of(make_fist()) == "fist"


def test_still_hand_does_not_scroll():
    eng, log = core.GestureEngine(), []
    run(eng, make_two(), 1.0, 0.0, log)
    assert not drags(log), drags(log)
    assert not [e for e in log if e[1] == "scroll_fling"], log


def test_hand_below_neutral_scrolls_down_every_frame():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_two(), 0.6, 0.0, log)          # neutral
    mpalm = eng.debug["mpalm"]
    frames = []
    start = t
    t = run(eng, make_two(dy=mpalm), 0.8, t, log, frames)   # one palm below
    ds = drags(log, since=start)
    assert ds, "no scroll below neutral"
    assert all(n < 0 for _, n in ds), ds[:4]          # page down
    # one scroll per frame, on every frame of the move
    assert len(ds) == len(frames), (len(ds), len(frames))
    assert all(abs(a - b) < 1e-6 for (a, _), b in zip(ds, frames)), ds[:4]
    # the size is steady once the hand has settled
    values = steady(ds)
    mean = sum(values) / len(values)
    want = -expected_travel(1.0)
    assert abs(mean - want) < abs(want) * 0.05, (mean, want)
    assert max(values) - min(values) < abs(mean) * 0.05, values


def test_further_below_scrolls_faster():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_two(), 0.6, 0.0, log)
    mpalm = eng.debug["mpalm"]
    start = t
    t = run(eng, make_two(dy=2 * mpalm), 0.8, t, log)
    ds = drags(log, since=start)
    assert ds, "no scroll two palms below neutral"
    assert all(n < 0 for _, n in ds), ds[:4]
    values = steady(ds)
    mean = sum(values) / len(values)
    want = -expected_travel(2.0)
    assert abs(mean - want) < abs(want) * 0.05, (mean, want)
    # twice the distance is a lot faster than once
    eng2, log2 = core.GestureEngine(), []
    t2 = run(eng2, make_two(), 0.6, 0.0, log2)
    start2 = t2
    t2 = run(eng2, make_two(dy=mpalm), 0.8, t2, log2)
    one = sum(steady(drags(log2, since=start2))) / 8
    assert abs(mean) > abs(one) * 2.0, (mean, one)


def test_the_speed_is_capped():
    eng, log = core.GestureEngine(), []
    # the hand starts high up, so it has room to go far below
    t = run(eng, make_two(dy=-200), 0.6, 0.0, log)
    mpalm = eng.debug["mpalm"]
    start = t
    t = run(eng, make_two(dy=-200 + 4 * mpalm), 0.8, t, log)
    ds = drags(log, since=start)
    assert ds, "no scroll far below neutral"
    values = steady(ds)
    mean = sum(values) / len(values)
    # the top speed, however far the hand goes
    want = -core.JOY_MAX_PX_S / FPS / core.SCROLL_PX_PER_PALM
    assert abs(mean - want) < abs(want) * 0.05, (mean, want)


def test_back_to_neutral_stops_and_above_scrolls_up():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_two(), 0.6, 0.0, log)
    mpalm = eng.debug["mpalm"]
    t = run(eng, make_two(dy=mpalm), 0.5, t, log)    # below
    start = t
    frames = []
    t = run(eng, make_two(), 0.6, t, log, frames)    # back to neutral
    # once the hand is back at neutral the page stops
    back = drags(log, since=start)
    assert back, "the page kept scrolling on the way back"
    assert not drags(log, since=frames[-8]), drags(log, since=frames[-8])
    # above neutral the page goes up on the very first frame
    frames = []
    start = t
    t = run(eng, make_two(dy=-mpalm), 0.4, t, log, frames)
    above = drags(log, since=start)
    assert above, "no scroll above neutral"
    assert above[0][1] > 0, above[:4]               # page up
    assert abs(above[0][0] - frames[0]) < 1e-6, (above[0], frames[0])


def test_leaving_the_pose_does_not_fling():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_two(), 0.6, 0.0, log)
    mpalm = eng.debug["mpalm"]
    # a fast dip: fast enough to be a flick in drag mode
    t = run(eng, make_two(dy=3 * mpalm), 0.1, t, log)
    t = run(eng, make_two(dy=3 * mpalm), 0.3, t, log)
    t = run(eng, make_fist(), 0.4, t, log)           # pose ends
    assert not [e for e in log if e[1] == "scroll_fling"], log
    eng.no_hand(t)
    eng.no_hand(t + 0.5)                             # hand gone
    assert not [e for e in log if e[1] == "scroll_fling"], log


def test_release_never_flings_in_joystick_mode():
    # Whatever the history holds, the gas pedal has no momentum: ending
    # the gesture must not send a scroll_fling.
    eng = core.GestureEngine()
    eng.scroll_hist.append((0.0, 40.0))
    ev = []
    eng._scroll_release(0.0, ev)
    assert not ev, ev
    # the same history in drag mode does fling
    eng.scroll_mode = "drag"
    ev = []
    eng._scroll_release(0.0, ev)
    assert ev == [("scroll_fling", 40.0)], ev


def test_the_neutral_point_resets_with_the_pose():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_two(), 0.6, 0.0, log)
    mpalm = eng.debug["mpalm"]
    t = run(eng, make_two(dy=mpalm), 0.5, t, log)    # below neutral
    t = run(eng, make_fist(), 0.4, t, log)           # pose ends
    # the two-finger pose starts again, one palm higher than before
    start = t
    t = run(eng, make_two(dy=-mpalm), 0.6, t, log)
    assert not drags(log, since=start), drags(log, since=start)
    # the new neutral is where the pose started, so one palm BELOW that
    # is one palm above the old neutral: still down the page
    start = t
    t = run(eng, make_two(dy=-mpalm + mpalm), 0.8, t, log)
    ds = drags(log, since=start)
    assert ds, "no scroll after the pose came back"
    assert all(n < 0 for _, n in ds), ds[:4]          # below the new neutral


def test_drag_mode_keeps_the_old_behaviour():
    eng, log = core.GestureEngine(), []
    eng.scroll_mode = "drag"
    t = run(eng, make_two(), 0.6, 0.0, log)
    t = run(eng, make_two(dy=60), 0.4, t, log)       # quick downward stroke
    ds = drags(log)
    assert ds, "no scroll_drag in drag mode"
    assert any(n > 0 for _, n in ds), ds[:4]         # hand down = page up
    flings = [n for _, name, n in log if name == "scroll_fling"]
    assert flings, "no scroll_fling after a fast stroke"
    assert flings[0] > 0, flings


def test_drag_mode_still_glides_when_the_pose_ends():
    # The old mode glides on: a fast stroke that ends keeps gliding.
    eng = core.GestureEngine()
    eng.scroll_mode = "drag"
    eng.scroll_hist.append((0.0, 40.0))
    ev = []
    eng._scroll_release(0.0, ev)
    assert ev == [("scroll_fling", 40.0)], ev


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
