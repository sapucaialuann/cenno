"""The gesture demos are executable documentation: every demo of
tools/gesture_demos.py is fed to a fresh engine, exactly like
gesture_check.replay_step feeds a recording, and must pass its own step (every
expected event fired, nothing else).  The negative steps must fire nothing.
No cv2 here.  Run:

    python tests/test_gesture_demos.py
"""

import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import hand_desktop_switcher as core            # noqa: E402
import gesture_check                            # noqa: E402
import gesture_demos as gd                      # noqa: E402

FPS = 30
MODES = ("relative", "joystick")

# Steps where the natural demo cannot pass because of the engine, not the
# demo.  The demo stays natural; the reason is printed and the step skipped.
# None right now: the textbook I-love-you sign (pinky straight up) reads as an
# open hand and fires nothing, see test_love_sign_with_a_lazy_pinky below.
KNOWN_ENGINE_FAILURES = {}


def run_demo(step):
    """The events a demo makes, counted the way the check counts them."""
    d = gd.demo(step["id"])
    eng = gesture_check.new_engine(MODES)
    counts = Counter()
    for i, fr in enumerate(d.frames):
        t = i / FPS
        if fr["pts"]:
            ev = eng.update(fr["pts"], 640, 480, t, face=fr["face"])
        else:
            ev = eng.no_hand(t)
        counts.update(gesture_check.action_names(ev))
    return counts


def test_every_step_has_a_demo():
    for step in gesture_check.STEPS:
        d = gd.demo(step["id"])
        assert d is not None, f"no demo for {step['id']}"
        assert d.caption and len(d.caption) <= 48, (step["id"], d.caption)
        assert len(d.frames) >= FPS, step["id"]
        assert d.loop is True
        for fr in d.frames:
            assert set(fr) == {"pts", "face"}
            assert fr["pts"] is None or len(fr["pts"]) == 21
    assert gd.demo("nope") is None


def test_keyframes_classify_as_intended():
    for name, want in gd.KEYFRAMES.items():
        pts = gd.keyframe_points(name)
        got = core.classify_pose(pts, core.palm_size(pts))[0]
        assert got == want, f"keyframe {name}: engine says {got}, wanted {want}"
    # The back of the hand (thumb on the right) is the thumb-right pose.
    pts = gd.keyframe_points("thumb_left", flip=True)
    assert core.classify_pose(pts, core.palm_size(pts))[0] == "thumb_right"


def test_hand_is_a_hand():
    """Natural proportions: the fingers are in the usual order and length, the
    middle finger is longest, the thumb is on the left of a right hand."""
    pts = gd.keyframe_points("open")
    d = core.dist
    palm = d(pts[0], pts[9])
    assert abs(palm - gd.PALM) < 1e-6
    length = {n: d(pts[b], pts[b + 3]) / palm for n, b in
              (("index", 5), ("middle", 9), ("ring", 13), ("pinky", 17))}
    assert length["middle"] == max(length.values())
    assert length["pinky"] == min(length.values())
    assert 0.8 < length["middle"] < 1.15, length
    assert pts[4][0] < pts[5][0] < pts[9][0] < pts[13][0] < pts[17][0]   # thumb ... pinky
    assert all(0 <= x <= 640 and 0 <= y <= 480 for x, y in pts)


def test_demos_pass_their_steps():
    failed = []
    for step in gesture_check.STEPS:
        sid = step["id"]
        if sid in KNOWN_ENGINE_FAILURES:
            print(f"  skip {sid}: known engine failure ({KNOWN_ENGINE_FAILURES[sid]})")
            continue
        counts = run_demo(step)
        missing, stray = gesture_check.judge(step, counts)
        status = "ok" if not missing and not stray else "FAIL"
        print(f"  {status:4s} {sid:15s} {dict(counts) or '-'}"
              + (f" missing={missing}" if missing else "")
              + (f" stray={stray}" if stray else ""))
        if missing or stray:
            failed.append(sid)
    assert not failed, f"demos that do not pass their step: {failed}"


def test_negative_demos_fire_nothing():
    for sid in ("scratch_face", "chin_rest", "love_sign", "fidget", "rest", "open_still"):
        if sid in KNOWN_ENGINE_FAILURES:
            continue
        step = next(s for s in gesture_check.STEPS if s["id"] == sid)
        assert not step["expect"]
        counts = run_demo(step)
        assert not counts, f"{sid} fired {dict(counts)}"


def test_love_sign_with_a_lazy_pinky():
    """Known engine weakness, reported and not hidden: the I-love-you sign
    with the pinky only half up (the way most hands make it) is read as
    "point", which can click.  The demo shows the textbook sign, which the
    engine ignores; this only prints where the engine flips."""
    flips = None
    for tenths in range(0, 10):
        p = list(gd.POSES["love"])
        p[12:16] = gd.finger(tenths / 10, 12)
        pts = gd.place(tuple(p), 320, 300)
        if core.classify_pose(pts, core.palm_size(pts))[0] == "point":
            flips = tenths / 10
            break
    if flips is None:
        print("  love sign: no longer reads as point, even with a lazy pinky")
    else:
        print(f"  KNOWN engine weakness: love sign reads as point once the pinky "
              f"curls past {flips:.1f}")


def test_demos_repeat_as_often_as_the_step_asks():
    """The repetitions are in the demo itself, not only in the caption: a step
    that expects n of an event gets at least n of it from its own demo."""
    for step in gesture_check.STEPS:
        if step["id"] in KNOWN_ENGINE_FAILURES or not step["expect"]:
            continue
        counts = run_demo(step)
        for key, need in step["expect"].items():
            got = sum(counts.get(n, 0) for n in key.split("|"))
            assert got >= need, (step["id"], key, got, need)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            print(name)
            fn()
    print("ok")
