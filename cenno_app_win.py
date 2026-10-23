"""
Cenno: system-tray app for Windows.

Wraps the gesture engine from hand_desktop_switcher.py in a normal
Windows app: a system-tray icon, no Terminal, optional camera preview, pause,
mouse control on/off, and launch at login.

Threads
  * main thread   : tkinter event loop (preview window, dialogs)
  * tray thread   : pystray system-tray icon and menu
  * camera thread : capture -> MediaPipe -> GestureEngine -> Dispatcher
  * dispatcher    : worker / scroll / pointer threads (see core)
"""

import io
import json
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.simpledialog as simpledialog
import traceback
import winreg
import webbrowser

import hand_desktop_switcher as core

APP_NAME = "Cenno"
VERSION = "0.2.0"
SUPPORT_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
LOG_PATH = os.path.join(SUPPORT_DIR, f"{APP_NAME}.log")
SETTINGS_PATH = os.path.join(SUPPORT_DIR, "settings.json")

# Migrate settings/logs from the pre-rename newMotion install.
_OLD_SUPPORT_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "newMotion")
if os.path.isdir(_OLD_SUPPORT_DIR) and not os.path.exists(SUPPORT_DIR):
    try:
        os.rename(_OLD_SUPPORT_DIR, SUPPORT_DIR)
    except OSError as exc:
        print(f"WARN: could not move old newMotion settings: {exc}")

SUPPORT_URL = "https://ko-fi.com/sapucaialuann"

DEFAULT_SETTINGS = {
    "enabled": True,
    "preview": True,
    "mouse": True,
    "preview_corner": "top_right",
    "dictation": "auto",
    "dictation_shortcut": "",
    "wispr_shortcut": "",
}

DICTATION_MODES = (
    ("auto",     "Automatic (Wispr Flow if running, else Win+H)"),
    ("wispr",    "Wispr Flow"),
    ("winvoice", "Windows Voice Typing (Win+H)"),
    ("custom",   "Other app (custom shortcut)..."),
)

PREVIEW_W, PREVIEW_H = 280, 210
PREVIEW_MARGIN = 12
CORNERS = (
    ("top_right",    "Top right (default)"),
    ("top_left",     "Top left"),
    ("bottom_right", "Bottom right"),
    ("bottom_left",  "Bottom left"),
)

POINTER_EVENTS = ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up")
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# =============================================================================
# Logging
# =============================================================================

def setup_logging():
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    try:
        if os.path.getsize(LOG_PATH) > 2_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    f = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = f
    print(f"\n===== {APP_NAME} {VERSION} started {time.ctime()} =====")


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            s = {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        s = dict(DEFAULT_SETTINGS)
    # Remap Mac-only dictation modes to the Windows default.
    if s["dictation"] not in ("auto", "wispr", "winvoice", "custom"):
        s["dictation"] = DEFAULT_SETTINGS["dictation"]
    return s


def save_settings(s):
    try:
        os.makedirs(SUPPORT_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception as exc:
        print(f"WARN: could not save settings: {exc}")


# =============================================================================
# Launch at login (Windows registry)
# =============================================================================

def _exe_path():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def set_startup(enable):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY,
                            0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _exe_path())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as exc:
        print(f"WARN: set_startup failed: {exc}")


# =============================================================================
# Camera / gesture thread
# =============================================================================

class Tracker(threading.Thread):
    def __init__(self, settings):
        super().__init__(daemon=True)
        self.settings = settings
        self.engine = core.GestureEngine()
        self.dispatcher = core.Dispatcher()
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.preview_frame = None
        self.status = "Starting camera..."
        self.last_action, self.last_action_time = "", -1e9
        self.fps = 0.0

    def set_paused(self, paused):
        self.engine.paused = paused
        self.dispatcher.submit("pointer_end", None)

    def run(self):
        try:
            self._loop()
        except Exception:
            print("FATAL in camera thread:\n" + traceback.format_exc())
            self.status = "Error: see log"

    def _open_camera(self, cv2):
        cap = cv2.VideoCapture(core.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, core.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, core.FRAME_HEIGHT)
        return cap

    def _loop(self):
        import cv2
        import mediapipe as mp

        mp_hands = mp.solutions.hands
        drawing = mp.solutions.drawing_utils
        hands = mp_hands.Hands(
            static_image_mode=False, max_num_hands=1,
            model_complexity=core.MODEL_COMPLEXITY,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        cap = None
        frames, fps_t0 = 0, time.monotonic()

        try:
            while not self.stop_flag.is_set():
                if not self.settings["enabled"]:
                    if cap is not None:
                        cap.release()
                        cap = None
                        self.dispatcher.submit("pointer_end", None)
                    self.status = "Off"
                    with self.lock:
                        self.preview_frame = None
                    time.sleep(0.2)
                    continue

                if cap is None or not cap.isOpened():
                    cap = self._open_camera(cv2)
                    if not cap.isOpened():
                        self.status = "No camera found"
                        cap = None
                        time.sleep(2.0)
                        continue

                ok, frame = cap.read()
                if not ok:
                    self.status = "Camera stopped, retrying"
                    cap.release()
                    cap = None
                    time.sleep(0.5)
                    continue

                now = time.monotonic()
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                res = hands.process(rgb)

                if res.multi_hand_landmarks:
                    hl = res.multi_hand_landmarks[0]
                    pts = [(p.x * w, p.y * h) for p in hl.landmark]
                    events = self.engine.update(pts, w, h, now)
                else:
                    hl = None
                    events = self.engine.no_hand(now)

                for name, n in events:
                    if name in POINTER_EVENTS and not self.settings["mouse"]:
                        continue
                    self.dispatcher.submit(name, n)
                    if name in ("pointer_move", "pointer_end", "scroll_drag"):
                        continue
                    label = core.ACTION_LABELS.get(name, name)
                    if name == "click" and n[1] == 2:
                        label = "DOUBLE CLICK"
                    elif name == "scroll_fling":
                        label = "FLICK"
                    elif isinstance(n, int) and n > 1:
                        label += f" x{n}"
                    self.last_action, self.last_action_time = label, now
                    print(f"-> {label}")

                pose = self.engine.pose
                state = "Paused" if self.engine.paused else "Active"
                self.status = f"{state}: {pose if pose != 'none' else 'no hand'}"

                frames += 1
                if now - fps_t0 >= 1.0:
                    self.fps = frames / (now - fps_t0)
                    frames, fps_t0 = 0, now

                if self.settings["preview"]:
                    jpg = self._make_preview(cv2, drawing, mp_hands, frame, hl, now)
                    with self.lock:
                        self.preview_frame = jpg
        finally:
            if cap is not None:
                cap.release()
            hands.close()

    def _make_preview(self, cv2, drawing, mp_hands, frame, hl, now):
        h, w = frame.shape[:2]
        if hl is not None:
            drawing.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)
            if self.engine.pose == "point" and self.settings["mouse"]:
                x0, y0, x1, y1 = core.POINTER_BOX
                cv2.rectangle(frame,
                              (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), (0, 255, 255), 2)
        small = cv2.resize(frame, (PREVIEW_W * 2, PREVIEW_H * 2),
                           interpolation=cv2.INTER_AREA)
        sh, sw = small.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX

        def text(s, x, y, scale, color, thick):
            cv2.putText(small, s, (x + 2, y + 2), font, scale,
                        (0, 0, 0), thick, cv2.LINE_AA)
            cv2.putText(small, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

        paused = self.engine.paused
        pose = self.engine.pose if self.engine.pose != "none" else "no hand"
        text("PAUSED" if paused else pose, 16, 38, 0.9,
             (80, 80, 255) if paused else (255, 255, 255), 2)
        if now - self.last_action_time < core.ACTION_FLASH_SECONDS:
            (tw, _), _ = cv2.getTextSize(self.last_action, font, 1.1, 3)
            text(self.last_action, max(10, (sw - tw) // 2), sh - 24,
                 1.1, (90, 255, 90), 3)
        if paused:
            cv2.rectangle(small, (0, 0), (sw - 1, sh - 1), (80, 80, 255), 6)
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return jpg.tobytes() if ok else None


# =============================================================================
# Floating preview window (tkinter – main thread only)
# =============================================================================

class TkPreview:
    """Borderless, always-on-top floating window in a screen corner."""

    def __init__(self, root, corner="top_right"):
        self.root = root
        self.corner = corner
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-toolwindow", True)  # no taskbar button on Windows
        except Exception:
            pass
        self.win.configure(bg="black")
        self.label = tk.Label(self.win, bg="black", bd=0)
        self.label.pack(fill=tk.BOTH, expand=True)
        self.win.geometry(f"{PREVIEW_W}x{PREVIEW_H}")
        self._place()
        self.win.withdraw()
        self.visible = False
        self._photo = None

    def _place(self):
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        left = self.corner.endswith("left")
        top = self.corner.startswith("top")
        x = PREVIEW_MARGIN if left else sw - PREVIEW_W - PREVIEW_MARGIN
        # Extra bottom margin to clear the taskbar (typically ~48 px).
        y = PREVIEW_MARGIN if top else sh - PREVIEW_H - PREVIEW_MARGIN * 5
        self.win.geometry(f"{PREVIEW_W}x{PREVIEW_H}+{x}+{y}")

    def set_corner(self, corner):
        self.corner = corner
        self._place()

    def show(self):
        if not self.visible:
            self._place()
            self.win.deiconify()
            self.win.lift()
            self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def set_jpeg(self, data):
        from PIL import Image, ImageTk
        img = Image.open(io.BytesIO(data)).resize(
            (PREVIEW_W, PREVIEW_H), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.label.configure(image=self._photo)


# =============================================================================
# Main application
# =============================================================================

class CennoApp:
    def __init__(self):
        self.settings = load_settings()
        self.tracker = Tracker(self.settings)
        self.root = None
        self.preview = None
        self.icon = None
        self._alive = True

    # --- helpers ---

    def _sync_dictation(self):
        d = self.tracker.dispatcher
        d.dictation_mode = self.settings["dictation"]
        d.dictation_shortcut = self.settings.get("dictation_shortcut", "")
        d.wispr_shortcut = self.settings.get("wispr_shortcut", "")

    def _set_enabled(self, on):
        if self.settings["enabled"] == on:
            return
        self.settings["enabled"] = on
        save_settings(self.settings)
        print(f"Cenno {'on' if on else 'off'}")

    # --- tray icon ---

    def _load_icon_img(self):
        from PIL import Image
        base = (getattr(sys, "_MEIPASS", None)
                or os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "assets", "icon_1024.png")
        try:
            if os.path.exists(path):
                return Image.open(path).resize((64, 64), Image.LANCZOS)
        except Exception:
            pass
        # Simple fallback: solid blue square.
        return Image.new("RGBA", (64, 64), (40, 110, 220, 255))

    def _build_tray(self):
        from pystray import Icon, Menu, MenuItem

        app = self

        # Callbacks run on the pystray thread; tkinter ops go via root.after().

        def on_quit(icon, item):
            app._do_quit()

        def on_toggle_enabled(icon, item):
            app._set_enabled(not app.settings["enabled"])

        def on_toggle_pause(icon, item):
            app.tracker.set_paused(not app.tracker.engine.paused)

        def on_toggle_preview(icon, item):
            app.settings["preview"] = not app.settings["preview"]
            save_settings(app.settings)

        def on_toggle_mouse(icon, item):
            app.settings["mouse"] = not app.settings["mouse"]
            if not app.settings["mouse"]:
                app.tracker.dispatcher.submit("pointer_end", None)
            save_settings(app.settings)

        def on_toggle_startup(icon, item):
            set_startup(not startup_enabled())

        def make_corner_cb(key):
            def cb(icon, item):
                app.settings["preview_corner"] = key
                save_settings(app.settings)
                if app.preview and app.root:
                    app.root.after(0, lambda: app.preview.set_corner(key))
            return cb

        def make_dictation_cb(key):
            def cb(icon, item):
                if key == "wispr":
                    app.settings["dictation"] = key
                    save_settings(app.settings)
                    app._sync_dictation()
                    if not app.settings.get("wispr_shortcut") and app.root:
                        app.root.after(0, app._ask_wispr_shortcut)
                elif key == "custom":
                    if app.root:
                        app.root.after(0, app._ask_dictation_shortcut)
                else:
                    app.settings["dictation"] = key
                    save_settings(app.settings)
                    app._sync_dictation()
            return cb

        def on_open_log(icon, item):
            try:
                os.makedirs(SUPPORT_DIR, exist_ok=True)
                target = LOG_PATH if os.path.exists(LOG_PATH) else SUPPORT_DIR
                os.startfile(target)
            except Exception as exc:
                print(f"WARN: open log: {exc}")

        def on_support(icon, item):
            webbrowser.open(SUPPORT_URL)

        corner_items = [
            MenuItem(label, make_corner_cb(key),
                     checked=lambda item, k=key: app.settings["preview_corner"] == k,
                     radio=True)
            for key, label in CORNERS
        ]
        dictation_items = [
            MenuItem(label, make_dictation_cb(key),
                     checked=lambda item, k=key: app.settings["dictation"] == k,
                     radio=True)
            for key, label in DICTATION_MODES
        ]
        gesture_items = [MenuItem(line, None, enabled=False)
                         for line in core.HELP_LINES]

        menu = Menu(
            MenuItem(lambda item: app.tracker.status, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Cenno on",
                     on_toggle_enabled,
                     checked=lambda item: app.settings["enabled"]),
            MenuItem("Pause gestures",
                     on_toggle_pause,
                     checked=lambda item: app.tracker.engine.paused),
            Menu.SEPARATOR,
            MenuItem("Camera preview", Menu(
                MenuItem("Show preview",
                         on_toggle_preview,
                         checked=lambda item: app.settings["preview"]),
                MenuItem("Position", Menu(*corner_items)),
            )),
            MenuItem("Mouse control (point + pinch)",
                     on_toggle_mouse,
                     checked=lambda item: app.settings["mouse"]),
            MenuItem("Dictation (hang loose)", Menu(*dictation_items)),
            Menu.SEPARATOR,
            MenuItem("Gestures", Menu(*gesture_items)),
            MenuItem("Open log file", on_open_log),
            MenuItem("Open at startup",
                     on_toggle_startup,
                     checked=lambda item: startup_enabled()),
            Menu.SEPARATOR,
            MenuItem("Support Cenno ☕", on_support),
            MenuItem(f"About {APP_NAME} {VERSION}", None, enabled=False),
            MenuItem(f"Quit {APP_NAME}", on_quit),
        )

        return Icon(APP_NAME, self._load_icon_img(), APP_NAME, menu)

    def _ask_wispr_shortcut(self):
        current = self.settings.get("wispr_shortcut", "")
        result = simpledialog.askstring(
            "Wispr Flow shortcut",
            "Enter the global shortcut Wispr Flow uses on this machine.\n"
            "Check Wispr Flow Settings > Shortcut to find it.\n\n"
            "Examples:  ctrl+shift+space   ctrl+shift+w\n\n"
            "Modifiers: ctrl, shift, alt, win.",
            initialvalue=current,
            parent=self.root,
        )
        if result and result.strip():
            self.settings["wispr_shortcut"] = result.strip().lower()
            save_settings(self.settings)
            self._sync_dictation()

    def _ask_dictation_shortcut(self):
        current = self.settings.get("dictation_shortcut", "")
        result = simpledialog.askstring(
            "Dictation shortcut",
            "Type the shortcut your dictation app uses to toggle,\n"
            "e.g.  ctrl+shift+d   or   win+h\n\n"
            "Modifiers: ctrl, shift, alt, win.",
            initialvalue=current,
            parent=self.root,
        )
        if result and result.strip():
            self.settings["dictation"] = "custom"
            self.settings["dictation_shortcut"] = result.strip().lower()
            save_settings(self.settings)
            self._sync_dictation()

    # --- periodic ticks (tkinter main thread) ---

    def _tick_preview(self):
        if not self._alive:
            return
        try:
            show = self.settings["preview"] and self.settings["enabled"]
            if self.preview is not None:
                if show:
                    with self.tracker.lock:
                        jpg = self.tracker.preview_frame
                        self.tracker.preview_frame = None
                    if jpg:
                        self.preview.set_jpeg(jpg)
                        self.preview.show()
                else:
                    self.preview.hide()
        except Exception as exc:
            print(f"WARN: preview tick: {exc}")
        self.root.after(33, self._tick_preview)   # ~30 fps

    def _tick_status(self):
        if not self._alive:
            return
        try:
            if self.icon:
                self.icon.title = f"{APP_NAME}: {self.tracker.status}"
        except Exception:
            pass
        self.root.after(250, self._tick_status)

    # --- lifecycle ---

    def _do_quit(self):
        self._alive = False
        self.tracker.stop_flag.set()
        self.tracker.dispatcher.submit("pointer_end", None)
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.root:
            self.root.after(200, self.root.destroy)

    def run(self):
        if getattr(sys, "frozen", False):
            setup_logging()

        self._sync_dictation()
        self.tracker.start()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        # Prevent accidentally closing the hidden root via Alt+F4.
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        try:
            self.preview = TkPreview(self.root, self.settings["preview_corner"])
        except Exception:
            print("WARN: preview unavailable:\n" + traceback.format_exc())
            self.settings["preview"] = False
            self.preview = None

        self.icon = self._build_tray()
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

        self.root.after(250, self._tick_status)
        self.root.after(33, self._tick_preview)

        self.root.mainloop()


def main():
    try:
        import pystray          # noqa: F401  -- surface missing dep early
        from PIL import Image   # noqa: F401
    except ImportError as exc:
        print(f"Missing dependency: {exc}")
        print("Run: pip install pystray Pillow")
        sys.exit(1)

    app = CennoApp()
    app.run()


if __name__ == "__main__":
    main()
