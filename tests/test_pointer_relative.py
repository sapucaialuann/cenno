"""Tests for the relative (trackpad) pointer and for the low pointer box.

Builds synthetic MediaPipe landmarks for a pointing hand and drives
GestureEngine with them, so no camera, mouse or keyboard is involved.  Run:

    python tests/test_pointer_relative.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402

FPS = 30.0
W, H = 640, 480


def make_point(cx=320, cy=300, scale=1.0, pinch=False):
    """21 pixel landmarks (y grows downward): a hand pointing up with the
    index finger and the other three curled.  The average of the four
    knuckles is exactly (cx, cy), which is what the pointer aims with."""
    s = scale
    pts = [(0.0, 0.0)] * 21
    pts[0] = (cx, cy + 120 * s)                   # wrist
    pts[1], pts[2] = (cx - 60 * s, cy + 100 * s), (cx - 90 * s, cy + 70 * s)
    pts[3] = (cx - 95 * s, cy + 30 * s)
    pts[4] = (cx - 30 * s, cy - 130 * s) if pinch else (cx - 110 * s, cy - 10 * s)
    pts[5] = (cx - 40 * s, cy)                   # index knuckle
    pts[6] = (cx - 42 * s, cy - 60 * s)
    pts[7] = (cx - 44 * s, cy - 100 * s)
    pts[8] = (cx - 45 * s, cy - 135 * s)         # index tip
    # The three curled fingers; the offsets cancel out so that the average
    # of the four knuckles is exactly (cx, cy).
    for mcp, x, y in ((9, cx - 16 * s, cy - 5 * s), (13, cx + 19 * s, cy - 1 * s),
                      (17, cx + 37 * s, cy + 6 * s)):
        pts[mcp] = (x, y)
        pts[mcp + 1] = (x, y - 50 * s)
        pts[mcp + 2] = (x, y - 20 * s)
        pts[mcp + 3] = (x, y + 5 * s)
    return pts


def engine(mode="relative"):
    eng = core.GestureEngine()
    eng.pointer_mode = mode
    return eng


def run(eng, pts, seconds, t, log):
    """Feed `pts` at 30 fps for `seconds`; append (time, event) to `log`."""
    end = t + seconds
    while t < end - 1e-9:
        for name, arg in eng.update(pts, W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
    return t


def glide(eng, x0, x1, seconds, t, log):
    """Move the hand from x0 to x1 smoothly, so the filter follows it."""
    steps = max(1, int(seconds * FPS))
    for i in range(steps):
        x = x0 + (x1 - x0) * (i + 1) / steps
        for name, arg in eng.update(make_point(x, 300), W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
    return t


def moves(log):
    """The pointer_move positions, in order."""
    return [arg for _, name, arg in log if name == "pointer_move"]


def steps(log):
    """The display_step directions, in order."""
    return [arg for _, name, arg in log if name == "display_step"]


def clicks(log):
    """The click positions, in order."""
    return [arg for _, name, arg in log if name == "click"]


def cursor_x(log):
    xs = [pos[0] for pos in moves(log)]
    return xs[-1] if xs else None


def creep(eng, x, t, log, step=4):
    """Move the hand to the right in small steps, so the cursor creeps up
    to the edge of the screen instead of jumping over it."""
    while x < 600:
        x += step
        for name, arg in eng.update(make_point(x, 300), W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
        if cursor_x(log) is not None and cursor_x(log) >= 0.999:
            break
    return x, t


# --- the pointer box sits low, so a hand resting low can reach the screen ---

def test_pointer_box_is_low():
    x0, y0, x1, y1 = core.POINTER_BOX
    assert (x0, x1) == (0.30, 0.75), core.POINTER_BOX
    # the bottom of the screen is reached with the knuckles at 0.85 of the
    # image height, the top at 0.40
    assert abs(y0 - 0.40) < 1e-6, core.POINTER_BOX
    assert abs(y1 - 0.85) < 1e-6, core.POINTER_BOX


def test_absolute_knuckles_low_and_high():
    """Absolute mode: the knuckles at 0.85 of the image height reach the
    bottom of the screen, at 0.40 the top."""
    eng, log = engine("absolute"), []
    run(eng, make_point(320, 0.85 * H), 1.5, 0.0, log)
    y = moves(log)[-1][1]
    assert abs(y - 1.0) < 0.02, y

    eng, log = engine("absolute"), []
    run(eng, make_point(320, 0.40 * H), 1.5, 0.0, log)
    y = moves(log)[-1][1]
    assert abs(y - 0.0) < 0.02, y


def test_absolute_x_still_maps_the_box():
    eng, log = engine("absolute"), []
    run(eng, make_point(0.30 * W, 300), 1.5, 0.0, log)
    x = moves(log)[-1][0]
    assert abs(x - 0.0) < 0.03, x

    eng, log = engine("absolute"), []
    run(eng, make_point(0.75 * W, 300), 1.5, 0.0, log)
    x = moves(log)[-1][0]
    assert abs(x - 1.0) < 0.03, x


# --- relative mode ----------------------------------------------------------

def test_relative_slow_move_is_small_and_fast_move_is_big():
    """A slow hand moves the cursor a little, a fast hand a lot more.

    The cursor follows the *filtered* knuckles, so the movement of the
    hand is measured after the filter, like the engine does it."""
    # slow: 60 px/s is 0.09 of the frame per second, below REL_SPEED_SLOW
    slow = drive(60, 1.0)
    # fast: 600 px/s is 0.94 of the frame per second, above REL_SPEED_FAST
    fast = drive(600, 0.25)
    assert slow["gain"] > 0.0, slow
    assert fast["gain"] > slow["gain"], (slow, fast)
    # the slow hand is below REL_SPEED_SLOW, so it gets the slow gain
    assert slow["speed"] < core.REL_SPEED_SLOW, slow
    assert abs(slow["gain"] - core.REL_GAIN_SLOW) < 0.05, slow
    # the fast hand is well past the slow speed, so it gets a bigger gain
    assert fast["speed"] > core.REL_SPEED_SLOW, fast
    assert fast["gain"] > core.REL_GAIN_SLOW + 1.0, fast
    assert fast["gain"] <= core.REL_GAIN_FAST, fast


def drive(speed_px, seconds, x0=120):
    """Point with a hand moving at `speed_px` pixels per second and report
    the gain the engine used: the cursor movement divided by the movement
    of the filtered knuckles."""
    eng = engine()
    t = 0.0
    prev_fx = prev_c = None
    gains = []
    speeds = []
    for i in range(int(seconds * FPS)):
        x = x0 + speed_px * (i + 1) / FPS
        for name, arg in eng.update(make_point(x, 300), W, H, t):
            if name != "pointer_move":
                continue
            fx = eng.fx.x / W                  # filtered knuckles, in frame units
            if prev_fx is not None and fx != prev_fx:
                # only frames where the cursor is free to move: at the edge
                # of the screen it is clamped and the gain cannot show
                if 0.0 < arg[0] < 1.0:
                    gains.append((arg[0] - prev_c) / (fx - prev_fx))
                    speeds.append(abs(fx - prev_fx) * FPS)
            prev_fx, prev_c = fx, arg[0]
        t += 1.0 / FPS
    # the steady state: the first frames are the filter catching up
    gains, speeds = gains[-12:], speeds[-12:]
    return {"gain": sum(gains) / len(gains), "speed": sum(speeds) / len(speeds)}


def test_relative_gain_follows_the_speed():
    """The gain is the slow one below the slow speed, the fast one at the
    fast speed, and in between it ramps."""
    eng = engine()
    assert eng._rel_gain(0.0) == core.REL_GAIN_SLOW
    assert eng._rel_gain(core.REL_SPEED_SLOW) == core.REL_GAIN_SLOW
    assert eng._rel_gain(core.REL_SPEED_FAST) == core.REL_GAIN_FAST
    assert eng._rel_gain(10.0) == core.REL_GAIN_FAST
    mid = eng._rel_gain(0.5 * (core.REL_SPEED_SLOW + core.REL_SPEED_FAST))
    assert core.REL_GAIN_SLOW < mid < core.REL_GAIN_FAST, mid


def test_relative_starts_in_the_middle():
    eng, log = engine(), []
    run(eng, make_point(200, 300), 0.5, 0.0, log)
    x = cursor_x(log)
    assert abs(x - 0.5) < 0.02, x


def test_relative_cursor_survives_the_hand_going_away():
    """Point, move, drop the hand, point again somewhere else: the cursor
    carries on from where it was, it does not jump."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = glide(eng, 200, 260, 0.6, t, log)
    before = cursor_x(log)
    assert before > 0.5, before

    # the hand is gone (the engine waits a moment before it gives up)
    eng.no_hand(t)
    eng.no_hand(t + 1.0)
    t += 1.0

    # point again, somewhere else entirely: the first frame only records
    # where the hand is, so the cursor stays where it was
    log.clear()
    t = run(eng, make_point(120, 300), 0.1, t, log)
    assert abs(cursor_x(log) - before) < 1e-6, (cursor_x(log), before)

    # and moving on from there continues from that spot
    t = glide(eng, 120, 180, 0.6, t, log)
    assert cursor_x(log) > before, (cursor_x(log), before)


def test_relative_pinch_clicks_once():
    """A short pinch is a click, at the spot the cursor was frozen on."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, make_point(280, 300), 0.5, t, log)
    at = cursor_x(log)

    # pinch for a moment, then let go: that is a click, not a drag
    t = run(eng, make_point(280, 300, pinch=True), 0.1, t, log)
    t = run(eng, make_point(280, 300), 0.3, t, log)

    cs = clicks(log)
    assert len(cs) == 1, log
    pos, count = cs[0]
    assert count == 1, count
    assert abs(pos[0] - at) < 0.05, (pos, at)


def test_relative_pinch_drag_follows_the_hand():
    """A pinch held down is a drag: the cursor follows the hand."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = glide(eng, 200, 260, 0.6, t, log)
    # hold the pinch long enough to become a drag
    t = run(eng, make_point(260, 300, pinch=True), 0.5, t, log)
    t = glide(eng, 260, 340, 0.6, t, log)
    t = run(eng, make_point(340, 300), 0.3, t, log)

    downs = [arg for _, name, arg in log if name == "mouse_down"]
    ups = [arg for _, name, arg in log if name == "mouse_up"]
    assert len(downs) == 1, log
    assert len(ups) == 1, log
    assert not clicks(log), log
    # the drag starts where the cursor was and ends where the hand went
    assert ups[0][0] > downs[0][0], (downs, ups)


def test_relative_double_click():
    """Two quick pinches are a double click."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    for _ in range(2):
        t = run(eng, make_point(200, 300, pinch=True), 0.05, t, log)
        t = run(eng, make_point(200, 300), 0.1, t, log)
    cs = clicks(log)
    assert len(cs) == 2, log
    assert cs[0][1] == 1, cs
    assert cs[1][1] == 2, cs


def test_relative_pushing_the_edge_changes_the_display():
    """The cursor against the right edge, the hand keeps pushing: one
    display_step to the right, and the cursor lands near the other edge."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    x, t = creep(eng, 200, t, log)
    assert cursor_x(log) >= 0.999, cursor_x(log)
    assert not steps(log), steps(log)

    # keep pushing
    t = glide(eng, x, x + 40, 0.5, t, log)
    st = steps(log)
    assert st == [(1, 0)], st
    assert abs(cursor_x(log) - core.REL_EDGE_RESTART) < 0.05, cursor_x(log)


def test_relative_push_needs_to_be_big_enough():
    """A small nudge at the edge does not change the display."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    x, t = creep(eng, 200, t, log)
    assert cursor_x(log) >= 0.999, cursor_x(log)
    # a tiny push, not enough to be a deliberate push
    t = glide(eng, x, x + 2, 0.1, t, log)
    assert not steps(log), steps(log)


def test_relative_edge_push_rearms_only_after_leaving_the_edge():
    """One push is one screen: the cursor has to come back before the next
    display_step can happen."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    x, t = creep(eng, 200, t, log)
    t = glide(eng, x, x + 40, 0.5, t, log)
    assert steps(log) == [(1, 0)], steps(log)
    # the cursor is just inside the left edge now, so it is not pushing at
    # an edge any more
    assert cursor_x(log) < 0.2, cursor_x(log)


def test_absolute_mode_ignores_the_hand_movement():
    """In absolute mode the cursor follows the knuckles, not their
    movement."""
    eng, log = engine("absolute"), []
    run(eng, make_point(200, 300), 0.5, 0.0, log)
    first = cursor_x(log)
    run(eng, make_point(400, 300), 0.5, 0.5, log)
    second = cursor_x(log)
    assert second > first, (first, second)
    # the box maps the knuckles, so this is not a small step
    assert second - first > 0.2, (first, second)


def test_relative_mode_constant():
    assert core.POINTER_MODE in ("relative", "absolute")
    eng = core.GestureEngine()
    assert eng.pointer_mode == core.POINTER_MODE


def test_relative_ignores_the_wrist():
    """Only the four knuckles steer the cursor: the wrist may be anywhere,
    even off the frame."""
    eng, log = engine(), []
    run(eng, make_point(200, 300), 0.5, 0.0, log)
    plain = cursor_x(log)

    eng, log = engine(), []
    pts = make_point(200, 300)
    pts[0] = (10, 470)                            # wrist pushed to a corner
    run(eng, pts, 0.5, 0.0, log)
    assert abs(cursor_x(log) - plain) < 1e-6, (cursor_x(log), plain)


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
