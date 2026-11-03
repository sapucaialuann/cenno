"""Slaps switch windows with Alt+Tab on Windows (#31).

The keys go to a fake sender, so nothing is pressed.  Run:

    python tests/test_alt_tab.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402
from test_dispatcher_displays import PRIMARY, dispatcher_with  # noqa: E402

HOLD = 0.15          # seconds; short, so the tests are quick


def tabber():
    """An AltTabber that writes its keys to a list, as 'Alt down' etc."""
    keys = []

    def hold(sc, down):
        keys.append(f"{sc['label']} {'down' if down else 'up'}")
        return True

    return core.AltTabber(hold=hold, hold_seconds=HOLD), keys


def taps(keys):
    """The keys that were tapped (down then up), Alt left out."""
    return [k[:-5] for k in keys if k.endswith(" down") and k != "Alt down"]


def test_first_slap_is_alt_tab_either_way():
    for forward in (True, False):
        t, keys = tabber()
        t.step(forward=forward)
        assert keys == ["Alt down", "Tab down", "Tab up"], keys


def test_alt_stays_down_then_lets_go():
    t, keys = tabber()
    t.step(forward=True)
    assert "Alt up" not in keys
    time.sleep(HOLD * 2)
    assert keys[-1] == "Alt up", keys


def test_more_slaps_step_through_the_switcher():
    t, keys = tabber()
    t.step(forward=True)
    t.step(forward=True)
    t.step(forward=False)
    assert taps(keys) == ["Tab", "Tab", "Shift+Tab"], keys
    assert keys.count("Alt down") == 1, keys
    time.sleep(HOLD * 2)
    assert keys.count("Alt up") == 1, keys


def test_each_slap_restarts_the_wait():
    t, keys = tabber()
    t.step(forward=True)
    time.sleep(HOLD * 0.7)
    t.step(forward=True)
    time.sleep(HOLD * 0.7)          # past the first slap's time, not the second's
    assert "Alt up" not in keys, keys
    time.sleep(HOLD)
    assert keys[-1] == "Alt up", keys


def test_after_letting_go_the_next_slap_starts_over():
    t, keys = tabber()
    t.step(forward=True)
    t.release()
    t.step(forward=False)
    assert keys == ["Alt down", "Tab down", "Tab up", "Alt up",
                    "Alt down", "Tab down", "Tab up"], keys
    t.release()


def test_dispatcher_slap_on_windows_uses_alt_tab_and_other_gestures_let_go():
    t, keys = tabber()
    with dispatcher_with([PRIMARY]) as (d, pag, _s):
        sent = []
        pag.hotkey = lambda *k, **_kw: sent.append(k)
        d.alt_tab = t
        d._do("space_right", 1)
        assert keys[:3] == ["Alt down", "Tab down", "Tab up"], keys
        assert not sent, sent                     # no Ctrl+Win+Arrow
        d._do("volume_up", 1)                     # another gesture
        assert keys[-1] == "Alt up", keys


def test_the_selection_follows_the_hand():
    # A slap to the right moves the selection right (Tab), whichever way
    # NATURAL_SWIPE names the event.
    for natural in (True, False):
        old = core.NATURAL_SWIPE
        core.NATURAL_SWIPE = natural
        try:
            right = "space_left" if natural else "space_right"
            left = "space_right" if natural else "space_left"
            t, keys = tabber()
            with dispatcher_with([PRIMARY]) as (d, _pag, _s):
                d.alt_tab = t
                for name in (right, right, left):
                    d._do(name, 1)
            t.release()
        finally:
            core.NATURAL_SWIPE = old
        assert taps(keys) == ["Tab", "Tab", "Shift+Tab"], (natural, keys)


if __name__ == "__main__":
    failed = 0
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok   {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    if failed:
        print(f"{failed} failed")
        sys.exit(1)
    print("all good")
