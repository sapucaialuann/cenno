"""Tests for the Spotlight gesture (open hand -> gather the fingertips).

Synthetic landmarks drive GestureEngine, so no camera or keyboard is
involved.  Run:

    python tests/test_spotlight.py
"""

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
import test_slap_wave as sw                     # noqa: E402

FACE_OVER_HAND = (100.0, 100.0, 540.0, 460.0)


def gather_hand(k=1.0):
    """Open hand with the fingertips pulled together; k scales how far the
    tips sit from their common point (bigger k = looser gather)."""
    h = dict(sw.OPEN_HAND)
    cx, cy = -0.10, -1.95
    for tip, (dx, dy) in ((8, (-0.05, 0.0)), (12, (0.05, -0.05)),
                          (16, (0.10, 0.0)), (20, (0.12, 0.15))):
        h[tip] = (cx + dx * k, cy + dy * k)
    # The thumb stays by the index tip whatever the looseness.
    h[4] = (h[8][0] - 0.05, h[8][1] + 0.15)
    return h


def ok_hand():
    """Thumb and index touching, the other three fingers up: OK."""
    h = dict(sw.OPEN_HAND)
    h[8] = (-0.55, -1.70)
    h[4] = (-0.55, -1.62)
    return h


def spread_of(template):
    pts = sw.hand(template, 320, 300)
    return core.classify_pose(pts, core.palm_size(pts))[1]["spread"]


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def run_gather(template, face=None, after_open=0.0, sweep_after=False, log=None,
               hold=0.7):
    """Open hand, an optional pause in another pose, then the gather."""
    eng = core.GestureEngine()
    log = [] if log is None else log

    def feed(tpl, x, t):
        for name, _ in eng.update(sw.hand(tpl, x, 300), sw.W, sw.H, t, face=face):
            log.append((t, name))
        return t + 1.0 / sw.FPS

    t = 0.0
    for _ in range(int(0.5 * sw.FPS)):
        t = feed(sw.OPEN_HAND, 320, t)
    for _ in range(int(after_open * sw.FPS)):
        t = feed(sw.TWO_HAND, 320, t)
    for _ in range(int(hold * sw.FPS)):
        t = feed(template, 320, t)
    if sweep_after:
        # The hand reopens and sweeps sideways, as it does after Spotlight opens.
        for i in range(int(0.3 * sw.FPS)):
            t = feed(sw.OPEN_HAND, 320 + 40 * i, t)
        for _ in range(int(0.6 * sw.FPS)):
            t = feed(sw.OPEN_HAND, 320 + 40 * 9, t)
    return eng, log, t


def names(log):
    return [n for _, n in log]


def test_gather_pose_values():
    assert sw.pose_of(sw.hand(gather_hand(1.0), 320, 300)) == "gather"
    assert spread_of(gather_hand(1.0)) <= core.GATHER_MAX_SPREAD
    assert core.GATHER_MAX_SPREAD >= 0.26


def test_open_then_gather_fires_launcher_once():
    _, log, _ = run_gather(gather_hand())
    assert names(log).count("launcher") == 1, log


def test_sweep_right_after_the_gather_fires_nothing():
    _, log, _ = run_gather(gather_hand(), sweep_after=True, hold=0.2)
    assert names(log).count("launcher") == 1, log
    assert not sw.spaces(log), log
    assert "lock" not in names(log), log


def test_gather_fires_with_a_face_box_over_the_hand():
    _, log, _ = run_gather(gather_hand(), face=FACE_OVER_HAND)
    assert names(log).count("launcher") == 1, log


def test_a_loose_gather_at_026_fires():
    # Find the scale that gives a spread just under the new limit.
    k = 1.0
    while spread_of(gather_hand(k)) < 0.26:
        k += 0.05
    assert 0.26 <= spread_of(gather_hand(k)) <= core.GATHER_MAX_SPREAD
    _, log, _ = run_gather(gather_hand(k))
    assert names(log).count("launcher") == 1, (k, log)


def test_flat_hand_and_ok_sign_are_not_gather():
    assert sw.pose_of(sw.hand(sw.FLAT_HAND, 320, 300)) == "flat"
    assert sw.pose_of(sw.hand(ok_hand(), 320, 300)) == "ok"
    assert sw.pose_of(sw.hand(sw.OPEN_HAND, 320, 300)) == "open"
    assert sw.pose_of(sw.hand(sw.POINT_HAND, 320, 300)) == "point"


def test_a_slow_gather_prints_one_miss_line():
    out = capture(lambda: run_gather(gather_hand(), after_open=0.8))
    lines = [l for l in out.splitlines() if l.startswith("gather missed")]
    assert len(lines) == 1, out
    assert "too slow" in lines[0], lines


def test_a_gather_that_is_too_loose_prints_the_spread():
    k = 1.0
    while spread_of(gather_hand(k)) < 0.33:
        k += 0.05
    out = capture(lambda: run_gather(gather_hand(k)))
    lines = [l for l in out.splitlines() if l.startswith("gather missed")]
    assert len(lines) == 1, out
    assert "closest spread" in lines[0], lines


def test_a_second_gather_inside_the_cooldown_says_so():
    def twice():
        eng, log, t = run_gather(gather_hand())
        for _ in range(int(0.3 * sw.FPS)):
            for n, _ in eng.update(sw.hand(sw.OPEN_HAND, 320, 300), sw.W, sw.H, t):
                log.append((t, n))
            t += 1.0 / sw.FPS
        for _ in range(int(0.7 * sw.FPS)):
            for n, _ in eng.update(sw.hand(gather_hand(), 320, 300), sw.W, sw.H, t):
                log.append((t, n))
            t += 1.0 / sw.FPS
        assert names(log).count("launcher") == 1, log
    out = capture(twice)
    lines = [l for l in out.splitlines() if l.startswith("gather missed")]
    assert len(lines) == 1 and "cooldown" in lines[0], out


def test_ordinary_use_prints_nothing():
    def use():
        for tpl in (sw.OPEN_HAND, sw.FLAT_HAND, ok_hand(), sw.POINT_HAND,
                    sw.FIST_HAND, sw.OPEN_HAND):
            eng, log = core.GestureEngine(), []
            sw.hold(eng, sw.OPEN_HAND, 320, 300, 0.4, 0.0, log)
            sw.hold(eng, tpl, 320, 300, 0.8, 0.5, log)
    assert capture(use) == ""


class FakePag:
    def __init__(self):
        self.hotkeys = []

    def hotkey(self, *keys, **kw):
        self.hotkeys.append(keys)


def test_launcher_on_mac_goes_through_shortcuts_tap():
    taps = []
    old_tap, old_os = core.shortcuts.tap, core.OS_NAME
    core.shortcuts.tap = lambda sc: taps.append(sc) or True
    core.OS_NAME = "Darwin"
    try:
        d = core.Dispatcher.__new__(core.Dispatcher)
        d.pag = FakePag()
        d.quartz, d.appkit = object(), None
        d.alt_tab = None
        d.bindings = core.KEY_BINDINGS["Darwin"]
        d._do("launcher", 1)
    finally:
        core.shortcuts.tap, core.OS_NAME = old_tap, old_os
    assert len(taps) == 1, taps
    assert not d.pag.hotkeys, d.pag.hotkeys
    sc = taps[0]
    assert core.shortcuts.is_valid(sc), sc
    assert core.shortcuts.from_legacy("cmd+space", "Darwin") == sc, sc


def test_launcher_on_windows_still_uses_hotkey():
    old_os = core.OS_NAME
    core.OS_NAME = "Windows"
    try:
        d = core.Dispatcher.__new__(core.Dispatcher)
        d.pag = FakePag()
        d.quartz = d.appkit = None
        d.alt_tab = None
        d.bindings = core.KEY_BINDINGS["Windows"]
        d._do("launcher", 1)
    finally:
        core.OS_NAME = old_os
    assert d.pag.hotkeys == [("win",)], d.pag.hotkeys


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:
                failed += 1
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}: {exc!r}")
    if failed:
        sys.exit(1)
    print("all tests passed")
