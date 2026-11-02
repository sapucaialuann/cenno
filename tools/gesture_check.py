"""
Guided gesture check (developer tool).

Walks you through every Cenno gesture with on-screen prompts, records your
real hand (all 21 landmarks plus the face box, every frame) and replays the
recording through the gesture engine to report, per gesture, what fired,
what was missed and what fired by mistake.

Nothing is sent to the system: no keys, no clicks.  Switch Cenno itself off
while recording, or it will act on the gestures.

    .venv-build/bin/python tools/gesture_check.py record      # ~6 min, saves checks/<time>.json
    python3 tools/gesture_check.py natural                    # natural recording mode (no coaching)
    python3 tools/gesture_check.py report [checks/<file>.json] # replay + report (latest by default)

Each step waits until the gesture is recognised; the panel says why it is not.
Keys in the recording window:  s = skip (cannot do it),  r = redo this step,  q = stop and save.
"""

import glob
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hand_desktop_switcher as core          # noqa: E402

CHECKS_DIR = os.path.join(ROOT, "checks")
SETTINGS_PATH = os.path.expanduser("~/Library/Application Support/Cenno/settings.json")
LEAD_SECONDS = 3.0           # "get ready" before each step (recorded, not judged)

# Events that are not actions: never counted as a mistake.
NEUTRAL = {"pointer_move", "pointer_end", "display_step", "dictation_hold_end"}

# Each step: what to do, how long, which events must fire (event -> minimum
# count; "a|b" accepts either), and which extra events are fine.  Any other
# action event is a false trigger.  scroll_drag is reported as scroll_down /
# scroll_up.
STEPS = [
    dict(id="rest", seconds=5, expect={},
         prompt="Rest: hand down, out of view"),
    dict(id="open_still", seconds=5, expect={},
         prompt="Open hand, fingers spread, hold still"),
    dict(id="spotlight", seconds=14, expect={"launcher": 3},
         prompt="Spotlight x3: open hand, then bunch all fingertips together. Pause between"),
    dict(id="spotlight_face", seconds=10, expect={"launcher": 2},
         prompt="Spotlight x2 again, this time in front of your face/chin"),
    dict(id="slap_right", seconds=12, expect={"space_left": 3},
         prompt="Slap RIGHT x3: long fast sweep left -> right. Settle between"),
    dict(id="slap_left", seconds=12, expect={"space_right": 3},
         prompt="Slap LEFT x3: long fast sweep right -> left. Settle between"),
    dict(id="swipe_up", seconds=12, expect={"overview": 3},
         allow={"close_overview", "app_windows"},
         prompt="Swipe UP x3 with the open hand. Settle between"),
    dict(id="swipe_down", seconds=12, expect={"app_windows|close_overview": 3},
         prompt="Swipe DOWN x3 with the open hand. Settle between"),
    dict(id="scroll_down", seconds=8, expect={"scroll_down": 10},
         prompt="Scroll DOWN: two fingers (index+middle), then move the hand down and hold"),
    dict(id="scroll_up", seconds=8, expect={"scroll_up": 10},
         prompt="Scroll UP: two fingers, then move the hand up and hold"),
    dict(id="back_forward", seconds=12, expect={"back": 2, "forward": 2},
         allow={"scroll_down", "scroll_up"},
         prompt="Two fingers: swipe RIGHT x2 (back), then LEFT x2 (forward)"),
    dict(id="point_move", seconds=8, expect={},
         prompt="Point with the index and move the cursor around. NO pinching"),
    dict(id="point_gap", seconds=8, expect={},
         prompt="Point with a 2-3 cm gap between thumb and index. Move a bit. Do NOT touch"),
    dict(id="click", seconds=10, expect={"click": 4},
         prompt="Click x4: point, quick pinch (thumb touches index), let go. Pause between"),
    dict(id="drag", seconds=12, expect={"mouse_down": 3, "mouse_up": 3},
         prompt="Drag x3: pinch, HOLD 1 s while moving a little, let go. Pause between"),
    dict(id="volume", seconds=10, expect={"volume_up": 1, "volume_down": 1},
         prompt="Volume: OK sign (thumb+index ring), twist clockwise, then counter-clockwise"),
    dict(id="thumbs_up", seconds=8, expect={"play_pause": 2},
         prompt="Thumbs UP x2: hold ~1 s each, hand down between"),
    dict(id="thumbs_down", seconds=8, expect={"undo": 2},
         prompt="Thumbs DOWN x2: hold ~1 s each, hand down between"),
    dict(id="thumb_left", seconds=6, expect={"arrow_left": 1},
         prompt="Fist, thumb pointing LEFT, hold"),
    dict(id="thumb_right", seconds=6, expect={"arrow_right": 1},
         prompt="Fist, thumb pointing RIGHT, hold"),
    dict(id="shaka", seconds=8, expect={"dictation": 2},
         prompt="Hang loose (thumb+pinky out) in front of you x2, hold ~1 s, hand down between"),
    dict(id="shaka_ear", seconds=8, expect={"dictation_hold_start": 1},
         prompt="Hang loose by your ear like a phone, hold 2 s, then take it away"),
    dict(id="wave", seconds=8, expect={"lock": 1},
         prompt="Wave: open hand, short quick strokes side to side"),
    dict(id="horns", seconds=12, expect={"pause_on": 1, "pause_off": 1},
         prompt="Rock horns hold 1.5 s (pause), hand down, horns 1.5 s again (resume)"),
    dict(id="scratch_face", seconds=10, expect={},
         prompt="NEGATIVE: scratch your face, rub your eyes, touch your hair"),
    dict(id="chin_rest", seconds=8, expect={},
         prompt="NEGATIVE: rest your chin on your hand, shift around a little"),
    dict(id="love_sign", seconds=6, expect={},
         prompt="NEGATIVE: the I-love-you sign (thumb, index, pinky out), hold still"),
    dict(id="fidget", seconds=12, expect={},
         prompt="NEGATIVE: just be natural - relax, gesture as if talking, move around"),
]

# Steps for natural recording mode: one entry per gesture, describing what the
# gesture is for (not how to do it), with repetitions and timing.
NATURAL_STEPS = [
    dict(id="spotlight", reps=5, window=3.0, rest=1.5, expect={"launcher": 1},
         prompt="Open Spotlight search, the way that feels natural to you"),
    dict(id="spotlight_face", reps=5, window=3.0, rest=1.5, expect={"launcher": 1},
         prompt="Open Spotlight in front of your face, the way that feels natural to you"),
    dict(id="slap_right", reps=5, window=3.0, rest=1.5, expect={"space_left": 1},
         prompt="Switch to the previous Space, the way that feels natural to you"),
    dict(id="slap_left", reps=5, window=3.0, rest=1.5, expect={"space_right": 1},
         prompt="Switch to the next Space, the way that feels natural to you"),
    dict(id="swipe_up", reps=5, window=3.0, rest=1.5, expect={"overview": 1},
         allow={"close_overview", "app_windows"},
         prompt="Open Mission Control, the way that feels natural to you"),
    dict(id="swipe_down", reps=5, window=3.0, rest=1.5, expect={"app_windows|close_overview": 1},
         prompt="Close Mission Control or minimize, the way that feels natural to you"),
    dict(id="scroll_down", reps=5, window=5.0, rest=1.5, expect={"scroll_down": 1},
         prompt="Scroll down, the way that feels natural to you"),
    dict(id="scroll_up", reps=5, window=5.0, rest=1.5, expect={"scroll_up": 1},
         prompt="Scroll up, the way that feels natural to you"),
    dict(id="back_forward", reps=5, window=4.0, rest=1.5, expect={"back|forward": 1},
         allow={"scroll_down", "scroll_up"},
         prompt="Navigate back or forward, the way that feels natural to you"),
    dict(id="click", reps=5, window=2.5, rest=1.5, expect={"click": 1},
         prompt="Click, the way that feels natural to you"),
    dict(id="drag", reps=5, window=4.0, rest=1.5, expect={"mouse_down": 1, "mouse_up": 1},
         prompt="Drag, the way that feels natural to you"),
    dict(id="volume", reps=5, window=3.5, rest=1.5, expect={"volume_up|volume_down": 1},
         prompt="Adjust the volume, the way that feels natural to you"),
    dict(id="thumbs_up", reps=3, window=3.5, rest=1.5, expect={"play_pause": 1},
         prompt="Play or pause media, the way that feels natural to you"),
    dict(id="thumbs_down", reps=3, window=3.5, rest=1.5, expect={"undo": 1},
         prompt="Undo, the way that feels natural to you"),
    dict(id="thumb_left", reps=3, window=3.5, rest=1.5, expect={"arrow_left": 1},
         prompt="Navigate left with the arrow key, the way that feels natural to you"),
    dict(id="thumb_right", reps=3, window=3.5, rest=1.5, expect={"arrow_right": 1},
         prompt="Navigate right with the arrow key, the way that feels natural to you"),
    dict(id="shaka", reps=3, window=3.5, rest=1.5, expect={"dictation": 1},
         prompt="Toggle dictation, the way that feels natural to you"),
    dict(id="shaka_ear", reps=3, window=3.5, rest=1.5, expect={"dictation_hold_start": 1},
         prompt="Push-to-talk dictation by your ear, the way that feels natural to you"),
    dict(id="wave", reps=5, window=4.0, rest=1.5, expect={"lock": 1},
         prompt="Lock the screen, the way that feels natural to you"),
    dict(id="horns", reps=3, window=3.5, rest=1.5, expect={"pause_on|pause_off": 1},
         prompt="Pause or resume Cenno, the way that feels natural to you"),
    dict(id="scratch_face", reps=1, window=10.0, rest=1.5, expect={},
         prompt="Scratch your face, rub your eyes, touch your hair"),
    dict(id="chin_rest", reps=1, window=10.0, rest=1.5, expect={},
         prompt="Rest your chin on your hand, shift around a little"),
    dict(id="love_sign", reps=1, window=10.0, rest=1.5, expect={},
         prompt="Make the I-love-you sign and hold it"),
    dict(id="fidget", reps=1, window=10.0, rest=1.5, expect={},
         prompt="Just be natural - relax, gesture as if talking, move around"),
]


def user_modes():
    try:
        with open(SETTINGS_PATH) as f:
            s = json.load(f)
        return s.get("pointer_mode", core.POINTER_MODE), s.get("scroll_mode", core.SCROLL_MODE)
    except Exception:
        return core.POINTER_MODE, core.SCROLL_MODE


def cenno_tracking():
    """True while the Cenno app runs with gestures switched on.  It would
    share the camera and the CPU (halving the frame rate of both) and act
    on the gestures being checked."""
    import subprocess
    try:
        with open(SETTINGS_PATH) as f:
            if not json.load(f).get("enabled", True):
                return False
    except Exception:
        pass
    found = subprocess.run(["pgrep", "-f", "Cenno.app/Contents/MacOS/Cenno"],
                           capture_output=True)
    return found.returncode == 0


def new_engine(modes):
    eng = core.GestureEngine()
    eng.pointer_mode, eng.scroll_mode = modes
    return eng


def action_names(events):
    """Engine events -> names as the check counts them."""
    out = []
    for name, n in events:
        if name == "scroll_drag":
            out.append("scroll_down" if n * core.SCROLL_DIRECTION < 0 else "scroll_up")
        elif name in NEUTRAL:
            continue
        else:
            out.append(name)
    return out


def judge(step, counts):
    """(missing, stray): unmet expectations and false triggers."""
    missing, wanted = [], set()
    for key, need in step["expect"].items():
        names = key.split("|")
        wanted.update(names)
        got = sum(counts.get(n, 0) for n in names)
        if got < need:
            missing.append(f"{key} {got}/{need}")
    allow = wanted | set(step.get("allow", ()))
    stray = {n: c for n, c in counts.items() if n not in allow}
    return missing, stray


# =============================================================================
# Why is it not recognised?  Live explanations for the recording window
# =============================================================================

# The pose each step needs, and the kind of movement it checks.
STEP_POSE = {
    "spotlight": "gather", "spotlight_face": "gather",
    "slap_right": "open", "slap_left": "open", "swipe_up": "open", "swipe_down": "open",
    "wave": "open", "scroll_down": "two", "scroll_up": "two", "back_forward": "two",
    "point_move": "point", "point_gap": "point", "click": "point", "drag": "point",
    "volume": "ok", "thumbs_up": "thumbs_up", "thumbs_down": "thumbs_down",
    "thumb_left": "thumb_left", "thumb_right": "thumb_right",
    "shaka": "shaka", "shaka_ear": "shaka", "horns": "horns",
}
STEP_MOTION = {
    "slap_right": "slap", "slap_left": "slap", "swipe_up": "swipe", "swipe_down": "swipe",
    "back_forward": "nav", "wave": "wave", "scroll_down": "scroll", "scroll_up": "scroll",
    "click": "pinch", "drag": "pinch",
}
HOLD_SECONDS = {"thumbs_up": core.THUMBS_UP_HOLD_SECONDS,
                "thumbs_down": core.THUMBS_DOWN_HOLD_SECONDS,
                "shaka": core.SHAKA_HOLD_SECONDS, "horns": core.PAUSE_HOLD_SECONDS}


def pose_checks(target, pts, palm):
    """[(label, ok, measured)] for the conditions of `target`, so the user
    sees which one fails.  Mirrors classify_pose (same constants)."""
    r = {f: core.finger_ratio(pts, f) for f in core.FINGERS}
    ext = lambda f: (f"{f} straight", r[f] >= core.EXTENDED_RATIO, f"{r[f]:.2f} need >= {core.EXTENDED_RATIO}")
    curl = lambda f: (f"{f} curled", r[f] <= core.CURLED_RATIO, f"{r[f]:.2f} need <= {core.CURLED_RATIO}")
    d = lambda a, b: core.dist(pts[a], pts[b]) / palm
    spread = core.fingertip_spread(pts) / palm
    pinch = d(4, 8)
    thumb_len = d(4, 2)
    if target == "gather":
        return [("fingertips together", spread <= core.GATHER_MAX_SPREAD,
                 f"spread {spread:.2f} need <= {core.GATHER_MAX_SPREAD}"),
                ("thumb at index", pinch <= core.PINCH_MAX * 1.3,
                 f"{pinch:.2f} need <= {core.PINCH_MAX * 1.3:.2f}")] + [
                (f"{f} not curled", r[f] > core.CURLED_RATIO, f"{r[f]:.2f} need > {core.CURLED_RATIO}")
                for f in core.FINGERS]
    if target == "open":
        return [("fingers spread", spread >= core.OPEN_MIN_SPREAD,
                 f"spread {spread:.2f} need >= {core.OPEN_MIN_SPREAD}")]
    if target == "point":
        return [("index straight", r["index"] >= core.POINT_INDEX_MIN_RATIO,
                 f"{r['index']:.2f} need >= {core.POINT_INDEX_MIN_RATIO}"),
                curl("middle"), curl("ring"), curl("pinky")]
    if target == "two":
        return [ext("index"), ext("middle"), curl("ring"), curl("pinky")]
    if target == "ok":
        others = sum(r[f] > core.CURLED_RATIO for f in ("middle", "ring", "pinky"))
        return [("thumb touches index", pinch <= core.PINCH_MAX, f"{pinch:.2f} need <= {core.PINCH_MAX}"),
                ("middle away from thumb", d(4, 12) >= core.OK_OTHER_MIN,
                 f"{d(4, 12):.2f} need >= {core.OK_OTHER_MIN}"),
                ("other fingers up", others >= 2, f"{others} of 3 need >= 2")]
    if target == "shaka":
        return [curl("index"), curl("middle"), curl("ring"), ext("pinky"),
                ("thumb out", thumb_len >= core.THUMB_UP_MIN_LEN,
                 f"{thumb_len:.2f} need >= {core.THUMB_UP_MIN_LEN}"),
                ("thumb far from pinky", d(4, 20) >= core.SHAKA_MIN_SPAN,
                 f"{d(4, 20):.2f} need >= {core.SHAKA_MIN_SPAN}")]
    if target == "horns":
        fold = min(d(4, 9), d(4, 13))
        return [ext("index"), ext("pinky"), curl("middle"), curl("ring"),
                ("thumb folded on palm", fold < core.HORNS_THUMB_FOLD_MAX,
                 f"{fold:.2f} need < {core.HORNS_THUMB_FOLD_MAX}")]
    if target in ("thumbs_up", "thumbs_down", "thumb_left", "thumb_right"):
        rest = [p for i, p in enumerate(pts) if i not in (3, 4)]
        tip = pts[4]
        if target == "thumbs_up":
            m = (min(p[1] for p in rest) - tip[1]) / palm
            need, ln = core.THUMB_UP_MARGIN, core.THUMB_UP_MIN_LEN
            what = "thumb above the fist"
        elif target == "thumbs_down":
            m = (tip[1] - max(p[1] for p in rest)) / palm
            need, ln = core.THUMB_UP_MARGIN, core.THUMB_DOWN_MIN_LEN
            what = "thumb below the fist"
        elif target == "thumb_left":
            m = (min(p[0] for p in rest) - tip[0]) / palm
            need, ln = core.THUMB_SIDE_MARGIN, core.THUMB_UP_MIN_LEN
            what = "thumb left of the fist"
        else:
            m = (tip[0] - max(p[0] for p in rest)) / palm
            need, ln = core.THUMB_SIDE_MARGIN, core.THUMB_UP_MIN_LEN
            what = "thumb right of the fist"
        return [curl("index"), curl("middle"), curl("ring"), curl("pinky"),
                ("thumb stretched", thumb_len >= ln, f"{thumb_len:.2f} need >= {ln}"),
                (what, m >= need, f"{m:+.2f} need >= {need}")]
    return []


class Coach:
    """Collects what the engine sees during a step and turns it into a few
    short lines: which pose condition fails, or how far the last movement
    was from what is needed."""

    def __init__(self, step_id):
        self.id = step_id
        self.target = STEP_POSE.get(step_id)
        self.motion = STEP_MOTION.get(step_id)
        self.strokes = []        # (t, dx, dy, v) recent swipe measurements
        self.pinch_min = None

    def lines(self, eng, pts, w, h, now):
        """[(text, ok)] for the panel; ok None = neutral info."""
        out = []
        if pts is None:
            return [("no hand in view", False)]
        palm = max(eng.ema_palm or core.palm_size(pts), 1.0)
        mpalm = eng.debug.get("mpalm", palm)
        if self.target:
            read = eng.pose
            checks = pose_checks(self.target, pts, palm)
            good = read == self.target or (self.target == "point" and read == "point")
            out.append((f"reads as: {read.upper()}" + ("" if good else f"  (need {self.target.upper()})"),
                        good))
            if not good:
                failing = [c for c in checks if not c[1]]
                for label, ok, val in failing[:3]:
                    out.append((f"{label}: {val}", False))
                if not failing and checks:
                    if read == "none":
                        out.append(("pose not steady yet: hold it a moment", None))
                    else:
                        out.append((f"all {self.target} checks pass; taken by "
                                    f"{read.upper()} first", False))
            held = now - eng.pose_since
            if good and self.id in HOLD_SECONDS and not eng.latched:
                out.append((f"hold {held:.1f} / {HOLD_SECONDS[self.id]:.1f} s", None))
        if eng.near_face and self.motion in ("slap", "swipe", "nav", "wave", "scroll", "pinch"):
            out.append(("hand is at your face: movement ignored here", False))
        if self.motion in ("slap", "swipe", "nav"):
            if not eng.armed:
                out.append(("hold still a moment to re-arm", False))
            sw = eng.debug.get("swipe")
            if sw:
                self.strokes.append((now, sw[0], sw[1], sw[2]))
            self.strokes = [s for s in self.strokes if now - s[0] < 1.5]
            if self.strokes:
                horiz = self.motion in ("slap", "nav")
                best = max(self.strokes, key=lambda s: abs(s[1] if horiz else s[2]))
                dist_ = abs(best[1] if horiz else best[2])
                need_d = core.NAV_SWIPE_DISTANCE_PALMS if self.motion == "nav" else core.MIN_SWIPE_DISTANCE_PALMS
                need_v = core.NAV_SWIPE_VELOCITY_PALMS if self.motion == "nav" else core.MIN_SWIPE_VELOCITY_PALMS
                out.append((f"best stroke: {dist_:.1f} palms (need {need_d})", dist_ >= need_d))
                out.append((f"speed: {best[3]:.1f} palms/s (need {need_v})", best[3] >= need_v))
                if self.motion == "slap":
                    frac = dist_ * mpalm / w
                    out.append((f"travel: {100 * frac:.0f}% of width (need {100 * core.SLAP_MIN_TRAVEL_FRAC:.0f}%)",
                                frac >= core.SLAP_MIN_TRAVEL_FRAC))
        if self.motion == "wave":
            out.append((f"direction changes: {len(eng.wave_flips)} / {core.WAVE_MIN_REVERSALS}", None))
        if self.motion == "scroll" and eng.scroll_neutral is not None and eng.ema_c:
            off = (eng.ema_c[1] - eng.scroll_neutral) / mpalm
            way = "below" if off > 0 else "above"
            out.append((f"hand {abs(off):.2f} palms {way} start (dead zone {core.JOY_DEADZONE_PALMS})",
                        abs(off) > core.JOY_DEADZONE_PALMS))
        if self.motion == "pinch" and eng.pose == "point":
            p = eng.pinch_s if eng.pinch_s is not None else 0.0
            self.pinch_min = p if self.pinch_min is None else min(self.pinch_min, p)
            out.append((f"pinch {p:.2f} (press <= {core.PINCH_ON})", p <= core.PINCH_ON))
            if eng.pinched:
                held = now - eng.pinch_start
                kind = "DRAG" if eng.dragging else ("click if released now" if held < core.CLICK_MAX_SECONDS else "becomes drag")
                out.append((f"pressed {held:.2f} s: {kind}", None))
        if self.id == "shaka_ear" and eng.pose == "shaka":
            out.append((f"by the ear: {eng.debug.get('head_why', '?')}", bool(eng.debug.get("head"))))
        return out


# =============================================================================
# Record
# =============================================================================

def record(only=None):
    import cv2
    import mediapipe as mp
    import numpy as np
    try:
        import gesture_demos
    except Exception:
        gesture_demos = None

    modes = user_modes()
    hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=1,
                                     model_complexity=core.MODEL_COMPLEXITY,
                                     min_detection_confidence=0.6,
                                     min_tracking_confidence=0.5)
    faces = core.FaceTracker(mp.solutions.face_detection)
    draw = mp.solutions.drawing_utils
    cap = cv2.VideoCapture(core.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, core.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, core.FRAME_HEIGHT)
    if not cap.isOpened():
        sys.exit("camera not available (is the terminal allowed to use the camera?)")
    win = "Cenno gesture check"
    # Fixed size: a resizable window is scaled on every frame, which on a
    # Retina screen took ~18 ms and halved the frame rate (30 -> 16 fps).
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    font = cv2.FONT_HERSHEY_SIMPLEX
    GREEN, RED, GREY, WHITE, AMBER = (90, 220, 90), (80, 80, 255), (190, 190, 190), (255, 255, 255), (0, 200, 255)
    PANEL_W = 640

    def text(img, s, x, y, scale=0.6, color=WHITE, thick=2):
        cv2.putText(img, s, (x, y), font, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(img, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

    def wrap(s, width=52):
        words, lines, cur = s.split(), [], ""
        for w_ in words:
            if len(cur) + len(w_) + 1 > width:
                lines.append(cur)
                cur = w_
            else:
                cur = f"{cur} {w_}".strip()
        return lines + [cur]

    def compose(frame, step_i, step, phase, coach_lines, counts, missing, stray, now, t_step):
        h, w = frame.shape[:2]
        canvas = np.zeros((max(h, 480) + 80, w + PANEL_W, 3), np.uint8)
        canvas[:] = (28, 28, 28)
        canvas[80:80 + h, :w] = frame
        # header: step and prompt
        neg = not step["expect"]
        tag = {"lead": ("GET READY", AMBER), "go": ("YOUR TURN", GREEN),
               "done": ("DONE", GREEN), "neg": ("DON'T TRIGGER ANYTHING", AMBER)}[phase]
        text(canvas, f"{step_i + 1}/{len(steps)}  {tag[0]}", 12, 28, 0.75, tag[1])
        for k, line in enumerate(wrap(step["prompt"], 100)[:2]):
            text(canvas, line, 12, 56 + 22 * k, 0.58)
        # right panel: demo, then why-not lines
        x0 = w + 16
        if gesture_demos is not None:
            try:
                demo = gesture_demos.demo(step["id"])
                if demo is not None:
                    text(canvas, "HOW IT SHOULD LOOK", x0, 104, 0.55, GREY, 1)
                    gesture_demos.draw(canvas, demo, t_step, (x0, 112, 320, 240))
            except Exception as exc:
                text(canvas, f"demo error: {exc}"[:60], x0, 130, 0.5, RED, 1)
        else:
            text(canvas, "(demo not available)", x0, 130, 0.5, GREY, 1)
        y = 380
        text(canvas, "WHAT CENNO SEES", x0, y, 0.55, GREY, 1)
        y += 26
        for s, ok in coach_lines[:6]:
            col = GREY if ok is None else (GREEN if ok else RED)
            mark = "" if ok is None else ("ok  " if ok else "x   ")
            text(canvas, mark + s, x0, y, 0.52, col, 1)
            y += 22
        # progress
        if neg:
            prog = "nothing fired - good" if not counts else f"fired by mistake: {dict(counts)}"
            text(canvas, prog, x0, y + 8, 0.55, GREEN if not counts else RED, 1)
        else:
            need = ", ".join(f"{k.replace('|', ' or ')} x{v}" for k, v in step["expect"].items())
            got = ", ".join(f"{n} x{c}" for n, c in counts.items()) or "nothing yet"
            text(canvas, f"need: {need}", x0, y + 8, 0.55, WHITE, 1)
            text(canvas, f"got:  {got}", x0, y + 30, 0.55, GREEN if not missing else WHITE, 1)
            if stray:
                text(canvas, f"also fired (wrong): {stray}", x0, y + 52, 0.5, RED, 1)
        text(canvas, "s skip (can't do it)   r redo   q stop and save", 12,
             canvas.shape[0] - 10, 0.5, GREY, 1)
        return canvas

    # Start screen: wait until the user is ready and Cenno is off.
    busy, busy_checked = True, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        if time.monotonic() - busy_checked > 1.0:
            busy, busy_checked = cenno_tracking(), time.monotonic()
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 150), (0, 0, 0), -1)
        text(frame, "Cenno gesture check", 12, 30, 0.8, AMBER)
        if busy:
            text(frame, "1. Cenno is ON: switch it off in the menu bar", 12, 64, 0.6, RED)
        else:
            text(frame, "1. Cenno is off - good", 12, 64, 0.6, GREEN)
        text(frame, "2. Each step waits until you do the gesture", 12, 92, 0.6)
        text(frame, "3. Press SPACE to start   (q = quit)", 12, 120, 0.6,
             GREY if busy else GREEN)
        cv2.imshow(win, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and not busy:
            break
        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            sys.exit("cancelled")

    rec = dict(version=2, created=time.strftime("%Y-%m-%d %H:%M:%S"),
               w=None, h=None, pointer_mode=modes[0], scroll_mode=modes[1],
               steps=[])
    steps = [s for s in STEPS if not only or s["id"] in only]
    quit_all = False
    i = 0
    while i < len(steps) and not quit_all:
        step = steps[i]
        neg = not step["expect"]
        frames, counts = [], Counter()
        eng = new_engine(modes)
        coach = Coach(step["id"])
        last_lines = []
        t0 = time.monotonic()
        done_at = None
        redo = skip = False
        fps, last_frame_t = 30.0, None
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            now = time.monotonic()
            el = now - t0
            if last_frame_t is not None and now > last_frame_t:
                fps = 0.9 * fps + 0.1 / (now - last_frame_t)
            last_frame_t = now
            if now - busy_checked > 2.0:
                busy, busy_checked = cenno_tracking(), now
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rec["w"], rec["h"] = w, h
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = hands.process(rgb)
            face = faces.update(rgb, w, h, now)
            lead = el < LEAD_SECONDS
            pts3 = pts = None
            handed = None
            if res.multi_hand_landmarks:
                hl = res.multi_hand_landmarks[0]
                pts3 = [[p.x * w, p.y * h, p.z * w] for p in hl.landmark]
                pts = [(p[0], p[1]) for p in pts3]
                # The frame is mirrored with cv2.flip before MediaPipe, and MediaPipe's
                # handedness assumes a mirrored selfie image, so the label then names
                # the user's real hand.
                if res.multi_handedness:
                    cls_ = res.multi_handedness[0].classification[0]
                    handed = [cls_.label, round(float(cls_.score), 2)]
                ev = eng.update(pts, w, h, now, face=face)
                draw.draw_landmarks(frame, hl, mp.solutions.hands.HAND_CONNECTIONS)
            else:
                ev = eng.no_hand(now)
            if not lead:
                counts.update(action_names(ev))
            frames.append(dict(t=round(now - t0, 4), lead=lead, w=w, h=h,
                               pts=[[round(v, 1) for v in p] for p in pts3] if pts3 else None,
                               face=[round(v, 1) for v in face] if face else None,
                               handed=handed))
            if face:
                cv2.rectangle(frame, (int(face[0]), int(face[1])), (int(face[2]), int(face[3])),
                              (120, 120, 120), 1)
            missing, stray = judge(step, counts)
            if not lead:
                last_lines = coach.lines(eng, pts, w, h, now)
            if lead:
                phase = "lead"
            elif neg:
                phase = "neg"
                if el >= LEAD_SECONDS + step["seconds"]:
                    break                          # negative steps are timed
            elif not missing:
                phase = "done"
                done_at = done_at or now
                if now - done_at >= 1.2:           # a moment to see it worked
                    break
            else:
                phase = "go"
            canvas = compose(frame, i, step, phase, last_lines, counts, missing, stray,
                             now, max(0.0, el - LEAD_SECONDS))
            slow = fps < 24
            text(canvas, f"{fps:4.0f} fps", canvas.shape[1] - 110, 28, 0.6,
                 RED if slow else GREY, 1)
            if busy or slow:
                warn = ("Cenno is ON: it shares the camera and acts on your gestures"
                        if busy else "camera is slow: close other camera apps")
                text(canvas, warn, 12, canvas.shape[0] - 34, 0.55, RED, 1)
            cv2.imshow(win, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                skip = True
                break
            if key == ord("r"):
                redo = True
                break
            if key == ord("q"):
                quit_all = True
                break
        if redo:
            continue
        missing, stray = judge(step, counts)
        result = ("skipped" if skip else "stopped" if quit_all else
                  ("clean" if not counts else "false triggers") if neg else "done")
        rec["steps"].append(dict(id=step["id"], prompt=step["prompt"], skipped=skip or quit_all,
                                 result=result, seconds=round(time.monotonic() - t0 - LEAD_SECONDS, 1),
                                 why=[s for s, ok in last_lines if ok is False],
                                 frames=frames))
        print(f"{step['id']:15s} {result:14s} {rec['steps'][-1]['seconds']:5.1f}s fired={dict(counts)}"
              + (f" missing={missing}" if missing else "")
              + (f" stray={stray}" if stray else "")
              + (f" why={rec['steps'][-1]['why']}" if skip else ""))
        i += 1

    cap.release()
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    hands.close()
    faces.close()
    os.makedirs(CHECKS_DIR, exist_ok=True)
    path = os.path.join(CHECKS_DIR, time.strftime("check-%Y%m%d-%H%M%S.json"))
    with open(path, "w") as f:
        json.dump(rec, f)
    print(f"\nsaved {path}  ({len(rec['steps'])} steps)")
    return path


# =============================================================================
# Natural record
# =============================================================================

def record_natural(only=None, reps_override=None, hand_mode="both"):
    """Record gestures naturally with repetitions, timed cues and no coaching."""
    import cv2
    import mediapipe as mp

    if hand_mode not in ("right", "left", "both"):
        raise ValueError("hand_mode must be right, left or both")
    modes = user_modes()
    hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=1,
                                     model_complexity=core.MODEL_COMPLEXITY,
                                     min_detection_confidence=0.6,
                                     min_tracking_confidence=0.5)
    faces = core.FaceTracker(mp.solutions.face_detection)
    cap = cv2.VideoCapture(core.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, core.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, core.FRAME_HEIGHT)
    if not cap.isOpened():
        sys.exit("camera not available (is the terminal allowed to use the camera?)")
    win = "Cenno natural gesture check"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    font = cv2.FONT_HERSHEY_SIMPLEX
    GREEN, RED, GREY, WHITE, AMBER = (90, 220, 90), (80, 80, 255), (190, 190, 190), (255, 255, 255), (0, 200, 255)

    def text(img, s, x, y, scale=0.6, color=WHITE, thick=2):
        cv2.putText(img, s, (x, y), font, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(img, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

    def wrap(s, width=65):
        words, lines, cur = s.split(), [], ""
        for w_ in words:
            if len(cur) + len(w_) + 1 > width:
                lines.append(cur)
                cur = w_
            else:
                cur = f"{cur} {w_}".strip()
        return lines + [cur]

    # Start screen: wait until Cenno is off and user presses SPACE
    busy, busy_checked = True, 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        now = time.monotonic()
        if now - busy_checked > 1.0:
            busy, busy_checked = cenno_tracking(), now
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 160), (0, 0, 0), -1)
        text(frame, "Cenno natural gesture check", 12, 30, 0.8, AMBER)
        if busy:
            text(frame, "1. Cenno is ON: switch it off in the menu bar", 12, 64, 0.6, RED)
        else:
            text(frame, "1. Cenno is off - good", 12, 64, 0.6, GREEN)
        text(frame, "2. Record each gesture naturally - no coaching, no demos", 12, 92, 0.6)
        text(frame, "3. Press SPACE to start   (q = quit)", 12, 120, 0.6,
             GREY if busy else GREEN)
        cv2.imshow(win, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" ") and not busy:
            break
        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            sys.exit("cancelled")

    hand_list = ["right", "left"] if hand_mode == "both" else [hand_mode]
    base_steps = [s for s in NATURAL_STEPS if not only or s["id"] in only]
    session_steps = []
    for s in base_steps:
        for h_choice in hand_list:
            sc = dict(s)
            sc["hand"] = h_choice
            if reps_override and sc["expect"]:
                sc["reps"] = reps_override
            session_steps.append(sc)
    # The base loop already gives RIGHT then LEFT for each gesture.

    rec = dict(version=2, mode="natural", created=time.strftime("%Y-%m-%d %H:%M:%S"),
               w=None, h=None, pointer_mode=modes[0], scroll_mode=modes[1],
               steps=[])
    quit_all = False
    step_idx = 0
    while step_idx < len(session_steps) and not quit_all:
        step = session_steps[step_idx]
        neg = not step["expect"]
        target_hand = step["hand"]
        total_reps = 1 if neg else step["reps"]
        window_sec = step["window"]
        rest_sec = step.get("rest", 1.5)

        frames = []
        eng = new_engine(modes)
        t_step_start = time.monotonic()
        phase = "lead"
        phase_start = t_step_start
        cur_rep = None
        redo = skip = False
        fps, last_frame_t = 30.0, None

        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            now = time.monotonic()
            el = now - t_step_start
            el_phase = now - phase_start

            if last_frame_t is not None and now > last_frame_t:
                fps = 0.9 * fps + 0.1 / (now - last_frame_t)
            last_frame_t = now
            if now - busy_checked > 2.0:
                busy, busy_checked = cenno_tracking(), now

            # Advance phases
            if phase == "lead":
                if el_phase >= LEAD_SECONDS:
                    if neg:
                        phase = "go"
                        phase_start = now
                        cur_rep = 0
                    else:
                        phase = "rest"
                        phase_start = now
                        cur_rep = 1
            elif phase == "rest":
                if el_phase >= rest_sec:
                    phase = "go"
                    phase_start = now
            elif phase == "go":
                if el_phase >= window_sec:
                    if neg or cur_rep >= total_reps:
                        break
                    else:
                        cur_rep += 1
                        phase = "rest"
                        phase_start = now

            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rec["w"], rec["h"] = w, h

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = hands.process(rgb)
            face = faces.update(rgb, w, h, now)

            pts3 = pts = None
            handed = None
            if res.multi_hand_landmarks:
                hl = res.multi_hand_landmarks[0]
                pts3 = [[p.x * w, p.y * h, p.z * w] for p in hl.landmark]
                pts = [(p[0], p[1]) for p in pts3]
                # The frame is mirrored with cv2.flip before MediaPipe, and MediaPipe's
                # handedness assumes a mirrored selfie image, so the label then names
                # the user's real hand.
                if res.multi_handedness:
                    cls_ = res.multi_handedness[0].classification[0]
                    handed = [cls_.label, round(float(cls_.score), 2)]
                ev = eng.update(pts, w, h, now, face=face)
            else:
                ev = eng.no_hand(now)

            lead = (phase == "lead")
            rep_tag = cur_rep if phase == "go" else None

            frames.append(dict(t=round(now - t_step_start, 4), lead=lead, rep=rep_tag,
                               w=w, h=h,
                               pts=[[round(v, 1) for v in p] for p in pts3] if pts3 else None,
                               face=[round(v, 1) for v in face] if face else None,
                               handed=handed))

            # Render camera overlay
            # The intent only ("Switch to the previous Space"), never the internal
            # id: "SLAP_RIGHT" would tell the user which way to move.
            intent = step["prompt"].split(",")[0]
            step_header = f"{step_idx + 1}/{len(session_steps)}  {intent}"
            text(frame, step_header, 16, 32, 0.75, AMBER)
            text(frame, f"{target_hand.upper()} HAND", 16, 62, 0.85, WHITE, 3)
            for k, line in enumerate(wrap(step["prompt"], 70)[:2]):
                text(frame, line, 16, 96 + 24 * k, 0.58, WHITE)

            # Center cues
            if phase == "lead":
                text(frame, "GET READY", w // 2 - 120, h // 2 - 20, 1.3, AMBER, 3)
                text(frame, f"{target_hand.upper()} HAND", w // 2 - 140, h // 2 + 35, 1.1, WHITE, 2)
            elif phase == "rest":
                text(frame, "REST", w // 2 - 60, h // 2 - 20, 1.3, GREY, 3)
                text(frame, f"{target_hand.upper()} HAND", w // 2 - 140, h // 2 + 25, 1.0, WHITE, 2)
            elif phase == "go":
                if neg:
                    text(frame, "GO  (0 / 1)", w // 2 - 130, h // 2 - 55, 1.4, GREEN, 3)
                else:
                    text(frame, f"GO  ({cur_rep} / {total_reps})", w // 2 - 130, h // 2 - 55, 1.4, GREEN, 3)
                text(frame, f"{target_hand.upper()} HAND", w // 2 - 140, h // 2 - 5, 1.2, WHITE, 3)

                # Shrinking progress bar
                bar_frac = max(0.0, 1.0 - el_phase / window_sec)
                bar_x0, bar_x1 = 50, w - 50
                bar_y0, bar_y1 = h // 2 + 65, h // 2 + 77
                cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (40, 40, 40), -1)
                fill_w = int((bar_x1 - bar_x0) * bar_frac)
                if fill_w > 0:
                    cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x0 + fill_w, bar_y1), GREEN, -1)

            # Live fps & keys
            slow = fps < 24
            text(frame, f"{fps:4.0f} fps", w - 110, 32, 0.6, RED if slow else GREY, 1)
            # Plain single-pass text on a dark strip: the outlined helper
            # smears thin small text into an unreadable blob.
            cv2.rectangle(frame, (0, h - 34), (w, h), (0, 0, 0), -1)
            cv2.putText(frame, "r redo   s skip   q stop and save", (16, h - 12),
                        font, 0.55, GREY, 1, cv2.LINE_AA)
            if busy:
                text(frame, "Cenno is ON: switch it off in the menu bar", 16, h - 42, 0.55, RED, 1)

            cv2.imshow(win, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                skip = True
                break
            if key == ord("r"):
                redo = True
                break
            if key == ord("q"):
                quit_all = True
                break

        if redo:
            continue

        result = "skipped" if skip else ("stopped" if quit_all else "done")
        step_entry = dict(
            id=step["id"],
            hand=step["hand"],
            prompt=step["prompt"],
            reps=step["reps"],
            window=step["window"],
            rest=step.get("rest", 1.5),
            skipped=skip or quit_all,
            result=result,
            seconds=round(time.monotonic() - t_step_start - LEAD_SECONDS, 1),
            frames=frames,
        )
        rec["steps"].append(step_entry)
        print(f"{step['id']:15s} [{step['hand']} hand] {result:10s} {step_entry['seconds']:5.1f}s  ({len(frames)} frames)")
        step_idx += 1

    cap.release()
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    hands.close()
    faces.close()

    os.makedirs(CHECKS_DIR, exist_ok=True)
    path = os.path.join(CHECKS_DIR, time.strftime("natural-%Y%m%d-%H%M%S.json"))
    with open(path, "w") as f:
        json.dump(rec, f)
    print(f"\nsaved {path}  ({len(rec['steps'])} steps)")
    return path

# =============================================================================
# Replay + report
# =============================================================================

def replay_step(rec, step_rec, modes=None):
    """Feed one recorded step through a fresh engine. Returns (counts,
    stats) for the judged part (after the get-ready lead)."""
    modes = modes or (rec.get("pointer_mode", core.POINTER_MODE),
                      rec.get("scroll_mode", core.SCROLL_MODE))
    eng = new_engine(modes)
    counts, poses = Counter(), Counter()
    pinch, spread, near = [], [], 0
    judged = 0
    for fr in step_rec["frames"]:
        t = fr["t"]
        # The camera can change its frame size mid-session, so the size is
        # kept per frame (older recordings: one size for the whole file).
        w, h = fr.get("w", rec["w"]), fr.get("h", rec["h"])
        if fr["pts"]:
            pts = [(p[0], p[1]) for p in fr["pts"]]
            ev = eng.update(pts, w, h, t, face=tuple(fr["face"]) if fr["face"] else None)
        else:
            ev = eng.no_hand(t)
        if fr["lead"]:
            continue
        judged += 1
        counts.update(action_names(ev))
        poses[eng.pose] += 1
        d = eng.debug
        if fr["pts"] and d:
            pinch.append(d.get("pinch", 0.0))
            spread.append(d.get("spread", 0.0))
            near += bool(d.get("face"))
    stats = dict(frames=judged, poses=poses, pinch=pinch, spread=spread, near_face=near)
    return counts, stats


def pct(v, p):
    if not v:
        return float("nan")
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def score_natural(rec):
    """Score a natural recording per gesture and hand.

    Returns a list of entries.  Each entry has hits, misses, wrong and
    wrong_hand counts, plus the repetitions that made each mistake.
    """
    by_id = {s["id"]: s for s in NATURAL_STEPS}
    results = []
    for sr in rec.get("steps", []):
        step = by_id.get(sr["id"], dict(expect={}, allow={}))
        hand = sr.get("hand", "right")
        expect = step.get("expect", {})
        allow = set(step.get("allow", ()))
        wanted = set()
        for key in expect:
            wanted.update(key.split("|"))

        # A fresh engine per gesture, like replay_step, but events are kept
        # with the repetition label that was active at the time.
        eng = new_engine((rec.get("pointer_mode", core.POINTER_MODE),
                          rec.get("scroll_mode", core.SCROLL_MODE)))
        events = []
        for fr in sr.get("frames", []):
            t = fr["t"]
            w, h = fr.get("w", rec.get("w")), fr.get("h", rec.get("h"))
            if fr.get("pts"):
                pts = [(p[0], p[1]) for p in fr["pts"]]
                ev = eng.update(pts, w, h, t,
                                face=tuple(fr["face"]) if fr.get("face") else None)
            else:
                ev = eng.no_hand(t)
            events.append((fr.get("rep"), action_names(ev), fr.get("handed")))

        reps = sorted({r for r, _, _ in events if r is not None})
        result = dict(id=sr["id"], hand=hand, reps=len(reps), hits=0,
                      misses=0, wrong=0, wrong_hand=0, missed=[], wrong_events=[],
                      wrong_hand_reps=[], fired={})

        # Map each event to the repetition it belongs to.  Events up to
        # 0.5 s after a window end still count for that repetition.
        rep_ends = {}
        for fr in sr.get("frames", []):
            if fr.get("rep") is not None:
                rep_ends[fr["rep"]] = max(rep_ends.get(fr["rep"], 0.0), fr["t"])
        by_rep = {rep: [] for rep in reps}
        for fr, (r, ev, _) in zip(sr.get("frames", []), events):
            if r in by_rep:
                by_rep[r].extend(ev)
                continue
            # A rest/lead frame: it belongs to the previous repetition when
            # it is within the 0.5 s grace period after that window.
            for rep in reversed(reps):
                if rep_ends.get(rep, -1e9) <= fr["t"] <= rep_ends.get(rep, -1e9) + 0.5:
                    by_rep[rep].extend(ev)
                    break

        for rep in reps:
            names = by_rep[rep]
            counts = Counter(names)
            if expect:
                # A hit is the expected event firing at least once.
                hit = any(sum(counts.get(n, 0) for n in key.split("|")) >= need
                          for key, need in expect.items())
                if hit:
                    result["hits"] += 1
                else:
                    result["misses"] += 1
                    result["missed"].append(rep)
            stray = sorted(n for n in set(names)
                           if n not in wanted and n not in allow)
            if stray:
                result["wrong"] += 1
                result["wrong_events"].extend(stray)

            labels = [h[0].lower() for r, _, h in events
                      if r == rep and h]
            # The majority label in the window decides which hand was seen.
            if labels:
                majority = Counter(labels).most_common(1)[0][0]
                if majority != hand:
                    result["wrong_hand"] += 1
                    result["wrong_hand_reps"].append(rep)
            result["fired"].update(Counter(names))
        results.append(result)
    return results


def report_natural(rec, path=None):
    if path is not None:
        print(f"recording: {os.path.relpath(path, ROOT)}  ({rec['created']}, "
              f"pointer={rec.get('pointer_mode')}, scroll={rec.get('scroll_mode')})\n")
    scored = score_natural(rec)
    total_hits = total_reps = total_wrong = total_wrong_hand = 0
    for item in scored:
        label = f"{item['id']} [{item['hand']} hand]"
        if item["reps"]:
            rate = f"{item['hits']}/{item['reps']} hit"
            misses = f"   {item['misses']} missed" if item["misses"] else ""
            wrong = (f"   {item['wrong']} wrong"
                     + (f" ({', '.join(item['wrong_events'])})" if item["wrong_events"] else "")
                     if item["wrong"] else "")
            wrong_hand = (f"   {item['wrong_hand']} wrong hand seen"
                          if item["wrong_hand"] else "")
            print(f"{label:28s} {rate}{misses}{wrong}{wrong_hand}")
        else:
            print(f"{label:28s} no repetitions")
        total_hits += item["hits"]
        total_reps += item["reps"]
        total_wrong += item["wrong"]
        total_wrong_hand += item["wrong_hand"]
    rate = f"{total_hits}/{total_reps} hit" if total_reps else "0/0 hit"
    print(f"\nTOTAL {rate}   {total_wrong} wrong"
          + (f"   {total_wrong_hand} wrong hand seen" if total_wrong_hand else ""))


def report(path=None):
    if path is None:
        found = sorted(glob.glob(os.path.join(CHECKS_DIR, "check-*.json")) +
                       glob.glob(os.path.join(CHECKS_DIR, "natural-*.json")))
        if not found:
            sys.exit("no recordings in checks/")
        path = found[-1]
    with open(path) as f:
        rec = json.load(f)
    if rec.get("mode") == "natural":
        return report_natural(rec, path)
    by_id = {s["id"]: s for s in STEPS}
    print(f"recording: {os.path.relpath(path, ROOT)}  ({rec['created']}, "
          f"pointer={rec.get('pointer_mode')}, scroll={rec.get('scroll_mode')})\n")
    passed = 0
    for sr in rec["steps"]:
        step = by_id.get(sr["id"], dict(expect={}, id=sr["id"]))
        counts, st = replay_step(rec, sr)
        missing, stray = judge(step, counts)
        ok = not missing and not stray and not sr.get("skipped")
        passed += ok
        secs = (sr["frames"][-1]["t"] - LEAD_SECONDS) if sr["frames"] else 0
        fps = st["frames"] / secs if secs > 0 else 0
        top = ", ".join(f"{p} {100 * c // max(st['frames'], 1)}%"
                        for p, c in st["poses"].most_common(3))
        mark = "PASS" if ok else ("SKIP" if sr.get("skipped") else "FAIL")
        print(f"{mark}  {sr['id']:15s} fired={dict(counts) or '-'}")
        if missing:
            print(f"        missing: {', '.join(missing)}")
        if stray:
            print(f"        false triggers: {stray}")
        print(f"        poses: {top}   fps {fps:.0f}   at face {st['near_face']}/{st['frames']}"
              f"   pinch p10/med {pct(st['pinch'], .1):.2f}/{pct(st['pinch'], .5):.2f}"
              f"   spread min {pct(st['spread'], 0):.2f}")
    print(f"\n{passed}/{len(rec['steps'])} steps pass")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "record":
        # record --only slap_right,slap_left  : just those steps
        only = None
        if "--only" in sys.argv:
            only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
            unknown = only - {s["id"] for s in STEPS}
            if unknown:
                sys.exit(f"unknown steps: {sorted(unknown)}")
        p = record(only)
        print()
        report(p)
    elif cmd == "natural":
        only = None
        if "--only" in sys.argv:
            only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
            unknown = only - {s["id"] for s in NATURAL_STEPS}
            if unknown:
                sys.exit(f"unknown steps: {sorted(unknown)}")
        reps = None
        if "--reps" in sys.argv:
            reps = int(sys.argv[sys.argv.index("--reps") + 1])
            if reps < 1:
                sys.exit("--reps must be at least 1")
        hand = "both"
        if "--hand" in sys.argv:
            hand = sys.argv[sys.argv.index("--hand") + 1]
            if hand not in ("right", "left", "both"):
                sys.exit("--hand must be right, left or both")
        p = record_natural(only, reps, hand)
        print()
        report(p)
    elif cmd == "report":
        report(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        sys.exit(__doc__)
