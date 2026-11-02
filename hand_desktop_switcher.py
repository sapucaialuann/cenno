"""
Cenno: hand-gesture control for macOS.

Gestures (all measured in "palms", i.e. relative to your hand size in the
frame, so they work whether you sit close to the camera or across the room):

  OPEN HAND (3+ fingers spread) or FLAT HAND (fingers straight, together)
    * slap right / left    -> previous / next Space        (Ctrl+Left/Right)
                              a long fast sweep across the frame; the hand may
                              be flat (fingers together) or spread, palm or back
                              to the camera.
                              trackpad style: the hand pushes the screen.
                              Set NATURAL_SWIPE = False to flip it.
    * swipe up             -> Mission Control              (Ctrl+Up)
    * swipe down           -> minimize the front window    (Cmd+M)
                              or closes an overview a swipe opened (Esc)

  TWO FINGERS (index + middle up, ring + pinky curled)
    * push down / up       -> scroll, like a gas pedal: where the gesture
                              starts is neutral, below it the page scrolls
                              down, above it up, and it stops dead at the end
    * swipe right / left   -> Back / Forward               (Cmd+[ / Cmd+])

  POINT (index up, middle / ring / pinky curled)
    * move                 -> moves the mouse cursor
    * pinch thumb + index  -> click; two quick pinches = double-click;
                              pinch and hold = drag (release to drop)

  OK SIGN (thumb + index tips touching, other fingers UP)
    * twist like a knob    -> volume up / down, one notch per 15 degrees,
                              with the native macOS volume HUD

  THUMBS UP (hold ~0.5 s)  -> play / pause media

  THUMB LEFT / RIGHT (fist, thumb sideways)
                           -> Left / Right arrow: slides, players, lists.
                              Fires at once, repeats if you keep holding

  OPEN HAND -> GATHER all fingertips together ("ma che vuoi")
                           -> Spotlight                    (Cmd+Space)
  WAVE (open or flat hand, short strokes side to side)
                           -> lock screen               (Ctrl+Cmd+Q)
                              wave again while locked to wake the screen

  ROCK HORNS (hold ~1 s)   -> pause / resume all gestures (fist = rest, does nothing)

Design notes
  * Finger states are rotation-invariant (distance from the wrist), so poses
    work with the hand tilted or sideways, not only upright.
  * A pose must be stable for a few frames before it counts, so gestures do
    not flicker into each other mid-motion.
  * Swipes need the hand fully in frame for a short warm-up (entering the
    frame is not a swipe) and re-arm only after the hand settles (the return
    stroke is not a swipe).
  * All OS actions run on a background thread: the camera loop never blocks
    on osascript or key events.
  * Shortcuts are sent with real key presses (Control down, arrow, Control
    up), which is what macOS needs to switch Spaces.  Media keys (volume,
    play/pause) are real system media keys, so the native HUD appears.
  * Scrolling is pixel-smooth at 120 Hz, on its own thread.  The two-finger
    gesture works like a gas pedal: the further the hand leaves the neutral
    point, the faster the page moves, and there is no momentum.
  * Several displays: the pointer can stay on the screen under the cursor
    (default) or span every screen, so moving the hand sideways walks from one
    monitor to the next.  Scrolling and Space switching go to the screen the
    hand is on: the cursor is moved there first, without clicking.

macOS permissions
  * Camera + Accessibility for the app running Python (Terminal, iTerm, IDE).
  * System Settings -> Keyboard -> Keyboard Shortcuts -> Mission Control:
    enable "Move left/right a space", "Mission Control", "Application windows".

Dependencies:
    pip install "mediapipe<0.10.10" opencv-python pyautogui
    (pyautogui pulls in pyobjc / Quartz on macOS)

Run:
    python3 hand_desktop_switcher.py
    keys in the preview window:  q quit,  p pause,  h help overlay
"""

import math
import platform
import queue
import subprocess
import threading
import time
from collections import deque

import displays as dpy
import headzone
import shortcuts


# =============================================================================
# CONSTANTS  --  tweak these to tune behaviour
# =============================================================================

# --- Camera / window ---
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
MODEL_COMPLEXITY = 1          # 0 = faster / less battery, 1 = more accurate
WINDOW_TITLE = "Hand Gesture Desktop Switcher (claude)"
ALWAYS_ON_TOP = True
SHOW_HELP_AT_START = True

# --- Smoothing ---
# EMA of the hand centroid.  Higher = more responsive, lower = smoother.
EMA_ALPHA = 0.40
# Palm size changes slowly (only with distance), so smooth it much harder:
# a noisy palm size would make every threshold wobble.
PALM_EMA_ALPHA = 0.10

# --- Pose classification (all ratios in palm units) ---
# A finger's "extension ratio" is dist(wrist, tip) / dist(wrist, PIP joint).
# Straight finger ~1.3-1.4, curled finger ~0.7-0.9.  Rotation-invariant.
EXTENDED_RATIO = 1.12         # >= this counts as extended
CURLED_RATIO = 1.00           # <= this counts as curled
OPEN_MIN_SPREAD = 0.40        # fingertip spread / palm for an "open" hand
PINCH_MAX = 0.30              # thumb-index tip distance for OK / gather
OK_OTHER_MIN = 0.45           # middle tip must be this far from thumb (OK)
GATHER_MAX_SPREAD = 0.28      # all fingertips within this spread = gather
THUMB_UP_MIN_LEN = 0.60       # thumb tip to thumb MCP, palms
THUMB_UP_MARGIN = 0.15        # thumb tip must be this far above everything
THUMB_DOWN_MIN_LEN = 0.45     # thumbs down: the thumb points away from a camera
                              # above the screen, so it looks shorter
THUMB_SIDE_MARGIN = 0.25      # thumb tip must be this far left / right of everything
POSE_STABLE_FRAMES = 3        # frames a pose must persist before it counts
HOLD_FLICKER_SECONDS = 0.3    # a hold pose that drops out for less than this
                              # and comes back keeps its hold timer (and does
                              # not fire twice)
SHAKA_MIN_SPAN = 0.95         # hang loose: thumb tip to pinky tip, palms
SHAKA_HOLD_SECONDS = 0.4      # hold hang loose this long to toggle dictation
PTT_HOLD_SECONDS = 0.25       # hang loose by the head: start push-to-talk this fast
PTT_MAX_SECONDS = 180.0       # safety: release push-to-talk after this long
HEAD_STABLE_FRAMES = 3        # consecutive "beside the head" frames to start talking
HEAD_LEAVE_FRAMES = 4         # consecutive frames away from the head to stop

# --- Motion units ---
# Motion is measured in palms, but a hand close to the camera has a huge
# palm, so swipes would need to cross half the frame.  The palm used for
# MOTION is capped at this fraction of the frame width (~70 px at 640 px),
# so close hands get roughly the original pixel thresholds.
MOTION_PALM_MAX_FRAC = 0.11
# Fast swipes can blur and MediaPipe drops the hand for a frame or two.
# Keep tracking state through gaps this short instead of resetting.
HAND_LOST_GRACE_SECONDS = 0.15
# How many of the 21 landmarks may be outside the frame and still count as
# "hand in view" (close hands often have the wrist below the frame edge).
MAX_LANDMARKS_OUTSIDE = 3

# --- Open-hand swipes ---
SWIPE_BUFFER_SECONDS = 0.22
MIN_SWIPE_DISTANCE_PALMS = 1.8
MIN_SWIPE_VELOCITY_PALMS = 10.0
SWIPE_MONOTONIC_RATIO = 0.85  # share of steps that must go the same way
COOLDOWN_SECONDS = 0.75
# A sideways sweep only changes Space when the hand really travels: this
# fraction of the frame width, measured inside the swipe buffer.  It keeps a
# small sideways wiggle from switching Spaces.
SLAP_MIN_TRAVEL_FRAC = 0.22
# True: trackpad style, hand moving right goes to the previous Space (the
# hand "pushes" the screen).  False: hand moving right goes to the next Space.
NATURAL_SWIPE = True

# Entering the frame looks like a swipe; require the whole hand to be in
# frame this long first.  Set 0 if you like to sweep in from the side.
WARMUP_SECONDS = 0.20

# After a swipe, wait until the hand is (nearly) still before the next one,
# so the return stroke does not fire the opposite direction.
REARM_MAX_SPEED_PALMS = 2.0
REARM_STILL_SECONDS = 0.15

# A swipe down within this time after an overview opened closes it (Esc).
OVERVIEW_STATE_TIMEOUT = 10.0

# --- Two-finger gestures ---
NAV_SWIPE_DISTANCE_PALMS = 1.5
NAV_SWIPE_VELOCITY_PALMS = 8.0

# --- Scrolling (two fingers) ---
SCROLL_PX_PER_PALM = 350       # screen pixels per palm of hand travel
SCROLL_DEADZONE_PALMS_S = 0.6  # below this, drift is ignored (soft ramp)
SCROLL_DIRECTION = 1           # 1 = drag the page (touchscreen); -1 = invert
# How the two-finger gesture scrolls: "joystick" = gas pedal (the spot
# where the gesture starts is neutral; below it the page scrolls down,
# above it up, with no momentum), "drag" = the page follows the hand.
SCROLL_MODE = "joystick"
# Joystick: how far the hand must leave the neutral point before the page
# moves, and how fast it moves from there.
JOY_DEADZONE_PALMS = 0.35      # dead zone around the neutral point
JOY_PX_S_PER_PALM = 900        # screen px/s per palm past the dead zone
JOY_EXPONENT = 1.5             # > 1: gentle near neutral, fast far away
JOY_MAX_PX_S = 4000            # top speed cap
# Flick -> momentum.  A fast stroke that ends keeps gliding and decays like
# a trackpad.  Repeated flicks in the same direction stack up.
FLICK_MIN_PALMS_S = 5.0        # release speed that starts a glide
FLICK_END_RATIO = 0.35         # stroke "ends" when speed drops below this x peak
FLICK_WINDOW_SECONDS = 0.20
FLING_GAIN = 1.0               # momentum start speed = flick speed x gain
MOMENTUM_TAU_SECONDS = 0.55    # decay time constant (bigger = longer glide)
MOMENTUM_MIN_PX_S = 15         # stop gliding below this speed
MOMENTUM_MAX_PX_S = 12000
DRAG_SMOOTH_SECONDS = 0.07     # spreads each camera frame's motion over time
# After a flick, the hand coming back the other way is ignored (like lifting
# fingers off a trackpad) until it pauses or this time passes.
RETURN_BLOCK_SECONDS = 0.8
SCROLL_TICK_HZ = 120
LINE_PX = 40                   # pixels per scroll line (non-macOS fallback)

# --- Mouse pointer (point with the index finger, pinch to click) ---
# The cursor follows the four KNUCKLES: they do not move when you pinch,
# unlike the fingertip, so clicks land where you aimed, and averaging four
# landmarks cancels most of the camera jitter.  The wrist is left out on
# purpose: a laptop webcam sits above the screen, so the hand is normally
# low in the frame and the wrist is often out of view, where MediaPipe
# guesses it and the anchor jitters.
# This box of the camera frame (fractions, mirrored view) maps to the whole
# screen, so you never have to stretch to reach the screen edges.  It sits
# low, because the hand rests low: the knuckles reach the top of the screen
# at ~0.40 of the image height and the bottom at ~0.85.
POINTER_BOX = (0.30, 0.40, 0.75, 0.85)   # x0, y0, x1, y1
# "absolute": the knuckles aim at the screen (POINTER_BOX maps to the screen).
# "relative": the hand works like a trackpad, the cursor follows the
# movement of the knuckles.  The engine copies this into self.pointer_mode,
# so the apps can switch modes while running.
POINTER_MODE = "relative"
# Relative mode: the cursor moves by the change of the knuckles (a fraction
# of the frame) times a gain.  The gain grows with the speed of the hand, so
# slow moves are precise and fast ones cross the screen quickly.
REL_GAIN_SLOW = 2.0            # gain below REL_SPEED_SLOW ...
REL_SPEED_SLOW = 0.15          # ... frames per second
REL_GAIN_FAST = 5.0            # gain at REL_SPEED_FAST ...
REL_SPEED_FAST = 1.0           # ... frames per second
REL_EDGE_PUSH = 0.10           # how far past the edge the hand must keep
                               # pushing before the display changes
REL_EDGE_RESTART = 0.02        # where the cursor lands on the new screen
# Several displays: push the palm centre this far past an edge of the box
# (fraction of the box size) and the pointer moves to the display on that
# side.  The palm has to come back inside the box before it can happen again,
# so one push is one screen.
DISPLAY_EDGE_MARGIN = 0.12
DISPLAY_EDGE_FRAMES = 3        # frames in a row past the edge (kills jitter)
POINT_INDEX_MIN_RATIO = 0.90   # index must be at least this straight ...
POINT_STAY_MIN_RATIO = 0.82    # ... to enter pointing; once in, it may bend
                               # this far (pinching bends it) without leaving
# Measured on a MacBook camera (2026-11-02): fingertips touching read about
# 0.12-0.30, a 2-3 cm gap 0.22-0.40.  The two overlap, so the release does
# not wait for a fixed distance: it comes as soon as the fingers move apart
# from how close they got during this pinch.
PINCH_ON = 0.25                # thumb-index distance (palms) to press ...
PINCH_OFF = 0.40               # ... released for sure past this ...
PINCH_RELEASE_RISE = 0.10      # ... or once this far above the closest point
                               # of this pinch (the fingers came apart)
PINCH_RELEASE_FRAMES = 2       # frames in a row needed to release (press is
                               # instant so quick taps are never missed)
PINCH_SMOOTH_ALPHA = 0.7       # EMA on the pinch distance (fingertips jitter)
PINCH_DRAG_OPEN = 0.08         # during a drag, the fingers opening this far
                                # above the closed level freeze the cursor:
                                # the hand shifts while letting go, and that
                                # shift would drag the item away from where
                                # the user aimed
PINCH_DRAG_LEVEL_ALPHA = 0.2   # how fast the closed level of the drag
                                # follows the pinch (it is averaged, so a
                                # jittery frame does not move it)
PINCH_DRAG_SLACK = 0.04        # how far the raw pinch may be above the
                                # closed level and still count as closed
                                # (it is what marks the spot the item is
                                # dropped on)
CLICK_MAX_SECONDS = 0.40       # pinch shorter than this = click, longer = drag
                                # (a deliberate click plus the release lag
                                # must fit in here, or it becomes a drag)
DOUBLE_CLICK_SECONDS = 0.60    # two clicks: the window has to fit a slow
                                # click (CLICK_MAX_SECONDS) plus its release
DOUBLE_CLICK_MAX_DIST = 0.03   # fraction of the screen
PINCH_LOOKBACK_SECONDS = 0.08  # click at where the cursor was just BEFORE
                               # the pinch (fingers drift while closing)
# One Euro filter (camera pixels): steady when still, responsive when moving.
CURSOR_MIN_CUTOFF = 0.5        # Hz; lower = steadier at rest, more lag
CURSOR_BETA = 0.04             # higher = less lag on fast moves
CURSOR_OFFSET_DECAY_SECONDS = 0.4
CURSOR_SMOOTH_SECONDS = 0.025  # 120 Hz interpolation between camera frames

# --- Volume knob (OK sign + twist) ---
VOLUME_DEG_PER_STEP = 15.0     # one volume notch (~6%) per this much twist
VOLUME_MAX_STEPS_PER_FRAME = 2
KNOB_ANGLE_ALPHA = 0.35        # smoothing of the twist angle
KNOB_DEADBAND_DEG = 9.0        # extra twist needed for the first notch
KNOB_HYSTERESIS_DEG = 4.0      # every notch must be passed by this much
VOLUME_DIRECTION = 1           # flip to -1 if clockwise feels backwards

# --- Hold / transition gestures ---
THUMBS_UP_HOLD_SECONDS = 0.5
THUMBS_DOWN_HOLD_SECONDS = 0.5  # thumbs down: undo (deletes dictated text)
ARROW_REPEAT_DELAY = 1.0       # thumb left / right: pause before it repeats
ARROW_REPEAT_INTERVAL = 0.5    # ...then one more arrow press per interval
GATHER_FROM_OPEN_WINDOW = 0.6  # gather must follow an open hand within this
LAUNCHER_COOLDOWN_SECONDS = 1.5  # Cmd+Space toggles: one fire per gesture, ignore flicker
# Diagnostics only: a hand that was open and then pulls its fingertips this
# close (thumb by the index) within this long is a gather attempt, and one
# that does not fire Spotlight leaves a single log line saying why.
GATHER_ATTEMPT_SPREAD = 0.40
GATHER_ATTEMPT_WINDOW = 1.0
GATHER_ATTEMPT_REPORT_AFTER = 0.5  # judge an attempt after the hand held this long
WAVE_STROKE_PALMS = 0.35       # wave: each side-to-side stroke at least this far
WAVE_MAX_STROKE_PALMS = 1.2    # wave: a stroke longer than this is a sweep
WAVE_MIN_REVERSALS = 3         # direction changes needed (two full waves)
WAVE_WINDOW_SECONDS = 1.5      # ...all within this long
WAVE_COOLDOWN_SECONDS = 3.0    # one lock per wave
PAUSE_HOLD_SECONDS = 1.0       # rock horns held this long pauses / resumes (0 = off)
HORNS_THUMB_FOLD_MAX = 0.5     # thumb tip this close (palms) to the middle or ring
                              # knuckle = thumb folded across the palm.  Works
                              # whichever finger it rests on and however the
                              # hand is turned; "I love you" (thumb out) is ~0.75+
HORNS_REDO_SECONDS = 0.15      # once horns has fired, another pose held this long
                              # before horns returns makes it a new gesture; a
                              # shorter dropout is tracking flicker (keeps latch)

# --- Face zone (motion gestures are ignored while the hand is at the face) ---
# Scratching your face or resting your chin on your hand looks like a swipe
# to the gesture engine, so the face box is a "do not move here" zone.
# The box is grown by this fraction of its width / height on each side.
# 10% margin: tight enough so normal swipes and slaps beside the face work,
# while still catching hand strokes near the face edges.
FACE_MARGIN = 0.10
# The hand counts as "at the face" when at least this share of its 21
# landmarks is inside the grown box, OR when the palm centre is inside.
FACE_HAND_SHARE = 0.60
# Landmarks forming the palm centre (wrist + 4 metacarpals).
FACE_PALM_INDICES = (0, 5, 9, 13, 17)
# The face detector is slower than the hand tracker, so it runs every Nth
# frame and the last box is reused in between.
FACE_EVERY_N_FRAMES = 3
# How long a face box stays valid after the last detection (seconds).
FACE_KEEP_SECONDS = 0.5

# --- HUD ---
ACTION_FLASH_SECONDS = 1.0


OS_NAME = platform.system()
DOWN_OPENS_OVERVIEW = False   # swipe down minimizes (Mac) / shows the desktop (Windows)

# Where the pointer box points: one screen, or every screen at once.
DISPLAY_MODE_CURRENT = "current"
DISPLAY_MODE_ALL = "all"
# Gestures that belong to the screen the hand is on.  On macOS, Spaces and
# Mission Control are per screen, so the cursor has to be moved there first.
# On Windows, virtual desktops and Task View are global, but the scroll wheel
# is sent to the window under the cursor, so the cursor still has to travel.
_FOCUS_SCREEN_ACTIONS = {
    "Darwin": ("space_left", "space_right", "overview", "close_overview"),
    "Windows": ("space_left", "space_right"),
}
FOCUS_SCREEN_ACTIONS = _FOCUS_SCREEN_ACTIONS.get(OS_NAME, ())
# Shortcuts handled by the app in front rather than by the system (macOS):
# these are sent with the modifier flags set on every key event.
APP_SHORTCUTS = ("undo", "back", "forward", "app_windows", "launcher")
# How often the scroll thread may re-check which screen it should be on.
FOCUS_CHECK_SECONDS = 0.05


# =============================================================================
# Geometry helpers (pts = list of 21 (x, y) pixel tuples)
# =============================================================================

FINGERS = {
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}
TIPS = (4, 8, 12, 16, 20)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def palm_size(pts):
    """Larger of wrist->middle knuckle and index->pinky knuckle.  Taking the
    max keeps it stable when the hand tilts (rarely both shrink at once)."""
    return max(dist(pts[0], pts[9]), dist(pts[5], pts[17]))


def centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def fingertip_spread(pts):
    tips = [pts[i] for i in TIPS]
    c = centroid(tips)
    return sum(dist(t, c) for t in tips) / len(tips)


def finger_ratio(pts, finger):
    _, pip, _, tip = FINGERS[finger]
    return dist(pts[0], pts[tip]) / max(dist(pts[0], pts[pip]), 1e-6)


def classify_pose(pts, palm):
    """Return (pose, features).  Poses: ok, gather, point, thumbs_up,
    thumbs_down, thumb_left, thumb_right, fist, horns,
    shaka (hang loose), two, open, flat, other."""
    ratios = {f: finger_ratio(pts, f) for f in FINGERS}
    ext = {f: r >= EXTENDED_RATIO for f, r in ratios.items()}
    curl = {f: r <= CURLED_RATIO for f, r in ratios.items()}
    spread = fingertip_spread(pts) / palm
    pinch = dist(pts[4], pts[8]) / palm
    feats = {"spread": spread, "pinch": pinch, "ratios": ratios}

    others_up = sum(not curl[f] for f in ("middle", "ring", "pinky"))
    if (pinch <= PINCH_MAX and dist(pts[4], pts[12]) / palm >= OK_OTHER_MIN
            and others_up >= 2):
        return "ok", feats
    if (spread <= GATHER_MAX_SPREAD and pinch <= PINCH_MAX * 1.3
            and all(r > CURLED_RATIO for r in ratios.values())):
        return "gather", feats
    if (curl["middle"] and curl["ring"] and curl["pinky"]
            and ratios["index"] >= POINT_INDEX_MIN_RATIO):
        # Pointing, with or without the thumb pinched onto the index.
        return "point", feats
    if (curl["index"] and curl["middle"] and curl["ring"] and ext["pinky"]
            and dist(pts[4], pts[2]) / palm >= THUMB_UP_MIN_LEN
            and dist(pts[4], pts[20]) / palm >= SHAKA_MIN_SPAN):
        # Hang loose: thumb and pinky out, the three middle fingers curled.
        return "shaka", feats
    if (ext["index"] and ext["pinky"] and curl["middle"] and curl["ring"]
            and min(dist(pts[4], pts[9]), dist(pts[4], pts[13])) / palm
            < HORNS_THUMB_FOLD_MAX):
        # Rock horns: index and pinky up, middle and ring curled, thumb folded
        # over the palm (shaka and "I love you" have the thumb out).
        return "horns", feats
    if all(curl.values()):
        thumb_len = dist(pts[4], pts[2]) / palm
        highest_other = min(p[1] for i, p in enumerate(pts) if i not in (3, 4))
        if (thumb_len >= THUMB_UP_MIN_LEN
                and pts[4][1] < highest_other - THUMB_UP_MARGIN * palm):
            return "thumbs_up", feats
        lowest_other = max(p[1] for i, p in enumerate(pts) if i not in (3, 4))
        if (thumb_len >= THUMB_DOWN_MIN_LEN
                and pts[4][1] > lowest_other + THUMB_UP_MARGIN * palm):
            return "thumbs_down", feats
        # The frame is mirrored before landmarks: image-left is the user's left.
        leftmost_other = min(p[0] for i, p in enumerate(pts) if i not in (3, 4))
        if (thumb_len >= THUMB_UP_MIN_LEN
                and pts[4][0] < leftmost_other - THUMB_SIDE_MARGIN * palm):
            return "thumb_left", feats
        rightmost_other = max(p[0] for i, p in enumerate(pts) if i not in (3, 4))
        if (thumb_len >= THUMB_UP_MIN_LEN
                and pts[4][0] > rightmost_other + THUMB_SIDE_MARGIN * palm):
            return "thumb_right", feats
        return "fist", feats
    if ext["index"] and ext["middle"] and curl["ring"] and curl["pinky"]:
        return "two", feats
    if all(ext.values()) and spread < OPEN_MIN_SPREAD:
        # Flat hand: the four fingers are straight and held together, so the
        # fingertips are close and the hand is not "open".  The thumb can be
        # anywhere.  Checked after every other pose, so it steals nothing.
        return "flat", feats
    if spread >= OPEN_MIN_SPREAD:
        return "open", feats
    return "other", feats


def near_face(pts, face):
    """True when the hand is at the user's face.

    `face` is the face box in pixels (x0, y0, x1, y1), or None.  The box is
    grown by FACE_MARGIN on every side.  The hand counts as "at the face"
    when its palm centre (mean of landmarks 0, 5, 9, 13, 17) is inside the
    grown box, or when at least FACE_HAND_SHARE of its 21 landmarks is inside.
    """
    if not face:
        return False
    x0, y0, x1, y1 = face
    mx = FACE_MARGIN * max(x1 - x0, 0.0)
    my = FACE_MARGIN * max(y1 - y0, 0.0)
    x0, y0, x1, y1 = x0 - mx, y0 - my, x1 + mx, y1 + my
    inside = sum(1 for x, y in pts if x0 <= x <= x1 and y0 <= y <= y1)
    if inside >= FACE_HAND_SHARE * len(pts):
        return True
    palm_x = sum(pts[i][0] for i in FACE_PALM_INDICES) / len(FACE_PALM_INDICES)
    palm_y = sum(pts[i][1] for i in FACE_PALM_INDICES) / len(FACE_PALM_INDICES)
    return x0 <= palm_x <= x1 and y0 <= palm_y <= y1


class OneEuro:
    """One Euro filter (Casiez et al. 2012): the cutoff frequency rises with
    speed, so a still hand is heavily smoothed and a moving one is not."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = None
        self.dx = 0.0
        self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x is None:
            self.x, self.t = x, t
            return x
        dt = max(t - self.t, 1e-3)
        self.t = t
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        a = self._alpha(self.min_cutoff + self.beta * abs(self.dx), dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


def monotonic_ok(buf, total, axis, noise):
    """Share of steps along `axis` agreeing in sign with `total`."""
    if len(buf) < 3:
        return True
    sign = total > 0
    matching = considered = 0
    for i in range(1, len(buf)):
        step = buf[i][axis] - buf[i - 1][axis]
        if abs(step) > noise:
            considered += 1
            matching += (step > 0) == sign
    return considered == 0 or matching / considered >= SWIPE_MONOTONIC_RATIO


# =============================================================================
# Face zone: where the user's face is, so gestures made there are ignored
# =============================================================================

class FaceTracker:
    """Finds the user's face box (pixels) so the engine can ignore motion
    gestures made while the hand is at the face.

    The detector is slower than the hand tracker, so it runs on every Nth
    frame and the last box is reused (for FACE_KEEP_SECONDS) in between.
    update(rgb, w, h, now) returns the box (x0, y0, x1, y1) or None.
    """

    def __init__(self, mp_face_detection):
        self.detector = mp_face_detection.FaceDetection(
            model_selection=0, min_detection_confidence=0.5)
        self.box = None
        self.last_seen = -1e9
        self.count = 0

    def update(self, rgb, w, h, now):
        self.count += 1
        if self.count % FACE_EVERY_N_FRAMES == 0:
            try:
                res = self.detector.process(rgb)
            except Exception:
                res = None
            dets = getattr(res, "detections", None) if res else None
            if dets:
                rb = dets[0].location_data.relative_bounding_box
                self.box = (rb.xmin * w, rb.ymin * h,
                            (rb.xmin + rb.width) * w, (rb.ymin + rb.height) * h)
                self.last_seen = now
        if self.box is not None and now - self.last_seen <= FACE_KEEP_SECONDS:
            return self.box
        return None

    def close(self):
        if self.detector is not None:
            self.detector.close()
            self.detector = None


# =============================================================================
# Gesture engine: landmarks in, abstract events out (no OS / OpenCV calls)
# =============================================================================

class GestureEngine:
    """Feed it one frame at a time with update() / no_hand().  Returns a list
    of (event_name, count) tuples.  Event names are mapped to OS actions by
    the Dispatcher, so the engine is testable with recorded landmarks."""

    def __init__(self):
        self.paused = False
        self.scroll_mode = SCROLL_MODE     # "joystick" (gas pedal) or "drag"
        self.last_fire = -1e9
        self.overview_until = 0.0
        self.last_open_time = -1e9
        self.last_launcher = -1e9
        self.last_lock = -1e9
        self._wave_reset()
        self.last_click_time = -1e9
        self.last_click_pos = (0.0, 0.0)
        self.near_face = False
        # Copied out of the constant so the apps can switch modes at runtime.
        self.pointer_mode = POINTER_MODE
        # The cursor in relative mode outlives the pointing session, so it
        # is kept here and not in _reset_pose_state.
        self.rel_cursor = (0.5, 0.5)
        # Asks whether a screen exists in a direction; the apps wire it to
        # Dispatcher.can_step.  None means "no neighbour": edges are walls.
        self.can_step_display = None
        self.ptt_active = False            # kept across hand resets: see _ptt_end
        self.ptt_since = 0.0
        self._reset_hand()

    # --- state resets ---
    def _reset_hand(self):
        self.ema_c = None
        self.ema_palm = None
        self.near_face = False
        self.ready_since = None
        self.buf = deque()
        self.armed = True
        self.still_since = None
        self.prev = None
        self.raw_pose = None
        self.raw_count = 0
        self.pose = "none"
        self.pose_since = 0.0
        self.left_pose = (None, 0.0, False, -1e9)   # pose, since, latched, left at
        self.lost_since = None
        self.latched = False
        self.debug = {}
        self._reset_pose_state()
        self.gather_try = None      # current gather attempt, for the miss log

    @property
    def wants_face(self):
        """True when face detection is needed (hang loose seen or talking),
        so the camera loop can skip it the rest of the time."""
        return (self.ptt_active or self.pose == "shaka"
                or self.raw_pose == "shaka")

    def _ptt_end(self, ev):
        if self.ptt_active:
            self.ptt_active = False
            ev.append(("dictation_hold_end", 1))

    def end_ptt(self):
        """Release push-to-talk if held (tracking switched off)."""
        ev = []
        self._ptt_end(ev)
        return ev

    def _wave_reset(self):
        self.wave_anchor = None
        self.wave_dir = 0
        self.wave_extreme = 0.0
        self.wave_flips = deque()

    def _wave_step(self, x, now):
        """Open hand moving side to side. x is the centroid in palm units.
        wave_anchor is where the current stroke started, wave_extreme the
        furthest point it has reached since."""
        if now - self.last_lock < WAVE_COOLDOWN_SECONDS:
            return False
        if self.wave_anchor is None:
            self.wave_anchor = self.wave_extreme = x
            return False
        # A stroke longer than WAVE_MAX_STROKE_PALMS is a sweep across the
        # frame (a slap), not a wave: drop the tracker and start over.
        # The two ranges cannot overlap.  A slap travels at least
        # SLAP_MIN_TRAVEL_FRAC of the frame width and the palm used for
        # motion is at most MOTION_PALM_MAX_FRAC of the frame width, so a
        # slap stroke is at least 0.22 / 0.11 = 2.0 palms long, while a wave
        # stroke stays below 1.2 palms.
        if abs(x - self.wave_anchor) > WAVE_MAX_STROKE_PALMS:
            self._wave_reset()
            return False
        if self.wave_dir == 0:
            if abs(x - self.wave_anchor) >= WAVE_STROKE_PALMS:
                self.wave_dir = 1 if x > self.wave_anchor else -1
                self.wave_extreme = x
            return False
        if (x - self.wave_extreme) * self.wave_dir > 0:
            # Still going the same way: the stroke grows.
            self.wave_extreme = x
        elif abs(self.wave_extreme - x) >= WAVE_STROKE_PALMS:
            # The hand came back far enough: that is a reversal, and the
            # next stroke starts where this one ended.
            self.wave_dir = -self.wave_dir
            self.wave_anchor = self.wave_extreme = x
            self.wave_flips.append(now)
        while self.wave_flips and now - self.wave_flips[0] > WAVE_WINDOW_SECONDS:
            self.wave_flips.popleft()
        if len(self.wave_flips) >= WAVE_MIN_REVERSALS:
            self.last_lock = now
            self._wave_reset()
            return True
        return False

    def _reset_pose_state(self):
        self.arrow_next = None
        self.knob_angle = None
        self.knob_ref = None
        self.knob_started = False
        self.scroll_hist = deque()
        self.scroll_block_dir = 0
        self.scroll_block_until = 0.0
        self.scroll_still_since = None
        self.scroll_neutral = None         # joystick neutral point, per pose
        self.fx = self.fy = None           # cursor filters
        self.pinched = False
        self.pinch_votes = 0
        self.pinch_s = None
        self.pinch_low = PINCH_OFF          # closest point of the current pinch
        self.dragging = False
        self.pinch_start = 0.0
        self.freeze_pos = None
        # A drag that is frozen: the fingers are opening, so the hand
        # drifts, but the item must stay where it was.
        self.drag_frozen = False
        self.drag_anchor = None
        # When the fingers started opening, and how close they were while
        # they were closed: the drag is dropped on the spot from before.
        self.drag_open_from = None
        self.drag_pinch_low = None
        self.cursor_hist = deque()
        self.pinch_hist = deque()       # (time, cursor spot, raw pinch)
        self.cursor_offset = (0.0, 0.0)
        self.cursor = None
        self.edge_votes = 0
        self.edge_dir = None
        self.edge_armed = True
        self.pointer_live = False
        # Relative mode: where the knuckles were the last frame, and how far
        # the hand has pushed past an edge of the screen.  Both belong to the
        # pointing session, so they are cleared here; the cursor itself is
        # not (it stays where it was).
        self.rel_prev = None
        self.rel_push = (0.0, 0.0)
        self.rel_edge_armed = True
        self.head_votes = 0
        self.head_away = 0

    def no_hand(self, now):
        ev = []
        if self.paused:
            self._ptt_end(ev)
        if self.pose != "none" and HAND_LOST_GRACE_SECONDS > 0:
            if self.lost_since is None:
                self.lost_since = now
            if now - self.lost_since < HAND_LOST_GRACE_SECONDS:
                return ev                    # brief dropout: keep state
        if self.pose == "open":
            self.last_open_time = now
        if self.pose == "two":
            self._scroll_release(now, ev)   # hand dropped mid-flick: glide
        if self.pose == "point":
            self._pointer_end(ev)
        self._ptt_end(ev)
        self._reset_hand()
        if self.paused:
            # The mouse button has to be let go even while paused, or it
            # stays down and the drag never ends.
            return [e for e in ev
                    if e[0] == "dictation_hold_end"
                    or e[0] in ("mouse_up", "pointer_end")]
        return ev

    def _scroll_release(self, now, ev):
        """Fingers 'lifted' (pose ended / hand gone): glide if moving fast."""
        if self.scroll_mode == "joystick":
            return                  # gas pedal: the page stops dead, no glide
        recent = [v for t, v in self.scroll_hist if t >= now - FLICK_WINDOW_SECONDS]
        if recent:
            peak = max(recent, key=abs)
            if abs(peak) >= FLICK_MIN_PALMS_S:
                ev.append(("scroll_fling", peak))

    def _gather_watch(self, feats, now):
        """Log one line when a gather attempt does not open Spotlight.
        An attempt: the hand was open a moment ago and the fingertips are
        now close together with the thumb by the index.  Silent otherwise."""
        close = (feats["spread"] < GATHER_ATTEMPT_SPREAD
                 and feats["pinch"] <= PINCH_MAX * 1.3
                 and all(r > CURLED_RATIO for r in feats["ratios"].values())
                 and now - self.last_open_time <= GATHER_ATTEMPT_WINDOW)
        a = self.gather_try
        if a is None:
            if close:
                self.gather_try = {"start": now, "best": feats["spread"],
                                   "done": False, "gather_age": None,
                                   "cooldown": False}
                a = self.gather_try
            else:
                return
        elif not close and not (self.pose == "gather" and not a["done"]):
            if not a["done"]:
                self._gather_report(a)
            self.gather_try = None
            return
        a["best"] = min(a["best"], feats["spread"])
        if a["done"]:
            return
        if self.last_launcher == now:
            a["done"] = True            # it worked: nothing to explain
            return
        if self.pose == "gather" and a["gather_age"] is None:
            a["gather_age"] = now - self.last_open_time
            a["cooldown"] = now - self.last_launcher <= LAUNCHER_COOLDOWN_SECONDS
        if now - a["start"] >= GATHER_ATTEMPT_REPORT_AFTER:
            self._gather_report(a)

    def _gather_report(self, a):
        a["done"] = True
        if a["gather_age"] is not None:
            if a["cooldown"]:
                why = "launcher cooldown"
            elif a["gather_age"] > GATHER_FROM_OPEN_WINDOW:
                why = (f"too slow after open hand ({a['gather_age']:.2f} s"
                       f" > {GATHER_FROM_OPEN_WINDOW} s)")
            else:
                why = "gather was not held steady"
        elif a["best"] > GATHER_MAX_SPREAD:
            why = (f"closest spread {a['best']:.2f}"
                   f" (need <= {GATHER_MAX_SPREAD})")
        else:
            why = "gather pose too brief (flickered)"
        print(f"gather missed: {why}")

    # --- main step ---
    def update(self, pts, w, h, now, face=None):
        ev = []
        if self.paused:
            self._ptt_end(ev)
        raw_palm = palm_size(pts)
        self.ema_palm = raw_palm if self.ema_palm is None else (
            PALM_EMA_ALPHA * raw_palm + (1 - PALM_EMA_ALPHA) * self.ema_palm)
        shape_palm = max(self.ema_palm, 1.0)
        palm = min(shape_palm, MOTION_PALM_MAX_FRAC * w)   # motion units
        self.lost_since = None

        # Hand at the face?  Motion gestures are ignored there (scratching
        # your face looks like a swipe), but hold poses still work.
        self.near_face = near_face(pts, face)
        if self.near_face:
            # Drop the scroll history too, so no flick is fired later on
            # from a stroke that started before the hand reached the face.
            self.scroll_hist.clear()

        raw_pose, feats = classify_pose(pts, shape_palm)
        if self.pose == "point" and raw_pose != "point":
            # Sticky pointer: a pinch bends the index; don't drop a drag.
            r = feats["ratios"]
            if (max(r["middle"], r["ring"], r["pinky"]) <= CURLED_RATIO
                    and r["index"] >= POINT_STAY_MIN_RATIO):
                raw_pose = "point"
        self.debug = dict(feats, raw=raw_pose, palm=shape_palm, mpalm=palm,
                          face=self.near_face)

        # Pose stability filter.
        if raw_pose == self.raw_pose:
            self.raw_count += 1
        else:
            self.raw_pose, self.raw_count = raw_pose, 1
        if self.raw_count >= POSE_STABLE_FRAMES and raw_pose != self.pose:
            if self.pose == "open":
                self.last_open_time = now
            if self.pose == "two":
                self._scroll_release(now, ev)
            if self.pose == "point":
                self._pointer_end(ev)
            self._ptt_end(ev)
            # A hold pose that flickers out for a moment (a thumbs down
            # reads as a fist for a frame or two) keeps its hold timer and
            # latch, so the hold still completes and never fires twice.
            left = (self.pose, self.pose_since, self.latched, now)
            back = self.left_pose
            self.left_pose = left
            self.pose, self.pose_since = raw_pose, now
            self.latched = False
            if back[0] == raw_pose and now - back[3] <= HOLD_FLICKER_SECONDS:
                self.pose_since, self.latched = back[1], back[2]
                # A fired horns that returns after a real break (not a
                # one-frame flicker) is a deliberate second gesture.
                if (raw_pose == "horns" and back[2]
                        and now - back[3] >= HORNS_REDO_SECONDS):
                    self.pose_since, self.latched = now, False
            self.buf.clear()
            self._reset_pose_state()
            if (raw_pose == "gather"
                    and now - self.last_open_time <= GATHER_FROM_OPEN_WINDOW
                    and now - self.last_launcher > LAUNCHER_COOLDOWN_SECONDS):
                ev.append(("launcher", 1))
                self.last_launcher = now
                self.latched = True
                # The hand reopens and drifts after Spotlight shows up; keep
                # that from firing a slap, swipe or wave (it would dismiss
                # Spotlight) until the hand has settled.
                self.buf.clear()
                self.armed, self.still_since = False, None
                self.last_fire = now
                self._wave_reset()
        if self.pose == "open":
            self.last_open_time = now
        self._gather_watch(feats, now)

        # Hang loose beside the head (push-to-talk) vs anywhere else (toggle).
        if self.pose == "shaka":
            near, why = headzone.head_check(pts, shape_palm, face)
            self.head_votes = self.head_votes + 1 if near else 0
            self.head_away = 0 if near else self.head_away + 1
            self.debug["head"] = near
            self.debug["head_why"] = why
            self.debug["face_box"] = face
            if self.ptt_active and (self.head_away >= HEAD_LEAVE_FRAMES
                                    or now - self.ptt_since >= PTT_MAX_SECONDS):
                self._ptt_end(ev)

        # Hold gestures.
        held = now - self.pose_since
        if not self.latched:
            if (self.pose == "horns" and PAUSE_HOLD_SECONDS > 0
                    and held >= PAUSE_HOLD_SECONDS):
                self.paused = not self.paused
                ev.append(("pause_on" if self.paused else "pause_off", 1))
                self.latched = True
            elif self.pose == "thumbs_up" and held >= THUMBS_UP_HOLD_SECONDS:
                ev.append(("play_pause", 1))
                self.latched = True
            elif self.pose == "thumbs_down" and held >= THUMBS_DOWN_HOLD_SECONDS:
                ev.append(("undo", 1))
                self.latched = True
            elif (self.pose == "shaka" and held >= PTT_HOLD_SECONDS
                  and self.head_votes >= HEAD_STABLE_FRAMES and not self.paused):
                ev.append(("dictation_hold_start", 1))
                print(f"hang loose: push to talk, {self.debug.get('head_why')}")
                self.ptt_active, self.ptt_since = True, now
                self.head_away = 0
                self.latched = True
            elif (self.pose == "shaka" and held >= SHAKA_HOLD_SECONDS
                  and self.head_votes == 0):
                ev.append(("dictation", 1))
                print(f"hang loose: toggle, {self.debug.get('head_why')}")
                self.latched = True

        # Thumb left / right: arrow key now, again after a pause, then
        # repeating while held (one slide per gesture unless you hold on).
        if self.pose in ("thumb_left", "thumb_right"):
            if self.arrow_next is None or now >= self.arrow_next:
                ev.append(("arrow_left" if self.pose == "thumb_left" else "arrow_right", 1))
                self.arrow_next = now + (ARROW_REPEAT_DELAY if self.arrow_next is None
                                         else ARROW_REPEAT_INTERVAL)

        # Entry warm-up: hand fully inside the frame for a moment.
        # A few landmarks (usually the wrist when the hand is close) may be
        # out of frame; a hand sliding in from the side has many more out.
        outside = sum(1 for x, y in pts if not (0 <= x <= w and 0 <= y <= h))
        if outside <= MAX_LANDMARKS_OUTSIDE:
            if self.ready_since is None:
                self.ready_since = now
        else:
            self.ready_since = None
            self.buf.clear()
        warmed = (self.ready_since is not None
                  and now - self.ready_since >= WARMUP_SECONDS)

        # Smoothed centroid (kept reset during warm-up so entry motion is
        # not carried into the swipe buffer).
        raw_c = centroid(pts)
        if self.ema_c is None or not warmed:
            self.ema_c = raw_c
        else:
            self.ema_c = (EMA_ALPHA * raw_c[0] + (1 - EMA_ALPHA) * self.ema_c[0],
                          EMA_ALPHA * raw_c[1] + (1 - EMA_ALPHA) * self.ema_c[1])
        cx, cy = self.ema_c

        step = None
        if self.prev is not None and now > self.prev[2]:
            sdt = now - self.prev[2]
            step = ((cx - self.prev[0]) / palm, (cy - self.prev[1]) / palm, sdt)
        self.prev = (cx, cy, now)

        # Re-arm once the hand settles.
        if not self.armed and step is not None:
            speed = math.hypot(step[0], step[1]) / step[2]
            if speed < REARM_MAX_SPEED_PALMS:
                if self.still_since is None:
                    self.still_since = now
                elif now - self.still_since >= REARM_STILL_SECONDS:
                    self.armed, self.still_since = True, None
            else:
                self.still_since = None

        # Volume knob.
        if self.pose == "ok":
            # Hand roll = direction from the wrist to the knuckle line,
            # averaged over all four knuckles (much less jittery than one).
            vx = sum(pts[i][0] for i in (5, 9, 13, 17)) / 4 - pts[0][0]
            vy = sum(pts[i][1] for i in (5, 9, 13, 17)) / 4 - pts[0][1]
            ang = math.degrees(math.atan2(vy, vx))
            if self.knob_angle is None:
                self.knob_angle = self.knob_ref = ang
            else:
                self.knob_angle += KNOB_ANGLE_ALPHA * wrap180(ang - self.knob_angle)
                delta = (self.knob_angle - self.knob_ref) * VOLUME_DIRECTION
                if self.near_face:
                    # Twisting at the face does nothing: re-base the knob so
                    # the twist does not fire all at once when the hand
                    # comes back out of the face box.
                    self.knob_ref = self.knob_angle
                    self.knob_started = False
                    delta = 0.0
                if not self.knob_started:
                    # First notch needs a little extra twist, so forming
                    # the OK sign itself never nudges the volume.
                    if abs(delta) < VOLUME_DEG_PER_STEP + KNOB_DEADBAND_DEG:
                        delta = 0.0
                    else:
                        self.knob_started = True
                mag = max(0.0, abs(delta) - KNOB_HYSTERESIS_DEG)
                steps = int(mag / VOLUME_DEG_PER_STEP) * (1 if delta > 0 else -1)
                steps = max(-VOLUME_MAX_STEPS_PER_FRAME,
                            min(VOLUME_MAX_STEPS_PER_FRAME, steps))
                if steps:
                    ev.append(("volume_up" if steps > 0 else "volume_down",
                               abs(steps)))
                    self.knob_ref += steps * VOLUME_DEG_PER_STEP * VOLUME_DIRECTION
            self.debug["knob"] = (self.knob_angle - self.knob_ref) * VOLUME_DIRECTION

        # Mouse pointer.
        if self.pose == "point" and not self.near_face:
            self._pointer_step(pts, w, h, now, feats["pinch"],
                               feats["ratios"]["index"], ev)
        elif self.near_face and self.pointer_live:
            # The hand went to the face: end the pointer cleanly, so no
            # cursor is left running behind the user's face.
            self._pointer_end(ev)

        # Two-finger scroll: drag follows the hand, flicks glide.
        if self.pose == "two" and warmed and step is not None and not self.near_face:
            self._scroll_step(step, now, ev, cy, palm)

        # Wave: open or flat hand side to side a few times -> lock screen.
        if self.pose in ("open", "flat") and warmed and not self.near_face:
            if self._wave_step(cx / palm, now):
                ev.append(("lock", 1))
                self.buf.clear()
                self.armed, self.still_since = False, None
                self.last_fire = now
        else:
            self._wave_reset()

        # Swipes (open / flat hand: 4 directions; two fingers: horizontal nav).
        family = self.pose if self.pose in ("open", "flat", "two") else None
        if self.near_face:
            # Motion made at the face must not carry over once the hand
            # leaves it, so the buffer is dropped every frame in there.
            family = None
            self.buf.clear()
        cutoff = now - SWIPE_BUFFER_SECONDS
        if family and warmed:
            self.buf.append((cx, cy, now))
        while self.buf and self.buf[0][2] < cutoff:
            self.buf.popleft()
        if (family and warmed and len(self.buf) >= 2 and self.armed
                and now - self.last_fire > COOLDOWN_SECONDS):
            fired = self._eval_swipe(family, palm, now, w)
            if fired:
                ev.append((fired, 1))
                self.buf.clear()
                self.armed, self.still_since = False, None
                self.last_fire = now
                if fired in ("space_left", "space_right"):
                    # A slap is not a wave: drop the wave tracker, or the
                    # return stroke could be counted as a wave.
                    self._wave_reset()

        if len(self.buf) >= 2:
            (x0, y0, t0), (x1, y1, t1) = self.buf[0], self.buf[-1]
            if t1 > t0:
                self.debug["swipe"] = ((x1 - x0) / palm, (y1 - y0) / palm,
                                       max(abs(x1 - x0), abs(y1 - y0)) / palm / (t1 - t0))

        if self.paused:
            # The mouse button has to be let go even while paused, or it
            # stays down and the drag never ends.
            ev = [e for e in ev
                  if e[0].startswith("pause") or e[0] == "dictation_hold_end"
                  or e[0] in ("mouse_up", "pointer_end")]
        return ev

    # --- pointer ---
    def _map_raw(self, x, y, w, h):
        """Knuckle centre in box units, unclamped: 0..1 inside the box."""
        x0, y0, x1, y1 = POINTER_BOX
        return ((x / w - x0) / (x1 - x0), (y / h - y0) / (y1 - y0))

    def _map_to_screen(self, x, y, w, h):
        nx, ny = self._map_raw(x, y, w, h)
        return (min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))

    def _rel_gain(self, speed):
        """Gain for a relative move: slow moves are precise, fast ones are
        quick.  Ramps linearly between the slow and the fast speed."""
        if speed <= REL_SPEED_SLOW:
            return REL_GAIN_SLOW
        if speed >= REL_SPEED_FAST:
            return REL_GAIN_FAST
        t = (speed - REL_SPEED_SLOW) / (REL_SPEED_FAST - REL_SPEED_SLOW)
        return REL_GAIN_SLOW + t * (REL_GAIN_FAST - REL_GAIN_SLOW)

    def _relative_step(self, ax, ay, w, h, now, ev):
        """Trackpad mode: the cursor follows the movement of the knuckles.

        The first frame of a pointing session only records where the hand
        is, so starting to point never jumps the cursor.  The cursor itself
        survives the session, so putting the hand back and pointing again
        carries on from where the cursor was."""
        pos = (ax / w, ay / h)
        if self.rel_prev is None:
            self.rel_prev = (pos[0], pos[1], now)
            return self.rel_cursor
        prev = self.rel_prev
        self.rel_prev = (pos[0], pos[1], now)
        # While the fingers are closed the cursor holds still, so the
        # movement of the hand is dropped and cannot make it jump later.
        if self.pinched and not self.dragging:
            return self.rel_cursor
        dt = max(now - prev[2], 1e-3)
        dx = pos[0] - prev[0]
        dy = pos[1] - prev[1]
        speed = math.hypot(dx, dy) / dt
        gain = self._rel_gain(speed)
        mx, my = dx * gain, dy * gain
        cx, cy = self.rel_cursor
        nx = min(1.0, max(0.0, cx + mx))
        ny = min(1.0, max(0.0, cy + my))
        # How much of the move was cut off by an edge of the screen.
        lost_x, lost_y = cx + mx - nx, cy + my - ny
        self.rel_cursor = (nx, ny)
        self._rel_edge(lost_x, lost_y, ev)
        return self.rel_cursor

    def _rel_edge(self, lost_x, lost_y, ev):
        """The cursor is stuck against an edge and the hand keeps pushing
        out: count the overshoot and, once it is big enough, ask for the
        display on that side.  The cursor then starts just inside the far
        edge of the new screen, so the same push does not repeat."""
        push_x, push_y = self.rel_push
        # The overshoot is signed: positive means pushed to the right/down.
        # Pushing back the other way cancels what came before.
        if lost_x:
            push_x = push_x + lost_x if (push_x >= 0) == (lost_x >= 0) else lost_x
        else:
            push_x = 0.0
        if lost_y:
            push_y = push_y + lost_y if (push_y >= 0) == (lost_y >= 0) else lost_y
        else:
            push_y = 0.0
        self.rel_push = (push_x, push_y)
        if not self.rel_edge_armed:
            # One display step per push: re-arm once the cursor has left
            # the edge it was stuck against.
            if lost_x == 0.0 and lost_y == 0.0:
                self.rel_edge_armed = True
                self.rel_push = (0.0, 0.0)
            return
        if push_x >= REL_EDGE_PUSH:
            d = (1, 0)
        elif push_x <= -REL_EDGE_PUSH:
            d = (-1, 0)
        elif push_y >= REL_EDGE_PUSH:
            d = (0, 1)
        elif push_y <= -REL_EDGE_PUSH:
            d = (0, -1)
        else:
            return
        self.rel_push = (0.0, 0.0)
        if not self._can_step(d):
            # No screen on that side: the edge is a wall.  The cursor stays
            # on it and the push starts counting from zero again.
            return
        self.rel_edge_armed = False
        # Pushing right lands on the left edge of the next screen.
        cx, cy = self.rel_cursor
        if d[0] > 0:
            cx = REL_EDGE_RESTART
        elif d[0] < 0:
            cx = 1.0 - REL_EDGE_RESTART
        elif d[1] > 0:
            cy = REL_EDGE_RESTART
        else:
            cy = 1.0 - REL_EDGE_RESTART
        self.rel_cursor = (cx, cy)
        # The landing spot travels with the step so the cursor goes straight
        # there instead of gliding over from the old screen's position.
        ev.append(("display_step", (d, self.rel_cursor)))

    def _can_step(self, d):
        try:
            return bool(self.can_step_display and self.can_step_display(d))
        except Exception:
            return False

    def _edge_step(self, raw, ev):
        """Knuckles pushed clearly past an edge of the box: ask for the
        display on that side.  Re-armed once the hand is back inside the
        box."""
        nx, ny = raw
        m = DISPLAY_EDGE_MARGIN
        if -m < nx < 1 + m and -m < ny < 1 + m:
            if 0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0:
                self.edge_armed = True
            self.edge_votes, self.edge_dir = 0, None
            return
        if not self.edge_armed or (self.pinched and not self.dragging):
            return
        # The axis it overshoots most is the direction.
        ox = nx - 1 if nx > 1 else nx if nx < 0 else 0.0
        oy = ny - 1 if ny > 1 else ny if ny < 0 else 0.0
        d = ((1 if ox > 0 else -1), 0) if abs(ox) >= abs(oy) else (0, (1 if oy > 0 else -1))
        self.edge_votes = self.edge_votes + 1 if d == self.edge_dir else 1
        self.edge_dir = d
        if self.edge_votes >= DISPLAY_EDGE_FRAMES:
            if self._can_step(d):
                ev.append(("display_step", d))
            self.edge_armed = False
            self.edge_votes, self.edge_dir = 0, None

    def _pointer_step(self, pts, w, h, now, pinch, index_ratio, ev):
        if self.fx is None:
            self.fx = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
            self.fy = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
        # Only the four knuckles: the wrist is often out of frame when the
        # hand is held low, and MediaPipe guesses it, which makes the
        # anchor jitter.
        anchor = [pts[i] for i in (5, 9, 13, 17)]
        ax = self.fx(sum(p[0] for p in anchor) / 4, now)
        ay = self.fy(sum(p[1] for p in anchor) / 4, now)
        relative = self.pointer_mode == "relative"

        # Pinch state: smoothed distance.  The smoothing comes first: the
        # drag freeze has to know whether the fingers are opening before
        # the cursor is moved.
        raw_pinch = pinch
        self.pinch_s = pinch if self.pinch_s is None else (
            PINCH_SMOOTH_ALPHA * pinch + (1 - PINCH_SMOOTH_ALPHA) * self.pinch_s)
        pinch = self.pinch_s

        if relative:
            # The cursor is moved by the movement of the hand, not by where
            # the hand is; the box says nothing about the screen then.
            mapped = self._relative_step(ax, ay, w, h, now, ev)
        else:
            raw = self._map_raw(ax, ay, w, h)
            mapped = (min(1.0, max(0.0, raw[0])), min(1.0, max(0.0, raw[1])))
            self._edge_step(raw, ev)
        ox, oy = self.cursor_offset
        live = (mapped[0] + ox, mapped[1] + oy)

        # A press needs a clearly straight index: closing the hand into a
        # fist also brings thumb and index together, and must not click.
        if self.pinched:
            # The closest the fingers have been during this pinch.
            self.pinch_low = min(self.pinch_low, pinch)
        release_at = min(PINCH_OFF, self.pinch_low + PINCH_RELEASE_RISE)
        want = ((pinch <= PINCH_ON and index_ratio >= POINT_INDEX_MIN_RATIO)
                if not self.pinched else not (pinch >= release_at))
        self.pinch_votes = self.pinch_votes + 1 if want != self.pinched else 0
        flip = self.pinch_votes >= (PINCH_RELEASE_FRAMES if self.pinched else 1)
        if flip:
            self.pinch_votes = 0
        if flip and not self.pinched:
            self.pinched, self.dragging, self.pinch_start = True, False, now
            self.pinch_low = pinch
            # Freeze where the cursor was just before the fingers closed.
            past = [p for t, p in self.cursor_hist if t <= now - PINCH_LOOKBACK_SECONDS]
            self.freeze_pos = past[-1] if past else (self.cursor or live)
            if relative:
                # The relative cursor is the truth here, so park it on the
                # frozen spot: the drag then continues from there.
                self.rel_cursor = self.freeze_pos
        elif flip and self.pinched:
            self.pinched = False
            if self.dragging:
                # The item is dropped where the cursor was when the
                # fingers started opening.
                at = (self.drag_anchor if self.drag_frozen
                      and self.drag_anchor is not None else self.cursor)
                if at is not None:
                    ev.append(("mouse_up", at))
                self.drag_frozen = False
                self.drag_anchor = None
                self.drag_open_from = None
                self.drag_pinch_low = None
            else:
                pos = self.freeze_pos
                lx, ly = self.last_click_pos
                double = (now - self.last_click_time <= DOUBLE_CLICK_SECONDS
                          and math.hypot(pos[0] - lx, pos[1] - ly) <= DOUBLE_CLICK_MAX_DIST)
                ev.append(("click", (pos, 2 if double else 1)))
                self.last_click_time = 0.0 if double else now   # no triple chain
                self.last_click_pos = pos
            self._rebase_offset(mapped)
            self.dragging = False
        if self.pinched and not self.dragging and now - self.pinch_start >= CLICK_MAX_SECONDS:
            self.dragging = True
            self.drag_anchor = self.freeze_pos
            self.drag_open_from = None
            self.drag_pinch_low = None
            ev.append(("mouse_down", self.freeze_pos))
            self._rebase_offset(mapped)

        # Letting go of a drag: the fingers open and the hand shifts with
        # them, and that shift would drag the item away from where it
        # was.  So the cursor freezes as soon as the fingers start
        # opening, and it only moves again if they close once more.
        if self.dragging:
            # How close the fingers are while they are closed: the level
            # the pinch sits at when nothing is happening.  It is averaged
            # over the frames where the fingers were still closed, so one
            # jittery frame does not move it and the opening itself does
            # not raise it.
            if self.drag_pinch_low is None:
                self.drag_pinch_low = raw_pinch
            closed = raw_pinch <= self.drag_pinch_low + PINCH_DRAG_SLACK
            # The fingers started opening.  The smoothed distance says so
            # a frame or two later than the raw one, but it does not
            # tremble, so it is the safer signal.
            opening = pinch > self.drag_pinch_low + PINCH_DRAG_OPEN
            if opening and self.drag_open_from is None:
                self.drag_open_from = now
            elif not opening and self.drag_open_from is not None:
                # The fingers closed again before the release: the drag
                # carries on from the frozen spot.
                self.drag_open_from = None
                self.drag_frozen = False
                self.drag_anchor = None
                if not relative:
                    # Carry the frozen spot over, so nothing jumps.
                    self._rebase_offset(mapped)
            if self.drag_open_from is not None:
                # The spot to drop the item on is where the cursor was
                # while the fingers were still closed, so the drift of the
                # hand letting go does not move the item.
                spots = [p for t, p, q in self.pinch_hist
                         if q <= self.drag_pinch_low + PINCH_DRAG_SLACK
                         and t <= self.drag_open_from]
                if spots:
                    self.drag_anchor = spots[-1]
                self.drag_frozen = True
                if relative:
                    # The hand drifted while the fingers opened; the cursor
                    # must not follow it, so it stays on the frozen spot.
                    self.rel_cursor = self.drag_anchor
                    mapped = self.drag_anchor
            elif closed:
                # Still closed: the level follows the pinch.
                self.drag_pinch_low = (PINCH_DRAG_LEVEL_ALPHA * raw_pinch
                                       + (1 - PINCH_DRAG_LEVEL_ALPHA)
                                       * self.drag_pinch_low)

        if self.pinched and not self.dragging:
            target = self.freeze_pos                 # hold still for the click
        elif self.drag_frozen:
            target = self.drag_anchor                # the fingers are opening
        elif relative:
            # The relative cursor is the truth, so there is no offset to
            # fade out here.
            target = mapped
        else:
            # Offset left over from a freeze fades out, so nothing jumps.
            k = math.exp(-(1 / 30) / CURSOR_OFFSET_DECAY_SECONDS) if not self.pinched else 1.0
            self.cursor_offset = (self.cursor_offset[0] * k, self.cursor_offset[1] * k)
            ox, oy = self.cursor_offset
            target = (min(1.0, max(0.0, mapped[0] + ox)), min(1.0, max(0.0, mapped[1] + oy)))
        self.cursor = target
        if self.dragging and not self.drag_frozen:
            # The anchor follows the cursor while the fingers stay closed.
            self.drag_anchor = target
        self.cursor_hist.append((now, target))
        self.pinch_hist.append((now, target, raw_pinch))
        while self.cursor_hist and self.cursor_hist[0][0] < now - 0.3:
            self.cursor_hist.popleft()
        while self.pinch_hist and self.pinch_hist[0][0] < now - 0.3:
            self.pinch_hist.popleft()
        ev.append(("pointer_move", target))
        self.debug["pointer"] = (target, self.pinched, self.dragging)
        self.pointer_live = True

    def _rebase_offset(self, mapped):
        """Keep the cursor where it is when it un-freezes."""
        if self.pointer_mode == "relative":
            # The relative cursor already carries the position over, so
            # there is nothing to shift.
            self.cursor_offset = (0.0, 0.0)
            return
        if self.cursor is not None:
            self.cursor_offset = (self.cursor[0] - mapped[0], self.cursor[1] - mapped[1])

    def _pointer_end(self, ev):
        if self.pinched and self.dragging:
            # The gesture ends mid-drag (pause, pointer mode change, the
            # hand leaves): let the button go at the spot the drag was
            # frozen on, or at the cursor.
            at = self.drag_anchor if (self.drag_frozen
                                      and self.drag_anchor is not None) else self.cursor
            if at is not None:
                ev.append(("mouse_up", at))
        self.drag_frozen = False
        self.drag_anchor = None
        self.drag_open_from = None
        self.drag_pinch_low = None
        if self.pointer_mode == "relative" and self.cursor is not None:
            # The cursor keeps its place between pointing sessions, so the
            # next one starts from where this one stopped.
            self.rel_cursor = self.cursor
        ev.append(("pointer_end", None))
        self.pointer_live = False

    def _scroll_step(self, step, now, ev, cy=None, palm=None):
        if self.scroll_mode == "joystick":
            # Gas pedal: the hand is a joystick, the page does not follow
            # it.  The height where the pose started is the neutral point,
            # so dipping down and coming straight back up scrolls both
            # ways (no direction lock).
            if self.scroll_neutral is None:
                self.scroll_neutral = cy
            offset = (cy - self.scroll_neutral) / palm   # + = below neutral
            reach = abs(offset) - JOY_DEADZONE_PALMS
            if reach <= 0:
                return                       # inside the dead zone: no motion
            speed = min(JOY_MAX_PX_S,
                        JOY_PX_S_PER_PALM * reach ** JOY_EXPONENT)
            # The Dispatcher turns scroll_drag into pixels with
            # SCROLL_PX_PER_PALM, so send the travel this frame would have
            # been: a speed of px/s for one frame is speed * sdt pixels.
            travel = speed * step[2] / SCROLL_PX_PER_PALM
            # Sign: in drag mode the page scrolls down when the hand moves
            # UP, and a negative scroll_drag scrolls the page down, so the
            # hand BELOW neutral (offset > 0) has to send a negative one.
            ev.append(("scroll_drag", -travel if offset > 0 else travel))
            return
        sdx, sdy, sdt = step
        vx, vy = sdx / sdt, sdy / sdt
        self.scroll_hist.append((now, vy))
        while self.scroll_hist and self.scroll_hist[0][0] < now - FLICK_WINDOW_SECONDS:
            self.scroll_hist.popleft()

        # Return-stroke block clears once the hand pauses or time runs out.
        if self.scroll_block_dir:
            if abs(vy) < SCROLL_DEADZONE_PALMS_S:
                if self.scroll_still_since is None:
                    self.scroll_still_since = now
                elif now - self.scroll_still_since >= REARM_STILL_SECONDS:
                    self.scroll_block_dir = 0
            else:
                self.scroll_still_since = None
            if now >= self.scroll_block_until:
                self.scroll_block_dir = 0

        # Soft dead zone: motion fades in between 50% and 100% of the dead
        # zone instead of switching on and off, so slow drags don't stutter.
        dz = SCROLL_DEADZONE_PALMS_S
        gain = min(1.0, max(0.0, (abs(vy) - 0.5 * dz) / (0.5 * dz)))
        moving = gain > 0 and abs(vy) > 0.7 * abs(vx)
        blocked = (moving and self.scroll_block_dir != 0
                   and (vy > 0) == (self.scroll_block_dir > 0))
        if moving and not blocked:
            ev.append(("scroll_drag", sdy * gain))

        # Flick: a fast stroke whose speed has just collapsed.
        peak = max((v for _, v in self.scroll_hist), key=abs)
        along = vy * (1 if peak > 0 else -1)
        peak_blocked = (self.scroll_block_dir != 0
                        and (peak > 0) == (self.scroll_block_dir > 0))
        if (abs(peak) >= FLICK_MIN_PALMS_S and along < FLICK_END_RATIO * abs(peak)
                and not peak_blocked):
            ev.append(("scroll_fling", peak))
            self.scroll_block_dir = -1 if peak > 0 else 1
            self.scroll_block_until = now + RETURN_BLOCK_SECONDS
            self.scroll_still_since = None
            self.scroll_hist.clear()

    def _eval_swipe(self, family, palm, now, w):
        (x0, y0, t0), (x1, y1, t1) = self.buf[0], self.buf[-1]
        dt = t1 - t0
        if dt <= 0:
            return None
        dx, dy = (x1 - x0) / palm, (y1 - y0) / palm
        if family in ("open", "flat"):
            dmin, vmin = MIN_SWIPE_DISTANCE_PALMS, MIN_SWIPE_VELOCITY_PALMS
        else:
            dmin, vmin = NAV_SWIPE_DISTANCE_PALMS, NAV_SWIPE_VELOCITY_PALMS
        noise = 0.03 * palm
        if abs(dx) >= abs(dy):
            if (abs(dx) >= dmin and abs(dx) / dt >= vmin
                    and monotonic_ok(self.buf, dx, 0, noise)):
                if family in ("open", "flat"):
                    # A slap has to cross a good part of the frame, so a
                    # small sideways move never switches Space.
                    if abs(x1 - x0) < SLAP_MIN_TRAVEL_FRAC * w:
                        return None
                    moved_right = dx > 0
                    if NATURAL_SWIPE:
                        return "space_left" if moved_right else "space_right"
                    return "space_right" if moved_right else "space_left"
                # Like a trackpad: fingers moving right = back.
                return "back" if dx > 0 else "forward"
        elif family in ("open", "flat"):
            if (abs(dy) >= dmin and abs(dy) / dt >= vmin
                    and monotonic_ok(self.buf, dy, 1, noise)):
                if dy < 0:
                    self.overview_until = now + OVERVIEW_STATE_TIMEOUT
                    return "overview"
                if now < self.overview_until:
                    self.overview_until = 0.0
                    return "close_overview"
                self.overview_until = (now + OVERVIEW_STATE_TIMEOUT
                                       if DOWN_OPENS_OVERVIEW else 0.0)
                return "app_windows"
        return None


# =============================================================================
# Dispatcher: abstract events -> OS actions, on a background thread
# =============================================================================

NX_SOUND_UP, NX_SOUND_DOWN, NX_PLAY = 0, 1, 16

KEY_BINDINGS = {
    "Darwin": {
        "space_left": ("ctrl", "left"), "space_right": ("ctrl", "right"),
        "overview": ("ctrl", "up"),
        "app_windows": ("cmd", "m"),          # swipe down: minimize the front window
        "close_overview": ("escape",),
        "back": ("cmd", "["), "forward": ("cmd", "]"),
        "launcher": ("cmd", "space"), "undo": ("cmd", "z"),
        "lock": ("ctrl", "cmd", "q"),
        "arrow_left": ("left",), "arrow_right": ("right",),
    },
    "Windows": {
        "space_left": ("ctrl", "win", "left"), "space_right": ("ctrl", "win", "right"),
        "overview": ("win", "tab"), "app_windows": ("win", "d"),
        "close_overview": ("escape",),
        "back": ("alt", "left"), "forward": ("alt", "right"),
        "launcher": ("win",), "undo": ("ctrl", "z"),
        "lock": ("win", "l"),
        "arrow_left": ("left",), "arrow_right": ("right",),
    },
    "Linux": {
        "space_left": ("ctrl", "alt", "left"), "space_right": ("ctrl", "alt", "right"),
        "overview": ("ctrl", "alt", "up"), "app_windows": ("ctrl", "alt", "down"),
        "close_overview": ("escape",),
        "back": ("alt", "left"), "forward": ("alt", "right"),
        "launcher": ("win",),
        "arrow_left": ("left",), "arrow_right": ("right",),
    },
}
MEDIA_KEYS = {"volume_up": ("volumeup", NX_SOUND_UP),
              "volume_down": ("volumedown", NX_SOUND_DOWN),
              "play_pause": ("playpause", NX_PLAY)}
PYAUTOGUI_NAMES = {"cmd": "command", "alt": "option"} if OS_NAME == "Darwin" else {}

LOCK_POLL_SECONDS = 0.5        # how often to ask the OS whether the screen is locked


def screen_locked(quartz=None):
    """True while the lock screen is up.  Cenno keeps running behind it, so
    the camera still sees the hand; this is how it knows to only listen for
    the wake wave."""
    try:
        if OS_NAME == "Darwin" and quartz is not None:
            session = quartz.CGSessionCopyCurrentDictionary()
            return bool(session and session.get("CGSSessionScreenIsLocked", False))
        if OS_NAME == "Windows":
            return _windows_input_desktop_locked()
    except Exception as exc:
        print(f"WARN: could not read the lock state: {exc}")
    return False


def _windows_input_desktop_locked():
    """Windows draws the lock screen on its own secure desktop (Winlogon).
    While it is up, the input desktop cannot be opened, or is not "Default"."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    desk = user32.OpenInputDesktop(0, False, 0x0001)      # DESKTOP_READOBJECTS
    if not desk:
        return True
    try:
        name = ctypes.create_unicode_buffer(64)
        needed = wintypes.DWORD()
        if not user32.GetUserObjectInformationW(desk, 2, name, ctypes.sizeof(name),
                                                ctypes.byref(needed)):  # UOI_NAME
            return False
        return name.value.lower() != "default"
    finally:
        user32.CloseDesktop(desk)


class Dispatcher:
    def __init__(self):
        import pyautogui
        pyautogui.PAUSE = 0.01
        self.pag = pyautogui
        self.bindings = KEY_BINDINGS.get(OS_NAME, KEY_BINDINGS["Linux"])
        self.quartz = self.appkit = None
        if OS_NAME == "Darwin":
            try:
                import Quartz
                import AppKit
                self.quartz, self.appkit = Quartz, AppKit
            except ImportError:
                print("WARN: Quartz/AppKit not available; using pyautogui keys.")
        self.display_mode = DISPLAY_MODE_CURRENT
        self.layout = dpy.fallback_layout(self.pag.size())
        self._focus_checked = 0.0
        self.refresh_displays()
        self.scroller = ScrollAnimator(self.quartz, self.pag,
                                       before_post=self._focus_screen)
        self.pointer = PointerAnimator(self.quartz, self.pag, self.layout,
                                       cursor_pos=self.cursor_position)
        self.locked = False
        self._lock_checked = -1e9
        self.q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    # --- lock screen ---
    def screen_locked(self, now=None):
        """The lock state, asked of the OS at most every LOCK_POLL_SECONDS."""
        now = time.monotonic() if now is None else now
        if now - self._lock_checked >= LOCK_POLL_SECONDS:
            self._lock_checked = now
            locked = screen_locked(self.quartz)
            if locked != self.locked:
                print("screen locked: only the wave (wake) is listened to"
                      if locked else "screen unlocked")
                self.locked = locked
        return self.locked

    def while_locked(self, events, now=None):
        """Filter a frame's gestures through the lock screen.  Unlocked they
        pass untouched.  Locked, nothing reaches the lock screen except the
        wave, which wakes the display so Touch ID, an Apple Watch, Windows
        Hello or the password can take over.  Cenno never unlocks itself:
        anyone can wave at a camera."""
        if not self.screen_locked(now):
            return events
        # Letting the mouse button go has to get through even on the lock
        # screen, or the button stays down when it unlocks.
        out = [e for e in events if e[0] in ("mouse_up", "pointer_end")]
        if any(name == "lock" for name, _ in events):
            out.append(("wake", 1))
        return out

    # --- screens ---
    def refresh_displays(self):
        """Ask the OS for the screens again.  Cheap enough to call a few
        times a second, which is how Cenno notices a display being plugged
        in, unplugged or rearranged.  True when it changed."""
        layout = dpy.fallback_layout(self.pag.size())
        found = dpy.system_displays(self.quartz)
        if found:
            layout = dpy.DisplayLayout(found)
        if layout.equals(self.layout):
            return False
        self.layout = layout
        if getattr(self, "pointer", None) is not None:
            self.pointer.set_layout(layout)
            if self.pointer.mode != self.display_mode:
                self.pointer.set_mode(self.display_mode)
        print(f"displays: {layout.describe()}")
        return True

    def set_display_mode(self, mode):
        """Where the pointer box reaches: the display under the cursor, or
        every display laid out side by side."""
        if mode not in (DISPLAY_MODE_CURRENT, DISPLAY_MODE_ALL):
            return
        if mode == self.display_mode:
            return
        self.display_mode = mode
        self.pointer.set_mode(mode)
        print(f"pointer mode: {mode}")

    def jump_to_next_display(self):
        """Move the cursor to the next screen (menu action).  No click, so
        nothing in the app on that screen is triggered."""
        if self.layout.count < 2:
            return False
        here = self.pointer.cursor_position() or self._raw_cursor()
        index = self.layout.next_index(self.layout.screen_of(here))
        self.pointer.focus_display(index)
        self._warp(self.layout.center(index))
        print(f"cursor -> display {index + 1} of {self.layout.count}")
        return True

    def _neighbor(self, direction):
        """Index of the screen next to the cursor's in `direction`, or None
        (one screen, "all displays" mode, or nothing on that side)."""
        if self.layout.count < 2 or self.display_mode != DISPLAY_MODE_CURRENT:
            return None
        here = self.layout.screen_of(self.pointer.cursor_position() or self._raw_cursor())
        return self.layout.neighbor(here, direction)

    def can_step(self, direction):
        """True when step_display(direction) would really move to a screen."""
        return self._neighbor(direction) is not None

    def step_display(self, step):
        """The hand pushed out of the pointer box: hand the pointer to the
        display on that side.  "All displays" already spans every screen, so
        there it does nothing.  `step` is a plain direction (absolute mode:
        the hand's spot keeps mapping the same way, now onto the new screen)
        or (direction, landing) from relative mode, where the cursor goes
        exactly to the landing spot (0..1) of the new screen."""
        landing = None
        direction = step
        if len(step) == 2 and isinstance(step[0], (tuple, list)):
            direction, landing = step
        direction = tuple(direction)
        index = self._neighbor(direction)
        if index is None:
            return False
        self.pointer.focus_display(index, landing)
        aim = self.pointer.target_pixel() or self.layout.center(index)
        self._warp(aim)
        print(f"pointer -> display {index + 1} of {self.layout.count}")
        return True

    def cursor_position(self):
        """Where the cursor is, in the same global space as the display rects.
        Quartz is asked directly on macOS: pyautogui's reading is the main
        screen only on some macOS versions."""
        if self.quartz is not None:
            try:
                loc = self.quartz.CGEventCreate(None).location()
                return (float(loc.x), float(loc.y))
            except Exception:
                pass
        x, y = self.pag.position()
        return (float(x), float(y))

    def _raw_cursor(self):
        try:
            return self.cursor_position()
        except Exception:
            return self.layout.center(self.layout.primary)

    def _warp(self, point):
        """Move the cursor to point with no button pressed.  This is what
        hands a screen its focus back: macOS switches Spaces per screen and
        follows the cursor, and on Windows the wheel goes to the window
        under the cursor."""
        x, y = (float(point[0]), float(point[1]))
        if self.quartz is not None:
            Q = self.quartz
            e = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (x, y),
                                          Q.kCGMouseButtonLeft)
            Q.CGEventPost(Q.kCGHIDEventTap, e)
        else:
            try:
                self.pag.moveTo(x, y, _pause=False)
            except Exception as exc:
                print(f"WARN: could not move the cursor: {exc}")
                return
        self.pointer.note_external_move((x, y))

    def _focus_screen(self):
        """Put the cursor on the screen the gesture is aimed at, so scrolling
        and Space switching act on that screen.  One screen: never any of
        this, which keeps single-display behaviour exactly as it was."""
        if self.layout.count < 2:
            return
        now = time.monotonic()
        if now - self._focus_checked < FOCUS_CHECK_SECONDS:
            return
        self._focus_checked = now
        aim = self.pointer.target_pixel()
        if aim is None:
            aim = self.pointer.last_aim_pixel()
        if aim is None:
            return
        want = self.layout.screen_of(aim)
        here = self.layout.screen_of(self._raw_cursor())
        if want != here:
            self._warp(self.layout.center(want))

    def submit(self, name, n=1):
        # Scroll goes straight to the animator (it has its own thread).
        if name == "scroll_drag":
            self.scroller.drag(n * SCROLL_PX_PER_PALM * SCROLL_DIRECTION)
        elif name == "scroll_fling":
            self.scroller.fling(n * SCROLL_PX_PER_PALM * FLING_GAIN * SCROLL_DIRECTION)
        elif name in ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up"):
            self.pointer.handle(name, n)
        elif name == "display_step":
            self.step_display(n)
        else:
            self.q.put((name, n))

    def _worker(self):
        while True:
            name, n = self.q.get()
            try:
                self._do(name, n)
            except Exception as exc:          # never let the worker die
                print(f"WARN: action {name} failed: {exc}")

    def _do(self, name, n):
        if name.startswith("pause"):
            return
        if name == "dictation":
            self._toggle_dictation()
            return
        if name in ("dictation_hold_start", "dictation_hold_end"):
            self._dictation_hold(name == "dictation_hold_start")
            return
        if name == "lock" and OS_NAME == "Darwin":
            self._lock_screen()
            return
        if name == "wake":
            self._wake_display()
            return
        if name in MEDIA_KEYS:
            pag_key, nx = MEDIA_KEYS[name]
            for _ in range(n):
                if self.appkit is not None:
                    self._mac_media_key(nx)
                elif OS_NAME == "Darwin" and name != "play_pause":
                    self._mac_volume_fallback(name)
                else:
                    self.pag.press(pag_key)
            return
        keys = self.bindings.get(name)
        if not keys:
            return
        if name in APP_SHORTCUTS and self.quartz is not None:
            # pyautogui leaves the Command flag off the key event itself.
            # Apps read the flag, so Cmd+Z arrived as a plain "z", and
            # Spotlight only opened some of the time.
            shortcuts.tap(shortcuts.from_legacy("+".join(keys), "Darwin"))
            return
        if name in FOCUS_SCREEN_ACTIONS:
            # Space, Mission Control and App windows belong to the screen the
            # cursor is on, so make sure that is the screen we mean.
            self._focus_screen()
        # Real key presses: each modifier goes down, then the key, then
        # everything comes back up.  macOS only fires Space switching
        # (Ctrl+Arrow) when Control is actually held, not just flagged.
        self.pag.hotkey(*[PYAUTOGUI_NAMES.get(k, k) for k in keys], interval=0.01)

    def _lock_screen(self):
        """Lock the Mac. A synthetic Ctrl+Cmd+Q is ignored by the system, so
        call the same lock the Apple menu uses; fall back to the shortcut."""
        try:
            import ctypes
            login = ctypes.CDLL("/System/Library/PrivateFrameworks/"
                                "login.framework/Versions/Current/login")
            login.SACLockScreenImmediate()
        except Exception as exc:
            print(f"WARN: lock via login.framework failed ({exc}); trying shortcut")
            self.pag.hotkey("ctrl", "command", "q", interval=0.01)

    def _wake_display(self):
        """Turn the display back on (lock screen stays locked)."""
        if OS_NAME == "Darwin":
            # -u declares user activity, which turns a sleeping display on.
            subprocess.Popen(["caffeinate", "-u", "-t", "2"])
        elif OS_NAME == "Windows":
            self._wake_display_windows()

    def _wake_display_windows(self):
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        # Reset the display idle timer, ask the monitors to power on, and
        # nudge the mouse: which of these lights a sleeping screen differs
        # between Windows versions and drivers.
        kernel32.SetThreadExecutionState(0x00000001 | 0x00000002)  # SYSTEM | DISPLAY
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        user32.SendMessageTimeoutW(0xFFFF, 0x0112, 0xF170, -1,   # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER on
                                   0x0002, 500, None)            # SMTO_ABORTIFHUNG
        user32.mouse_event(0x0001, 0, 1, 0, 0)                   # MOUSEEVENTF_MOVE
        user32.mouse_event(0x0001, 0, -1, 0, 0)

    # --- dictation -------------------------------------------------------
    # mode: "apple" (Apple Dictation, macOS), "winvoice" (Windows Voice
    # Typing, Win+H) or "shortcut" (tap the recorded dictation_toggle, for
    # Wispr Flow and the like).  dictation_ptt is an optional recorded
    # push-to-talk key, held while the hand is by the head.
    dictation_mode = "winvoice" if OS_NAME == "Windows" else "apple"
    dictation_toggle = None
    dictation_ptt = None
    _apple_dictating = False       # our guess, only used when the menu is no help
    _ptt_held = None               # the push-to-talk shortcut now pressed, if any
    _hold_toggled = False          # push-to-talk without a key: we started it
    _hold_lock = threading.Lock()

    # Menu titles that mean Start / Stop Dictation (en, de, pt, es, fr).
    DICTATION_WORDS = ("dictation", "diktat", "ditado", "dictado", "dictée")
    DICTATION_STOP_WORDS = ("stop", "beenden", "parar", "interromper",
                            "detener", "arrêter", "arreter")

    def _toggle_dictation(self):
        """Start or stop dictation with whichever tool the user picked."""
        mode = self.dictation_mode
        if mode == "shortcut":
            if shortcuts.tap(self.dictation_toggle):
                print(f"dictation: sent {self.dictation_toggle['label']}")
            else:
                print("WARN: dictation shortcut is not set or could not be sent "
                      "(record one from the menu > Dictation)")
        elif mode == "winvoice" and OS_NAME == "Windows":
            self.pag.hotkey("win", "h")
            print("dictation: toggled Windows Voice Typing (win+h)")
        elif mode == "apple" and OS_NAME == "Darwin":
            self._apple_toggle()

    def _dictation_hold(self, down):
        """Push-to-talk (hang loose by the head): down=True when the hand
        arrives, False when it leaves.  Holds the recorded push-to-talk key;
        with none recorded, toggles dictation on at start and off at end."""
        with self._hold_lock:
            ptt = self.dictation_ptt
            if self.dictation_mode == "shortcut" and shortcuts.is_valid(ptt):
                if down and not self._ptt_held:
                    if shortcuts.hold(ptt, True):
                        self._ptt_held = ptt
                elif not down and self._ptt_held:
                    shortcuts.hold(self._ptt_held, False)
                    self._ptt_held = None
                return
            if self._ptt_held and not down:     # the key was changed while held
                shortcuts.hold(self._ptt_held, False)
                self._ptt_held = None
                return
            if down == self._hold_toggled:
                return              # already on, or never started
            self._hold_toggled = down
        self._toggle_dictation()

    def release_dictation(self):
        """Let go of a held push-to-talk key (or stop dictation we started
        for it).  The apps call this on pause, off and quit, so a key is
        never left pressed when the hand can no longer let go."""
        if self._ptt_held or self._hold_toggled:
            self._dictation_hold(False)

    def _apple_toggle(self):
        """Apple Dictation: press Edit > Start Dictation, or Stop Dictation
        while it runs.  The menu title tells which, so this stays right when
        dictation was stopped some other way."""
        if self.appkit is None:
            return
        try:
            import ApplicationServices as AS
        except ImportError:
            print("WARN: dictation needs pyobjc ApplicationServices")
            return
        app = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        name = app.localizedName()

        def attr(el, key):
            err, val = AS.AXUIElementCopyAttributeValue(el, key, None)
            return val if err == 0 else None

        bar = attr(AS.AXUIElementCreateApplication(app.processIdentifier()),
                   AS.kAXMenuBarAttribute)
        tops = (attr(bar, AS.kAXChildrenAttribute) or []) if bar is not None else []
        for top in tops:
            for menu in attr(top, AS.kAXChildrenAttribute) or []:
                for item in attr(menu, AS.kAXChildrenAttribute) or []:
                    title = str(attr(item, AS.kAXTitleAttribute) or "").lower()
                    if not (any(w in title for w in self.DICTATION_WORDS)
                            and attr(item, AS.kAXEnabledAttribute)):
                        continue
                    stopping = any(w in title for w in self.DICTATION_STOP_WORDS)
                    err = AS.AXUIElementPerformAction(item, AS.kAXPressAction)
                    if stopping and err != 0:
                        shortcuts.tap(shortcuts.escape())
                    self._apple_dictating = not stopping
                    print(f"dictation: pressed '{title}' in {name}")
                    return
        if self._apple_dictating:           # no menu item to read: trust our guess
            self._apple_dictating = False
            shortcuts.tap(shortcuts.escape())
            print("dictation: stopped Apple Dictation (esc)")
            return
        print(f"dictation: no Dictation menu item in {name} "
              "(is Dictation on in System Settings > Keyboard?)")

    def _mac_media_key(self, code):
        A, Q = self.appkit, self.quartz
        for down in (True, False):
            e = A.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), 0xA00 if down else 0xB00, 0, 0, 0, 8,
                (code << 16) | ((0xA if down else 0xB) << 8), -1)
            Q.CGEventPost(0, e.CGEvent())

    @staticmethod
    def _mac_volume_fallback(name):
        sign = "+" if name == "volume_up" else "-"
        script = (f"set v to (output volume of (get volume settings)) {sign} 6\n"
                  "if v > 100 then set v to 100\nif v < 0 then set v to 0\n"
                  "set volume output volume v")
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)


class PointerAnimator:
    """Moves the real cursor at 120 Hz toward the target the engine sets at
    camera rate, and performs clicks / drags in order on the same thread.

    The engine speaks in 0..1; which pixels that means depends on the display
    mode: one screen (the one under the cursor) or every screen (their union).
    The target is kept normalized and only converted when it is posted, so
    plugging in a display or rearranging the desk never teleports the cursor,
    and crossing from one screen to the next is just more distance to
    smooth through."""

    def __init__(self, quartz, pag, layout=None, cursor_pos=None):
        self.Q, self.pag = quartz, pag
        self.layout = layout or dpy.DisplayLayout.fallback(pag.size())
        self.cursor_pos = cursor_pos or (lambda: tuple(pag.position()))
        self.mode = DISPLAY_MODE_CURRENT
        self.display = None
        self.rect = self.layout.map_rect(self.mode)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.target = None        # pixels, in the global desktop
        self.target_n = None      # 0..1, straight from the engine
        self.last_aim = None      # last target, kept after the gesture ends
        self.pos = None
        self.button_down = False
        self.last_posted = None
        self.actions = deque()
        threading.Thread(target=self._run, daemon=True).start()

    # --- screens ---
    def set_layout(self, layout):
        with self.lock:
            self.layout = layout
            self.rect = layout.map_rect(self.mode, self.display)
            self._update_target()

    def set_mode(self, mode):
        with self.lock:
            self.mode = (mode if mode in (DISPLAY_MODE_CURRENT, DISPLAY_MODE_ALL)
                         else DISPLAY_MODE_CURRENT)
            if self.mode == DISPLAY_MODE_ALL:
                self.display = None
            elif self.display is None:
                self.display = self.layout.screen_of(self.pos or self.cursor_pos())
            self.rect = self.layout.map_rect(self.mode, self.display)
            self._update_target()

    def focus_display(self, index, landing=None):
        """Next point gesture aims at this screen, even if the cursor is
        still somewhere else.  With a landing spot (0..1) the aim is set
        there on the new screen, so the cursor does not first go to where
        the old spot would map and then glide across."""
        with self.lock:
            self.display = index
            if self.mode != DISPLAY_MODE_ALL:
                self.rect = self.layout.map_rect(self.mode, index)
                if landing is not None:
                    self.target_n = (min(1.0, max(0.0, landing[0])),
                                     min(1.0, max(0.0, landing[1])))
                self._update_target()

    def cursor_position(self):
        """Where the cursor really is now, or None while it is ours."""
        if self.pos is not None:
            return self.pos
        try:
            return tuple(self.cursor_pos())
        except Exception:
            return None

    def target_pixel(self):
        """Where the hand is aiming, or None when the hand is not pointing."""
        with self.lock:
            return self.target

    def last_aim_pixel(self):
        """Where the hand was aiming the last time it pointed.  Kept after
        the gesture ends, so a scroll that follows a point still knows which
        screen it belongs to."""
        with self.lock:
            return self.last_aim

    def note_external_move(self, point):
        """Something else moved the cursor (a focus warp, the real mouse):
        accept it instead of dragging the cursor back."""
        with self.lock:
            self.pos = (float(point[0]), float(point[1]))
            self.last_posted = self.pos

    def _update_target(self):
        if self.target_n is None:
            self.target = None
        else:
            self.target = self._to_px(self.target_n)
            self.last_aim = self.target

    def _to_px(self, n):
        # The engine's 0..1 in the target rect, padded off the edges:
        # pyautogui's fail-safe trips on corners and the cursor should not
        # stick on a bezel.
        if self.mode == DISPLAY_MODE_ALL and self.layout.count > 1:
            # The box spans the desk as arranged in System Settings; points
            # in the dead area next to a shorter screen slide onto its edge.
            return dpy.clamp_to_nearest(dpy.normalized_to_point(n, self.rect),
                                        self.layout.rects)
        return dpy.normalized_to_rect(n, self.rect)

    def handle(self, name, arg):
        with self.lock:
            if name == "pointer_move":
                if self.target_n is None:
                    # Start of a gesture: whatever screen the cursor is on is
                    # the one this gesture belongs to.
                    self.display = self.layout.screen_of(self.cursor_position())
                    self.rect = self.layout.map_rect(self.mode, self.display)
                self.target_n = (min(1.0, max(0.0, arg[0])),
                                 min(1.0, max(0.0, arg[1])))
                self._update_target()
                if self.pos is None:
                    x, y = self.cursor_pos()
                    self.pos = (float(x), float(y))
            elif name == "pointer_end":
                # The gesture ended with the button still down (paused, the
                # mouse control was switched off, the pointer mode changed
                # or the app is quitting).  Let the button go, or it stays
                # stuck down and the next click becomes a double click.
                # The release is queued, so it goes out after the press.
                # Play the queue forward: a release already queued (the
                # usual end of a drag) means there is nothing left to let go.
                held = self.button_down
                for a in self.actions:
                    if a[0] in ("mouse_down", "mouse_up"):
                        held = a[0] == "mouse_down"
                if held:
                    at = self.pos or self.target or self.cursor_position()
                    if at is not None:
                        self.actions.append(("mouse_up", at, 1))
                self.target = None
                self.target_n = None
                self.pos = None
            elif name == "click":
                pos, count = arg
                self.actions.append(("click", self._to_px(pos), count))
            elif name in ("mouse_down", "mouse_up"):
                self.actions.append((name, self._to_px(arg) if arg else None, 1))
        self.wake.set()

    def _run(self):
        tick = 1.0 / SCROLL_TICK_HZ
        last = time.perf_counter()
        while True:
            with self.lock:
                idle = self.target is None and not self.actions
            if idle:
                self.wake.wait()
                self.wake.clear()
                last = time.perf_counter()
                continue
            time.sleep(tick)
            now = time.perf_counter()
            dt, last = now - last, now
            with self.lock:
                actions = list(self.actions)
                self.actions.clear()
                # The press is out of the queue and on its way, so the
                # button counts as down from here on: a pointer_end that
                # comes in now has to let it go again.
                if any(a[0] == "mouse_down" for a in actions):
                    self.button_down = True
                tgt, pos = self.target, self.pos
                if tgt is not None and pos is not None:
                    k = 1.0 - math.exp(-dt / CURSOR_SMOOTH_SECONDS)
                    pos = (pos[0] + (tgt[0] - pos[0]) * k, pos[1] + (tgt[1] - pos[1]) * k)
                    self.pos = pos
            try:
                for kind, at, count in actions:
                    at = at or pos
                    if kind == "click":
                        self._mouse("move", at)
                        self._mouse("down", at, count)
                        self._mouse("up", at, count)
                        with self.lock:
                            self.pos = at
                    elif kind == "mouse_down":
                        self._mouse("down", at)
                        self.button_down = True
                    else:
                        self._mouse("up", at)
                        self.button_down = False
                # Only post when the cursor actually moves, so a still hand
                # never pins the cursor and the real mouse stays usable.
                if tgt is not None and pos is not None and (
                        self.last_posted is None
                        or math.hypot(pos[0] - self.last_posted[0],
                                      pos[1] - self.last_posted[1]) > 0.3):
                    self._mouse("drag" if self.button_down else "move", pos)
                    self.last_posted = pos
            except Exception as exc:
                print(f"WARN: pointer failed: {exc}")

    def _mouse(self, kind, at, count=1):
        x, y = at
        if self.Q is not None:
            Q = self.Q
            etype = {"move": Q.kCGEventMouseMoved, "drag": Q.kCGEventLeftMouseDragged,
                     "down": Q.kCGEventLeftMouseDown, "up": Q.kCGEventLeftMouseUp}[kind]
            e = Q.CGEventCreateMouseEvent(None, etype, (x, y), Q.kCGMouseButtonLeft)
            if kind in ("down", "up"):
                # Click state 2 makes macOS see a real double-click.
                Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, count)
            Q.CGEventPost(Q.kCGHIDEventTap, e)
        elif kind in ("move", "drag"):
            self.pag.moveTo(x, y, _pause=False)
        elif kind == "down":
            self.pag.mouseDown(x, y, _pause=False)
        else:
            self.pag.mouseUp(x, y, _pause=False)


class ScrollAnimator:
    """Smooth pixel scrolling with momentum, on its own 120 Hz thread.

    drag(px):  the hand moved; the motion is spread over a few ms so 30 fps
               camera steps don't feel steppy.  Dragging against a glide
               stops it, like touching a trackpad.
    fling(v):  start (or boost) a glide at v px/s that decays exponentially.
    Negative px = scroll down (content moves up).
    before_post():  called before the pixels go out, so the Dispatcher can
                put the cursor on the right screen first."""

    def __init__(self, quartz, pag, before_post=None):
        self.Q, self.pag = quartz, pag
        self.before_post = before_post
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.pending = 0.0
        self.velocity = 0.0
        self.frac = 0.0
        self.line_acc = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def drag(self, px):
        with self.lock:
            if self.velocity and (px > 0) != (self.velocity > 0):
                self.velocity = 0.0
            self.pending += px
        self.wake.set()

    def fling(self, v):
        with self.lock:
            if self.velocity and (v > 0) == (self.velocity > 0):
                v += 0.6 * self.velocity          # repeated flicks stack
            self.velocity = max(-MOMENTUM_MAX_PX_S, min(MOMENTUM_MAX_PX_S, v))
        self.wake.set()

    def _run(self):
        tick = 1.0 / SCROLL_TICK_HZ
        last = time.perf_counter()
        while True:
            with self.lock:
                idle = abs(self.pending) < 0.5 and self.velocity == 0.0
            if idle:
                self.wake.wait()
                self.wake.clear()
                last = time.perf_counter()
            time.sleep(tick)
            now = time.perf_counter()
            dt, last = now - last, now
            with self.lock:
                out = self.pending * (1.0 - math.exp(-dt / DRAG_SMOOTH_SECONDS))
                self.pending -= out
                out += self.velocity * dt
                self.velocity *= math.exp(-dt / MOMENTUM_TAU_SECONDS)
                if abs(self.velocity) < MOMENTUM_MIN_PX_S:
                    self.velocity = 0.0
                self.frac += out
                n = int(self.frac)
                self.frac -= n
            if n:
                try:
                    self._post(n)
                except Exception as exc:
                    print(f"WARN: scroll failed: {exc}")

    def _post(self, px):
        if self.before_post is not None:
            self.before_post()
        if self.Q is not None:
            Q = self.Q
            e = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 1, px)
            Q.CGEventSetIntegerValueField(e, Q.kCGScrollWheelEventIsContinuous, 1)
            Q.CGEventPost(Q.kCGHIDEventTap, e)
        else:
            # No pixel scrolling available: fall back to whole lines.
            self.line_acc += px / LINE_PX
            lines = int(self.line_acc)
            if lines:
                self.line_acc -= lines
                self.pag.scroll(lines)


# =============================================================================
# Preview window helpers
# =============================================================================

def set_always_on_top_macos(window_title, level=1000):
    """macOS-only: float the OpenCV preview window above other apps via
    System Events.  Requires Accessibility permission for the parent app.
    Tries each likely Python process name once; returns True on success."""
    proc_names = ("Python3", "Python", "python3", "python")
    last_err = ""
    for proc in proc_names:
        script = (
            'tell application "System Events"\n'
            '  set successFlag to false\n'
            f'  repeat with p in (every process whose name is "{proc}")\n'
            '    repeat with w in (every window of p)\n'
            f'      if name of w contains "{window_title}" then\n'
            f'        set level of w to {level}\n'
            '        set successFlag to true\n'
            '        exit repeat\n'
            '      end if\n'
            '    end repeat\n'
            '    if successFlag then exit repeat\n'
            '  end repeat\n'
            '  return successFlag\n'
            'end tell\n'
        )
        try:
            result = subprocess.run(["osascript", "-e", script],
                                    capture_output=True, text=True, timeout=1)
        except Exception as exc:
            last_err = f"osascript failed: {exc}"
            continue
        if result.returncode == 0 and (result.stdout or "").strip().lower() == "true":
            return True
        if result.stderr:
            last_err = result.stderr.strip().splitlines()[-1]
    if last_err:
        print(f"WARN: could not pin preview window: {last_err}")
    return False


HELP_LINES_MAC = (
    "open/flat swipe -> <-   prev / next Space" if NATURAL_SWIPE
    else "open/flat swipe <- ->   prev / next Space",
    "open hand swipe up      Mission Control",
    "open hand swipe down    minimize window",
    "2 fingers down / up     scroll (gas pedal)"
    if SCROLL_MODE == "joystick" else "2 fingers move / flick  scroll (glides)",
    "2 fingers swipe -> <-   back / forward",
    "point index finger      move cursor",
    "pinch while pointing    click (x2 / hold=drag)",
    "OK sign + twist         volume",
    "thumbs up (hold)        play / pause",
    "hang loose (hold)       dictation on / off",
    "thumbs down (hold)      undo (delete dictated text)",
    "open -> gather tips     Spotlight",
    "wave (short strokes)    lock screen; again to wake",
    "rock horns (hold)       pause / resume gestures",
    "key t: test Space switch (no gesture)",
)
HELP_LINES_WIN = (
    "open/flat swipe -> <-   prev / next desktop" if NATURAL_SWIPE
    else "open/flat swipe <- ->   prev / next desktop",
    "open hand swipe up      Task View",
    "open hand swipe down    show desktop",
    "2 fingers down / up     scroll (gas pedal)"
    if SCROLL_MODE == "joystick" else "2 fingers move / flick  scroll (glides)",
    "2 fingers swipe -> <-   back / forward",
    "point index finger      move cursor",
    "pinch while pointing    click (x2 / hold=drag)",
    "OK sign + twist         volume",
    "thumbs up (hold)        play / pause",
    "hang loose (hold)       dictation on / off",
    "thumbs down (hold)      undo (delete dictated text)",
    "open -> gather tips     Start menu",
    "wave (short strokes)    lock screen; again to wake",
    "rock horns (hold)       pause / resume gestures",
    "key t: test desktop switch (no gesture)",
)
HELP_LINES = HELP_LINES_WIN if OS_NAME == "Windows" else HELP_LINES_MAC

# What an action is called in the preview and in the notifications.  The
# names follow the OS: Windows has virtual desktops and Task View, not
# Spaces and Mission Control.
ACTION_LABELS_MAC = {
    "space_left": "SPACE <-", "space_right": "SPACE ->",
    "display_step": "NEXT DISPLAY",
    "overview": "MISSION CONTROL", "app_windows": "MINIMIZE",
    "close_overview": "CLOSE OVERVIEW", "back": "BACK", "forward": "FORWARD",
    "launcher": "SPOTLIGHT", "lock": "LOCK SCREEN", "wake": "WAKE SCREEN", "volume_up": "VOLUME +", "volume_down": "VOLUME -",
    "play_pause": "PLAY / PAUSE", "dictation": "DICTATION", "dictation_hold_start": "TALK", "dictation_hold_end": "TALK END", "undo": "UNDO", "scroll_drag": "SCROLL", "scroll_fling": "FLICK",
    "arrow_left": "ARROW <-", "arrow_right": "ARROW ->",
    "pause_on": "GESTURES PAUSED", "pause_off": "GESTURES ON",
    "click": "CLICK", "mouse_down": "DRAG", "mouse_up": "DROP",
}
ACTION_LABELS_WIN = {
    "space_left": "DESKTOP <-", "space_right": "DESKTOP ->",
    "overview": "TASK VIEW", "app_windows": "SHOW DESKTOP",
    "close_overview": "CLOSE TASK VIEW", "back": "BACK", "forward": "FORWARD",
    "launcher": "START MENU", "lock": "LOCK SCREEN", "wake": "WAKE SCREEN", "volume_up": "VOLUME +", "volume_down": "VOLUME -",
    "play_pause": "PLAY / PAUSE", "dictation": "DICTATION", "dictation_hold_start": "TALK", "dictation_hold_end": "TALK END", "undo": "UNDO", "scroll_drag": "SCROLL", "scroll_fling": "FLICK",
    "arrow_left": "ARROW <-", "arrow_right": "ARROW ->",
    "pause_on": "GESTURES PAUSED", "pause_off": "GESTURES ON",
    "click": "CLICK", "mouse_down": "DRAG", "mouse_up": "DROP",
}
ACTION_LABELS = (ACTION_LABELS_WIN if OS_NAME == "Windows" else ACTION_LABELS_MAC)


# =============================================================================
# Main loop
# =============================================================================

def main():
    import cv2
    import mediapipe as mp

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                           model_complexity=MODEL_COMPLEXITY,
                           min_detection_confidence=0.6,
                           min_tracking_confidence=0.5)
    face_tracker = FaceTracker(mp.solutions.face_detection)
    engine = GestureEngine()
    dispatcher = Dispatcher()
    engine.can_step_display = dispatcher.can_step

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    print(f"Detected OS : {OS_NAME}")
    for line in HELP_LINES:
        print("  " + line)
    print("Keys: q quit, p pause, h help.\n")

    show_help = SHOW_HELP_AT_START
    last_action, last_action_time = "", -1e9
    last_console = None
    topmost_attempted = False
    frame_count = 0
    font = cv2.FONT_HERSHEY_SIMPLEX

    def text(img, s, y, scale=0.5, color=(220, 220, 220), thick=1, x=10):
        # Drop shadow with the SAME thickness: OpenCV's letter spacing
        # depends on thickness, so a thicker outline pass would not line up
        # with the text and the letters would look doubled.
        cv2.putText(img, s, (x + 1, y + 1), font, scale, (0, 0, 0), thick, cv2.LINE_AA)
        cv2.putText(img, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                print("WARN: failed to read frame from camera")
                break
            # Timestamp at capture, before processing jitter.
            now = time.monotonic()
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = hands.process(rgb)
            face = face_tracker.update(rgb, w, h, now)

            if results.multi_hand_landmarks:
                hl = results.multi_hand_landmarks[0]
                mp_drawing.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)
                pts = [(p.x * w, p.y * h) for p in hl.landmark]
                events = engine.update(pts, w, h, now, face=face)
                if face is not None and engine.ptt_active:
                    cv2.rectangle(frame, (int(face[0]), int(face[1])),
                                  (int(face[2]), int(face[3])), (0, 255, 0), 1)
                if engine.pose == "point":
                    # Show the area that maps to the whole screen.
                    x0, y0, x1, y1 = POINTER_BOX
                    cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                                  (int(x1 * w), int(y1 * h)), (0, 255, 255), 1)
                    pcx = sum(pts[i][0] for i in (0, 5, 9, 13, 17)) / 5
                    pcy = sum(pts[i][1] for i in (0, 5, 9, 13, 17)) / 5
                    cv2.circle(frame, (int(pcx), int(pcy)), 7,
                               (0, 0, 255) if engine.pinched else (0, 255, 255), -1)
                elif engine.ema_c:
                    cv2.circle(frame, (int(engine.ema_c[0]), int(engine.ema_c[1])),
                               6, (0, 255, 255), -1)
            else:
                events = engine.no_hand(now)
            events = dispatcher.while_locked(events, now)

            for name, n in events:
                dispatcher.submit(name, n)
                if name in ("pointer_move", "pointer_end"):
                    continue
                label = ACTION_LABELS.get(name, name)
                if name.startswith("scroll"):
                    label += " down" if n * SCROLL_DIRECTION < 0 else " up"
                elif name == "click" and n[1] == 2:
                    label = "DOUBLE CLICK"
                elif isinstance(n, int) and n > 1:
                    label += f" x{n}"
                last_action, last_action_time = label, now
                if name != "scroll_drag":
                    print(f"-> {label}")

            # --- HUD ---
            status = "PAUSED" if engine.paused else "ACTIVE"
            text(frame, f"{status}  pose: {engine.pose}", 25, 0.6,
                 (80, 80, 255) if engine.paused else (255, 255, 255), 2)
            if now - last_action_time < ACTION_FLASH_SECONDS:
                text(frame, last_action, 55, 0.8, (0, 255, 0), 2)
            elif engine.ptt_active:
                text(frame, "TALK", 55, 0.8, (0, 255, 0), 2)
            elif engine.pose in ("open", "flat", "two") and not engine.armed:
                text(frame, "settle hand to re-arm", 55, 0.55, (0, 200, 255))
            d = engine.debug
            if d and results.multi_hand_landmarks:
                text(frame, f"palm={d['palm']:4.0f}px ({d['mpalm']:.0f})  spread={d['spread']:.2f}"
                            f"  pinch={d['pinch']:.2f}  raw={d['raw']}", 80)
                if "swipe" in d:
                    sx, sy, sv = d["swipe"]
                    text(frame, f"dx={sx:+5.1f} dy={sy:+5.1f} palms  v={sv:4.1f}/s", 100)
                if "pointer" in d and engine.pose == "point":
                    (cx_, cy_), pinched, dragging = d["pointer"]
                    state = "DRAG" if dragging else ("PINCH" if pinched else "move")
                    text(frame, f"cursor {cx_:.2f},{cy_:.2f}  {state}", 120,
                         0.5, (0, 255, 255) if pinched else (220, 220, 220))
                if "knob" in d and engine.pose == "ok":
                    text(frame, f"knob {d['knob']:+5.1f} / {VOLUME_DEG_PER_STEP:.0f} deg", 120)
            if show_help:
                y0 = h - 20 - 18 * len(HELP_LINES)
                overlay = frame.copy()
                cv2.rectangle(overlay, (5, y0 - 18), (330, h - 28), (0, 0, 0), -1)
                frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)
                for i, line in enumerate(HELP_LINES):
                    text(frame, line, y0 + 18 * i, 0.45, (230, 230, 230))
            text(frame, "q quit  p pause  h help", h - 10, 0.45, (200, 200, 200))

            cv2.imshow(WINDOW_TITLE, frame)

            console = f"pose: {engine.pose}{' (paused)' if engine.paused else ''}"
            if console != last_console:
                print(console)
                last_console = console

            # Pin the preview window on top once, shortly after it appears.
            if ALWAYS_ON_TOP and not topmost_attempted and frame_count == 30:
                try:
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_TOPMOST, 1)
                except cv2.error:
                    pass
                if OS_NAME == "Darwin" and not set_always_on_top_macos(WINDOW_TITLE):
                    print("Note: could not pin the preview window. Grant "
                          "Accessibility permission to your terminal/IDE.")
                topmost_attempted = True
            frame_count += 1

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("p"):
                engine.paused = not engine.paused
                for name, n in engine.end_ptt():
                    dispatcher.submit(name, n)
                dispatcher.submit("pointer_end", None)
            if key == ord("h"):
                show_help = not show_help
            if key == ord("t"):
                # Test the key path without gestures: sends "next Space".
                print("-> TEST: sending next-Space shortcut")
                dispatcher.submit("space_right")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        hands.close()
        face_tracker.close()


if __name__ == "__main__":
    main()
