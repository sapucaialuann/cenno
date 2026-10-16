"""
newMotion: hand-gesture control for macOS (Claude's version).

Gestures (all measured in "palms", i.e. relative to your hand size in the
frame, so they work whether you sit close to the camera or across the room):

  OPEN HAND (3+ fingers spread)
    * swipe right / left   -> previous / next Space        (Ctrl+Left/Right)
                              trackpad style: the hand pushes the screen.
                              Set NATURAL_SWIPE = False to flip it.
    * swipe up             -> Mission Control              (Ctrl+Up)
    * swipe down           -> App windows                  (Ctrl+Down)
                              or closes an overview a swipe opened (Esc)

  TWO FINGERS (index + middle up, ring + pinky curled)
    * move up / down       -> scroll, like dragging the page; a quick flick
                              keeps gliding and slows down (trackpad momentum)
    * swipe right / left   -> Back / Forward               (Cmd+[ / Cmd+])

  POINT (index up, middle / ring / pinky curled)
    * move                 -> moves the mouse cursor
    * pinch thumb + index  -> click; two quick pinches = double-click;
                              pinch and hold = drag (release to drop)

  OK SIGN (thumb + index tips touching, other fingers UP)
    * twist like a knob    -> volume up / down, one notch per 15 degrees,
                              with the native macOS volume HUD

  THUMBS UP (hold ~0.5 s)  -> play / pause media

  OPEN HAND -> GATHER all fingertips together ("ma che vuoi")
                           -> Spotlight                    (Cmd+Space)

  FIST (hold ~1.5 s)       -> pause / resume all gestures (safety switch)

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
  * Scrolling is pixel-smooth at 120 Hz with momentum, on its own thread.

macOS permissions
  * Camera + Accessibility for the app running Python (Terminal, iTerm, IDE).
  * System Settings -> Keyboard -> Keyboard Shortcuts -> Mission Control:
    enable "Move left/right a space", "Mission Control", "Application windows".

Dependencies:
    pip install "mediapipe<0.10.10" opencv-python pyautogui
    (pyautogui pulls in pyobjc / Quartz on macOS)

Run:
    python3 hand_desktop_switcher_claude.py
    keys in the preview window:  q quit,  p pause,  h help overlay
"""

import math
import platform
import queue
import subprocess
import threading
import time
from collections import deque


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
GATHER_MAX_SPREAD = 0.22      # all fingertips within this spread = gather
THUMB_UP_MIN_LEN = 0.60       # thumb tip to thumb MCP, palms
THUMB_UP_MARGIN = 0.15        # thumb tip must be this far above everything
POSE_STABLE_FRAMES = 3        # frames a pose must persist before it counts

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
# The cursor follows the PALM CENTRE (wrist + four knuckles): it does not
# move when you pinch, unlike the fingertip, so clicks land where you aimed,
# and averaging five landmarks cancels most of the camera jitter.
# This box of the camera frame (fractions, mirrored view) maps to the whole
# screen, so you never have to stretch to reach the screen edges.
POINTER_BOX = (0.30, 0.25, 0.75, 0.65)   # x0, y0, x1, y1
POINT_INDEX_MIN_RATIO = 0.90   # index must be at least this straight ...
POINT_STAY_MIN_RATIO = 0.82    # ... to enter pointing; once in, it may bend
                               # this far (pinching bends it) without leaving
PINCH_ON = 0.33                # thumb-index distance (palms) to press ...
PINCH_OFF = 0.50               # ... and to release (hysteresis)
PINCH_RELEASE_FRAMES = 2       # frames in a row needed to release (press is
                               # instant so quick taps are never missed)
PINCH_SMOOTH_ALPHA = 0.7       # EMA on the pinch distance (fingertips jitter)
CLICK_MAX_SECONDS = 0.25       # pinch shorter than this = click, longer = drag
DOUBLE_CLICK_SECONDS = 0.45
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
GATHER_FROM_OPEN_WINDOW = 0.6  # gather must follow an open hand within this
FIST_PAUSE_HOLD_SECONDS = 1.5  # set to 0 to disable the pause gesture

# --- HUD ---
ACTION_FLASH_SECONDS = 1.0


OS_NAME = platform.system()
DOWN_OPENS_OVERVIEW = OS_NAME == "Darwin"   # macOS App windows is an overview


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
    """Return (pose, features).  Poses: ok, gather, point, thumbs_up, fist,
    two, open, other."""
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
    if all(curl.values()):
        thumb_len = dist(pts[4], pts[2]) / palm
        highest_other = min(p[1] for i, p in enumerate(pts) if i not in (3, 4))
        if (thumb_len >= THUMB_UP_MIN_LEN
                and pts[4][1] < highest_other - THUMB_UP_MARGIN * palm):
            return "thumbs_up", feats
        return "fist", feats
    if ext["index"] and ext["middle"] and curl["ring"] and curl["pinky"]:
        return "two", feats
    if spread >= OPEN_MIN_SPREAD:
        return "open", feats
    return "other", feats


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
# Gesture engine: landmarks in, abstract events out (no OS / OpenCV calls)
# =============================================================================

class GestureEngine:
    """Feed it one frame at a time with update() / no_hand().  Returns a list
    of (event_name, count) tuples.  Event names are mapped to OS actions by
    the Dispatcher, so the engine is testable with recorded landmarks."""

    def __init__(self):
        self.paused = False
        self.last_fire = -1e9
        self.overview_until = 0.0
        self.last_open_time = -1e9
        self.last_click_time = -1e9
        self.last_click_pos = (0.0, 0.0)
        self._reset_hand()

    # --- state resets ---
    def _reset_hand(self):
        self.ema_c = None
        self.ema_palm = None
        self.ready_since = None
        self.buf = deque()
        self.armed = True
        self.still_since = None
        self.prev = None
        self.raw_pose = None
        self.raw_count = 0
        self.pose = "none"
        self.pose_since = 0.0
        self.lost_since = None
        self.latched = False
        self.debug = {}
        self._reset_pose_state()

    def _reset_pose_state(self):
        self.knob_angle = None
        self.knob_ref = None
        self.knob_started = False
        self.scroll_hist = deque()
        self.scroll_block_dir = 0
        self.scroll_block_until = 0.0
        self.scroll_still_since = None
        self.fx = self.fy = None           # cursor filters
        self.pinched = False
        self.pinch_votes = 0
        self.pinch_s = None
        self.dragging = False
        self.pinch_start = 0.0
        self.freeze_pos = None
        self.cursor_hist = deque()
        self.cursor_offset = (0.0, 0.0)
        self.cursor = None

    def no_hand(self, now):
        ev = []
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
        self._reset_hand()
        return [] if self.paused else ev

    def _scroll_release(self, now, ev):
        """Fingers 'lifted' (pose ended / hand gone): glide if moving fast."""
        recent = [v for t, v in self.scroll_hist if t >= now - FLICK_WINDOW_SECONDS]
        if recent:
            peak = max(recent, key=abs)
            if abs(peak) >= FLICK_MIN_PALMS_S:
                ev.append(("scroll_fling", peak))

    # --- main step ---
    def update(self, pts, w, h, now):
        ev = []
        raw_palm = palm_size(pts)
        self.ema_palm = raw_palm if self.ema_palm is None else (
            PALM_EMA_ALPHA * raw_palm + (1 - PALM_EMA_ALPHA) * self.ema_palm)
        shape_palm = max(self.ema_palm, 1.0)
        palm = min(shape_palm, MOTION_PALM_MAX_FRAC * w)   # motion units
        self.lost_since = None

        raw_pose, feats = classify_pose(pts, shape_palm)
        if self.pose == "point" and raw_pose != "point":
            # Sticky pointer: a pinch bends the index; don't drop a drag.
            r = feats["ratios"]
            if (max(r["middle"], r["ring"], r["pinky"]) <= CURLED_RATIO
                    and r["index"] >= POINT_STAY_MIN_RATIO):
                raw_pose = "point"
        self.debug = dict(feats, raw=raw_pose, palm=shape_palm, mpalm=palm)

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
            self.pose, self.pose_since = raw_pose, now
            self.latched = False
            self.buf.clear()
            self._reset_pose_state()
            if (raw_pose == "gather"
                    and now - self.last_open_time <= GATHER_FROM_OPEN_WINDOW):
                ev.append(("launcher", 1))
                self.latched = True
        if self.pose == "open":
            self.last_open_time = now

        # Hold gestures.
        held = now - self.pose_since
        if not self.latched:
            if (self.pose == "fist" and FIST_PAUSE_HOLD_SECONDS > 0
                    and held >= FIST_PAUSE_HOLD_SECONDS):
                self.paused = not self.paused
                ev.append(("pause_on" if self.paused else "pause_off", 1))
                self.latched = True
            elif self.pose == "thumbs_up" and held >= THUMBS_UP_HOLD_SECONDS:
                ev.append(("play_pause", 1))
                self.latched = True

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
        if self.pose == "point":
            self._pointer_step(pts, w, h, now, feats["pinch"],
                               feats["ratios"]["index"], ev)

        # Two-finger scroll: drag follows the hand, flicks glide.
        if self.pose == "two" and warmed and step is not None:
            self._scroll_step(step, now, ev)

        # Swipes (open hand: 4 directions; two fingers: horizontal nav).
        family = self.pose if self.pose in ("open", "two") else None
        cutoff = now - SWIPE_BUFFER_SECONDS
        if family and warmed:
            self.buf.append((cx, cy, now))
        while self.buf and self.buf[0][2] < cutoff:
            self.buf.popleft()
        if (family and warmed and len(self.buf) >= 2 and self.armed
                and now - self.last_fire > COOLDOWN_SECONDS):
            fired = self._eval_swipe(family, palm, now)
            if fired:
                ev.append((fired, 1))
                self.buf.clear()
                self.armed, self.still_since = False, None
                self.last_fire = now

        if len(self.buf) >= 2:
            (x0, y0, t0), (x1, y1, t1) = self.buf[0], self.buf[-1]
            if t1 > t0:
                self.debug["swipe"] = ((x1 - x0) / palm, (y1 - y0) / palm,
                                       max(abs(x1 - x0), abs(y1 - y0)) / palm / (t1 - t0))

        if self.paused:
            ev = [e for e in ev if e[0].startswith("pause")]
        return ev

    # --- pointer ---
    def _map_to_screen(self, x, y, w, h):
        x0, y0, x1, y1 = POINTER_BOX
        nx = (x / w - x0) / (x1 - x0)
        ny = (y / h - y0) / (y1 - y0)
        return (min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))

    def _pointer_step(self, pts, w, h, now, pinch, index_ratio, ev):
        if self.fx is None:
            self.fx = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
            self.fy = OneEuro(CURSOR_MIN_CUTOFF, CURSOR_BETA)
        anchor = [pts[i] for i in (0, 5, 9, 13, 17)]
        ax = self.fx(sum(p[0] for p in anchor) / 5, now)
        ay = self.fy(sum(p[1] for p in anchor) / 5, now)
        mapped = self._map_to_screen(ax, ay, w, h)
        ox, oy = self.cursor_offset
        live = (mapped[0] + ox, mapped[1] + oy)

        # Pinch state: smoothed distance, hysteresis, debounce.
        self.pinch_s = pinch if self.pinch_s is None else (
            PINCH_SMOOTH_ALPHA * pinch + (1 - PINCH_SMOOTH_ALPHA) * self.pinch_s)
        pinch = self.pinch_s
        # A press needs a clearly straight index: closing the hand into a
        # fist also brings thumb and index together, and must not click.
        want = ((pinch <= PINCH_ON and index_ratio >= POINT_INDEX_MIN_RATIO)
                if not self.pinched else not (pinch >= PINCH_OFF))
        self.pinch_votes = self.pinch_votes + 1 if want != self.pinched else 0
        flip = self.pinch_votes >= (PINCH_RELEASE_FRAMES if self.pinched else 1)
        if flip:
            self.pinch_votes = 0
        if flip and not self.pinched:
            self.pinched, self.dragging, self.pinch_start = True, False, now
            # Freeze where the cursor was just before the fingers closed.
            past = [p for t, p in self.cursor_hist if t <= now - PINCH_LOOKBACK_SECONDS]
            self.freeze_pos = past[-1] if past else (self.cursor or live)
        elif flip and self.pinched:
            self.pinched = False
            if self.dragging:
                ev.append(("mouse_up", self.cursor))
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
            ev.append(("mouse_down", self.freeze_pos))
            self._rebase_offset(mapped)

        if self.pinched and not self.dragging:
            target = self.freeze_pos                 # hold still for the click
        else:
            # Offset left over from a freeze fades out, so nothing jumps.
            k = math.exp(-(1 / 30) / CURSOR_OFFSET_DECAY_SECONDS) if not self.pinched else 1.0
            self.cursor_offset = (self.cursor_offset[0] * k, self.cursor_offset[1] * k)
            ox, oy = self.cursor_offset
            target = (min(1.0, max(0.0, mapped[0] + ox)), min(1.0, max(0.0, mapped[1] + oy)))
        self.cursor = target
        self.cursor_hist.append((now, target))
        while self.cursor_hist and self.cursor_hist[0][0] < now - 0.3:
            self.cursor_hist.popleft()
        ev.append(("pointer_move", target))
        self.debug["pointer"] = (target, self.pinched, self.dragging)

    def _rebase_offset(self, mapped):
        """Keep the cursor where it is when it un-freezes."""
        if self.cursor is not None:
            self.cursor_offset = (self.cursor[0] - mapped[0], self.cursor[1] - mapped[1])

    def _pointer_end(self, ev):
        if self.pinched and self.dragging:
            ev.append(("mouse_up", self.cursor))
        ev.append(("pointer_end", None))

    def _scroll_step(self, step, now, ev):
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

    def _eval_swipe(self, family, palm, now):
        (x0, y0, t0), (x1, y1, t1) = self.buf[0], self.buf[-1]
        dt = t1 - t0
        if dt <= 0:
            return None
        dx, dy = (x1 - x0) / palm, (y1 - y0) / palm
        if family == "open":
            dmin, vmin = MIN_SWIPE_DISTANCE_PALMS, MIN_SWIPE_VELOCITY_PALMS
        else:
            dmin, vmin = NAV_SWIPE_DISTANCE_PALMS, NAV_SWIPE_VELOCITY_PALMS
        noise = 0.03 * palm
        if abs(dx) >= abs(dy):
            if (abs(dx) >= dmin and abs(dx) / dt >= vmin
                    and monotonic_ok(self.buf, dx, 0, noise)):
                if family == "open":
                    moved_right = dx > 0
                    if NATURAL_SWIPE:
                        return "space_left" if moved_right else "space_right"
                    return "space_right" if moved_right else "space_left"
                # Like a trackpad: fingers moving right = back.
                return "back" if dx > 0 else "forward"
        elif family == "open":
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
        "overview": ("ctrl", "up"), "app_windows": ("ctrl", "down"),
        "close_overview": ("escape",),
        "back": ("cmd", "["), "forward": ("cmd", "]"),
        "launcher": ("cmd", "space"),
    },
    "Windows": {
        "space_left": ("ctrl", "win", "left"), "space_right": ("ctrl", "win", "right"),
        "overview": ("win", "tab"), "app_windows": ("win", "d"),
        "close_overview": ("escape",),
        "back": ("alt", "left"), "forward": ("alt", "right"),
        "launcher": ("win",),
    },
    "Linux": {
        "space_left": ("ctrl", "alt", "left"), "space_right": ("ctrl", "alt", "right"),
        "overview": ("ctrl", "alt", "up"), "app_windows": ("ctrl", "alt", "down"),
        "close_overview": ("escape",),
        "back": ("alt", "left"), "forward": ("alt", "right"),
        "launcher": ("win",),
    },
}
MEDIA_KEYS = {"volume_up": ("volumeup", NX_SOUND_UP),
              "volume_down": ("volumedown", NX_SOUND_DOWN),
              "play_pause": ("playpause", NX_PLAY)}
PYAUTOGUI_NAMES = {"cmd": "command", "alt": "option"} if OS_NAME == "Darwin" else {}


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
        self.scroller = ScrollAnimator(self.quartz, self.pag)
        self.pointer = PointerAnimator(self.quartz, self.pag)
        self.q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, name, n=1):
        # Scroll goes straight to the animator (it has its own thread).
        if name == "scroll_drag":
            self.scroller.drag(n * SCROLL_PX_PER_PALM * SCROLL_DIRECTION)
        elif name == "scroll_fling":
            self.scroller.fling(n * SCROLL_PX_PER_PALM * FLING_GAIN * SCROLL_DIRECTION)
        elif name in ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up"):
            self.pointer.handle(name, n)
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
        # Real key presses: each modifier goes down, then the key, then
        # everything comes back up.  macOS only fires Space switching
        # (Ctrl+Arrow) when Control is actually held, not just flagged.
        self.pag.hotkey(*[PYAUTOGUI_NAMES.get(k, k) for k in keys], interval=0.01)

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
    camera rate, and performs clicks / drags in order on the same thread."""

    def __init__(self, quartz, pag):
        self.Q, self.pag = quartz, pag
        sw, sh = pag.size()
        self.sw, self.sh = sw, sh
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.target = None
        self.pos = None
        self.button_down = False
        self.last_posted = None
        self.actions = deque()
        threading.Thread(target=self._run, daemon=True).start()

    def _to_px(self, n):
        # Stay 1 px inside the edges: pyautogui's fail-safe trips on corners.
        return (min(self.sw - 2, max(1, n[0] * self.sw)),
                min(self.sh - 2, max(1, n[1] * self.sh)))

    def handle(self, name, arg):
        with self.lock:
            if name == "pointer_move":
                self.target = self._to_px(arg)
                if self.pos is None:
                    x, y = self.pag.position()
                    self.pos = (float(x), float(y))
            elif name == "pointer_end":
                self.target = None
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
    Negative px = scroll down (content moves up)."""

    def __init__(self, quartz, pag):
        self.Q, self.pag = quartz, pag
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


HELP_LINES = (
    "open hand swipe -> <-   prev / next Space" if NATURAL_SWIPE
    else "open hand swipe <- ->   prev / next Space",
    "open hand swipe up      Mission Control",
    "open hand swipe down    App windows / close",
    "2 fingers move / flick  scroll (glides)",
    "2 fingers swipe -> <-   back / forward",
    "point index finger      move cursor",
    "pinch while pointing    click (x2 / hold=drag)",
    "OK sign + twist         volume",
    "thumbs up (hold)        play / pause",
    "open -> gather tips     Spotlight",
    "fist (hold)             pause gestures",
    "key t: test Space switch (no gesture)",
)

ACTION_LABELS = {
    "space_left": "SPACE <-", "space_right": "SPACE ->",
    "overview": "MISSION CONTROL", "app_windows": "APP WINDOWS",
    "close_overview": "CLOSE OVERVIEW", "back": "BACK", "forward": "FORWARD",
    "launcher": "SPOTLIGHT", "volume_up": "VOLUME +", "volume_down": "VOLUME -",
    "play_pause": "PLAY / PAUSE", "scroll_drag": "SCROLL", "scroll_fling": "FLICK",
    "pause_on": "GESTURES PAUSED", "pause_off": "GESTURES ON",
    "click": "CLICK", "mouse_down": "DRAG", "mouse_up": "DROP",
}


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
    engine = GestureEngine()
    dispatcher = Dispatcher()

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

            if results.multi_hand_landmarks:
                hl = results.multi_hand_landmarks[0]
                mp_drawing.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)
                pts = [(p.x * w, p.y * h) for p in hl.landmark]
                events = engine.update(pts, w, h, now)
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
            elif engine.pose in ("open", "two") and not engine.armed:
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


if __name__ == "__main__":
    main()
