"""
Hand-gesture virtual desktop switcher -- robust baseline.

Three gestures, all measured in "palm units" (i.e. relative to the hand size
in the frame) so they work whether the camera is across the room or under
your chin:

  1. Horizontal swipe with four fingers extended (index, middle, ring, pinky):
       * left  -> previous space / virtual desktop
       * right -> next space / virtual desktop

  2. OK sign (thumb-index pinch) with middle/ring/pinky curled, plus a
     rotational spin:
       * clockwise         -> volume up
       * counter-clockwise -> volume down

  3. Vertical swipe with index + middle extended (thumb/ring/pinky curled):
       * up   -> scroll content down
       * down -> scroll content up

OS shortcuts fired:

  * macOS  : Ctrl+Left / Ctrl+Right      (Spaces)
             F11/F12 media keys + AppleScript (volume + native OSD)
             pyautogui.scroll()           (scroll)
  * Windows: Win+Ctrl+Left / Right       (virtual desktops)
             volumeup / volumedown media keys
             pyautogui.scroll()
  * Linux  : Ctrl+Alt+Left / Right       (generic)
             (no default volume / scroll handlers)

What this version adds over a strict-pixel baseline:

  * Palm-relative thresholds.  Distance and velocity are measured in
    fractions of the hand size, so a swipe feels the same close-up or far
    away.
  * Rotation-invariant finger extension.  dist(wrist, tip) / dist(wrist,
    PIP) instead of a raw y-delta, so the open-hand pose is recognised
    even when the hand is tilted or sideways.
  * Pose stability debounce.  A pose must persist for POSE_STABLE_FRAMES
    frames before it counts, so single-frame MediaPipe hiccups don't fire
    gestures.
  * Swipe re-arm.  After a swipe, the hand must slow down for
    REARM_STILL_SECONDS before the next one can fire -- the return stroke
    is no longer mistaken for a swipe in the opposite direction.
  * Hand-in-frame warm-up.  All 21 landmarks must be inside the frame for
    WARMUP_SECONDS before a swipe can fire, so the natural entry motion
    of bringing the hand up isn't counted as a swipe.
  * Background dispatcher thread.  OS actions (osascript, key events)
    run on a worker thread so the camera loop never stalls waiting on them.

Dependencies:
    pip install "mediapipe<0.10.10" opencv-python pyautogui

Run:
    python3 hand_desktop_switcher.py
    press 'q' in the preview window (or Ctrl+C in the terminal) to quit.

Tunable knobs live in the CONSTANTS block below.
"""

import math
import platform
import queue
import subprocess
import threading
import time
from collections import deque

import cv2
import mediapipe as mp
import pyautogui


# =============================================================================
# CONSTANTS  --  tweak these to tune behaviour
# =============================================================================

# --- Camera ---
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# --- Finger extension (rotation-invariant ratio) ---
# dist(wrist, tip) / dist(wrist, PIP).  Straight finger ~1.3, curled ~0.7.
# Same value works whether the hand is upright, sideways, or in between.
EXTENDED_RATIO = 1.12
CURLED_RATIO = 1.00

# --- Pose stability debounce ---
# A pose must persist for this many frames before it counts.  Kills single-
# frame MediaPipe hiccups.
POSE_STABLE_FRAMES = 3

# --- Smoothing ---
# Centroid EMA: higher = more responsive, lower = smoother.
EMA_ALPHA = 0.55
# Palm size EMA: much smoother -- palm size only changes with distance,
# so a noisy palm size makes every threshold wobble.
PALM_EMA_ALPHA = 0.15

# --- Hand-in-frame warm-up ---
# All 21 landmarks must be inside the frame for this long before a swipe
# can fire.  Stops "bringing the hand up" from counting as a swipe.
WARMUP_SECONDS = 0.20

# --- Swipe re-arm ---
# After a swipe, the per-frame hand speed (palm units / second) must drop
# below REARM_MAX_SPEED_PALMS for REARM_STILL_SECONDS before the next swipe
# can fire.  Without this, the return stroke fires the opposite direction.
REARM_MAX_SPEED_PALMS = 2.0
REARM_STILL_SECONDS = 0.15

# --- Four-finger horizontal swipe (palm-relative units) ---
SWIPE_BUFFER_SECONDS = 0.22
MIN_SWIPE_DISTANCE_PALMS = 0.5      # ~75 px on a 150 px palm
MIN_SWIPE_PEAK_VELOCITY_PALMS = 4.0  # ~600 px/s on a 150 px palm
MIN_SWIPE_AVG_VELOCITY_PALMS = 2.5   # ~375 px/s on a 150 px palm
SWIPE_MONOTONIC_RATIO = 0.85
SWIPE_NOISE_PALMS = 0.02            # ignore sub-noise steps in monotonicity
COOLDOWN_SECONDS = 0.75

# --- Volume knob (OK sign + rotation) ---
# Cumulative per-frame rotation tracker.  Cross threshold -> fire and
# subtract one threshold's worth.  Continuous twisting keeps firing while
# the OK sign is held; no per-fire cooldown.
SPIN_MIN_TOTAL_ANGLE_DEG = 5
SPIN_DELTA_FILTER_DEG = 0.15
SPIN_MIN_TOTAL_DEPTH = 0.025
SPIN_DEPTH_DELTA_FILTER = 0.0008
# Thumb-index tip distance as a fraction of palm size.
OK_PINCH_MAX_RATIO = 0.30
# volume change (%) = rotation (deg) * SPIN_VOLUME_PER_DEGREE
SPIN_VOLUME_PER_DEGREE = 0.20
SPIN_VOLUME_PER_DEPTH = 80

# --- Two-finger vertical scroll (palm-relative units) ---
SCROLL_BUFFER_SECONDS = 0.22
SCROLL_MIN_DISTANCE_PALMS = 0.4      # ~60 px on a 150 px palm
SCROLL_MIN_PEAK_VELOCITY_PALMS = 3.0  # ~450 px/s on a 150 px palm
SCROLL_COOLDOWN_SECONDS = 0.3
SCROLL_CLICKS_PER_PALM = 15.0        # 0.4 palm swipe -> 6 clicks
SCROLL_NOISE_PALMS = 0.02


# =============================================================================
# OS-specific shortcut mapping
# =============================================================================

OS_NAME = platform.system()

if OS_NAME == "Darwin":
    SWIPE_LEFT_KEYS = ("ctrl", "left")
    SWIPE_RIGHT_KEYS = ("ctrl", "right")
elif OS_NAME == "Windows":
    SWIPE_LEFT_KEYS = ("ctrl", "win", "left")
    SWIPE_RIGHT_KEYS = ("ctrl", "win", "right")
else:
    SWIPE_LEFT_KEYS = ("ctrl", "alt", "left")
    SWIPE_RIGHT_KEYS = ("ctrl", "alt", "right")


# =============================================================================
# MediaPipe setup
# =============================================================================

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5,
)


# =============================================================================
# Geometry helpers
# =============================================================================

TIP_IDS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIP_IDS = {"thumb": 3, "index": 6, "middle": 10, "ring": 14, "pinky": 18}


def _px(landmarks, i, w, h):
    return (landmarks[i].x * w, landmarks[i].y * h)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def palm_size_px(landmarks, w, h):
    """Hand size in pixels.  Larger of wrist->middle-knuckle and
    index->pinky-knuckle -- max-of-two keeps it stable when the hand tilts."""
    w_p = _px(landmarks, 0, w, h)
    mcp_middle = _px(landmarks, 9, w, h)
    mcp_index = _px(landmarks, 5, w, h)
    mcp_pinky = _px(landmarks, 17, w, h)
    return max(_dist(w_p, mcp_middle), _dist(mcp_index, mcp_pinky))


def finger_extension_ratio(landmarks, w, h, name):
    """Rotation-invariant extension: dist(wrist, tip) / dist(wrist, PIP).
    Straight finger ~1.3, curled ~0.7, regardless of hand orientation."""
    w_p = _px(landmarks, 0, w, h)
    tip = _px(landmarks, TIP_IDS[name], w, h)
    pip = _px(landmarks, PIP_IDS[name], w, h)
    return _dist(w_p, tip) / max(_dist(w_p, pip), 1e-6)


def hand_centroid_px(landmarks, w, h):
    xs = [lm.x * w for lm in landmarks]
    ys = [lm.y * h for lm in landmarks]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def classify_pose(landmarks, w, h, palm_px):
    """Return one of 'ok', 'four', 'two', 'none'.  Priority order:
    ok > four > two > none."""
    if palm_px <= 0:
        return "none"
    ratios = {n: finger_extension_ratio(landmarks, w, h, n)
              for n in ("index", "middle", "ring", "pinky")}
    ext = {n: r >= EXTENDED_RATIO for n, r in ratios.items()}
    curl = {n: r <= CURLED_RATIO for n, r in ratios.items()}
    pinch = _dist(_px(landmarks, TIP_IDS["thumb"], w, h),
                  _px(landmarks, TIP_IDS["index"], w, h)) / palm_px
    if (pinch <= OK_PINCH_MAX_RATIO
            and curl["middle"] and curl["ring"] and curl["pinky"]):
        return "ok"
    if ext["index"] and ext["middle"] and ext["ring"] and ext["pinky"]:
        return "four"
    if ext["index"] and ext["middle"] and curl["ring"] and curl["pinky"]:
        return "two"
    return "none"


def monotonic_ratio(buf, axis, total, noise):
    """Share of in-buffer steps along `axis` that agree in sign with
    `total`.  Returns 1.0 if there are no steps above the noise floor."""
    if len(buf) < 2:
        return 1.0
    sign = total > 0
    matching = considered = 0
    for j in range(1, len(buf)):
        step = buf[j][axis] - buf[j - 1][axis]
        if abs(step) > noise:
            considered += 1
            if (step > 0) == sign:
                matching += 1
    return matching / considered if considered else 1.0


def peak_velocity(buf, axis):
    """Max |step / dt| along `axis` over consecutive in-buffer samples."""
    peak = 0.0
    for j in range(1, len(buf)):
        dt = buf[j][-1] - buf[j - 1][-1]
        step = abs(buf[j][axis] - buf[j - 1][axis])
        if dt > 0:
            v = step / dt
            if v > peak:
                peak = v
    return peak


# =============================================================================
# macOS volume helpers
# =============================================================================

def macos_volume_delta(delta_pct):
    """Apply a signed percentage-point change to macOS volume, clamped
    to [0, 100].  Silent (no OSD).  Used as a fallback when F11/F12
    keystrokes aren't available."""
    delta_pct = max(-100.0, min(100.0, delta_pct))
    abs_d = abs(delta_pct)
    if delta_pct >= 0:
        script = (
            "set v to output volume of (get volume settings)\n"
            f"set nv to (v + {abs_d})\n"
            "if nv > 100 then set nv to 100\n"
            "set volume output volume nv\n"
        )
    else:
        script = (
            "set v to output volume of (get volume settings)\n"
            f"set nv to (v - {abs_d})\n"
            "if nv < 0 then set nv to 0\n"
            "set volume output volume nv\n"
        )
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=2)
    except Exception as exc:
        print(f"WARN: macos_volume_delta({delta_pct}) failed: {exc}")


def macos_volume_knob_with_osd(signed_pct):
    """Adjust macOS volume AND show the native volume OSD.

    The volume OSD only appears in response to a real volume key press, not
    when the volume is changed programmatically.  This function sends N F11 /
    F12 keystrokes through System Events -- each one is one macOS volume
    notch (~6.25 %) and each one flashes the OSD.

    Requires Accessibility permission for the parent process (Terminal / IDE)
    so System Events can synthesize keystrokes."""
    direction = "up" if signed_pct > 0 else "down"
    n_presses = max(1, int(round(abs(signed_pct) / 6.25)))
    key_code = 96 if direction == "up" else 97  # F12 = vol up, F11 = vol down
    script = (
        'tell application "System Events"\n'
        f'  repeat {n_presses} times\n'
        f'    keystroke (key code {key_code})\n'
        '    delay 0.05\n'
        '  end repeat\n'
        'end tell\n'
    )
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True,
                                timeout=3 + n_presses * 0.15)
        if result.returncode != 0:
            err = result.stderr.strip() or "unknown error"
            print(f"WARN: macOS volume OSD keystroke failed ({err}); "
                  f"falling back to silent set.")
            macos_volume_delta(signed_pct)
    except subprocess.TimeoutExpired:
        print("WARN: macOS volume OSD keystroke timed out; "
              "falling back to silent set.")
        macos_volume_delta(signed_pct)
    except Exception as exc:
        print(f"WARN: macos_volume_knob_with_osd failed: {exc}; "
              f"falling back to silent set.")
        macos_volume_delta(signed_pct)


# =============================================================================
# Background dispatcher
# =============================================================================

class Dispatcher:
    """Run OS actions on a worker thread so the camera loop never blocks on
    osascript or key events."""

    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, fn):
        self.q.put(fn)

    def _worker(self):
        while True:
            fn = self.q.get()
            try:
                fn()
            except Exception as exc:
                print(f"WARN: action failed: {exc}")


# =============================================================================
# State
# =============================================================================

# (cx, cy in palm units, t) accumulated while the four-finger pose is held.
pose_buffer = deque()
last_swipe_time = 0.0
ema_cx = ema_cy = None
ema_palm = None
# Previous EMA centroid for re-arm speed estimation (independent of pose).
prev_ema_c = None

# Pose stability debounce.
raw_pose = "none"
raw_pose_count = 0
active_pose = "none"

# Re-arm after a swipe.
armed = True
still_since = None

# Hand-in-frame warm-up.
ready_since = None

# Volume knob.
spin_cumulative_angle = 0.0
spin_cumulative_depth = 0.0
spin_prev_angle = None
spin_prev_depth = None
last_spin_time = 0.0

# Scroll.
scroll_buffer = deque()
last_scroll_time = 0.0

last_console_label = None


# =============================================================================
# Main loop
# =============================================================================

dispatcher = Dispatcher()

cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

print(f"Detected OS : {OS_NAME}")
print(f"Swipe LEFT  -> {SWIPE_LEFT_KEYS}")
print(f"Swipe RIGHT -> {SWIPE_RIGHT_KEYS}")
print(f"Two-finger vertical swipe -> pyautogui.scroll(N)")
if OS_NAME == "Darwin":
    print("Twist (OK + rotate) -> AppleScript volume + native OSD")
elif OS_NAME == "Windows":
    print("Twist (OK + rotate) -> volumeup / volumedown media keys")
else:
    print("Twist (OK + rotate) -> (no Linux volume handler)")
print("Press 'q' in the preview window to quit.\n")

try:
    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            print("WARN: failed to read frame from camera")
            break
        now = time.monotonic()
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = hands.process(rgb)
        rgb.flags.writeable = True

        gesture_label = "no hand"
        fired_direction = None
        fired_spin = None
        fired_scroll = None
        palm_hud = 0.0
        warmed = False

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            lm = hand_landmarks.landmark
            mp_drawing.draw_landmarks(
                frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            # Smoothed palm size (only changes with distance, so smooth hard).
            raw_palm = palm_size_px(lm, w, h)
            if ema_palm is None:
                ema_palm = raw_palm
            else:
                ema_palm = PALM_EMA_ALPHA * raw_palm + (1 - PALM_EMA_ALPHA) * ema_palm
            palm = max(ema_palm, 1.0)
            palm_hud = palm

            # Pose classification with stability debounce.
            detected = classify_pose(lm, w, h, palm)
            if detected == raw_pose:
                raw_pose_count += 1
            else:
                raw_pose, raw_pose_count = detected, 1
            if raw_pose_count >= POSE_STABLE_FRAMES and detected != active_pose:
                if active_pose == "ok":
                    spin_cumulative_angle = 0.0
                    spin_cumulative_depth = 0.0
                    spin_prev_angle = None
                    spin_prev_depth = None
                active_pose = detected
                pose_buffer.clear()
                scroll_buffer.clear()

            # Centroid EMA (in pixels, for drawing; converted to palms later).
            raw_cx, raw_cy = hand_centroid_px(lm, w, h)
            if ema_cx is None:
                ema_cx, ema_cy = raw_cx, raw_cy
            else:
                ema_cx = EMA_ALPHA * raw_cx + (1 - EMA_ALPHA) * ema_cx
                ema_cy = EMA_ALPHA * raw_cy + (1 - EMA_ALPHA) * ema_cy
            cv2.circle(frame, (int(ema_cx), int(ema_cy)), 6, (0, 255, 255), -1)

            # Warm-up: every landmark must be inside the frame.
            pts_px = [_px(lm, i, w, h) for i in range(21)]
            if all(0 <= x <= w and 0 <= y <= h for x, y in pts_px):
                if ready_since is None:
                    ready_since = now
            else:
                ready_since = None
                pose_buffer.clear()
                scroll_buffer.clear()
            warmed = (ready_since is not None
                      and now - ready_since >= WARMUP_SECONDS)

            # Re-arm: after a swipe, wait for the hand to slow down.
            # Uses the EMA centroid (in pixels), so it works regardless of
            # what pose the hand is currently in.
            if not armed and prev_ema_c is not None:
                dt_arm = now - prev_ema_c[2]
                if dt_arm > 0 and palm > 0:
                    speed_palms_s = (math.hypot(
                        ema_cx - prev_ema_c[0],
                        ema_cy - prev_ema_c[1]) / dt_arm) / palm
                    if speed_palms_s < REARM_MAX_SPEED_PALMS:
                        if still_since is None:
                            still_since = now
                        elif now - still_since >= REARM_STILL_SECONDS:
                            armed = True
                            still_since = None
                    else:
                        still_since = None
            prev_ema_c = (ema_cx, ema_cy, now)

            # --- Volume knob (OK sign + rotation) ---
            if active_pose == "ok":
                pinch_px = (
                    (lm[TIP_IDS["thumb"]].x + lm[TIP_IDS["index"]].x) * 0.5 * w,
                    (lm[TIP_IDS["thumb"]].y + lm[TIP_IDS["index"]].y) * 0.5 * h,
                )
                wrist_px = (lm[0].x * w, lm[0].y * h)
                angle = math.degrees(math.atan2(pinch_px[1] - wrist_px[1],
                                                 pinch_px[0] - wrist_px[0]))
                depth = (lm[TIP_IDS["thumb"]].z + lm[TIP_IDS["index"]].z) * 0.5
                cv2.circle(frame, (int(pinch_px[0]), int(pinch_px[1])),
                           5, (255, 255, 0), -1)
                cv2.circle(frame, (int(wrist_px[0]), int(wrist_px[1])),
                           5, (255, 0, 255), -1)
                if spin_prev_angle is not None:
                    d = angle - spin_prev_angle
                    while d > 180:
                        d -= 360
                    while d < -180:
                        d += 360
                    if abs(d) > SPIN_DELTA_FILTER_DEG:
                        spin_cumulative_angle += d
                spin_prev_angle = angle
                if spin_prev_depth is not None:
                    dd = depth - spin_prev_depth
                    if abs(dd) > SPIN_DEPTH_DELTA_FILTER:
                        spin_cumulative_depth += dd
                spin_prev_depth = depth
                if abs(spin_cumulative_angle) >= SPIN_MIN_TOTAL_ANGLE_DEG:
                    direction = "up" if spin_cumulative_angle > 0 else "down"
                    pct = abs(spin_cumulative_angle) * SPIN_VOLUME_PER_DEGREE
                    fired_spin = (direction, pct)
                    last_spin_time = now
                    sign = 1 if spin_cumulative_angle > 0 else -1
                    spin_cumulative_angle -= sign * SPIN_MIN_TOTAL_ANGLE_DEG
                elif abs(spin_cumulative_depth) >= SPIN_MIN_TOTAL_DEPTH:
                    direction = "up" if spin_cumulative_depth < 0 else "down"
                    pct = abs(spin_cumulative_depth) * SPIN_VOLUME_PER_DEPTH
                    fired_spin = (direction, pct)
                    last_spin_time = now
                    sign = 1 if spin_cumulative_depth > 0 else -1
                    spin_cumulative_depth -= sign * SPIN_MIN_TOTAL_DEPTH
            else:
                spin_cumulative_angle = 0.0
                spin_cumulative_depth = 0.0
                spin_prev_angle = None
                spin_prev_depth = None

            # --- Swipe (four-finger, horizontal) ---
            if active_pose == "four" and warmed:
                pose_buffer.append((ema_cx / palm, ema_cy / palm, now))
                cutoff = now - SWIPE_BUFFER_SECONDS
                while pose_buffer and pose_buffer[0][2] < cutoff:
                    pose_buffer.popleft()
                if (len(pose_buffer) >= 2
                        and armed
                        and now - last_swipe_time > COOLDOWN_SECONDS):
                    (x0, _, t0), (x1, _, t1) = pose_buffer[0], pose_buffer[-1]
                    dx = x1 - x0
                    dt = t1 - t0
                    if dt > 0:
                        peak_v = peak_velocity(pose_buffer, 0)
                        mono = monotonic_ratio(pose_buffer, 0, dx,
                                               SWIPE_NOISE_PALMS)
                        if (abs(dx) >= MIN_SWIPE_DISTANCE_PALMS
                                and abs(dx) / dt >= MIN_SWIPE_AVG_VELOCITY_PALMS
                                and peak_v >= MIN_SWIPE_PEAK_VELOCITY_PALMS
                                and mono >= SWIPE_MONOTONIC_RATIO):
                            fired_direction = "right" if dx > 0 else "left"

            # --- Scroll (two-finger, vertical) ---
            if active_pose == "two" and warmed:
                scroll_buffer.append((ema_cy / palm, now))
                cutoff = now - SCROLL_BUFFER_SECONDS
                while scroll_buffer and scroll_buffer[0][1] < cutoff:
                    scroll_buffer.popleft()
                if (len(scroll_buffer) >= 2
                        and now - last_scroll_time > SCROLL_COOLDOWN_SECONDS):
                    (y0, t0), (y1, t1) = scroll_buffer[0], scroll_buffer[-1]
                    dy = y1 - y0
                    dt = t1 - t0
                    if dt > 0:
                        peak_v = peak_velocity(scroll_buffer, 0)
                        mono = monotonic_ratio(scroll_buffer, 0, dy,
                                               SCROLL_NOISE_PALMS)
                        if (abs(dy) >= SCROLL_MIN_DISTANCE_PALMS
                                and peak_v >= SCROLL_MIN_PEAK_VELOCITY_PALMS
                                and mono >= SWIPE_MONOTONIC_RATIO):
                            # Inverted mapping: swipe UP -> content DOWN.
                            fired_scroll = int(round(-dy * SCROLL_CLICKS_PER_PALM))
                            scroll_buffer.clear()
        else:
            # Hand lost -- forget EMA, pose, swipe / scroll buffers, spin state.
            ema_cx = ema_cy = None
            ema_palm = None
            prev_ema_c = None
            raw_pose = "none"
            raw_pose_count = 0
            active_pose = "none"
            ready_since = None
            pose_buffer.clear()
            scroll_buffer.clear()
            spin_cumulative_angle = 0.0
            spin_cumulative_depth = 0.0
            spin_prev_angle = None
            spin_prev_depth = None

        # --- Fire ---
        if fired_direction is not None:
            last_swipe_time = time.monotonic()
            armed = False
            still_since = None
            # Inverted mapping: hand right pushes screen left.
            if fired_direction == "right":
                keys = SWIPE_LEFT_KEYS
                gesture_label = "SWIPE hand-RIGHT -> screen LEFT"
            else:
                keys = SWIPE_RIGHT_KEYS
                gesture_label = "SWIPE hand-LEFT -> screen RIGHT"
            dispatcher.submit(lambda k=keys: pyautogui.hotkey(*k))
        elif fired_spin is not None:
            direction, pct = fired_spin
            signed_pct = pct if direction == "up" else -pct
            last_spin_time = time.monotonic()
            if OS_NAME == "Darwin":
                dispatcher.submit(lambda s=signed_pct: macos_volume_knob_with_osd(s))
                gesture_label = f"TWIST {direction} {signed_pct:+.0f}%"
            elif OS_NAME == "Windows":
                key = "volumeup" if direction == "up" else "volumedown"
                n = max(1, int(round(pct / 2.0)))
                dispatcher.submit(lambda k=key, n=n: [pyautogui.press(k) for _ in range(n)])
                gesture_label = f"TWIST {direction} {signed_pct:+.0f}%"
            else:
                gesture_label = f"TWIST {direction} (no Linux volume handler)"
        elif fired_scroll is not None:
            last_scroll_time = time.monotonic()
            dispatcher.submit(lambda n=fired_scroll: pyautogui.scroll(n))
            direction = "down" if fired_scroll > 0 else "up"
            gesture_label = f"SCROLL {direction} ({fired_scroll:+d})"
        else:
            if active_pose == "four":
                gesture_label = "four fingers (tracking)"
            elif active_pose == "two":
                gesture_label = "two fingers (tracking)"
            elif active_pose == "ok":
                gesture_label = "ok sign (tracking)"
            elif results.multi_hand_landmarks:
                gesture_label = "hand seen (pose not matched)"

        # --- HUD ---
        cv2.putText(frame, f"OS: {OS_NAME}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        color = (0, 255, 0) if any(
            tag in gesture_label for tag in ("SWIPE", "TWIST", "SCROLL")
        ) else (255, 255, 255)
        cv2.putText(frame, f"Gesture: {gesture_label}",
                    (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        cv2.putText(
            frame,
            f"palm={palm_hud:.0f}px  pose={active_pose}  raw={raw_pose}({raw_pose_count})",
            (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 180), 1,
        )
        if results.multi_hand_landmarks:
            if not warmed:
                if ready_since is None:
                    warmup_str = "warm-up: hand not fully in frame"
                else:
                    left = max(0.0, WARMUP_SECONDS - (now - ready_since))
                    warmup_str = f"warm-up: {left:.2f}s"
                cv2.putText(frame, warmup_str, (10, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 220), 1)
            if not armed:
                cv2.putText(frame, "settle hand to re-arm", (10, 120),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
            if active_pose == "four" and len(pose_buffer) >= 2:
                (x0, _, t0), (x1, _, t1) = pose_buffer[0], pose_buffer[-1]
                dx_h = x1 - x0
                dt_h = t1 - t0
                peak_v = peak_velocity(pose_buffer, 0)
                avg_v = abs(dx_h) / dt_h if dt_h > 0 else 0.0
                cv2.putText(
                    frame,
                    f"dx={dx_h:+.2f}palms  avg={avg_v:.1f}/s  peak={peak_v:.1f}/s",
                    (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 180), 1,
                )
            if active_pose == "ok":
                cv2.putText(
                    frame,
                    f"spin cum={spin_cumulative_angle:+.1f}deg  "
                    f"depth={spin_cumulative_depth:+.3f}",
                    (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 180), 1,
                )
            if active_pose == "two" and len(scroll_buffer) >= 2:
                (y0, t0), (y1, t1) = scroll_buffer[0], scroll_buffer[-1]
                dy_h = y1 - y0
                dt_h = t1 - t0
                peak_v = peak_velocity(scroll_buffer, 0)
                cv2.putText(
                    frame,
                    f"scroll dy={dy_h:+.2f}palms  peak={peak_v:.1f}/s",
                    (10, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 180), 1,
                )
        cv2.putText(frame, "q: quit",
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.imshow("Hand Gesture Desktop Switcher", frame)

        if gesture_label != last_console_label:
            print(gesture_label)
            last_console_label = gesture_label

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
finally:
    cap.release()
    cv2.destroyAllWindows()
    hands.close()