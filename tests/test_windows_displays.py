"""Tests for the Windows screen enumeration.

These talk to the real user32, so they only run on Windows; everywhere else
they report "skipped".  Run:

    python tests/test_windows_displays.py
"""

import os
import platform
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import displays as dpy  # noqa: E402

ON_WINDOWS = platform.system() == "Windows"


def test_windows_displays_are_usable_rects():
    """Every monitor comes back as a rect with a real size."""
    if not ON_WINDOWS:
        return "skipped (not Windows)"
    rects = dpy.windows_displays()
    assert rects, "no monitor found"
    for x, y, w, h in rects:
        assert w > 0 and h > 0, (x, y, w, h)
        assert float(x).is_integer() and float(y).is_integer()


def test_the_primary_monitor_comes_first():
    """DisplayLayout treats index 0 as the primary screen."""
    if not ON_WINDOWS:
        return "skipped (not Windows)"
    rects = dpy.windows_displays()
    assert rects
    primary = rects[0]
    # The primary monitor's top left is the origin of the virtual desktop.
    assert primary[0] >= 0 and primary[1] >= 0, primary


def test_system_displays_matches_the_windows_ones():
    """system_displays() is what the engine calls; it must not lose any."""
    if not ON_WINDOWS:
        return "skipped (not Windows)"
    assert dpy.system_displays() == dpy.windows_displays()


def test_virtual_desktop_covers_every_monitor():
    """The whole desktop is the union of the monitors (plus the gaps)."""
    if not ON_WINDOWS:
        return "skipped (not Windows)"
    rects = dpy.windows_displays()
    desk = dpy.virtual_desktop()
    assert desk is not None
    union = dpy.union_rect(rects)
    assert desk[0] <= union[0] and desk[1] <= union[1]
    assert desk[0] + desk[2] >= union[0] + union[2]
    assert desk[1] + desk[3] >= union[1] + union[3]


def test_the_layout_survives_the_real_screens():
    """The layout the engine builds from the real screens is coherent."""
    if not ON_WINDOWS:
        return "skipped (not Windows)"
    lay = dpy.DisplayLayout(dpy.windows_displays())
    assert lay.count >= 1
    assert lay.rect(0) == lay.rects[0]
    # Every monitor is inside the union.
    for r in lay.rects:
        assert dpy.contains(lay.union, dpy.center(r)), r
    # And the pointer can reach every one of them.
    for i in range(lay.count):
        assert dpy.contains(lay.rect(i),
                            dpy.normalized_to_rect((0.5, 0.5), lay.rect(i))), i


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            result = fn()
            print(f"ok   {name}" + (f" ({result})" if result else ""))
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    print("all good" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
