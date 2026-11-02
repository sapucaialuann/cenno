"""Tests for the lock screen: while it is up only the wave gets through,
and it wakes the display instead of locking again.  The OS lock state is
faked, so nothing is locked or woken.  Run:

    python tests/test_lock_wake.py
"""

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402
from test_dispatcher_displays import PRIMARY, dispatcher_with  # noqa: E402


@contextlib.contextmanager
def lock_state(locked):
    """Pretend the screen is (or is not) locked."""
    state = {"locked": locked}
    old = core.screen_locked
    core.screen_locked = lambda quartz=None: state["locked"]
    try:
        yield state
    finally:
        core.screen_locked = old


SOME_GESTURES = [("space_left", 1), ("pointer_move", (0.5, 0.5)),
                 ("volume_up", 2), ("click", ((1.0, 1.0), 1))]


def test_unlocked_gestures_pass_untouched():
    with lock_state(False), dispatcher_with([PRIMARY]) as (d, _pag, _s):
        events = SOME_GESTURES + [("lock", 1)]
        assert d.while_locked(events, now=0.0) == events


def test_locked_drops_everything_but_the_wave():
    with lock_state(True), dispatcher_with([PRIMARY]) as (d, _pag, _s):
        assert d.while_locked(SOME_GESTURES, now=0.0) == []
        assert d.while_locked([], now=1.0) == []


def test_locked_wave_wakes_instead_of_locking():
    with lock_state(True), dispatcher_with([PRIMARY]) as (d, _pag, _s):
        events = SOME_GESTURES + [("lock", 1)]
        assert d.while_locked(events, now=0.0) == [("wake", 1)]


def test_the_lock_state_is_polled_not_asked_every_frame():
    with lock_state(False) as state, dispatcher_with([PRIMARY]) as (d, _pag, _s):
        assert d.screen_locked(now=10.0) is False
        state["locked"] = True
        # Too soon: the last answer is reused.
        assert d.screen_locked(now=10.0 + core.LOCK_POLL_SECONDS / 2) is False
        assert d.screen_locked(now=10.0 + core.LOCK_POLL_SECONDS) is True


def test_windows_lock_calls_the_system_lock_not_keys():
    # A synthetic Win+L is ignored by Windows (#30).
    locked = []
    old_os, old_lock = core.OS_NAME, core._windows_lock
    core.OS_NAME, core._windows_lock = "Windows", lambda: locked.append(True)
    try:
        with dispatcher_with([PRIMARY]) as (d, pag, _s):
            keys = []
            pag.hotkey = lambda *k, **_kw: keys.append(k)
            d._do("lock", 1)
            assert locked == [True]
            assert not keys, keys
    finally:
        core.OS_NAME, core._windows_lock = old_os, old_lock


def test_wake_turns_the_display_on():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s):
        woken = []
        d._wake_display = lambda: woken.append(True)
        d._do("wake", 1)
        assert woken == [True]


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
