"""Tests for thumbs down -> undo, and for hold gestures that flicker.

Reuses the synthetic fist from test_thumb_arrows.py.  Run:

    python tests/test_undo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
import shortcuts                       # noqa: E402
from test_thumb_arrows import make_fist, pose_of, run   # noqa: E402

FRAME = 1.0 / 30


def fired(log, name):
    return [t for t, n in log if n == name]


def test_thumbs_down_held_fires_undo_once():
    eng, log = core.GestureEngine(), []
    run(eng, make_fist("down", 100, 0), 1.5, 0.0, log)
    assert len(fired(log, "undo")) == 1, log


def test_short_thumb_still_counts_as_thumbs_down():
    # Thumb pointing down and away from the camera looks shorter.
    pts = make_fist("down")
    pts[3], pts[4] = (254, 390), (255, 416)
    palm = core.palm_size(pts)
    assert core.dist(pts[4], pts[2]) / palm < core.THUMB_UP_MIN_LEN
    assert pose_of(pts) == "thumbs_down"


def test_flicker_to_fist_does_not_restart_the_hold():
    # 0.3 s down, 4 frames read as a fist, then down again: without the
    # flicker tolerance the 0.5 s hold would start over.
    eng, log = core.GestureEngine(), []
    t = run(eng, make_fist("down", 100, 0), 0.3, 0.0, log)
    t = run(eng, make_fist("tucked", 100, 0), 4 * FRAME, t, log)
    mark = t
    run(eng, make_fist("down", 100, 0), 0.5, t, log)
    ts = fired(log, "undo")
    assert len(ts) == 1, log
    assert ts[0] - mark < 0.25, (ts, mark)


def test_flicker_after_firing_does_not_fire_again():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_fist("up", 100, 0), 0.8, 0.0, log)
    t = run(eng, make_fist("tucked", 100, 0), 4 * FRAME, t, log)
    run(eng, make_fist("up", 100, 0), 0.8, t, log)
    assert len(fired(log, "play_pause")) == 1, log


def test_a_real_release_starts_a_new_hold():
    eng, log = core.GestureEngine(), []
    t = run(eng, make_fist("up", 100, 0), 0.8, 0.0, log)
    t = run(eng, make_fist("tucked", 100, 0), 0.6, t, log)
    run(eng, make_fist("up", 100, 0), 0.8, t, log)
    assert len(fired(log, "play_pause")) == 2, log


def test_app_shortcuts_have_mac_key_codes():
    # Sent through _send_shortcut, which needs a code for every key.
    for name in core.APP_SHORTCUTS:
        keys = core.KEY_BINDINGS["Darwin"][name]
        assert shortcuts.from_legacy("+".join(keys), "Darwin"), (name, keys)


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
