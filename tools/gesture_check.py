"""
Guided gesture check (developer tool).

Walks you through every Cenno gesture with on-screen prompts, records your
real hand (all 21 landmarks plus the face box, every frame) and replays the
recording through the gesture engine to report, per gesture, what fired,
what was missed and what fired by mistake.

Nothing is sent to the system: no keys, no clicks.  Switch Cenno itself off
while recording, or it will act on the gestures.

    .venv-build/bin/python tools/gesture_check.py record      # ~6 min, saves checks/<time>.json
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
            if res.multi_hand_landmarks:
                hl = res.multi_hand_landmarks[0]
                pts3 = [[p.x * w, p.y * h, p.z * w] for p in hl.landmark]
                pts = [(p[0], p[1]) for p in pts3]
                ev = eng.update(pts, w, h, now, face=face)
                draw.draw_landmarks(frame, hl, mp.solutions.hands.HAND_CONNECTIONS)
            else:
                ev = eng.no_hand(now)
            if not lead:
                counts.update(action_names(ev))
            frames.append(dict(t=round(now - t0, 4), lead=lead, w=w, h=h,
                               pts=[[round(v, 1) for v in p] for p in pts3] if pts3 else None,
                               face=[round(v, 1) for v in face] if face else None))
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


def report(path=None):
    if path is None:
        found = sorted(glob.glob(os.path.join(CHECKS_DIR, "check-*.json")))
        if not found:
            sys.exit("no recordings in checks/")
        path = found[-1]
    with open(path) as f:
        rec = json.load(f)
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
    elif cmd == "report":
        report(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        sys.exit(__doc__)
