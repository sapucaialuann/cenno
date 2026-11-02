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

Keys in the recording window:  n = next step,  r = redo this step,  q = stop and save.
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
# Record
# =============================================================================

def record():
    import cv2
    import mediapipe as mp

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
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 720)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    except cv2.error:
        pass
    font = cv2.FONT_HERSHEY_SIMPLEX

    def text(img, s, y, scale=0.6, color=(255, 255, 255), thick=2):
        cv2.putText(img, s, (12, y), font, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
        cv2.putText(img, s, (12, y), font, scale, color, thick, cv2.LINE_AA)

    def wrap(s, width=58):
        words, lines, cur = s.split(), [], ""
        for w_ in words:
            if len(cur) + len(w_) + 1 > width:
                lines.append(cur)
                cur = w_
            else:
                cur = f"{cur} {w_}".strip()
        return lines + [cur]

    # Start screen: wait until the user is ready (and Cenno is off).
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 150), (0, 0, 0), -1)
        text(frame, "Cenno gesture check", 30, 0.8, (0, 220, 255))
        text(frame, "1. Switch Cenno OFF in the menu bar first", 64, 0.6)
        text(frame, f"2. {len(STEPS)} short steps, ~6 min. Follow each prompt", 92, 0.6)
        text(frame, "3. Press SPACE to start   (q = quit)", 120, 0.6, (0, 255, 0))
        cv2.imshow(win, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            break
        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            sys.exit("cancelled")

    rec = dict(version=1, created=time.strftime("%Y-%m-%d %H:%M:%S"),
               w=None, h=None, pointer_mode=modes[0], scroll_mode=modes[1],
               steps=[])
    quit_all = False
    i = 0
    while i < len(STEPS) and not quit_all:
        step = STEPS[i]
        frames, counts = [], Counter()
        eng = new_engine(modes)
        t0 = time.monotonic()
        redo = skip = False
        while True:
            now = time.monotonic()
            el = now - t0
            if el >= LEAD_SECONDS + step["seconds"]:
                break
            ok, frame = cap.read()
            if not ok:
                continue
            now = time.monotonic()
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rec["w"], rec["h"] = w, h
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            res = hands.process(rgb)
            face = faces.update(rgb, w, h, now)
            lead = el < LEAD_SECONDS
            pts3 = None
            if res.multi_hand_landmarks:
                hl = res.multi_hand_landmarks[0]
                pts3 = [[p.x * w, p.y * h, p.z * w] for p in hl.landmark]
                ev = eng.update([(p[0], p[1]) for p in pts3], w, h, now, face=face)
                draw.draw_landmarks(frame, hl, mp.solutions.hands.HAND_CONNECTIONS)
            else:
                ev = eng.no_hand(now)
            if not lead:
                counts.update(action_names(ev))
            frames.append(dict(t=round(now - t0, 4), lead=lead,
                               pts=[[round(v, 1) for v in p] for p in pts3] if pts3 else None,
                               face=[round(v, 1) for v in face] if face else None))
            if face:
                cv2.rectangle(frame, (int(face[0]), int(face[1])), (int(face[2]), int(face[3])),
                              (120, 120, 120), 1)

            # --- overlay ---
            cv2.rectangle(frame, (0, 0), (w, 118), (0, 0, 0), -1)
            head = f"{i + 1}/{len(STEPS)}  " + ("GET READY" if lead else "GO")
            text(frame, head, 26, 0.7, (0, 220, 255) if lead else (0, 255, 0))
            for k, line in enumerate(wrap(step["prompt"])[:3]):
                text(frame, line, 54 + 24 * k, 0.6)
            left = (LEAD_SECONDS - el) if lead else (LEAD_SECONDS + step["seconds"] - el)
            cv2.putText(frame, f"{left:4.1f}s", (w - 90, 28), font, 0.7, (255, 255, 255), 2,
                        cv2.LINE_AA)
            missing, stray = judge(step, counts)
            status = f"pose: {eng.pose}"
            text(frame, status, h - 62, 0.55, (220, 220, 220), 1)
            got = ", ".join(f"{n} x{c}" for n, c in counts.items()) or "-"
            ok_now = not missing and not stray
            text(frame, "fired: " + got, h - 38, 0.55,
                 (0, 255, 0) if ok_now and step["expect"] else (220, 220, 220), 1)
            text(frame, "n next   r redo   q stop", h - 12, 0.45, (180, 180, 180), 1)
            cv2.imshow(win, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("n"):
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
        rec["steps"].append(dict(id=step["id"], prompt=step["prompt"], skipped=skip,
                                 frames=frames))
        missing, stray = judge(step, counts)
        verdict = "ok" if not missing and not stray else "CHECK"
        print(f"{step['id']:15s} {verdict:5s} fired={dict(counts)}"
              + (f" missing={missing}" if missing else "")
              + (f" stray={stray}" if stray else ""))
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
    w, h = rec["w"], rec["h"]
    counts, poses = Counter(), Counter()
    pinch, spread, near = [], [], 0
    judged = 0
    for fr in step_rec["frames"]:
        t = fr["t"]
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
        p = record()
        print()
        report(p)
    elif cmd == "report":
        report(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        sys.exit(__doc__)
