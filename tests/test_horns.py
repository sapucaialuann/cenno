"""Rock horns: pause / resume, thumb positions, quick re-do, and the
shaking hand that must not be taken for a wave.  Run:

    python tests/test_horns.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_desktop_switcher as core            # noqa: E402
from test_face_zone import open_hand, fist      # noqa: E402

FPS = 30


def horns(thumb_tip=(338, 318), dx=0):
    p = {0: (320, 400), 1: (295, 388), 2: (280, 368), 3: (300, 345), 4: thumb_tip,
         5: (292, 330), 6: (286, 292), 7: (284, 268), 8: (283, 244),
         9: (315, 325), 10: (318, 296), 11: (319, 312), 12: (317, 328),
         13: (338, 328), 14: (341, 300), 15: (341, 316), 16: (339, 332),
         17: (358, 338), 18: (362, 308), 19: (365, 288), 20: (367, 268)}
    return [(p[i][0] + dx, p[i][1]) for i in range(21)]


def shaka():
    """Pinky and thumb out, index / middle / ring curled."""
    pts = horns(thumb_tip=(262, 345))
    # Curl the index: tip back down near its knuckle.
    pts[3], pts[4] = (255, 355), (232, 342)   # thumb stuck right out
    pts[6], pts[7], pts[8] = (295, 296), (296, 312), (294, 328)
    return pts


def pose_of(pts):
    return core.classify_pose(pts, core.palm_size(pts))[0]


def run(script):
    eng = core.GestureEngine()
    t = 0.0
    out = []
    for maker, secs in script:
        for _ in range(round(secs * FPS)):
            ev = eng.no_hand(t) if maker is None else eng.update(maker(), 640, 480, t)
            out += [n for n, _ in ev if n.startswith("pause")]
            t += 1 / FPS
    return out


H = horns
F = lambda: fist("up")  # noqa: E731


# --- the shaking hand that must not lock the screen --------------------------

# The palm the engine measures the wave against: the hand size, but never
# more than MOTION_PALM_MAX_FRAC of the frame.
WAVE_PALM = min(core.palm_size(open_hand()), core.MOTION_PALM_MAX_FRAC * 640)


def shake(half_range_palms, cycles=4, secs=1.6):
    """An open hand shaking side to side.  The hand travels
    `half_range_palms` to each side of the middle, so it covers twice that
    from left to right."""
    step = half_range_palms * WAVE_PALM
    n = round(secs * FPS)
    out = []
    for i in range(n):
        # A triangle wave: the hand goes over and back, `cycles` times.
        k = (i / n) * cycles
        x = 320.0 + (step if int(k * 2) % 2 == 0 else -step) * (1 - abs((k % 1) - 0.5) * 2)
        out.append(open_hand(cx=x))
    return out


def wave_events(frames):
    """Feed the frames and return the lock events."""
    eng = core.GestureEngine()
    out = []
    t = 0.0
    for pts in frames:
        out += [n for n, _ in eng.update(pts, 640, 480, t) if n == "lock"]
        t += 1 / FPS
    return out


def test_shaking_does_not_lock():
    # Forming the horns sign shakes the hand in a narrow band: the strokes
    # are short and the hand stays in one place.  That must not be a wave.
    assert wave_events(shake(0.4)) == []


def test_a_real_wave_locks_once():
    # A real wave covers much more ground: the strokes together span more
    # than WAVE_MIN_SPAN_PALMS, and then it locks the screen once.
    assert wave_events(shake(0.8)) == ["lock"]


def test_a_narrow_shake_after_a_wave_does_not_lock():
    # The wave is over once it has locked: the next shake starts from
    # scratch and does not inherit the span of the wave.
    eng = core.GestureEngine()
    t = 0.0
    for pts in shake(0.8):
        eng.update(pts, 640, 480, t)
        t += 1 / FPS
    t += core.WAVE_COOLDOWN_SECONDS
    for pts in shake(0.4):
        locks = [n for n, _ in eng.update(pts, 640, 480, t) if n == "lock"]
        assert not locks, locks
        t += 1 / FPS


def test_classify():
    for tip in ((338, 318), (318, 318), (305, 322)):
        assert pose_of(horns(thumb_tip=tip)) == "horns", tip
    assert pose_of(horns(thumb_tip=(262, 345))) != "horns"
    assert pose_of(shaka()) == "shaka", pose_of(shaka())
    assert pose_of(open_hand()) == "open"
    assert pose_of(fist("up")) != "horns"   # this fixture reads as thumbs_up


def test_pause_resume():
    assert run([(H, 1.3), (None, 1.0), (H, 1.3)]) == ["pause_on", "pause_off"]


def test_quick_redo():
    assert run([(H, 1.3), (F, 0.2), (H, 1.3)]) == ["pause_on", "pause_off"]


def test_flicker_keeps_latch():
    assert run([(H, 1.3), (F, 0.1), (H, 1.5)]) == ["pause_on"]


def test_single_fire():
    assert run([(H, 3.0)]) == ["pause_on"]


if __name__ == "__main__":
    test_classify()
    test_pause_resume()
    test_quick_redo()
    test_flicker_keeps_latch()
    test_single_fire()
    test_shaking_does_not_lock()
    test_a_real_wave_locks_once()
    test_a_narrow_shake_after_a_wave_does_not_lock()
    print("horns tests passed")
