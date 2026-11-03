"""Scrolling on Windows sends wheel deltas in 1/120 notches (#27).

pyautogui.scroll passed its number as the raw wheel delta, so scrolling ran
about 100x too slow.  No mouse is touched: the wheel call is replaced.
Run:

    python tests/test_windows_scroll.py
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402


def post_all(pixels):
    """Post each pixel amount as the Windows scroller would; return the
    wheel deltas that went out."""
    sent = []
    with patch.object(core, "OS_NAME", "Windows"), \
            patch.object(core, "_windows_wheel", sent.append):
        scroller = core.ScrollAnimator(None, None)
        for px in pixels:
            scroller._post(px)
    return sent


def test_one_notch_of_pixels_is_one_notch():
    assert post_all([core.WIN_PX_PER_NOTCH]) == [core.WHEEL_DELTA]


def test_sign_follows_the_pixels():
    up, down = post_all([50]), post_all([-50])
    assert up and up[0] > 0, up
    assert down and down[0] < 0, down


def test_small_steps_add_up_without_loss():
    # a slow scroll: many 1 px ticks must still add up to the full distance
    sent = post_all([1] * core.WIN_PX_PER_NOTCH * 3)
    # (within one unit: the leftover fraction stays for the next tick)
    assert abs(sum(sent) - 3 * core.WHEEL_DELTA) <= 1, sum(sent)


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"ok   {name}")
    print("all good")
