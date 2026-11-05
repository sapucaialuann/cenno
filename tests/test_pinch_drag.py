"""Tests for the pinch: click vs drag, and the drop point of a drag.

A drag must not drag the item further while the fingers are opening
(the hand shifts a little when you let go of a pinch), and the mouse
button must never stay down.  Run:

    python tests/test_pinch_drag.py
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
from test_dispatcher_displays import (           # noqa: E402
    PRIMARY, dispatcher_with)
from test_face_zone import zone_engine          # noqa: E402
from test_pointer_relative import make_point     # noqa: E402

FPS = 30.0
W, H = 640, 480


def pinch_point(cx=320, cy=300, ratio=0.10, scale=1.0):
    """A pointing hand whose thumb sits `ratio` palm-lengths from the index
    tip: 0.1 = touching, 1 = far apart.  The pose stays "point"."""
    pts = make_point(cx, cy, scale=scale)
    palm = core.palm_size(pts)
    tip, thumb = pts[8], pts[4]
    dx, dy = thumb[0] - tip[0], thumb[1] - tip[1]
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    r = ratio * palm
    pts[4] = (tip[0] + ux * r, tip[1] + uy * r)
    return pts


def engine(mode="relative"):
    eng = core.GestureEngine()
    eng.pointer_mode = mode
    return eng


def feed(eng, pts, t, log, frames=1):
    """Push `frames` frames of the same landmarks into the engine."""
    for _ in range(frames):
        for name, arg in eng.update(pts, W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
    return t


def run(eng, pts, seconds, t, log):
    """Feed `pts` at 30 fps for `seconds`."""
    end = t + seconds
    while t < end - 1e-9:
        for name, arg in eng.update(pts, W, H, t):
            log.append((t, name, arg))
        t += 1.0 / FPS
    return t


def of(log, name):
    return [arg for _, n, arg in log if n == name]


def clicks(log):
    return of(log, "click")


# --- a pinch is a click, a long pinch is a drag ---------------------------

def test_a_short_pinch_is_one_click():
    """300 ms of touching fingers: one click, and no mouse_down at all."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    # touch for 300 ms
    t = run(eng, pinch_point(200, 300, 0.10), 0.30, t, log)
    # and let go
    t = run(eng, make_point(200, 300), 0.4, t, log)

    assert len(clicks(log)) == 1, log
    assert clicks(log)[0][1] == 1, clicks(log)
    assert not of(log, "mouse_down"), log
    assert not of(log, "mouse_up"), log


def test_a_long_pinch_is_a_drag():
    """700 ms of touching fingers: the button goes down and comes up."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.70, t, log)
    t = run(eng, make_point(200, 300), 0.4, t, log)

    assert len(of(log, "mouse_down")) == 1, log
    assert len(of(log, "mouse_up")) == 1, log
    assert not clicks(log), log


def test_the_click_window_is_long_enough():
    """The click/drag border is late enough for a deliberate click: 350 ms
    of touching is still a click, 450 ms is already a drag."""
    assert core.CLICK_MAX_SECONDS >= 0.35, core.CLICK_MAX_SECONDS
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.35, t, log)
    t = run(eng, make_point(200, 300), 0.4, t, log)
    assert len(clicks(log)) == 1, log
    assert not of(log, "mouse_down"), log

    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.45, t, log)
    t = run(eng, make_point(200, 300), 0.4, t, log)
    assert len(of(log, "mouse_down")) == 1, log
    assert not clicks(log), log


# --- the drop point of a drag --------------------------------------------

def test_the_drop_point_ignores_the_unpinch_drift():
    """While the fingers open, the hand shifts and the cursor must not
    follow: the item is dropped where the cursor was before the shift."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    # pinch and hold long enough to become a drag
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    # the drag is running now; remember where the cursor is
    assert len(of(log, "mouse_down")) == 1, log

    # now open the fingers while the hand moves: the pinch rises from
    # 0.2 to 0.6 over four frames.
    before = of(log, "pointer_move")[-1]
    for ratio in (0.2, 0.35, 0.5, 0.6):
        t = feed(eng, pinch_point(240, 300, ratio), t, log)
    # and let go for good
    t = run(eng, make_point(240, 300), 0.5, t, log)

    ups = of(log, "mouse_up")
    assert len(ups) == 1, log
    assert abs(ups[0][0] - before[0]) <= 0.005, (ups[0], before)
    assert abs(ups[0][1] - before[1]) <= 0.005, (ups[0], before)


def test_the_drop_point_ignores_the_unpinch_drift_in_absolute_mode():
    """The same in absolute mode: the cursor follows the knuckles, so the
    drift of the hand would move the item there too."""
    eng, log = engine("absolute"), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    assert len(of(log, "mouse_down")) == 1, log
    before = of(log, "pointer_move")[-1]

    for ratio in (0.2, 0.35, 0.5, 0.6):
        t = feed(eng, pinch_point(240, 300, ratio), t, log)
    t = run(eng, make_point(240, 300), 0.5, t, log)

    ups = of(log, "mouse_up")
    assert len(ups) == 1, log
    assert abs(ups[0][0] - before[0]) <= 0.005, (ups[0], before)
    assert abs(ups[0][1] - before[1]) <= 0.005, (ups[0], before)


def test_the_cursor_stops_moving_while_the_fingers_open():
    """Once the opening is noticed the cursor is frozen: the pointer_move
    positions stop following the hand."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    # open the fingers while the hand moves away
    for ratio in (0.2, 0.35, 0.5, 0.6):
        t = feed(eng, pinch_point(240, 300, ratio), t, log)
    # The fingers coming apart ends the drag during the opening (not only
    # past a fixed wide gap), and the item is dropped on the spot from
    # before the opening, not where the drifting hand would have taken it.
    ups = of(log, "mouse_up")
    assert len(ups) == 1, log
    assert abs(ups[0][0] - 0.5) <= 0.005, ups[0]


def test_closing_the_fingers_again_unfreezes_the_drag():
    """The fingers open a little and close again before the release: the
    drag carries on from the frozen spot, it does not jump."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    before = of(log, "pointer_move")[-1]
    # open a little (not far enough to release) and close again
    t = feed(eng, pinch_point(210, 300, 0.30), t, log)
    t = feed(eng, pinch_point(210, 300, 0.10), t, log)
    t = run(eng, pinch_point(210, 300, 0.10), 0.3, t, log)
    t = run(eng, make_point(210, 300), 0.4, t, log)

    ups = of(log, "mouse_up")
    assert len(ups) == 1, log
    # the drag continued from the frozen spot, so the drop is near it
    assert abs(ups[0][0] - before[0]) <= 0.05, (ups[0], before)


# --- the button must never stay down --------------------------------------

def test_pausing_mid_drag_lets_go_of_the_button():
    """Paused in the middle of a drag: the button still comes up."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    assert len(of(log, "mouse_down")) == 1, log

    eng.paused = True
    t = run(eng, make_point(200, 300), 0.3, t, log)

    assert len(of(log, "mouse_up")) == 1, log
    assert len(of(log, "mouse_down")) == 1, log


def test_the_hand_leaving_mid_drag_lets_go_of_the_button():
    """The hand disappears in the middle of a drag: the button comes up."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    assert len(of(log, "mouse_down")) == 1, log

    # the hand is gone for good: the engine waits a moment before it
    # believes it
    for step in range(20):
        for name, arg in eng.no_hand(t + 0.05 * step):
            log.append((t + 0.05 * step, name, arg))

    assert len(of(log, "mouse_up")) == 1, log
    assert len(of(log, "pointer_end")) == 1, log


def test_the_locked_screen_still_gets_the_mouse_up():
    """The lock screen swallows the gestures, but not the button release."""
    with dispatcher_with([PRIMARY]) as (d, _pag, _screens):
        d.screen_locked = lambda now=None: True
        events = [("mouse_up", (0.5, 0.5)), ("pointer_end", None),
                  ("click", ((0.5, 0.5), 1)), ("lock", 1)]
        out = d.while_locked(events)
        got = [name for name, _ in out]
        assert "mouse_up" in got, out
        assert "pointer_end" in got, out
        assert "click" not in got, out
        assert "wake" in got, out

        # unlocked: everything passes untouched
        d.screen_locked = lambda now=None: False
        assert d.while_locked(events) == events


# --- the pointer animator -------------------------------------------------

class FakeQuartz:
    """Records the mouse events instead of posting them."""

    kCGEventMouseMoved = 1
    kCGEventLeftMouseDragged = 2
    kCGEventLeftMouseDown = 3
    kCGEventLeftMouseUp = 4
    kCGMouseButtonLeft = 0
    kCGHIDEventTap = 0
    kCGMouseEventClickState = 0

    def __init__(self):
        self.posted = []

    def CGEventCreateMouseEvent(self, source, etype, pos, button):
        return (etype, pos)

    def CGEventSetIntegerValueField(self, event, field, value):
        pass

    def CGEventPost(self, tap, event):
        self.posted.append(event)


class FakePag:
    """Just enough pyautogui for the animator."""

    PAUSE = 0

    def __init__(self):
        self._pos = (100.0, 100.0)
        self.events = []

    def size(self):
        return (1440.0, 900.0)

    def position(self):
        return self._pos

    def moveTo(self, x, y, _pause=True):
        self._pos = (float(x), float(y))
        self.events.append(("move", x, y))

    def mouseDown(self, x, y, _pause=False):
        self.events.append(("down", x, y))

    def mouseUp(self, x, y, _pause=False):
        self.events.append(("up", x, y))


def test_the_pointer_animator_releases_the_button_on_pointer_end():
    """A mouse_down followed by a pointer_end: the button comes up."""
    q = FakeQuartz()
    pag = FakePag()
    anim = core.PointerAnimator(q, pag, layout=None,
                                 cursor_pos=lambda: (100.0, 100.0))
    anim.handle("pointer_move", (0.5, 0.5))
    anim.handle("mouse_down", (0.5, 0.5))
    anim.handle("pointer_end", None)

    deadline = time.time() + 0.2
    while time.time() < deadline:
        kinds = [e[0] for e in q.posted]
        if q.kCGEventLeftMouseUp in kinds:
            break
        time.sleep(0.005)

    kinds = [e[0] for e in q.posted]
    assert q.kCGEventLeftMouseDown in kinds, q.posted
    assert q.kCGEventLeftMouseUp in kinds, q.posted
    # the release comes after the press
    assert kinds.index(q.kCGEventLeftMouseUp) > kinds.index(q.kCGEventLeftMouseDown), kinds


def test_the_pointer_animator_does_not_release_without_a_press():
    """A pointer_end on its own posts nothing: no stray button release."""
    q = FakeQuartz()
    pag = FakePag()
    anim = core.PointerAnimator(q, pag, layout=None,
                                 cursor_pos=lambda: (100.0, 100.0))
    anim.handle("pointer_move", (0.5, 0.5))
    anim.handle("pointer_end", None)
    time.sleep(0.15)
    kinds = [e[0] for e in q.posted]
    assert q.kCGEventLeftMouseUp not in kinds, q.posted


def test_the_pointer_animator_releases_a_press_that_was_not_out_yet():
    """The pointer_end arrives before the animator got to the press (the
    menu was opened right after the drag started): the button still comes
    up, and it comes up after the press."""
    q = FakeQuartz()
    pag = FakePag()
    anim = core.PointerAnimator(q, pag, layout=None,
                                 cursor_pos=lambda: (100.0, 100.0))
    anim.handle("mouse_down", (0.5, 0.5))
    anim.handle("pointer_end", None)

    deadline = time.time() + 0.2
    while time.time() < deadline:
        kinds = [e[0] for e in q.posted]
        if q.kCGEventLeftMouseUp in kinds:
            break
        time.sleep(0.005)

    kinds = [e[0] for e in q.posted]
    assert q.kCGEventLeftMouseDown in kinds, q.posted
    assert q.kCGEventLeftMouseUp in kinds, q.posted
    assert kinds.index(q.kCGEventLeftMouseUp) > kinds.index(q.kCGEventLeftMouseDown), kinds
    assert anim.button_down is False


def test_the_paused_engine_still_lets_go_of_the_button():
    """Paused in the middle of a drag, with the hand gone: the button
    comes up even though everything else is swallowed."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.6, t, log)
    assert len(of(log, "mouse_down")) == 1, log

    eng.paused = True
    for step in range(20):
        for name, arg in eng.no_hand(t + 0.05 * step):
            log.append((t + 0.05 * step, name, arg))

    assert len(of(log, "mouse_up")) == 1, log


def test_pointer_end_after_a_queued_release_does_not_release_twice():
    # A drag ends the normal way: the engine sends mouse_up, then
    # pointer_end.  The release is still queued when pointer_end arrives,
    # so the animator must not queue a second one.
    anim = core.PointerAnimator.__new__(core.PointerAnimator)
    import threading
    from collections import deque
    anim.lock = threading.Lock()
    anim.wake = threading.Event()
    anim.actions = deque()
    anim.button_down = True
    anim.pos = anim.target = (100.0, 100.0)
    anim.target_n = (0.5, 0.5)
    anim.layout = core.dpy.fallback_layout((1440, 900))
    anim.mode = core.DISPLAY_MODE_CURRENT
    anim.display = 0
    anim.rect = anim.layout.map_rect(anim.mode, 0)
    anim.actions.append(("mouse_up", (100.0, 100.0), 1))
    anim.handle("pointer_end", None)
    ups = [a for a in anim.actions if a[0] == "mouse_up"]
    assert len(ups) == 1, list(anim.actions)


def test_a_small_gap_ends_the_drag():
    """Measured on the user's camera: touching reads ~0.12 and a 2-3 cm
    gap ~0.22-0.40.  A drag must end once the fingers come apart, even
    when the gap stays well under the old fixed release distance (0.50)."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.12), 0.7, t, log)
    assert of(log, "mouse_down"), log
    t = run(eng, pinch_point(200, 300, 0.30), 0.4, t, log)
    assert len(of(log, "mouse_up")) == 1, log


def test_a_loose_pinch_still_drags_and_releases():
    """A pinch that only closes to ~0.22 (also measured) still drags, and
    ends when the fingers open from there."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.22), 0.7, t, log)
    assert of(log, "mouse_down"), log
    assert not of(log, "mouse_up"), log
    t = run(eng, pinch_point(200, 300, 0.36), 0.4, t, log)
    assert len(of(log, "mouse_up")) == 1, log


def test_a_steady_wide_gap_never_presses():
    """Pointing with a 2-3 cm gap that reads 0.34 (the screenshot case)
    never presses the button."""
    eng, log = engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.34), 1.0, t, log)
    assert not of(log, "mouse_down") and not of(log, "click"), log


def test_drag_cut_by_the_face_zone_releases_once():
    """A drag whose hand passes through the face zone sends exactly one
    release per press.  It used to send a release on every exit from or
    entry to the face zone (30 releases for 13 presses in a recorded
    session); since #9 the drag simply carries on through the face."""
    eng, log = zone_engine(), []
    t = run(eng, make_point(200, 300), 0.5, 0.0, log)
    t = run(eng, pinch_point(200, 300, 0.10), 0.7, t, log)
    assert len(of(log, "mouse_down")) == 1, log
    face = (100.0, 150.0, 300.0, 450.0)          # over the hand
    for _ in range(3):                            # in and out of the face zone
        for k in range(6):
            for name, arg in eng.update(pinch_point(200, 300, 0.10), 640, 480, t, face=face):
                log.append((t, name, arg))
            t += 1.0 / 30
        for k in range(6):
            for name, arg in eng.update(pinch_point(200, 300, 0.10), 640, 480, t, face=None):
                log.append((t, name, arg))
            t += 1.0 / 30
    t = run(eng, make_point(200, 300), 0.5, t, log)
    downs, ups = len(of(log, "mouse_down")), len(of(log, "mouse_up"))
    assert ups == downs, (downs, ups)


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
