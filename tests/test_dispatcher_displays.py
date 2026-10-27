"""Tests for the Dispatcher's screen handling.

A stub pyautogui stands in for the real one, so no mouse is moved and no
window server is involved.  Run:

    python tests/test_dispatcher_displays.py
"""

import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import displays as dpy                          # noqa: E402
import hand_desktop_switcher as core            # noqa: E402

PRIMARY = (0.0, 0.0, 1440.0, 900.0)
RIGHT = (1440.0, 0.0, 1920.0, 1080.0)


class StubPag:
    """Just enough pyautogui to keep the dispatcher off the real desktop."""

    PAUSE = 0

    def __init__(self):
        self._pos = (100.0, 100.0)
        self.moved = []

    def size(self):
        return (1440.0, 900.0)

    def position(self):
        return self._pos

    def moveTo(self, x, y, _pause=True):
        self._pos = (float(x), float(y))
        self.moved.append((float(x), float(y)))

    def press(self, *args, **kwargs):
        pass

    def hotkey(self, *args, **kwargs):
        pass

    def scroll(self, lines):
        pass


class FakeScreens:
    """Stands in for the screens the OS reports."""

    def __init__(self, rects):
        self.rects = list(rects)

    def __call__(self, quartz=None):
        return list(self.rects)


@contextlib.contextmanager
def dispatcher_with(rects):
    """A dispatcher that believes the machine has these screens."""
    stub = StubPag()
    screens = FakeScreens(rects)
    old_module = sys.modules.get("pyautogui")
    old_displays = dpy.system_displays
    sys.modules["pyautogui"] = stub
    dpy.system_displays = screens
    try:
        d = core.Dispatcher()
        # On macOS the dispatcher talks to Quartz instead of pyautogui: it
        # would post real mouse events and read the real cursor.  Drop it so
        # the stub is the only thing the test can see.
        d.quartz = d.appkit = None
        yield d, stub, screens
    finally:
        dpy.system_displays = old_displays
        if old_module is None:
            sys.modules.pop("pyautogui", None)
        else:
            sys.modules["pyautogui"] = old_module


def test_the_dispatcher_reads_the_screens():
    with dispatcher_with([PRIMARY, RIGHT]) as (d, _pag, _screens):
        assert d.layout.count == 2
        assert d.layout.rect(0) == PRIMARY
        assert d.display_mode == core.DISPLAY_MODE_CURRENT


def test_the_pointer_mode_switches_between_one_screen_and_all():
    with dispatcher_with([PRIMARY, RIGHT]) as (d, _pag, _screens):
        assert d.pointer.rect == PRIMARY              # current display
        d.set_display_mode("all")
        assert d.display_mode == "all"
        assert d.pointer.rect == (0.0, 0.0, 3360.0, 1080.0)
        d.set_display_mode("current")
        assert d.pointer.rect == PRIMARY
        # A mode that does not exist is ignored.
        d.set_display_mode("sideways")
        assert d.display_mode == "current"


def test_jumping_to_the_next_display_moves_the_cursor():
    with dispatcher_with([PRIMARY, RIGHT]) as (d, pag, _screens):
        assert d.jump_to_next_display() is True
        # The cursor sits in the middle of the second screen.
        assert pag.moved
        assert pag.moved[-1] == dpy.center(RIGHT)
        # ... and it comes back on the next jump.
        d.jump_to_next_display()
        assert pag.moved[-1] == dpy.center(PRIMARY)


def test_jumping_needs_two_screens():
    with dispatcher_with([PRIMARY]) as (d, pag, _screens):
        assert d.jump_to_next_display() is False
        assert not pag.moved


def test_a_new_screen_is_picked_up():
    with dispatcher_with([PRIMARY]) as (d, _pag, screens):
        assert d.layout.count == 1
        # Nothing changed: no news.
        assert d.refresh_displays() is False
        # A second screen shows up.
        screens.rects = [PRIMARY, RIGHT]
        assert d.refresh_displays() is True
        assert d.layout.count == 2
        assert d.pointer.layout.count == 2
        # ... and it goes away again.
        screens.rects = [PRIMARY]
        assert d.refresh_displays() is True
        assert d.layout.count == 1


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
