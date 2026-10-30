"""Tests for push-to-talk: the head-zone geometry and how GestureEngine turns
a hang loose held beside the head into dictation_hold_start / _end.

No camera: landmarks are synthetic.  Run:

    python tests/test_headzone.py
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402
import headzone                                 # noqa: E402

W, H = 640, 480
FACE = (270.0, 100.0, 370.0, 230.0)             # 100 x 130 px, centre x 320
DT = 1 / 30


def shaka(hx, hy, scale=1.0):
    """Hang loose, fingers up, with the hand centre (mean of the wrist and
    the four knuckles) at (hx, hy).  Palm size is 80 * scale px."""
    s = scale
    p = [(0.0, 0.0)] * 21
    for i, x in ((5, -24), (9, -8), (13, 8), (17, 24)):
        p[i] = (x * s, -80 * s)
    for i, x in ((6, -24), (10, -8), (14, 8)):      # curled: tip below the pip
        p[i] = (x * s, -110 * s)
    for i, x in ((7, -24), (11, -8), (15, 8)):
        p[i] = (x * s, -90 * s)
    for i, x in ((8, -24), (12, -8), (16, 8)):
        p[i] = (x * s, -60 * s)
    p[18], p[19], p[20] = (24 * s, -110 * s), (24 * s, -140 * s), (24 * s, -170 * s)
    p[1], p[2], p[3], p[4] = ((-20 * s, -20 * s), (-35 * s, -40 * s),
                              (-60 * s, -50 * s), (-95 * s, -60 * s))
    cx = sum(p[i][0] for i in (0, 5, 9, 13, 17)) / 5
    cy = sum(p[i][1] for i in (0, 5, 9, 13, 17)) / 5
    return [(x - cx + hx, y - cy + hy) for x, y in p]


def phone(tx, ty, side="right", scale=1.0, turn=135):
    """Hang loose held like a phone: the shaka turned so the thumb points up
    and the pinky down, with the thumb tip at (tx, ty).  side="left" mirrors
    it for the other ear."""
    import math
    a = math.radians(turn)
    p = [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))
         for x, y in shaka(0, 0, scale)]
    if side == "left":
        p = [(-x, y) for x, y in p]
    dx, dy = tx - p[4][0], ty - p[4][1]
    return [(x + dx, y + dy) for x, y in p]


def open_hand(hx, hy):
    """Same hand with the three middle fingers straightened."""
    pts = shaka(hx, hy)
    for i in (8, 12, 16):
        pts[i] = (pts[i][0], pts[i][1] - 120)
    return pts


def palm(pts):
    return core.palm_size(pts)


# --- geometry ---

def test_shaka_fixture_is_shaka():
    pts = shaka(450, 160)
    assert core.classify_pose(pts, palm(pts))[0] == "shaka"
    pts = open_hand(450, 160)
    assert core.classify_pose(pts, palm(pts))[0] != "shaka"


def test_phone_fixture_is_shaka():
    for side in ("right", "left"):
        pts = phone(390, 150, side)
        assert core.classify_pose(pts, palm(pts))[0] == "shaka", side
        assert pts[4][1] < pts[20][1], "thumb above pinky"


def test_near_head_like_a_phone():
    # FACE is x 270..370, y 100..230: the thumb at either ear.
    for tx, side in ((390, "right"), (250, "left"), (360, "right")):
        pts = phone(tx, 150, side)
        ok, why = headzone.head_check(pts, palm(pts), FACE)
        assert ok, (tx, side, why)


def test_near_head_rejects():
    cases = {
        # The misfire people hit: a hang loose shown to the camera, next to
        # the face.  Pinky up, thumb sideways: not a phone.
        "upright shaka beside the face": shaka(450, 170),
        "upright shaka beside the face, left": shaka(190, 170),
        "upright shaka in front of the face": shaka(320, 170),
        "upright shaka in front of the chest": shaka(320, 330),
        "phone hold in front of the face": phone(320, 150),
        "phone hold far to the side": phone(470, 150),
        "phone hold at the chest": phone(390, 330),
        "phone hold above the head": phone(390, 40),
        "phone hold, much closer to the camera": phone(390, 150, scale=2.5),
    }
    for name, pts in cases.items():
        ok, why = headzone.head_check(pts, palm(pts), FACE)
        assert not ok, (name, why)
    pts = phone(390, 150)
    assert not headzone.near_head(pts, palm(pts), None), "no face"


def test_face_box_from_detection():
    box = SimpleNamespace(xmin=0.25, ymin=0.5, width=0.5, height=0.25)
    det = SimpleNamespace(location_data=SimpleNamespace(relative_bounding_box=box))
    assert headzone.face_box_from_detection(det, 200, 100) == (50, 50, 150, 75)
    assert headzone.face_box_from_detection(SimpleNamespace(), 200, 100) is None


def test_face_tracker_blank_image():
    try:
        import numpy as np
        import mediapipe  # noqa: F401
    except ImportError:
        return
    ft = headzone.FaceTracker()
    try:
        assert ft.update(np.zeros((H, W, 3), np.uint8), W, H, 0.0) is None
    finally:
        ft.close()


# --- engine ---

class Run:
    """Feeds an engine frame by frame and collects the event names."""

    def __init__(self):
        self.e = core.GestureEngine()
        self.t = 10.0
        self.log = []

    def feed(self, pts, seconds, face=FACE):
        for _ in range(int(round(seconds / DT))):
            self.t += DT
            self._add(self.e.update(pts, W, H, self.t, face=face))

    def lose(self, seconds):
        for _ in range(int(round(seconds / DT))):
            self.t += DT
            self._add(self.e.no_hand(self.t))

    def _add(self, events):
        self.log.extend(name for name, _ in events)


BESIDE = phone(390, 150)
AWAY = shaka(320, 330)
STARTED_ENDED = ["dictation_hold_start", "dictation_hold_end"]


def test_ptt_start_and_end_on_leaving():
    r = Run()
    r.feed(BESIDE, 0.6)
    assert r.log == ["dictation_hold_start"], r.log
    assert r.e.ptt_active
    r.feed(AWAY, 2 * DT)                        # shorter than the hysteresis
    assert r.e.ptt_active
    r.feed(AWAY, 0.3)
    assert r.log == STARTED_ENDED, r.log
    assert not r.e.ptt_active
    r.feed(AWAY, 1.0)                           # latched: no toggle afterwards
    assert r.log == STARTED_ENDED, r.log


def test_ptt_starts_quickly():
    r = Run()
    r.feed(BESIDE, 0.25 + 4 * DT)
    assert r.log == ["dictation_hold_start"], r.log


def test_ptt_wants_face():
    r = Run()
    assert not r.e.wants_face
    r.feed(BESIDE, 0.1)
    assert r.e.wants_face
    r.feed(open_hand(450, 170), 0.3)
    assert not r.e.wants_face


def test_ptt_ends_on_pose_change():
    r = Run()
    r.feed(BESIDE, 0.6)
    r.feed(open_hand(450, 170), 0.3)
    assert r.log == STARTED_ENDED, r.log


def test_ptt_ends_when_hand_lost():
    r = Run()
    r.feed(BESIDE, 0.6)
    r.lose(0.1)                                 # inside the grace period
    assert r.e.ptt_active
    r.lose(0.3)
    assert r.log == STARTED_ENDED, r.log
    r.lose(0.5)
    assert r.log == STARTED_ENDED, r.log


def test_ptt_ends_when_paused():
    r = Run()
    r.feed(BESIDE, 0.6)
    r.e.paused = True
    r.feed(BESIDE, 0.1)
    assert r.log == STARTED_ENDED, r.log
    r2 = Run()
    r2.feed(BESIDE, 0.6)
    r2.e.paused = True
    r2.lose(0.05)                               # paused beats the grace period
    assert r2.log == STARTED_ENDED, r2.log


def test_ptt_not_started_while_paused():
    r = Run()
    r.e.paused = True
    r.feed(BESIDE, 1.0)
    assert not any(n.startswith("dictation_hold") for n in r.log), r.log


def test_ptt_timeout():
    r = Run()
    r.feed(BESIDE, 0.6)
    r.t += core.PTT_MAX_SECONDS
    r.feed(BESIDE, 0.1)
    assert r.log == STARTED_ENDED, r.log


def test_ptt_survives_face_dropout_flicker():
    r = Run()
    r.feed(BESIDE, 0.6)
    r.feed(BESIDE, 2 * DT, face=None)           # a couple of missed frames
    r.feed(BESIDE, 0.3)
    assert r.log == ["dictation_hold_start"], r.log


def test_end_ptt_method():
    r = Run()
    assert r.e.end_ptt() == []
    r.feed(BESIDE, 0.6)
    assert r.e.end_ptt() == [("dictation_hold_end", 1)]
    assert r.e.end_ptt() == []


def test_toggle_away_from_head():
    r = Run()
    r.feed(AWAY, 1.0)
    assert r.log == ["dictation"], r.log
    assert not r.e.ptt_active


def test_toggle_without_face():
    r = Run()
    r.feed(BESIDE, 1.0, face=None)
    assert r.log == ["dictation"], r.log


def test_moving_to_head_after_toggle_does_nothing():
    r = Run()
    r.feed(AWAY, 0.6)
    assert r.log == ["dictation"]
    r.feed(BESIDE, 1.0)
    assert r.log == ["dictation"], r.log


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
