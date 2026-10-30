"""Tests for the open-hand vertical swipes: up opens Mission Control, down
minimizes the front window (Mac) or shows the desktop (Windows), and down
right after an up closes Mission Control instead.  Run:

    python tests/test_swipe_down.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
from test_slap_wave import OPEN_HAND, hand, feed, hold   # noqa: E402

X = 320.0


def vertical(engine, y0, y1, seconds, t, log):
    end = t + seconds
    while t < end - 1e-9:
        k = (t - (end - seconds)) / seconds
        t = feed(engine, hand(OPEN_HAND, X, y0 + (y1 - y0) * k), t, log)
    return t


def swipe(engine, down, t, log):
    """Settle, swipe, settle again (re-arms the next swipe)."""
    y0, y1 = (260.0, 460.0) if down else (460.0, 260.0)
    t = hold(engine, OPEN_HAND, X, y0, 0.5, t, log)
    t = vertical(engine, y0, y1, 0.2, t, log)
    return hold(engine, OPEN_HAND, X, y1, 0.9, t, log)


def actions(log):
    return [n for _, n in log if n in ("overview", "app_windows", "close_overview")]


def test_swipe_down_is_the_down_action_every_time():
    eng, log = core.GestureEngine(), []
    t = swipe(eng, True, 0.0, log)
    t = vertical(eng, 460.0, 260.0, 1.5, t, log)       # slow return: no swipe
    swipe(eng, True, t, log)
    assert actions(log) == ["app_windows", "app_windows"], log


def test_down_after_up_closes_mission_control():
    eng, log = core.GestureEngine(), []
    t = swipe(eng, False, 0.0, log)
    swipe(eng, True, t, log)
    assert actions(log) == ["overview", "close_overview"], log


def test_mac_swipe_down_minimizes():
    assert core.KEY_BINDINGS["Darwin"]["app_windows"] == ("cmd", "m")
    assert "app_windows" in core.APP_SHORTCUTS
    assert core.ACTION_LABELS_MAC["app_windows"] == "MINIMIZE"
    assert core.KEY_BINDINGS["Windows"]["app_windows"] == ("win", "d")


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
