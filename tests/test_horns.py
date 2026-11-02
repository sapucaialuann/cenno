"""Rock horns: pause / resume, thumb positions, quick re-do.  Run:

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
    print("horns tests passed")
