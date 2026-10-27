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

# Optional: pywin32 for click-through (WS_EX_TRANSPARENT) on the preview hwnd.
# Falls back gracefully if pywin32 is not installed.
try:
    import win32gui
    import win32con
except Exception:  # pragma: no cover - pywin32 may not be installed
    win32gui = None
    win32con = None

import displays as dpy
import hand_desktop_switcher as core
import theme

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
PRIVACY_LINE = "Runs on your machine. Nothing leaves it."
SUPPORT_LINE = "Cenno is free. Support it on Ko-fi."

DEFAULT_SETTINGS = {
    "enabled": True,
    "preview": True,
    "mouse": True,
    "preview_corner": "top_right",
    "preview_size": "medium",
    "preview_pos": None,
    "dictation": "auto",
    "dictation_shortcut": "",
    "wispr_shortcut": "",
    "first_run": True,
    "theme": "system",
    "display_mode": "current",
}

DICTATION_MODES = (
    ("auto",     "Automatic (Wispr Flow if running, else Win+H)"),
    ("wispr",    "Wispr Flow"),
    ("winvoice", "Windows Voice Typing (Win+H)"),
    ("custom",   "Other app (custom shortcut)..."),
)

# Where the pointer box reaches: the screen the cursor is on, or every
# screen at once.
DISPLAY_MODES = (
    ("current", "Current display"),
    ("all",     "All displays"),
)

PREVIEW_W, PREVIEW_H = 280, 210        # current panel size; mutated by set_size()
PREVIEW_SIZES = (
    ("small",     "Small",            (200, 150)),
    ("medium",    "Medium (default)", (280, 210)),
    ("large",     "Large",            (400, 300)),
)
PREVIEW_MARGIN = 12
CORNERS = (
    ("top_right",    "Top right (default)"),
    ("top_left",     "Top left"),
    ("bottom_right", "Bottom right"),
    ("bottom_left",  "Bottom left"),
    ("free",         "Anywhere (drag to move)"),
)

POINTER_EVENTS = ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up")
STARTUP_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def gesture_lines():
    """Menu list in the 'Gesture · Action' pattern, in Windows words."""
    prev_dir, next_dir = ("right", "left") if core.NATURAL_SWIPE else ("left", "right")
    return (f"Swipe {prev_dir} · Previous virtual desktop",
            f"Swipe {next_dir} · Next virtual desktop",
            "Swipe up · Task View",
            "Swipe down · Show desktop",
            "Two fingers move or flick · Scroll",
            "Two fingers swipe · Back or forward",
            "Point · Move cursor",
            "Pinch while pointing · Click, twice to double click, hold to drag",
            "OK sign and twist · Volume",
            "Thumbs up, hold · Play or pause",
            "Thumbs down, hold · Undo dictated text",
            "Hang loose, hold · Dictation on or off",
            "Open hand, gather fingertips · Start menu",
            "Wave, open hand side to side · Lock screen",
            "Rock horns, hold · Pause or resume gestures")

# ------------------------------------------------------------------
# Appearance.  The design tokens in theme.py are the only place the
# colours live: Day (light) and Night (dark), picked from the Windows
# apps theme unless the user overrides them in the tray menu.
# ------------------------------------------------------------------

def detect_windows_theme():
    """Return "dark" or "light" from the Windows AppsUseLightTheme setting."""
    return "dark" if theme.system_is_dark() else "light"


def system_is_dark():
    """True when Windows is using a dark apps theme."""
    return theme.system_is_dark()


def preview_colors(dark):
    """Return (panel background, border) hex for the given theme."""
    return theme.hex_of("paper-sunk", dark), theme.hex_of("line", dark)


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
    if s.get("display_mode") not in ("current", "all"):
        s["display_mode"] = DEFAULT_SETTINGS["display_mode"]
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


# ------------------------------------------------------------------
# cenno:// URL protocol handler
# ------------------------------------------------------------------

CENNO_PROTOCOL_KEY = r"Software\Classes\cenno\shell\open\command"


def register_cenno_protocol():
    """Register cenno:// in HKCU so browsers launch this exe with the URL."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CENNO_PROTOCOL_KEY) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"{_exe_path()} \"%1\"")
    except Exception as exc:
        print(f"WARN: register_cenno_protocol failed: {exc}")


def handle_cenno_url(url):
    """Parse a cenno:// URL.

    Returns "on", "off" or "toggle" for a recognized command, else None.
    The caller applies the result via app._set_enabled().
    """
    try:
        scheme, _, rest = url.partition("://")
    except AttributeError:
        return None
    if scheme.lower() != "cenno":
        return None
    cmd = rest.strip().lower().split("/")[0]
    if cmd in ("on", "off", "toggle"):
        return cmd
    return None


# =============================================================================
# Dialogs (tkinter - main thread only)
# =============================================================================

def show_dialog(root, title, body, dark=True, action=None, action_label="OK"):
    """A small window in the Cenno design: paper background, ink text, a
    trace-coloured action button.  Blocks until it is closed."""
    paper = theme.hex_of("paper", dark)
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=paper)
    win.resizable(False, False)
    # No transient() here: the main window is withdrawn, and a transient
    # window of a withdrawn window never gets mapped on Windows.

    inner = tk.Frame(win, bg=paper)
    inner.pack(fill=tk.BOTH, expand=True,
               padx=theme.SPACE[6], pady=theme.SPACE[4])

    tk.Label(inner, text=title, bg=paper, fg=theme.hex_of("ink", dark),
             font=theme.type_font("display", "title"),
             justify="left", anchor="w").pack(fill=tk.X)
    tk.Label(inner, text=body, bg=paper, fg=theme.hex_of("ink-muted", dark),
             font=theme.type_font("sans", "body-sm"),
             justify="left", anchor="w").pack(fill=tk.X, pady=theme.SPACE[2])

    def close():
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    def on_action():
        close()
        if action:
            action()

    tk.Button(inner, text=action_label, command=on_action,
              bg=theme.hex_of("trace", dark),
              fg=theme.hex_of("on-trace", dark),
              activebackground=theme.hex_of("trace-soft", dark),
              activeforeground=theme.hex_of("on-trace", dark),
              font=theme.type_font("sans", "label"),
              relief=tk.FLAT, bd=0, padx=theme.SPACE[4], pady=theme.SPACE[2],
              cursor="hand2").pack(anchor="e", pady=(theme.SPACE[3], 0))

    win.protocol("WM_DELETE_WINDOW", close)
    win.update_idletasks()
    # Always on top: the app has no other window, so the dialog would
    # otherwise open behind whatever the user was doing.
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    # Centre it on the primary screen.
    try:
        lay = dpy.system_displays()
        rect = lay[0] if lay else (0, 0, win.winfo_screenwidth(),
                                   win.winfo_screenheight())
        x = int(rect[0] + (rect[2] - win.winfo_width()) / 2)
        y = int(rect[1] + (rect[3] - win.winfo_height()) / 2)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass
    try:
        win.grab_set()
        win.lift()
        win.focus_force()
    except Exception:
        pass
    root.wait_window(win)


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
        self.dark = True            # set from the main thread (tick)
        self.reduce_motion = False

    def set_paused(self, paused):
        self.engine.paused = paused
        self.dispatcher.submit("pointer_end", None)

    # --- screens ---

    @property
    def displays_count(self):
        """How many screens Windows reports right now."""
        return self.dispatcher.layout.count

    def refresh_displays(self):
        """Re-read the screen layout.  True when it changed (a display was
        plugged in, unplugged or moved)."""
        return self.dispatcher.refresh_displays()

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
                if self.engine.paused:
                    self.status = "Paused"
                elif pose == "none":
                    self.status = "No hand"
                else:
                    self.status = f"Tracking · {pose}"

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
        """Small preview with status pills, encoded as JPEG for the panel.

        Same design as the macOS preview: the landmarks and the pointer box
        are drawn in the theme colours, and the state sits in pills instead
        of loose text."""
        dark = self.dark
        col = lambda name: theme.bgr(name, dark)
        h, w = frame.shape[:2]
        if hl is not None:
            drawing.draw_landmarks(
                frame, hl, mp_hands.HAND_CONNECTIONS,
                drawing.DrawingSpec(color=col("trace"), thickness=2, circle_radius=2),
                drawing.DrawingSpec(color=col("ink"), thickness=1))
            if self.engine.pose == "point" and self.settings["mouse"]:
                x0, y0, x1, y1 = core.POINTER_BOX
                box = col("ember") if self.engine.pinched else col("trace")
                cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), box, 2)
        # Render at 2x the panel size so it stays sharp on scaled screens.
        small = cv2.resize(frame, (PREVIEW_W * 2, PREVIEW_H * 2),
                           interpolation=cv2.INTER_AREA)
        sh, sw = small.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        s2 = 2                                   # token px -> render px

        def pill(x, y, label, fill, ink, outline=None):
            """Label-style pill (uppercase, radius-pill). Returns its width."""
            scale, thick = 0.62, 2
            (tw, th), _ = cv2.getTextSize(label, font, scale, thick)
            px, py = theme.SPACE[3] * s2, theme.SPACE[1] * s2
            wd, ht = tw + 2 * px, th + 2 * py

            def shape(c, inset=0):
                r = ht // 2 - inset
                x0, x1, cy = x + inset + r, x + wd - inset - r, y + ht // 2
                cv2.circle(small, (x0, cy), r, c, -1, cv2.LINE_AA)
                cv2.circle(small, (x1, cy), r, c, -1, cv2.LINE_AA)
                cv2.rectangle(small, (x0, cy - r), (x1, cy + r), c, -1)

            if outline is not None:
                shape(outline)
                shape(fill, inset=2)
            else:
                shape(fill)
            cv2.putText(small, label, (x + px, y + py + th), font, scale, ink, thick,
                        cv2.LINE_AA)
            return wd

        gap = theme.SPACE[2] * s2
        x0 = y0 = theme.SPACE[3] * s2
        pose = self.engine.pose
        if self.engine.paused:
            pill(x0, y0, "PAUSED", col("paper-raised"), col("ink"), col("line-strong"))
        elif pose == "none":
            pill(x0, y0, "NO HAND", col("paper-raised"), col("ember-ink"), col("line-strong"))
        else:
            wd = pill(x0, y0, "TRACKING", col("trace"), col("on-trace"))
            pill(x0 + wd + gap, y0, pose.upper(), col("paper-raised"), col("ink"),
                 col("line-strong"))

        age = now - self.last_action_time
        if age < core.ACTION_FLASH_SECONDS:
            label = self.last_action.upper()
            (tw, th), _ = cv2.getTextSize(label, font, 0.62, 2)
            wd = tw + 2 * theme.SPACE[3] * s2
            ht = th + 2 * theme.SPACE[1] * s2
            flash = age < theme.FLASH_S and not self.reduce_motion
            pill((sw - wd) // 2, sh - theme.SPACE[3] * s2 - ht, label,
                 col("trace-soft") if flash else col("paper-raised"),
                 col("ink"), col("line-strong"))     # ink, not on-trace: Night trace-soft is dark
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return jpg.tobytes() if ok else None


# =============================================================================
# Floating preview window (tkinter – main thread only)
# =============================================================================

class TkPreview:
    """Borderless, always-on-top floating window: a screen corner (click-through)
    or free/draggable (position remembered across restarts).

    It follows the design system: the panel is a card with rounded corners in
    the theme colours, and it knows about every screen, so it can be parked on
    a second monitor."""

    def __init__(self, root, corner="top_right", size=None, pos=None, dark=True,
                 layout=None):
        self.root = root
        self.corner = corner
        self.free = corner == "free"
        self.w, self.h = size or (PREVIEW_W, PREVIEW_H)
        self.pos = tuple(pos) if pos else None
        self.dark = dark
        self.layout = layout or (lambda: None)
        self._jpeg = None
        bg, border = preview_colors(dark)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-toolwindow", True)  # no taskbar button on Windows
        except Exception:
            pass
        # 1 px border of `border` around the `bg` panel.
        self.win.configure(bg=border)
        self.container = tk.Frame(self.win, bg=bg, bd=0, highlightthickness=0)
        self.container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.label = tk.Label(self.container, bg=bg, bd=0, highlightthickness=0)
        self.label.pack(fill=tk.BOTH, expand=True)

        # Click-through in corner mode; draggable in free mode.
        self._click_through(not self.free)
        self._bind_drag()

        self.win.geometry(f"{self.w}x{self.h}")
        self.place()
        self.win.withdraw()
        self.visible = False
        self._photo = None

    # -- positioning -------------------------------------------------

    def _layout(self):
        """The current display layout, or None when it cannot be read."""
        try:
            return self.layout()
        except Exception:
            return None

    def _primary_rect(self):
        """The primary screen (the one with the taskbar)."""
        lay = self._layout()
        if lay is not None and lay.count:
            return lay.rect(lay.primary)
        return (0.0, 0.0, float(self.win.winfo_screenwidth()),
                float(self.win.winfo_screenheight()))

    def _desktop_rect(self):
        """Every screen as one rect, so the preview can sit on any of them."""
        lay = self._layout()
        if lay is not None and lay.count:
            return lay.union
        desk = dpy.windows_virtual_screen()
        if desk:
            return desk
        return (0.0, 0.0, float(self.win.winfo_screenwidth()),
                float(self.win.winfo_screenheight()))

    def _corner_origin(self):
        sx, sy, sw, sh = self._primary_rect()
        left = self.corner.endswith("left")
        top = self.corner.startswith("top")
        x = sx + (PREVIEW_MARGIN if left else sw - self.w - PREVIEW_MARGIN)
        # Extra bottom margin to clear the taskbar (typically ~48 px).
        y = sy + (PREVIEW_MARGIN if top else sh - self.h - PREVIEW_MARGIN * 5)
        return x, y

    def _clamp(self, x, y):
        """Keep the preview on the desktop (any of the screens)."""
        dx, dy, dw, dh = self._desktop_rect()
        x = max(dx, min(x, dx + dw - self.w))
        y = max(dy, min(y, dy + dh - self.h))
        return x, y

    def place(self):
        """Corner of the primary screen, or the dragged-to spot (free mode)."""
        self._click_through(not self.free)
        if self.free and self.pos:
            x, y = self.pos
        else:
            x, y = self._corner_origin()
            self.pos = (x, y)
        x, y = self._clamp(x, y)
        self.win.geometry(f"{self.w}x{self.h}+{int(x)}+{int(y)}")

    def origin(self):
        return (self.win.winfo_x(), self.win.winfo_y())

    # -- click-through / drag ----------------------------------------

    def _click_through(self, enable):
        """Corner mode: clicks pass through the preview (WS_EX_TRANSPARENT)."""
        if win32gui is None or win32con is None:
            return
        try:
            hwnd = int(self.win.winfo_id())
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if enable:
                ex |= win32con.WS_EX_TRANSPARENT
            else:
                ex &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
            win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                                  | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
        except Exception:
            pass

    def _bind_drag(self):
        for w in (self.win, self.label):
            w.bind("<Button-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)

    def _on_press(self, event):
        if not self.free:
            return
        self._drag_start = (event.x_root, event.y_root)
        self._drag_origin = self.origin()

    def _on_drag(self, event):
        if not self.free or getattr(self, "_drag_origin", None) is None:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        x, y = self._drag_origin
        x, y = self._clamp(x + dx, y + dy)
        self.win.geometry(f"+{int(x)}+{int(y)}")
        self.pos = (x, y)

    def _on_release(self, event):
        self._drag_origin = None

    # -- size / theme ------------------------------------------------

    def set_size(self, size_key):
        for key, _, dims in PREVIEW_SIZES:
            if key == size_key:
                w, h = dims
                break
        else:
            return
        x, y = self.pos if self.pos else self.origin()  # keep top-left in place
        self.w, self.h = w, h
        global PREVIEW_W, PREVIEW_H
        PREVIEW_W, PREVIEW_H = w, h
        self.win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self.pos = (x, y)

    def set_corner(self, corner):
        self.corner = corner
        self.free = corner == "free"
        # keep self.pos (last known top-left); place() uses it for free mode.
        self.place()

    def apply_theme(self, dark):
        self.dark = dark
        bg, border = preview_colors(dark)
        self.win.configure(bg=border)
        self.container.configure(bg=bg)
        self.label.configure(bg=bg)
        self._render()

    # -- visibility / image ------------------------------------------

    def show(self):
        if not self.visible:
            self.place()
            self.win.deiconify()
            self.win.lift()
            self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def set_jpeg(self, data):
        self._jpeg = data
        self._render()

    def _render(self):
        """Draw the camera frame as a card: rounded corners in the theme
        colours, like the macOS preview panel."""
        if not self._jpeg:
            return
        from PIL import Image, ImageDraw, ImageTk
        img = Image.open(io.BytesIO(self._jpeg)).convert("RGB").resize(
            (self.w, self.h), Image.LANCZOS)
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, img.size[0] - 1, img.size[1] - 1],
            radius=theme.RADIUS_MD, fill=255)
        card = Image.new("RGB", img.size, theme.rgb("paper-sunk", self.dark))
        card.paste(img, (0, 0), mask)
        self._photo = ImageTk.PhotoImage(card)
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
        self._drag_since = None
        self._theme_tick = 0
        self._icon_base = self._load_icon_img()
        self._icon_state_cur = None
        self._gesture_notified = False

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

    def _effective_dark(self):
        """Effective dark/light from settings["theme"] (system|light|dark)."""
        theme = self.settings.get("theme", "system")
        if theme == "dark":
            return True
        if theme == "light":
            return False
        return detect_windows_theme() == "dark"   # "system"

    def _preview_size(self):
        for key, _, dims in PREVIEW_SIZES:
            if key == self.settings.get("preview_size"):
                return dims
        return (PREVIEW_W, PREVIEW_H)

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
            app._update_icon_state()
            app._sync_menu()

        def on_toggle_pause(icon, item):
            app.tracker.set_paused(not app.tracker.engine.paused)
            app._update_icon_state()
            app._sync_menu()

        def on_toggle_preview(icon, item):
            app.settings["preview"] = not app.settings["preview"]
            save_settings(app.settings)
            app._sync_menu()

        def on_toggle_mouse(icon, item):
            app.settings["mouse"] = not app.settings["mouse"]
            if not app.settings["mouse"]:
                app.tracker.dispatcher.submit("pointer_end", None)
            save_settings(app.settings)
            app._sync_menu()

        def on_toggle_startup(icon, item):
            set_startup(not startup_enabled())

        def on_register_protocol(icon, item):
            register_cenno_protocol()

        def make_corner_cb(key):
            def cb(icon, item):
                app.settings["preview_corner"] = key
                save_settings(app.settings)
                if app.preview and app.root:
                    app.root.after(0, lambda: app.preview.set_corner(key))
                app._sync_menu()
            return cb

        def make_size_cb(key):
            def cb(icon, item):
                app.settings["preview_size"] = key
                save_settings(app.settings)
                if app.preview and app.root:
                    app.root.after(0, lambda: app.preview.set_size(key))
                app._sync_menu()
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
                app._sync_menu()
            return cb

        def make_theme_cb(theme_name):
            def cb(icon, item):
                app.settings["theme"] = theme_name
                save_settings(app.settings)
                app.dark = app._effective_dark()
                if app.preview and app.root:
                    app.root.after(0, lambda: app.preview.apply_theme(app.dark))
                app._sync_menu()
            return cb

        def make_display_mode_cb(key):
            def cb(icon, item):
                app.settings["display_mode"] = key
                save_settings(app.settings)
                app.tracker.dispatcher.set_display_mode(key)
                app._sync_menu()
            return cb

        def on_next_display(icon, item):
            if not app.tracker.dispatcher.jump_to_next_display():
                app._notify(APP_NAME, "Only one display is connected.")

        def on_open_log(icon, item):
            try:
                os.makedirs(SUPPORT_DIR, exist_ok=True)
                target = LOG_PATH if os.path.exists(LOG_PATH) else SUPPORT_DIR
                os.startfile(target)
            except Exception as exc:
                print(f"WARN: open log: {exc}")

        def on_open_settings_folder(icon, item):
            try:
                os.makedirs(SUPPORT_DIR, exist_ok=True)
                os.startfile(SUPPORT_DIR)
            except Exception as exc:
                print(f"WARN: open settings folder: {exc}")

        def on_open_camera_settings(icon, item):
            try:
                os.startfile("ms-settings:privacy-webcam")
            except Exception as exc:
                print(f"WARN: open camera settings: {exc}")

        def on_support(icon, item):
            webbrowser.open(SUPPORT_URL)

        def on_about(icon, item):
            if app.root:
                app.root.after(0, lambda: show_dialog(
                    app.root,
                    f"{APP_NAME} {VERSION}",
                    f"{PRIVACY_LINE}\n\n{SUPPORT_LINE}\n\n{SUPPORT_URL}",
                    dark=app.dark,
                    action=lambda: webbrowser.open(SUPPORT_URL),
                    action_label="Support on Ko-fi",
                ))

        corner_items = [
            MenuItem(label, make_corner_cb(key),
                     checked=lambda item, k=key: app.settings["preview_corner"] == k,
                     radio=True)
            for key, label in CORNERS
        ]
        size_items = [
            MenuItem(label, make_size_cb(key),
                     checked=lambda item, k=key: app.settings["preview_size"] == k,
                     radio=True)
            for key, label, _ in PREVIEW_SIZES
        ]
        dictation_items = [
            MenuItem(label, make_dictation_cb(key),
                     checked=lambda item, k=key: app.settings["dictation"] == k,
                     radio=True)
            for key, label in DICTATION_MODES
        ]
        theme_items = [
            MenuItem(label, make_theme_cb(key),
                     checked=lambda item, k=key: app.settings["theme"] == k,
                     radio=True)
            for key, label in (("system", "System"), ("light", "Light"), ("dark", "Dark"))
        ]
        display_items = [
            MenuItem(label, make_display_mode_cb(key),
                     checked=lambda item, k=key: app.settings.get("display_mode", "current") == k,
                     radio=True)
            for key, label in DISPLAY_MODES
        ]
        gesture_items = [MenuItem(line, None, enabled=False)
                         for line in gesture_lines()]

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
                Menu.SEPARATOR,
                MenuItem("Size", Menu(*size_items)),
            )),
            MenuItem("Mouse control (point + pinch)",
                     on_toggle_mouse,
                     checked=lambda item: app.settings["mouse"]),
            MenuItem("Displays", Menu(
                *display_items,
                Menu.SEPARATOR,
                MenuItem("Move pointer to next display", on_next_display),
            )),
            MenuItem("Dictation (hang loose)", Menu(*dictation_items)),
            MenuItem("Theme", Menu(*theme_items)),
            Menu.SEPARATOR,
            MenuItem("Gestures", Menu(*gesture_items)),
            MenuItem("Open log file", on_open_log),
            MenuItem("Open settings folder", on_open_settings_folder),
            MenuItem("Open Camera settings", on_open_camera_settings),
            MenuItem("Open at startup",
                     on_toggle_startup,
                     checked=lambda item: startup_enabled()),
            MenuItem("Register cenno:// protocol", on_register_protocol),
            Menu.SEPARATOR,
            MenuItem("Support Cenno ☕", on_support),
            MenuItem(f"About {APP_NAME} {VERSION}", on_about),
            MenuItem(f"Quit {APP_NAME}", on_quit),
        )

        return Icon(APP_NAME, self._icon_base, APP_NAME, menu)

    # --- tray icon state / notifications ---

    def _tint_icon(self, base, tint_rgb, alpha):
        """Return `base` blended with a solid tint color (alpha 0..1)."""
        from PIL import Image
        base = base.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (*tint_rgb, 255))
        return Image.blend(base, overlay, alpha)

    def _icon_state(self):
        """Current tray-icon state: "off" | "paused" | "camera" | "default"."""
        if not self.settings["enabled"]:
            return "off"
        if self.tracker.engine.paused:
            return "paused"
        if self.tracker.status == "No camera found":
            return "camera"
        return "default"

    def _update_icon_state(self):
        """Swap self.icon.icon to match state, only when the state changes."""
        if not self.icon:
            return
        state = self._icon_state()
        if state == self._icon_state_cur:
            return
        prev = self._icon_state_cur
        self._icon_state_cur = state
        base = self._icon_base
        # The tints follow the Windows taskbar, so they follow the system
        # theme and not the theme the preview uses.
        system_dark = theme.system_is_dark()
        if state == "default":
            img = base
        elif state == "paused":
            img = self._tint_icon(base, theme.rgb("ink-muted", system_dark), 0.45)
        elif state == "off":
            img = self._tint_icon(base, theme.rgb("ink", system_dark), 0.45)
        else:  # camera
            img = self._tint_icon(base, theme.rgb("danger", system_dark), 0.45)
        try:
            self.icon.icon = img
        except Exception:
            pass
        # One-shot notifications on meaningful transitions.
        if state == "camera":
            self._notify("Cenno", "No camera found — check your webcam access.")
        elif prev == "paused" and state == "default":
            self._notify("Cenno", "Gestures resumed.")
        elif prev == "default" and state == "paused":
            self._notify("Cenno", "Gestures paused.")

    def _notify(self, title, msg):
        """Show a pystray notification, falling back to the log."""
        try:
            self.icon.notify(title, msg)
        except AttributeError:
            print(f"[notify] {title}: {msg}")
        except Exception:
            pass

    def _sync_menu(self):
        """Rebuild the tray menu so its check marks match the settings.

        Called from the tray thread, after the menu has closed: rebuilding a
        menu that is open is not safe."""
        if not self.icon:
            return
        try:
            self.icon.update_menu()
        except Exception as exc:
            print(f"WARN: could not refresh the tray menu: {exc}")

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

    def _show_welcome(self):
        """One-time first-run welcome dialog with camera permission guidance."""
        show_dialog(
            self.root,
            f"Welcome to {APP_NAME}",
            "Cenno needs access to your webcam to track hand gestures.\n\n"
            "1. Open Windows Settings > Privacy & security > Camera\n"
            "   and make sure camera access is allowed.\n"
            "2. You can also jump there from the tray icon: "
            "\"Open Camera settings\".\n\n"
            "No Accessibility permission is needed on Windows. Gestures work\n"
            "right away once the camera is allowed.",
            dark=self.dark,
        )
        self.settings["first_run"] = False
        save_settings(self.settings)

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
            # Remember a dragged position (free mode) after a 0.7 s settle.
            self._remember_drag()
            # Periodically re-check the Windows dark/light theme.
            self._theme_tick += 1
            if self._theme_tick >= 150:  # ~5 s at 33 ms
                self._theme_tick = 0
                dark = self._effective_dark()
                self.tracker.reduce_motion = theme.reduce_motion()
                if dark != self.dark:
                    self.dark = dark
                    self.tracker.dark = dark
                    if self.preview is not None:
                        self.preview.apply_theme(dark)
        except Exception as exc:
            print(f"WARN: preview tick: {exc}")
        self.root.after(33, self._tick_preview)   # ~30 fps

    def _remember_drag(self):
        """Save the preview's spot after it has been dragged (and let go)."""
        if (self.settings["preview_corner"] != "free"
                or not self.preview or not self.preview.visible):
            self._drag_since = None
            return
        pos = self.preview.origin()
        stored = self.settings.get("preview_pos")
        if stored is not None and tuple(stored) == pos:
            self._drag_since = None
            return
        now = time.time()
        if self._drag_since is None:
            self._drag_since = now
        elif now - self._drag_since > 0.7:      # stopped moving: save once
            self.settings["preview_pos"] = list(pos)
            self.preview.pos = tuple(pos)
            save_settings(self.settings)
            self._drag_since = None

    def _tick_status(self):
        if not self._alive:
            return
        try:
            if self.icon:
                self.icon.title = f"{APP_NAME}: {self.tracker.status}"
            self._update_icon_state()
            # 4 Hz is enough to notice a screen being plugged in, unplugged or
            # dragged to another spot, and cheap enough to leave running.
            if self.tracker.refresh_displays() and self.preview is not None:
                # A screen came or went: keep the preview where it is, but
                # make sure it is still on a screen that exists.
                self.preview.place()
            if (
                self.tracker.last_action
                and not self._gesture_notified
            ):
                self._gesture_notified = True
                self._notify("Cenno", f"First gesture: {self.tracker.last_action}")
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
        self._sync_dictation()
        # Where the hand reaches: one screen or every screen.
        self.tracker.dispatcher.set_display_mode(
            self.settings.get("display_mode", core.DISPLAY_MODE_CURRENT))
        self.tracker.start()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        # Prevent accidentally closing the hidden root via Alt+F4.
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        # Effective preview theme from settings["theme"] (system|light|dark).
        self.dark = self._effective_dark()
        self.tracker.dark = self.dark
        self.tracker.reduce_motion = theme.reduce_motion()
        theme.installed_families()      # warm the font cache for the dialogs
        try:
            size = self._preview_size()
            pos = (self.settings.get("preview_pos")
                   if self.settings["preview_corner"] == "free" else None)
            self.preview = TkPreview(self.root, self.settings["preview_corner"],
                                     size=size, pos=pos, dark=self.dark,
                                     layout=lambda: self.tracker.dispatcher.layout)
        except Exception:
            print("WARN: preview unavailable:\n" + traceback.format_exc())
            self.settings["preview"] = False
            self.preview = None

        self.icon = self._build_tray()
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()

        # First-run welcome: camera permission guidance (one time).
        if self.settings.get("first_run"):
            self._show_welcome()

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

    # Send the prints to the log file first: an app has no Terminal, and the
    # engine says what it is doing (screens, gestures) from the start.
    if getattr(sys, "frozen", False):
        setup_logging()

    app = CennoApp()

    # Launched via the cenno:// protocol: apply on/off/toggle and exit.
    # A running tray instance picks up the saved setting on its next tick.
    if len(sys.argv) > 1:
        action = handle_cenno_url(sys.argv[1])
        if action in ("on", "off", "toggle"):
            if action == "toggle":
                app._set_enabled(not app.settings["enabled"])
            else:
                app._set_enabled(action == "on")
            return

    app.run()


if __name__ == "__main__":
    main()
