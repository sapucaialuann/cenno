"""Tests for the face zone size and gestures: normal gestures (swipes, slaps)
beside or below the face box work again, while motions directly over the face
(scratching, resting chin) are ignored.

Face box used for laptop webcam fixture: (245, 60, 395, 250) in a 640x480 frame.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hand_desktop_switcher as core            # noqa: E402
from tests.test_face_zone import open_hand, two_hand, names, zone_engine  # noqa: E402

FPS = 30.0
FACE_BOX = (245.0, 60.0, 395.0, 250.0)


def swipe_up(engine, log, cx, y0=370.0, y1=170.0, seconds=0.23, hold=0.5, face=None, t=0.0):
    """Vertical swipe upwards crossing dy in `seconds` after `hold` seconds still."""
    end = t + hold
    while t < end - 1e-9:
        for name, _ in engine.update(open_hand(cx=cx, cy=y0), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    steps = int(seconds * FPS)
    for i in range(steps + 1):
        cy = y0 + (y1 - y0) * i / steps
        for name, _ in engine.update(open_hand(cx=cx, cy=cy), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    return t


def slap(engine, log, x0=330.0, x1=620.0, cy=260.0, seconds=0.27, hold=0.5, face=None, t=0.0):
    """Horizontal sweep crossing dx in `seconds` after `hold` seconds still."""
    end = t + hold
    while t < end - 1e-9:
        for name, _ in engine.update(open_hand(cx=x0, cy=cy), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    steps = int(seconds * FPS)
    for i in range(steps + 1):
        cx = x0 + (x1 - x0) * i / steps
        for name, _ in engine.update(open_hand(cx=cx, cy=cy), 640, 480, t, face=face):
            log.append((t, name))
        t += 1.0 / FPS
    return t


def test_swipe_up_beside_face_fires_overview():
    eng, log = core.GestureEngine(), []
    swipe_up(eng, log, cx=470.0, face=FACE_BOX)
    fired = names(log)
    assert "overview" in fired, f"expected overview, got {fired}"


def test_swipe_up_into_face_is_blocked():
    # A swipe straight up ending right over the face (x=320, cy=170) is
    # indistinguishable from reaching to touch the face and must stay blocked.
    eng, log = zone_engine(), []
    swipe_up(eng, log, cx=320.0, face=FACE_BOX)
    fired = names(log)
    assert not fired, f"expected no gestures, got {fired}"


def test_slap_below_face_fires_space_left():
    eng, log = core.GestureEngine(), []
    slap(eng, log, x0=330.0, x1=620.0, cy=260.0, seconds=0.27, face=FACE_BOX)
    fired = names(log)
    assert "space_left" in fired, f"expected space_left, got {fired}"


def test_face_scratching_strokes_fire_nothing():
    eng, log = zone_engine(), []
    t = 0.0
    # Horizontal scratching strokes over the face (cy around 160)
    for _ in range(5):
        for dx in (-30.0, 30.0):
            for _ in range(5):
                for name, _ in eng.update(open_hand(cx=320.0 + dx, cy=160.0), 640, 480, t, face=FACE_BOX):
                    log.append((t, name))
                t += 1.0 / FPS
    # Vertical scratching strokes over the face
    for _ in range(5):
        for dy in (-15.0, 15.0):
            for _ in range(5):
                for name, _ in eng.update(open_hand(cx=320.0, cy=160.0 + dy), 640, 480, t, face=FACE_BOX):
                    log.append((t, name))
                t += 1.0 / FPS
    fired = names(log)
    assert not fired, f"expected no gestures during face scratching, got {fired}"


def test_chin_resting_wiggling_fires_nothing():
    eng, log = zone_engine(), []
    t = 0.0
    # Two-finger hand held at chin (bottom of face box is y=250; hand at cy=200 has fingers in face)
    while t < 0.5:
        for name, _ in eng.update(two_hand(cx=320.0, cy=200.0), 640, 480, t, face=FACE_BOX):
            log.append((t, name))
        t += 1.0 / FPS
    # Wiggling side to side and up and down
    for dx, dy in [(-25, 0), (25, 0), (0, -25), (0, 25), (-25, 25), (25, -25)] * 3:
        for _ in range(4):
            for name, _ in eng.update(two_hand(cx=320.0 + dx, cy=200.0 + dy), 640, 480, t, face=FACE_BOX):
                log.append((t, name))
            t += 1.0 / FPS
    fired = [n for n in names(log) if n.startswith("scroll_") or n.startswith("space_") or n in ("back", "forward")]
    assert not fired, f"expected no scroll or swipe while resting chin, got {fired}"


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
