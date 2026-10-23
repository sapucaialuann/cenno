"""Tests for how the pointer maps onto several displays.

Drives PointerAnimator with a stub pyautogui, so no mouse is moved and no
window server is involved.  Run:

    python tests/test_pointer_mapping.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import displays as dpy                          # noqa: E402
import hand_desktop_switcher as core            # noqa: E402

PRIMARY = (0.0, 0.0, 1440.0, 900.0)
RIGHT = (1440.0, 0.0, 1920.0, 1080.0)
LEFT = (-1440.0, 0.0, 1440.0, 900.0)


class StubPag:
    """Just enough pyautogui to keep the animator off the real desktop."""

    def __init__(self, size=(1440.0, 900.0), position=(100.0, 100.0)):
        self._size = size
        self._pos = position
        self.posted = []

    def size(self):
        return self._size

    def position(self):
        return self._pos

    def moveTo(self, x, y, _pause=True):
        self._pos = (x, y)
        self.posted.append((x, y))

    def move_to(self, point):
        """Pretend the cursor was moved there, e.g. by a focus warp."""
        self._pos = (float(point[0]), float(point[1]))


def animator(rects, mode="current", position=(100.0, 100.0)):
    pag = StubPag(position=position)
    ptr = core.PointerAnimator(None, pag, dpy.DisplayLayout(rects),
                               cursor_pos=lambda: tuple(pag.position()))
    ptr.set_mode(mode)
    return ptr, pag


def aim(ptr, nx, ny):
    ptr.handle("pointer_move", (nx, ny))
    return ptr.target_pixel()


def test_one_display_maps_exactly_as_before():
    ptr, _ = animator([PRIMARY])
    for nx, ny in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.9, 0.1)):
        want = (min(1438.0, max(1.0, nx * 1440.0)),
                min(898.0, max(1.0, ny * 900.0)))
        assert aim(ptr, nx, ny) == want, (nx, ny)


def test_current_display_follows_the_cursor():
    """The gesture belongs to the screen the cursor was on when it started."""
    for where, screen in (((100.0, 100.0), PRIMARY), ((2000.0, 500.0), RIGHT)):
        ptr, _ = animator([PRIMARY, RIGHT], position=where)
        ptr.handle("pointer_move", (0.5, 0.5))
        assert ptr.rect == screen, where
        # the pointer box now covers only that screen, so even the far edge of
        # the hand stays on it
        for nx in (0.0, 0.5, 1.0):
            assert dpy.contains(screen, aim(ptr, nx, 0.5)), (where, nx)
        ptr.handle("pointer_end", None)


def test_all_displays_span_the_whole_desk():
    ptr, _ = animator([PRIMARY, RIGHT], mode="all")
    assert ptr.rect == (0.0, 0.0, 3360.0, 1080.0)
    on_primary = aim(ptr, 0.2, 0.5)
    on_right = aim(ptr, 0.8, 0.5)
    assert dpy.contains(PRIMARY, on_primary)
    assert dpy.contains(RIGHT, on_right)
    # moving the hand sideways walks across the seam, forwards and back
    sweep = [aim(ptr, t, 0.5) for t in (0.1, 0.4, 0.45, 0.5, 0.6, 0.9)]
    assert all(sweep[i][0] < sweep[i + 1][0] for i in range(len(sweep) - 1))
    assert dpy.contains(PRIMARY, sweep[1])
    assert dpy.contains(RIGHT, sweep[2])


def test_all_displays_with_a_display_on_the_left():
    ptr, _ = animator([PRIMARY, LEFT], mode="all")
    assert ptr.rect == (-1440.0, 0.0, 2880.0, 900.0)
    on_left = aim(ptr, 0.1, 0.5)
    on_primary = aim(ptr, 0.9, 0.5)
    assert dpy.contains(LEFT, on_left)
    assert dpy.contains(PRIMARY, on_primary)
    assert on_left[0] < 0 < on_primary[0]


def test_focus_display_picks_where_the_cursor_was_warped():
    """After "move pointer to next display" the cursor really is on the other
    screen, so the next gesture aims there."""
    ptr, pag = animator([PRIMARY, RIGHT], mode="all")
    pag.move_to(dpy.center(RIGHT))             # what Dispatcher._warp does
    ptr.set_mode("current")
    assert ptr.rect == RIGHT
    assert dpy.contains(RIGHT, aim(ptr, 0.0, 0.5))
    assert dpy.contains(RIGHT, aim(ptr, 1.0, 0.5))


def test_display_is_fixed_for_the_length_of_a_gesture():
    """Walking the hand over a screen edge must not hand the gesture to the
    other screen; a new gesture picks up wherever the cursor is."""
    ptr, pag = animator([PRIMARY, RIGHT], mode="all")
    aim(ptr, 0.1, 0.5)                     # starts with the cursor on the primary
    assert ptr.display == 0
    aim(ptr, 0.9, 0.5)                     # hand walks over to the right screen
    assert ptr.display == 0
    ptr.handle("pointer_end", None)
    pag.move_to(dpy.center(RIGHT))         # the cursor itself moved
    aim(ptr, 0.5, 0.5)                     # next gesture belongs there
    assert ptr.display == 1


def test_layout_change_keeps_the_target_on_a_screen():
    """Unplugging a display must not leave the cursor pointing at nothing."""
    ptr, _ = animator([PRIMARY, RIGHT], mode="all")
    aim(ptr, 0.9, 0.5)
    one = dpy.DisplayLayout([PRIMARY])
    ptr.set_layout(one)
    assert ptr.layout.count == 1
    assert dpy.contains(PRIMARY, ptr.target_pixel())
    two = dpy.DisplayLayout([PRIMARY, RIGHT])
    ptr.set_layout(two)
    assert dpy.contains(two.union, ptr.target_pixel())
    assert two.union == (0.0, 0.0, 3360.0, 1080.0)


def test_mode_switch_leaves_the_cursor_where_it_is():
    ptr, _ = animator([PRIMARY, RIGHT], mode="all")
    aim(ptr, 0.5, 0.5)
    ptr.note_external_move((1700.0, 500.0))
    before = ptr.cursor_position()
    ptr.set_mode("current")
    assert ptr.cursor_position() == before        # no teleport
    assert ptr.rect == PRIMARY                    # cursor was on the primary
    assert dpy.contains(PRIMARY, ptr.target_pixel())


def test_pointer_end_stops_the_gesture():
    ptr, _ = animator([PRIMARY, RIGHT], mode="all")
    aim(ptr, 0.5, 0.5)
    assert ptr.target_pixel() is not None
    ptr.handle("pointer_end", None)
    assert ptr.target_pixel() is None


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