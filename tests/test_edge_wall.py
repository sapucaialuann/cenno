"""An edge with no screen behind it is a wall: the cursor stays put and no
display_step is sent.  With a neighbour the cursor lands exactly on the new
screen.  Run:

    python tests/test_edge_wall.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import displays as dpy                          # noqa: E402
import hand_desktop_switcher as core            # noqa: E402
from test_pointer_relative import W, H, FPS, make_point, run  # noqa: E402
import test_dispatcher_displays as td           # noqa: E402


def push(eng, dx, dy, log, steps_n=40):
    """Run the hand from the middle, then keep moving by (dx, dy) in small
    steps, so the cursor reaches the edge and keeps pushing."""
    t = run(eng, make_point(300, 300), 0.5, 0.0, log)
    x, y = 300.0, 300.0
    for _ in range(steps_n):
        x += dx
        y += dy
        for name, arg in eng.update(make_point(x, y), W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
    return t


def last_cursor(log):
    return [a for _, n, a in log if n == "pointer_move"][-1]


def test_one_screen_every_edge_is_a_wall():
    for dx, dy, axis, edge in ((12, 0, 0, 1.0), (-12, 0, 0, 0.0),
                               (0, 12, 1, 1.0), (0, -12, 1, 0.0)):
        for wired in (None, lambda d: False):
            eng, log = core.GestureEngine(), []
            eng.pointer_mode = "relative"
            eng.can_step_display = wired
            push(eng, dx, dy, log)
            assert not [e for e in log if e[1] == "display_step"], log
            assert last_cursor(log)[axis] == edge, last_cursor(log)


def test_neighbour_gives_one_step_with_a_landing():
    eng, log = core.GestureEngine(), []
    eng.pointer_mode = "relative"
    eng.can_step_display = lambda d: d == (1, 0)
    push(eng, 12, 0, log, steps_n=18)
    st = [e[2] for e in log if e[1] == "display_step"]
    assert len(st) == 1 and st[0][0] == (1, 0), st
    assert abs(st[0][1][0] - core.REL_EDGE_RESTART) < 1e-6, st
    # No neighbour on the left: wall.
    eng, log = core.GestureEngine(), []
    eng.pointer_mode = "relative"
    eng.can_step_display = lambda d: d == (1, 0)
    push(eng, -12, 0, log)
    assert not [e for e in log if e[1] == "display_step"]
    assert last_cursor(log)[0] == 0.0


def test_absolute_mode_wall():
    eng, log = core.GestureEngine(), []
    eng.pointer_mode = "absolute"
    push(eng, 12, 0, log)
    assert not [e for e in log if e[1] == "display_step"], log


def test_can_step_follows_the_layout():
    with td.dispatcher_with([td.PRIMARY]) as (d, _p, _s):
        assert d.can_step((1, 0)) is False
    with td.dispatcher_with([td.PRIMARY, td.RIGHT]) as (d, pag, _s):
        pag._pos = (100.0, 100.0)
        assert d.can_step((1, 0)) is True
        assert d.can_step((-1, 0)) is False
        d.set_display_mode("all")
        assert d.can_step((1, 0)) is False


def test_step_with_landing_goes_straight_to_the_new_screen():
    with td.dispatcher_with([td.PRIMARY, td.RIGHT]) as (d, pag, _s):
        d.pointer.cursor_pos = lambda: pag.position()
        pag._pos = (1400.0, 450.0)
        d.pointer.handle("pointer_move", (1.0, 0.5))
        assert d.step_display(((1, 0), (0.02, 0.5))) is True
        aim = d.pointer.target_pixel()
        r = td.RIGHT
        assert r[0] <= aim[0] < r[0] + 0.1 * (r[2] - r[0]), aim
        # Warp went to the landing spot, not to the old x=1.0 mapping.
        assert pag.moved[-1] == aim, (pag.moved[-1], aim)
        # The next engine move keeps it there.
        d.pointer.handle("pointer_move", (0.02, 0.5))
        assert d.pointer.target_pixel()[0] < r[0] + 0.1 * (r[2] - r[0])


def test_plain_direction_still_works():
    with td.dispatcher_with([td.PRIMARY, td.RIGHT]) as (d, pag, _s):
        pag._pos = (100.0, 100.0)
        assert d.step_display((1, 0)) is True
        assert d.pointer.display == 1


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
                fails += 1
    if fails:
        print(f"{fails} failed")
        sys.exit(1)
