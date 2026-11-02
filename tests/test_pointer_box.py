"""Tests for pointer box preview styling and drawing.

Tests both the pure styling logic in pointer_box.py and the actual
preview drawing in Tracker._make_preview for macOS and Windows.

Usage:
    python tests/test_pointer_box.py
"""

import os
import sys
import types
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402
from pointer_box import pointer_box_style        # noqa: E402
import theme                                     # noqa: E402

# Stub platform-specific modules before importing the app wrappers.
if "rumps" not in sys.modules:
    rumps_stub = types.ModuleType("rumps")
    rumps_stub.App = object
    rumps_stub.MenuItem = object
    sys.modules["rumps"] = rumps_stub

if "AppKit" not in sys.modules:
    appkit_stub = types.ModuleType("AppKit")
    appkit_stub.NSObject = object
    sys.modules["AppKit"] = appkit_stub

if "PyObjCTools" not in sys.modules:
    sys.modules["PyObjCTools"] = types.ModuleType("PyObjCTools")
    sys.modules["PyObjCTools.AppHelper"] = types.ModuleType("PyObjCTools.AppHelper")

if "winreg" not in sys.modules:
    sys.modules["winreg"] = types.ModuleType("winreg")

if "ctypes.wintypes" not in sys.modules:
    sys.modules["ctypes.wintypes"] = types.ModuleType("ctypes.wintypes")

import cenno_app                                 # noqa: E402
import cenno_app_win                             # noqa: E402
import cv2                                       # noqa: E402


# --- Pure styling helper tests ---------------------------------------------

def test_style_point_absolute_unpinched():
    style = pointer_box_style("point", mouse_on=True, pointer_mode="absolute", pinched=False)
    assert style == (2, "trace"), f"expected (2, 'trace'), got {style}"


def test_style_point_absolute_pinched():
    style = pointer_box_style("point", mouse_on=True, pointer_mode="absolute", pinched=True)
    assert style == (2, "ember"), f"expected (2, 'ember'), got {style}"


def test_style_point_relative_unpinched():
    style = pointer_box_style("point", mouse_on=True, pointer_mode="relative", pinched=False)
    assert style == (2, "trace"), f"expected (2, 'trace'), got {style}"


def test_style_point_relative_pinched():
    style = pointer_box_style("point", mouse_on=True, pointer_mode="relative", pinched=True)
    assert style == (2, "ember"), f"expected (2, 'ember'), got {style}"


def test_style_mouse_disabled():
    assert pointer_box_style("point", mouse_on=False, pointer_mode="absolute", pinched=False) is None
    assert pointer_box_style("point", mouse_on=False, pointer_mode="relative", pinched=False) is None
    assert pointer_box_style("point", mouse_on=False, pointer_mode="absolute", pinched=True) is None


def test_style_non_pointing_poses():
    for pose in ("fist", "palm", "two", "none", "shaka", "thumb_up"):
        assert pointer_box_style(pose, mouse_on=True, pointer_mode="absolute", pinched=False) is None
        assert pointer_box_style(pose, mouse_on=True, pointer_mode="relative", pinched=False) is None


def test_style_unknown_pointer_mode():
    assert pointer_box_style("point", mouse_on=True, pointer_mode="other", pinched=False) is None
    assert pointer_box_style("point", mouse_on=True, pointer_mode="", pinched=False) is None


# --- Tracker preview rendering tests ---------------------------------------

class _FakeDrawing:
    HAND_CONNECTIONS = []

    def DrawingSpec(self, **kwargs):
        return None

    def draw_landmarks(self, *args, **kwargs):
        pass


class _FakeHands:
    HAND_CONNECTIONS = []


def _make_cv2_spy():
    rectangles = []
    orig_rect = cv2.rectangle

    def spy_rectangle(img, pt1, pt2, color, thickness=1, *args, **kwargs):
        rectangles.append((pt1, pt2, color, thickness))
        return orig_rect(img, pt1, pt2, color, thickness, *args, **kwargs)

    proxy = types.SimpleNamespace()
    for attr in dir(cv2):
        setattr(proxy, attr, getattr(cv2, attr))
    proxy.rectangle = spy_rectangle
    return proxy, rectangles


def _create_tracker(app_module, pose="point", mouse_on=True, pointer_mode="relative", pinched=False):
    tracker = object.__new__(app_module.Tracker)
    tracker.dark = False
    tracker.settings = {"preview": True, "mouse": mouse_on}
    tracker.reduce_motion = False
    tracker.last_action_time = 0.0
    tracker.last_action = ""
    tracker.engine = types.SimpleNamespace(
        debug={},
        ptt_active=False,
        pose=pose,
        pointer_mode=pointer_mode,
        pinched=pinched,
        paused=False,
    )
    return tracker


def _find_pointer_box_rect(rectangles, w, h):
    """Find rectangle matching POINTER_BOX dimensions."""
    x0, y0, x1, y1 = core.POINTER_BOX
    expected_pt1 = (int(x0 * w), int(y0 * h))
    expected_pt2 = (int(x1 * w), int(y1 * h))
    matches = [r for r in rectangles if r[0] == expected_pt1 and r[1] == expected_pt2]
    return matches[0] if matches else None


def test_mac_preview_relative_draws_1px_box():
    w, h = 640, 480
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2_spy, rects = _make_cv2_spy()
    tracker = _create_tracker(cenno_app, pose="point", mouse_on=True, pointer_mode="relative", pinched=False)
    tracker._make_preview(cv2_spy, _FakeDrawing(), _FakeHands(), frame, object(), 100.0)

    box = _find_pointer_box_rect(rects, w, h)
    assert box is not None, "pointer box rectangle was not drawn in relative mode"
    _pt1, _pt2, color, thick = box
    assert thick == 2, f"expected thickness 2 for relative guide box, got {thick}"
    assert color == theme.bgr("trace", False), f"expected trace color, got {color}"


def test_mac_preview_absolute_draws_2px_box():
    w, h = 640, 480
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2_spy, rects = _make_cv2_spy()
    tracker = _create_tracker(cenno_app, pose="point", mouse_on=True, pointer_mode="absolute", pinched=True)
    tracker._make_preview(cv2_spy, _FakeDrawing(), _FakeHands(), frame, object(), 100.0)

    box = _find_pointer_box_rect(rects, w, h)
    assert box is not None, "pointer box rectangle was not drawn in absolute mode"
    _pt1, _pt2, color, thick = box
    assert thick == 2, f"expected thickness 2 for absolute box, got {thick}"
    assert color == theme.bgr("ember", False), f"expected ember color when pinched, got {color}"


def test_mac_preview_hidden_when_mouse_off():
    w, h = 640, 480
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2_spy, rects = _make_cv2_spy()
    tracker = _create_tracker(cenno_app, pose="point", mouse_on=False, pointer_mode="relative")
    tracker._make_preview(cv2_spy, _FakeDrawing(), _FakeHands(), frame, object(), 100.0)

    box = _find_pointer_box_rect(rects, w, h)
    assert box is None, "pointer box must not be drawn when mouse control is disabled"


def test_win_preview_relative_and_absolute():
    w, h = 640, 480

    # Test relative unpinched
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2_spy, rects = _make_cv2_spy()
    tracker = _create_tracker(cenno_app_win, pose="point", mouse_on=True, pointer_mode="relative", pinched=False)
    tracker._make_preview(cv2_spy, _FakeDrawing(), _FakeHands(), frame, object(), 100.0)
    box = _find_pointer_box_rect(rects, w, h)
    assert box is not None, "win preview did not draw pointer box in relative mode"
    assert box[3] == 2, f"expected thickness 2 on win relative, got {box[3]}"
    assert box[2] == theme.bgr("trace", False)

    # Test absolute pinched
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2_spy, rects = _make_cv2_spy()
    tracker = _create_tracker(cenno_app_win, pose="point", mouse_on=True, pointer_mode="absolute", pinched=True)
    tracker._make_preview(cv2_spy, _FakeDrawing(), _FakeHands(), frame, object(), 100.0)
    box = _find_pointer_box_rect(rects, w, h)
    assert box is not None, "win preview did not draw pointer box in absolute mode"
    assert box[3] == 2, f"expected thickness 2 on win absolute, got {box[3]}"
    assert box[2] == theme.bgr("ember", False)


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
