"""
Animated gesture demos for the guided gesture check (developer tool).

One short looping animation per step of tools/gesture_check.py: a right hand,
as the user sees it in the mirrored camera preview, doing the gesture the way
the engine needs it, as many times as the step asks.

    demo(step_id) -> Demo       frames (30 fps), caption, loop
    draw(img, demo, t, rect)    paint frame int(t * 30) % len(frames) into img

The demos are executable documentation: tests/test_gesture_demos.py feeds every
demo to the real engine and checks that it passes its own step.  So when an
engine threshold changes and a demo stops working, the test says so.

Preview:

    .venv-build/bin/python tools/gesture_demos.py thumbs_up         # loops, q quits
    .venv-build/bin/python tools/gesture_demos.py --sheet out.png   # one still per step

Only draw() and the preview use cv2 (imported lazily), so the frames and the
tests run on a plain python.
"""

import math
import sys
from dataclasses import dataclass

FPS = 30
W, H = 640, 480                  # the camera frame the landmarks live in
PALM = 130.0                     # px from the wrist to the middle knuckle
PIVOT_Y = -0.55                  # hand units: the palm centre, the hand is turned and placed by it


# =============================================================================
# The hand: 21 MediaPipe landmarks from a handful of joint angles
# =============================================================================
# Hand units: the wrist is (0, 0), the middle knuckle (0, -1), x is to the
# right of the picture, y is down.  The pose is the hand of a RIGHT hand,
# palm to the camera, in the mirrored preview: the thumb is on the left.

KNUCKLE = ((-0.31, -0.95), (0.0, -1.0), (0.29, -0.95), (0.53, -0.80))    # index .. pinky
SEGMENT = ((0.43, 0.27, 0.22), (0.48, 0.30, 0.24),
           (0.45, 0.28, 0.23), (0.35, 0.21, 0.19))
THUMB_BASE = (-0.22, -0.18)      # landmark 1
THUMB_SEGMENT = (0.40, 0.37, 0.31)


def finger(curl, lean=0.0):
    """One finger: three joint flexions (degrees) from one curl number
    (0 straight, 1 fist) and the lean of the finger (degrees, + to the right)."""
    return (85.0 * curl, 100.0 * curl, 65.0 * curl, lean)


def bent(f1, f2, f3, lean=0.0):
    return (f1, f2, f3, lean)


def pose(index, middle, ring, pinky, thumb, wrist=(0.0, 0.0)):
    """A pose is a flat tuple of numbers, so two of them can be blended.
    thumb = (a1, a2, a3[, k1, k2, k3]): the direction of each thumb bone in
    degrees from straight up (+ clockwise), k = how much of its length
    shows (a thumb that points at the camera is foreshortened)."""
    t = tuple(thumb) + (1.0,) * (6 - len(thumb))
    return tuple(index) + tuple(middle) + tuple(ring) + tuple(pinky) + t + tuple(wrist)


def lerp_pose(a, b, u):
    return tuple(x + (y - x) * u for x, y in zip(a, b))


def hand_units(p):
    """The 21 landmarks in hand units."""
    pts = [(p[22], p[23])] + [(0.0, 0.0)] * 20
    pts[1] = THUMB_BASE
    x, y = THUMB_BASE
    for i in range(3):
        a = math.radians(p[16 + i])
        n = THUMB_SEGMENT[i] * p[19 + i]
        x, y = x + n * math.sin(a), y - n * math.cos(a)
        pts[2 + i] = (x, y)
    for f in range(4):
        f1, f2, f3, lean = p[4 * f: 4 * f + 4]
        x, y = KNUCKLE[f]
        pts[5 + 4 * f] = (x, y)
        a = math.radians(lean)
        dx, dy = math.sin(a), -math.cos(a)
        cum = 0.0
        for i, flex in enumerate((f1, f2, f3)):
            cum += flex
            n = SEGMENT[f][i] * math.cos(math.radians(cum))
            x, y = x + dx * n, y + dy * n
            pts[6 + 4 * f + i] = (x, y)
    return pts


def place(p, x, y, rot=0.0, scale=1.0, flip=False):
    """The landmarks in camera pixels: the palm centre at (x, y), turned
    `rot` degrees clockwise.  flip shows the back of the hand (the thumb on the
    other side)."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    k = PALM * scale
    out = []
    for hx, hy in hand_units(p):
        if flip:
            hx = -hx
        hy -= PIVOT_Y
        out.append((x + k * (hx * c - hy * s), y + k * (hx * s + hy * c)))
    return out


def curled(lean=0.0):
    """A finger folded into the palm (the tip lands below the knuckle)."""
    return finger(1.15, lean)


# --- keyframe poses -----------------------------------------------------------
# Each is tuned against core.classify_pose; KEYFRAMES below says what the
# engine must call it, and the test checks that.

TUCKED = (20, 62, 88, 1, .9, .8)          # thumb folded across the fingers

POSES = {}

POSES["open"] = pose(finger(0, -14), finger(0, -2), finger(0, 9), finger(0, 22),
                     (-34, -42, -48))
POSES["flat"] = pose(finger(0, 3), finger(0, 0), finger(0, -3), finger(0, -9),
                     (-4, -2, 0))
POSES["relax"] = pose(finger(.38, -2), finger(.4, 0), finger(.42, 1), finger(.45, 3),
                      (-8, 14, 38, 1, .9, .8))
POSES["fist"] = pose(curled(-3), curled(0), curled(2), curled(5), TUCKED)
POSES["point"] = pose(finger(0, -3), curled(0), curled(2), curled(5), TUCKED)
POSES["pinch"] = pose(bent(40, 48, 17, -14), curled(0), curled(2), curled(5),
                      (-9, -6, -9))
POSES["two"] = pose(finger(0, -6), finger(0, 5), curled(2), curled(5), TUCKED)
POSES["ok"] = pose(bent(58.9, 26.1, 38.7, -26.8), finger(0, 3), finger(0, 10), finger(0, 20),
                   (-58.0, -5.8, 31.4))
POSES["gather"] = pose(finger(.32, 21), finger(.34, 0), finger(.32, -8), finger(.18, -18),
                       (6, 12, 9))
POSES["thumbs_up"] = pose(curled(-3), curled(0), curled(2), curled(5), (-12, -6, -3))
POSES["thumbs_down"] = pose(curled(-3), curled(0), curled(2), curled(5), (235, 205, 190))
POSES["thumb_left"] = pose(curled(-3), curled(0), curled(2), curled(5), (-75, -85, -90))
POSES["shaka"] = pose(curled(-3), curled(0), curled(2), finger(0, 12), (-62, -68, -72))
POSES["horns"] = pose(finger(0, -8), curled(0), curled(2), finger(0, 12), TUCKED)
POSES["love"] = pose(finger(0, -8), curled(0), curled(2), finger(0, 12), (-62, -68, -72))

# What the engine must call each keyframe pose (checked by the tests).
KEYFRAMES = {
    "open": "open", "flat": "flat", "relax": "other", "fist": "fist",
    "point": "point", "pinch": "point", "two": "two", "ok": "ok",
    "gather": "gather", "thumbs_up": "thumbs_up", "thumbs_down": "thumbs_down",
    "thumb_left": "thumb_left", "shaka": "shaka", "horns": "horns",
    "love": "open",          # the engine has no pose for it: it sees an open hand
}


def keyframe_points(name, x=320, y=300, rot=0.0, flip=False):
    """Landmarks of a keyframe pose in a 640x480 frame (for the tests)."""
    return place(POSES[name], x, y, rot, 1.0, flip)


# =============================================================================
# Timeline: keyframes -> frames
# =============================================================================

FACE = (235.0, 60.0, 405.0, 275.0)   # where a face sits in the preview
HOME = (320.0, 300.0)                # the hand held up in front of the camera
OFF = 420.0                          # how far below HOME the hand is out of view


def _ease(kind, u):
    if kind == "lin":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) ** 2
    if kind == "io3":                # a harder ease: the slap is still, then gone, then still
        return u * u * u * (u * (6 * u - 15) + 10)
    return u * u * (3 - 2 * u)


class Timeline:
    """Builds a demo from keyframes: the hand holds a pose, morphs to the next
    one, moves, turns, leaves the picture.  Every change eases in and out, like
    a real hand."""

    def __init__(self, face=None):
        self.face = face
        self.states = []             # (pose, x, y, rot, flip, visible) per frame
        self.still = None            # the frame that says it best (for the contact sheet)
        self.pose = POSES["relax"]
        self.x, self.y = HOME
        self.rot = 0.0
        self.flip = False
        self.vis = False

    @staticmethod
    def _n(secs):
        return max(1, int(round(secs * FPS)))

    def _emit(self, pose, x, y, rot):
        self.states.append((pose, x, y, rot, self.flip, self.vis))

    def show(self, name, x=None, y=None, rot=0.0, flip=False):
        """The hand is there from the next frame, no animation."""
        self.pose = POSES[name] if isinstance(name, str) else name
        self.x = self.x if x is None else x
        self.y = self.y if y is None else y
        self.rot, self.flip, self.vis = rot, flip, True

    def hide(self, secs):
        self.vis = False
        for _ in range(self._n(secs)):
            self._emit(self.pose, self.x, self.y, self.rot)

    def hold(self, secs):
        for _ in range(self._n(secs)):
            self._emit(self.pose, self.x, self.y, self.rot)

    def to(self, secs, pose=None, x=None, y=None, rot=None, ease="io", add=None):
        """Morph / move / turn to the given values over `secs`.  `add(u)` is an
        extra (dx, dy, drot) laid over the move, u = 0..1; it must end at zero."""
        target = (POSES[pose] if isinstance(pose, str) else pose) if pose is not None else self.pose
        x1 = self.x if x is None else x
        y1 = self.y if y is None else y
        r1 = self.rot if rot is None else rot
        n = self._n(secs)
        for k in range(1, n + 1):
            u = k / n
            e = _ease(ease, u)
            dx, dy, dr = add(u) if add else (0.0, 0.0, 0.0)
            self._emit(lerp_pose(self.pose, target, e),
                       self.x + (x1 - self.x) * e + dx,
                       self.y + (y1 - self.y) * e + dy,
                       self.rot + (r1 - self.rot) * e + dr)
        self.pose, self.x, self.y, self.rot = target, x1, y1, r1

    # --- the hand comes and goes ---
    def rise(self, name, x=None, y=None, secs=0.9, rot=0.0, flip=False):
        """The hand comes up from below the picture, already in `name`."""
        x = self.x if x is None else x
        y = self.y if y is None else y
        self.show(name, x, y + OFF, rot, flip)
        self.to(secs, y=y)

    def drop(self, secs=0.8):
        self.to(secs, y=self.y + OFF, ease="in")
        self.vis = False

    def mark(self, ahead=0):
        """The frame `ahead` frames from now is the one to show as a still."""
        self.still = len(self.states) + ahead

    def frames(self):
        out = []
        for pose, x, y, rot, flip, vis in self.states:
            out.append({"pts": place(pose, x, y, rot, 1.0, flip) if vis else None,
                        "face": self.face})
        return out


# =============================================================================
# The demos, one per step of gesture_check.STEPS
# =============================================================================
# Each one is what the engine needs, taken from the step's `expect`: the same
# number of repetitions, the still hand before a swipe (the engine waits 0.2 s
# before it believes a hand), a pause between repetitions longer than the
# cooldowns, and the hand out of view between holds.

_BUILDERS = {}


def _step(step_id, caption):
    def reg(fn):
        _BUILDERS[step_id] = (fn, caption)
        return fn
    return reg


def _wave(amp_x, amp_rot, cycles):
    """Side to side: starts and ends at the middle."""
    def add(u):
        s = math.sin(2 * math.pi * cycles * u)
        return (amp_x * s, 0.0, amp_rot * s)
    return add


def _loop(r, cycles):
    """A wandering path that starts and ends where it began."""
    def add(u):
        a = 2 * math.pi * cycles * u
        return (r * math.sin(a), 0.7 * r * (1 - math.cos(a)), 0.0)
    return add


@_step("rest", "hand down, out of view")
def _rest():
    tl = Timeline()
    tl.hide(0.5)
    tl.rise("relax", 320, 350, 0.9)
    tl.mark()
    tl.hold(0.6)
    tl.drop(0.9)
    tl.hide(2.0)
    return tl


@_step("open_still", "open hand, fingers spread, hold still")
def _open_still():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("open", 320, 310, 1.0)
    tl.mark()
    tl.hold(3.6)
    tl.drop(0.9)
    tl.hide(0.5)
    return tl


def _spotlight(face):
    tl = Timeline(face)
    tl.hide(0.4)
    y = 250 if face else 300
    tl.rise("open", 320, y, 1.0)
    tl.hold(0.5)
    for rep in range(3 if not face else 2):
        # Open, then all fingertips into one point, then open again.
        tl.to(0.28, "gather")
        if rep == 0:
            tl.mark()
        tl.hold(0.55)
        tl.to(0.4, "open")
        tl.hold(1.1)
    tl.drop(0.9)
    tl.hide(0.4)
    return tl


@_step("spotlight", "fingertips meet in one point")
def _spotlight_plain():
    return _spotlight(None)


@_step("spotlight_face", "same, in front of your face")
def _spotlight_face():
    return _spotlight(FACE)


def _slap(sign):
    tl = Timeline()
    left, right = 175.0, 465.0
    a, b = (left, right) if sign > 0 else (right, left)
    tl.hide(0.4)
    tl.rise("flat", a, 300, 1.0)
    tl.hold(0.7)                          # still: the warm-up
    for rep in range(3):
        # One long fast sweep, the hand leaning into it, then it settles.
        if rep == 0:
            tl.mark(4)
        tl.to(0.26, x=b, ease="io3", add=lambda u: (0, 0, sign * 16 * math.sin(math.pi * u)))
        tl.hold(0.7)
        if rep < 2:
            tl.to(1.3, x=a)               # slowly back: no second slap
            tl.hold(0.6)
    tl.hold(0.3)
    tl.drop(0.9)
    tl.hide(0.4)
    return tl


@_step("slap_right", "one long fast sweep to the right")
def _slap_right():
    return _slap(1)


@_step("slap_left", "one long fast sweep to the left")
def _slap_left():
    return _slap(-1)


def _swipe_v(sign):
    """sign -1: up, +1: down."""
    tl = Timeline()
    top, bottom = 205.0, 395.0
    a, b = (bottom, top) if sign < 0 else (top, bottom)
    tl.hide(0.4)
    tl.rise("open", 320, a, 1.0)
    tl.hold(0.7)
    for rep in range(3):
        if rep == 0:
            tl.mark(4)
        tl.to(0.26, y=b, ease="io3")
        tl.hold(0.7)
        if rep < 2:
            tl.to(1.3, y=a)
            tl.hold(0.6)
    tl.hold(0.3)
    tl.drop(0.9)
    tl.hide(0.4)
    return tl


@_step("swipe_up", "swipe up with the open hand")
def _swipe_up():
    return _swipe_v(-1)


@_step("swipe_down", "swipe down with the open hand")
def _swipe_down():
    return _swipe_v(1)


def _scroll(sign):
    """sign +1: the hand moves down (page scrolls down), -1: up."""
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 320, 300, 0.9)
    tl.hold(0.3)
    tl.to(0.35, "two")
    tl.hold(0.8)                          # the height here is the "neutral" of the pedal
    tl.to(0.5, y=300 + sign * 85)
    tl.mark()
    tl.hold(2.4)
    tl.to(0.6, y=300)
    tl.to(0.35, "relax")
    tl.drop(0.8)
    tl.hide(0.5)
    return tl


@_step("scroll_down", "two fingers, then hand down and hold")
def _scroll_down():
    return _scroll(1)


@_step("scroll_up", "two fingers, then hand up and hold")
def _scroll_up():
    return _scroll(-1)


@_step("back_forward", "two fingers: swipe right, then left")
def _back_forward():
    tl = Timeline()
    left, right = 245.0, 415.0
    tl.hide(0.4)
    tl.rise("relax", left, 300, 0.9)
    tl.hold(0.3)
    tl.to(0.35, "two")
    tl.hold(0.8)
    for rep in range(2):                   # right = back
        if rep == 0:
            tl.mark(4)
        tl.to(0.26, x=right, ease="io3")
        tl.hold(0.6)
        tl.to(1.1, x=left)
        tl.hold(0.5)
    tl.to(1.0, x=right)                    # over to the right, slowly
    tl.hold(0.6)
    for rep in range(2):                   # left = forward
        tl.to(0.26, x=left, ease="io3")
        tl.hold(0.6)
        if rep == 0:
            tl.to(1.1, x=right)
            tl.hold(0.5)
    tl.to(0.35, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


@_step("point_move", "point and move, no pinch")
def _point_move():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 320, 300, 0.9)
    tl.to(0.4, "point")
    tl.hold(0.5)
    tl.mark(50)
    tl.to(3.6, add=_loop(75, 2))
    tl.hold(0.4)
    tl.to(0.4, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


POSES["gap"] = lerp_pose(POSES["point"], POSES["pinch"], 0.45)


@_step("point_gap", "keep a gap between thumb and index")
def _point_gap():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 320, 300, 0.9)
    tl.to(0.4, "point")
    tl.hold(0.3)
    tl.to(0.5, "gap")
    tl.mark()
    tl.hold(0.5)
    tl.to(3.6, add=_loop(60, 2))
    tl.hold(0.4)
    tl.to(0.4, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


@_step("click", "pinch quickly and let go")
def _click():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 320, 300, 0.9)
    tl.to(0.4, "point")
    tl.hold(0.7)
    for _ in range(4):
        tl.to(0.14, "pinch", ease="lin")
        if _ == 0:
            tl.mark()
        tl.hold(0.08)                      # touching: under 0.4 s in all
        tl.to(0.14, "point", ease="lin")
        tl.hold(1.0)
    tl.to(0.4, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


@_step("drag", "pinch, hold and move, let go")
def _drag():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 300, 300, 0.9)
    tl.to(0.4, "point")
    tl.hold(0.7)
    for _ in range(3):
        tl.to(0.15, "pinch", ease="lin")
        tl.hold(0.25)
        if _ == 0:
            tl.mark(14)
        tl.to(0.9, x=tl.x + 70, y=tl.y - 25)   # held for over 0.4 s, carried along
        tl.hold(0.15)
        tl.to(0.15, "point", ease="lin")
        tl.hold(0.5)
        tl.to(0.9, x=tl.x - 70, y=tl.y + 25)
        tl.hold(0.4)
    tl.to(0.4, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


@_step("volume", "OK sign, twist like a knob")
def _volume():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("relax", 320, 300, 0.9)
    tl.to(0.4, "ok")
    tl.hold(0.6)
    tl.to(0.9, rot=40)                     # clockwise: louder
    tl.mark()
    tl.hold(0.6)
    tl.to(1.7, rot=-40)                    # counter-clockwise: quieter
    tl.hold(0.6)
    tl.to(0.8, rot=0)
    tl.to(0.4, "relax")
    tl.drop(0.8)
    tl.hide(0.4)
    return tl


def _hold_twice(name, secs, x=320, y=300, face=None):
    """A pose shown to the camera twice, hand down in between."""
    tl = Timeline(face)
    tl.hide(0.4)
    for _ in range(2):
        tl.rise(name, x, y, 0.7)
        if tl.still is None:
            tl.mark(10)
        tl.hold(secs)
        tl.drop(0.6)
        tl.hide(0.6)
    return tl


@_step("thumbs_up", "thumb up, hold about 1 s")
def _thumbs_up():
    return _hold_twice("thumbs_up", 1.3)


@_step("thumbs_down", "thumb down, hold about 1 s")
def _thumbs_down():
    return _hold_twice("thumbs_down", 1.3, y=250)


def _hold_once(name, secs, flip=False):
    tl = Timeline()
    tl.hide(0.4)
    tl.rise(name, 320, 300, 0.8, flip=flip)
    tl.mark(10)
    tl.hold(secs)
    tl.drop(0.7)
    tl.hide(0.5)
    return tl


@_step("thumb_left", "fist, thumb points left, hold")
def _thumb_left():
    return _hold_once("thumb_left", 2.6)


@_step("thumb_right", "fist, thumb points right, hold")
def _thumb_right():
    return _hold_once("thumb_left", 2.6, flip=True)     # the back of the hand: thumb on the right


@_step("shaka", "hang loose in front of you, hold 1 s")
def _shaka():
    return _hold_twice("shaka", 1.3, 330, 350, face=FACE)


@_step("shaka_ear", "hang loose by your ear, hold 2 s")
def _shaka_ear():
    tl = Timeline(FACE)
    tl.hide(0.4)
    ear = (462.0, 215.0, -98.0)
    tl.show("relax", 540, 520, -40, flip=True)           # comes up from the side, relaxed
    tl.to(0.8, x=ear[0] + 30, y=ear[1] + 30, rot=ear[2] + 25)
    tl.to(0.3, "shaka", x=ear[0], y=ear[1], rot=ear[2])     # forms it at the ear
    tl.mark(20)
    tl.hold(2.2)
    tl.to(0.5, "relax", x=560, y=330, rot=-40)           # takes it away
    tl.drop(0.5)
    tl.hide(0.6)
    return tl


@_step("wave", "short quick waves side to side")
def _wave_demo():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("open", 320, 300, 0.9)
    tl.hold(0.6)
    tl.mark(8)
    tl.to(1.8, add=_wave(34, 14, 3.5))
    tl.hold(0.4)
    tl.drop(0.8)
    tl.hide(0.5)
    return tl


@_step("horns", "rock horns 1.5 s, hand down, again")
def _horns():
    tl = Timeline()
    tl.hide(0.4)
    for _ in range(2):
        tl.rise("horns", 320, 300, 0.7)
        if tl.still is None:
            tl.mark(10)
        tl.hold(1.6)
        tl.drop(0.6)
        tl.hide(1.0)
    return tl


# --- things that must NOT trigger anything ---

POSES["claw"] = pose(finger(.55, -4), finger(.6, 0), finger(.6, 2), finger(.6, 6),
                     (-8, 14, 38, 1, .9, .8))


@_step("scratch_face", "NOT a gesture: scratching your face")
def _scratch_face():
    tl = Timeline(FACE)
    tl.hide(0.4)
    tl.show("claw", 470, 520, -20)
    tl.to(0.9, x=392, y=205, rot=-10)                    # the cheek
    tl.mark(20)
    tl.to(1.4, add=_loop(14, 3))                         # scratch
    tl.to(0.7, x=345, y=135, rot=0)                      # the eye
    tl.to(1.2, add=_loop(10, 3))
    tl.to(0.7, x=330, y=110)                             # the hair
    tl.to(1.2, add=_loop(14, 3))
    tl.to(0.9, x=470, y=520, rot=-20)
    tl.vis = False
    tl.hide(0.5)
    return tl


@_step("chin_rest", "NOT a gesture: chin on your hand")
def _chin_rest():
    tl = Timeline(FACE)
    tl.hide(0.4)
    tl.show("claw", 330, 520, -8)
    tl.to(1.0, y=292)
    tl.mark()
    tl.hold(0.8)
    tl.to(1.2, x=345, y=288, rot=-4)
    tl.hold(0.6)
    tl.to(1.2, x=320, y=296, rot=-10)
    tl.hold(0.8)
    tl.to(0.9, y=520)
    tl.vis = False
    tl.hide(0.5)
    return tl


@_step("love_sign", "NOT a gesture: I-love-you sign")
def _love_sign():
    tl = Timeline()
    tl.hide(0.4)
    tl.rise("love", 320, 300, 0.8)
    tl.mark(10)
    tl.hold(3.0)
    tl.drop(0.7)
    tl.hide(0.5)
    return tl


@_step("fidget", "NOT a gesture: relaxed, talking hands")
def _fidget():
    tl = Timeline(FACE)
    tl.hide(0.4)
    tl.rise("relax", 250, 360, 1.0)
    tl.to(1.4, x=300, y=330, rot=-12)
    tl.to(1.2, "claw", x=360, y=345, rot=10)
    tl.mark()
    tl.to(1.4, "relax", x=420, y=320, rot=18)
    tl.to(1.2, "open", x=360, y=360, rot=-6)             # a loose, slow open palm
    tl.to(1.6, "relax", x=290, y=350, rot=-14)
    tl.to(1.0, "claw", x=330, y=370, rot=0)
    tl.drop(0.9)
    tl.hide(0.5)
    return tl


CAPTIONS = {k: v[1] for k, v in _BUILDERS.items()}


@dataclass
class Demo:
    frames: list              # per frame {"pts": 21 (x, y) | None, "face": box | None}
    caption: str
    loop: bool = True
    still: float = 0.0        # seconds: the frame that shows the gesture best


_CACHE = {}


def demo(step_id):
    """The animation for a step id of gesture_check.STEPS, or None."""
    if step_id not in _BUILDERS:
        return None
    if step_id not in _CACHE:
        fn, caption = _BUILDERS[step_id]
        tl = fn()
        _CACHE[step_id] = Demo(tl.frames(), caption, True,
                               (tl.still if tl.still is not None else 0) / FPS)
    return _CACHE[step_id]


# =============================================================================
# Drawing (cv2, imported lazily)
# =============================================================================

PANEL = (36, 30, 28)             # BGR
PANEL_EDGE = (78, 70, 66)
SKIN = (150, 160, 205)
BONE = (240, 240, 240)
THUMB_COLOR = (50, 150, 255)     # thumb and index are the two that matter most
INDEX_COLOR = (255, 205, 70)
FACE_COLOR = (190, 190, 190)
CAPTION_H = 30

PALM_POLY = (0, 1, 2, 5, 9, 13, 17)
CHAINS = (
    (THUMB_COLOR, (1, 2, 3, 4)),
    (INDEX_COLOR, (5, 6, 7, 8)),
    (BONE, (9, 10, 11, 12)),
    (BONE, (13, 14, 15, 16)),
    (BONE, (17, 18, 19, 20)),
)
PALM_LINES = ((0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (0, 17))
TIPS = (4, 8, 12, 16, 20)


def _flesh(view, pts, at, k):
    """The soft hand under the skeleton: palm, wrist, a bit of forearm and a
    fat stroke along every finger, so it reads as a hand and not as wires."""
    import cv2
    import numpy as np
    palm = math.dist(pts[0], pts[9])
    across = (pts[5][0] - pts[17][0], pts[5][1] - pts[17][1])          # pinky -> index
    back = (pts[0][0] - pts[9][0], pts[0][1] - pts[9][1])              # towards the arm
    n = math.hypot(*back) or 1.0
    back = (back[0] / n * palm * 0.9, back[1] / n * palm * 0.9)
    wl = (pts[0][0] + across[0] * 0.30, pts[0][1] + across[1] * 0.30)   # left / right wrist
    wr = (pts[0][0] - across[0] * 0.30, pts[0][1] - across[1] * 0.30)
    arm = [wl, wr, (wr[0] + back[0], wr[1] + back[1]), (wl[0] + back[0], wl[1] + back[1])]
    skin = view.copy()
    cv2.fillPoly(skin, [np.array([at(p) for p in arm], np.int32)], SKIN)
    outline = [wl, pts[1], pts[2], pts[5], pts[9], pts[13], pts[17], wr]
    cv2.fillPoly(skin, [np.array([at(p) for p in outline], np.int32)], SKIN)
    base = max(5, int(PALM * 0.19 * k))
    for _, chain in CHAINS:
        w_ = int(base * (1.45 if chain[0] == 1 else 0.9 if chain[0] == 17 else 1.0))
        for a_, b_ in zip(chain, chain[1:]):
            cv2.line(skin, at(pts[a_]), at(pts[b_]), SKIN, w_, cv2.LINE_AA)
        for i in chain:
            cv2.circle(skin, at(pts[i]), w_ // 2, SKIN, -1, cv2.LINE_AA)
    cv2.addWeighted(skin, 0.62, view, 0.38, 0, view)


def _bones(view, pts, at, lw, dim=1.0):
    import cv2
    for a_, b_ in PALM_LINES:
        cv2.line(view, at(pts[a_]), at(pts[b_]), tuple(int(c * dim) for c in (190, 190, 190)),
                 lw, cv2.LINE_AA)
    for color, chain in CHAINS:
        c = tuple(int(v * dim) for v in color)
        for a_, b_ in zip(chain, chain[1:]):
            cv2.line(view, at(pts[a_]), at(pts[b_]), c, lw + 1, cv2.LINE_AA)


def draw(img, demo, t, rect):
    """Paint the demo at time `t` (seconds) into rect = (x, y, w, h) of a BGR
    image: a dark panel, the hand, the face box and the caption."""
    import cv2
    import numpy as np

    rx, ry, rw, rh = rect
    cv2.rectangle(img, (rx, ry), (rx + rw - 1, ry + rh - 1), PANEL, -1)
    cv2.rectangle(img, (rx, ry), (rx + rw - 1, ry + rh - 1), PANEL_EDGE, 1)
    i = int(t * FPS) % len(demo.frames)
    fr = demo.frames[i]

    # The camera frame, scaled to fit above the caption.
    ah = rh - CAPTION_H
    k = min((rw - 2) / W, (ah - 2) / H)
    ox, oy = (rw - W * k) / 2, (ah - H * k) / 2
    view = np.empty((ah, rw, 3), np.uint8)
    view[:] = PANEL
    cv2.rectangle(view, (int(ox), int(oy)), (int(ox + W * k), int(oy + H * k)),
                  (46, 40, 38), -1)

    def at(p):
        return (int(round(ox + p[0] * k)), int(round(oy + p[1] * k)))

    face = fr["face"]
    if face:
        x0, y0, x1, y1 = face
        cv2.rectangle(view, at((x0, y0)), at((x1, y1)), FACE_COLOR, 1, cv2.LINE_AA)
        cv2.putText(view, "face", (at((x0, y0))[0] + 4, at((x0, y0))[1] + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, FACE_COLOR, 1, cv2.LINE_AA)

    pts = fr["pts"]
    if pts is None:
        msg = "hand out of view"
        (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.putText(view, msg, ((rw - tw) // 2, (ah + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (125, 125, 125), 1, cv2.LINE_AA)
    else:
        lw = max(1, int(round(2.2 * k * 1.4)))
        # Fading ghosts of where the hand just was, so a sweep shows its way.
        for back, dim in ((9, 0.22), (6, 0.34), (3, 0.5)):
            old = demo.frames[(i - back) % len(demo.frames)]["pts"]
            if old and math.dist(old[9], pts[9]) > 10:
                _bones(view, old, at, lw, dim)
        _flesh(view, pts, at, k)
        _bones(view, pts, at, lw)
        for color, chain in CHAINS:
            for j in chain:
                cv2.circle(view, at(pts[j]), 3 if j in TIPS else 2, color, -1, cv2.LINE_AA)
        cv2.circle(view, at(pts[0]), 3, (190, 190, 190), -1, cv2.LINE_AA)

    # Paste the view inside the panel border.
    ih, iw = ah - 2, rw - 2
    img[ry + 1: ry + 1 + ih, rx + 1: rx + 1 + iw] = view[1: 1 + ih, 1: 1 + iw]

    size = 0.5
    (tw, th), _ = cv2.getTextSize(demo.caption, cv2.FONT_HERSHEY_SIMPLEX, size, 1)
    if tw > rw - 12:
        size *= (rw - 12) / tw
        (tw, th), _ = cv2.getTextSize(demo.caption, cv2.FONT_HERSHEY_SIMPLEX, size, 1)
    cv2.putText(img, demo.caption, (rx + (rw - tw) // 2, ry + rh - (CAPTION_H - th) // 2 - 1),
                cv2.FONT_HERSHEY_SIMPLEX, size, (240, 240, 240), 1, cv2.LINE_AA)


# =============================================================================
# Preview
# =============================================================================

def sheet(path, cols=4, cell=(320, 240)):
    """One still per step, in step order, as a PNG."""
    import cv2
    import numpy as np
    ids = list(_BUILDERS)
    rows = (len(ids) + cols - 1) // cols
    img = np.zeros((rows * cell[1], cols * cell[0], 3), np.uint8)
    for n, sid in enumerate(ids):
        d = demo(sid)
        x, y = (n % cols) * cell[0], (n // cols) * cell[1]
        draw(img, d, d.still, (x, y, cell[0], cell[1]))
        cv2.putText(img, sid, (x + 6, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (150, 150, 150), 1, cv2.LINE_AA)
    cv2.imwrite(path, img)


def preview(step_id, size=(640, 480)):
    """A window that loops one demo; q quits."""
    import time
    import cv2
    import numpy as np
    d = demo(step_id)
    if d is None:
        sys.exit(f"no demo for {step_id!r}; steps: {', '.join(_BUILDERS)}")
    win = f"gesture demo: {step_id}"
    img = np.zeros((size[1], size[0], 3), np.uint8)
    t0 = time.monotonic()
    while True:
        draw(img, d, time.monotonic() - t0, (0, 0, size[0], size[1]))
        cv2.imshow(win, img)
        if cv2.waitKey(1000 // FPS) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


def main(argv):
    if len(argv) == 3 and argv[1] == "--sheet":
        sheet(argv[2])
    elif len(argv) == 2 and not argv[1].startswith("-"):
        preview(argv[1])
    else:
        sys.exit("usage: gesture_demos.py <step_id>  |  gesture_demos.py --sheet out.png")


if __name__ == "__main__":
    main(sys.argv)
