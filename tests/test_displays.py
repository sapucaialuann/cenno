"""Tests for the display geometry in displays.py.

Pure maths: no camera, no window server, no screen API.  Run:

    python tests/test_displays.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import displays as dpy  # noqa: E402

PRIMARY = (0.0, 0.0, 1440.0, 900.0)          # the screen with the menu bar
RIGHT = (1440.0, 0.0, 1440.0, 900.0)
LEFT = (-1920.0, 0.0, 1920.0, 1200.0)        # left of the primary one
ABOVE = (0.0, -1080.0, 1920.0, 1080.0)       # above it
BELOW = (0.0, 900.0, 1440.0, 900.0)


def old_to_px(n, sw, sh):
    """The single-screen mapping Cenno used before multi-display support."""
    return (min(sw - 2, max(1, n[0] * sw)), min(sh - 2, max(1, n[1] * sh)))


def test_single_display_is_identical():
    """One screen must behave exactly as it did before, down to the pixel."""
    sw, sh = 1512.0, 944.0
    one = dpy.DisplayLayout([(0.0, 0.0, sw, sh)])
    assert one.count == 1
    assert one.map_rect("current") == (0.0, 0.0, sw, sh)
    assert one.map_rect("all") == (0.0, 0.0, sw, sh)
    for nx in (0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0):
        for ny in (0.0, 0.37, 0.5, 1.0):
            got = dpy.normalized_to_rect((nx, ny), one.map_rect("current"))
            assert got == old_to_px((nx, ny), sw, sh), (nx, ny, got)
    # ... and the fallback layout is the same thing.
    assert dpy.DisplayLayout.fallback((sw, sh)).rects == [(0.0, 0.0, sw, sh)]


def test_two_displays_side_by_side():
    """The pointer box spans both, and each half lands on the right screen."""
    lay = dpy.DisplayLayout([PRIMARY, RIGHT])
    assert lay.count == 2
    assert lay.map_rect("all") == (0.0, 0.0, 2880.0, 900.0)
    assert dpy.normalized_to_point((0.0, 0.0), lay.union) == (0.0, 0.0)
    assert dpy.normalized_to_point((1.0, 1.0), lay.union) == (2880.0, 900.0)
    left_centre = dpy.normalized_to_point((0.25, 0.5), lay.union)
    right_centre = dpy.normalized_to_point((0.75, 0.5), lay.union)
    assert left_centre == (720.0, 450.0)
    assert right_centre == (2160.0, 450.0)
    assert lay.index_at(left_centre) == 0
    assert lay.index_at(right_centre) == 1
    # Each screen on its own, for the "current display" mode.
    assert lay.map_rect("current", 0) == PRIMARY
    assert lay.map_rect("current", 1) == RIGHT
    # and the far corners stay on their own screen
    assert dpy.normalized_to_rect((0.0, 0.0), RIGHT)[0] == 1441
    assert dpy.normalized_to_rect((1.0, 1.0), RIGHT)[0] == 1440 + 1440 - 2


def test_displays_stacked_vertically():
    lay = dpy.DisplayLayout([PRIMARY, BELOW])
    assert lay.map_rect("all") == (0.0, 0.0, 1440.0, 1800.0)
    on_first = dpy.normalized_to_point((0.5, 0.21), lay.union)
    on_second = dpy.normalized_to_point((0.5, 0.79), lay.union)
    assert lay.index_at(on_first) == 0
    assert lay.index_at(on_second) == 1
    assert dpy.center(lay.rect(1))[1] == 1350.0


def test_negative_origin_layout():
    """Displays left of / above the primary one have negative coordinates."""
    lay = dpy.DisplayLayout([PRIMARY, LEFT])
    assert lay.count == 2
    assert lay.rects[0] == PRIMARY
    assert lay.rects[1] == LEFT
    assert lay.union == (-1920.0, 0.0, 3360.0, 1200.0)
    assert dpy.normalized_to_point((0.0, 0.0), lay.union) == (-1920.0, 0.0)
    assert dpy.normalized_to_point((1.0, 1.0), lay.union) == (1440.0, 1200.0)
    far_left = dpy.normalized_to_point((0.25, 0.5), lay.union)
    far_right = dpy.normalized_to_point((0.75, 0.5), lay.union)
    assert lay.index_at(far_left) == 1        # the display with the negative x
    assert lay.index_at(far_right) == 0
    # A display above: the union grows upwards, y stays downwards.
    tall = dpy.DisplayLayout([PRIMARY, ABOVE])
    assert tall.union == (0.0, -1080.0, 1920.0, 1980.0)
    assert tall.index_at((960.0, -540.0)) == 1
    assert tall.index_at((960.0, 450.0)) == 0


def test_gaps_and_edges_pick_the_nearest_display():
    """A staggered layout leaves holes; the nearest centre decides."""
    lay = dpy.DisplayLayout([PRIMARY, BELOW])
    assert lay.count == 2
    hole = (1500.0, 880.0)                   # off the right edge, above the gap
    assert lay.index_at(hole) == -1
    assert lay.nearest(hole) == 0
    assert lay.index_at((2.0, 1800.0)) == 1
    # a shared edge belongs to the primary display (edges count as inside)
    assert lay.index_at((0.0, 900.0)) == 0


def test_next_display_walks_the_desk():
    lay = dpy.DisplayLayout([PRIMARY, LEFT, RIGHT, ABOVE])
    assert lay.rects[0] == PRIMARY           # primary always first
    assert [r[0] for r in lay.rects[1:]] == [-1920.0, 0.0, 1440.0]
    assert lay.next_index(0) == 1
    assert lay.next_index(lay.count - 1) == 0         # wraps around
    assert lay.next_index(None) == 1
    assert lay.next_index(99) == 1                    # stale index is ignored


def test_mirrored_and_empty_layouts():
    """Mirrored displays report the same rect, and nothing must never crash."""
    assert dpy.DisplayLayout([PRIMARY, PRIMARY]).count == 1
    assert dpy.DisplayLayout([]).count == 1
    assert dpy.DisplayLayout([PRIMARY], primary=7).count == 1
    assert dpy.DisplayLayout([(0.0, 0.0, 0.0, 900.0)]).count == 1   # off screen
    assert dpy.DisplayLayout([PRIMARY]).equals(dpy.DisplayLayout([PRIMARY]))
    assert not dpy.DisplayLayout([PRIMARY]).equals(dpy.DisplayLayout([PRIMARY, RIGHT]))


def test_layout_orders_by_the_primary_display_id():
    """The OS hands displays back in no particular order; the primary one
    (the one with the taskbar / menu bar) has to come first, the rest left to
    right."""
    lay = dpy.DisplayLayout([RIGHT, PRIMARY], primary=1)
    assert lay.rects[0] == PRIMARY
    assert lay.rects[1] == RIGHT


def test_fallback_layout_is_always_one_screen():
    """Without a screen API there is still exactly one screen to aim at."""
    lay = dpy.fallback_layout((1920, 1080))
    assert lay.count == 1
    assert lay.rect(0) == (0.0, 0.0, 1920.0, 1080.0)
    # A broken size must not produce a zero-sized screen.
    assert dpy.fallback_layout((0, 0)).count == 1
    assert dpy.fallback_layout(None).count == 1


def test_neighbor_follows_the_push_direction():
    """Pushing out of the box on a side picks the screen on that side."""
    lay = dpy.DisplayLayout([PRIMARY, LEFT, RIGHT, ABOVE])
    p = 0
    assert lay.rects[lay.neighbor(p, (-1, 0))] == LEFT
    assert lay.rects[lay.neighbor(p, (1, 0))] == RIGHT
    assert lay.rects[lay.neighbor(p, (0, -1))] == ABOVE
    assert lay.neighbor(p, (0, 1)) is None
    right = lay.rects.index(RIGHT)
    assert lay.rects[lay.neighbor(right, (-1, 0))] == PRIMARY
    assert lay.neighbor(right, (1, 0)) is None


def test_neighbor_with_one_display_is_none():
    assert dpy.DisplayLayout([PRIMARY]).neighbor(0, (1, 0)) is None


class _FakeQuartz:
    """pyobjc style: out-parameters come back as (err, ids, count)."""
    class _P:
        def __init__(self, a, b):
            self.x = self.width = a
            self.y = self.height = b

    class _B:
        def __init__(self, r):
            self.origin = _FakeQuartz._P(r[0], r[1])
            self.size = _FakeQuartz._P(r[2], r[3])

    def __init__(self, rects):
        self.rects = rects

    def CGGetActiveDisplayList(self, maxn, ids, count):
        return (0, tuple(range(1, len(self.rects) + 1)), len(self.rects))

    def CGDisplayBounds(self, did):
        return self._B(self.rects[did - 1])

    def CGMainDisplayID(self):
        return 2


def test_quartz_tuple_return_finds_every_display():
    """Regression: the tuple return used to crash into "one screen"."""
    found = dpy.quartz_displays(_FakeQuartz([RIGHT, PRIMARY]))
    assert found == [PRIMARY, RIGHT], found


def test_dead_area_slides_onto_the_shorter_screen():
    short = (1440.0, 0.0, 1016.0, 746.0)
    q = dpy.clamp_to_nearest((2000.0, 880.0), [PRIMARY, short])
    assert dpy.contains(short, q) and q[0] == 2000.0, q
    assert dpy.clamp_to_nearest((700.0, 400.0), [PRIMARY, short]) == (700.0, 400.0)


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
