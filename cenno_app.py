"""
Cenno: menu bar app for macOS.

Wraps the gesture engine from hand_desktop_switcher.py in a normal Mac
app: a menu bar icon, no Terminal, optional camera preview, pause, mouse
control on/off, launch at login and permission helpers.

Threads
  * main thread   : the menu bar (rumps / AppKit) and the preview window
  * camera thread : capture -> MediaPipe -> GestureEngine -> Dispatcher
  * dispatcher    : its own worker / scroll / pointer threads (see core)
"""

import json
import os
import queue
import sys
import threading
import time
import traceback

import rumps

import hand_desktop_switcher as core
from pointer_box import pointer_box_style
import app_version
import headzone
import onboarding
import onboarding_mac
import recorder_mac
import shortcuts
import theme

APP_NAME = "Cenno"
VERSION = app_version.read_version()
SUPPORT_DIR = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
LOG_PATH = os.path.expanduser(f"~/Library/Logs/{APP_NAME}.log")
SETTINGS_PATH = os.path.join(SUPPORT_DIR, "settings.json")

# One-time move of settings from the app's old name (newMotion).
_OLD_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/newMotion")
if os.path.isdir(_OLD_SUPPORT_DIR) and not os.path.exists(SUPPORT_DIR):
    try:
        os.rename(_OLD_SUPPORT_DIR, SUPPORT_DIR)
    except OSError:
        pass
SUPPORT_URL = "https://ko-fi.com/sapucaialuann"
DEFAULT_SETTINGS = {"settings_version": 2,
                    "enabled": True, "preview": True, "mouse": True,
                    "preview_corner": "top_right",
                    "preview_size": "medium", "preview_pos": None,
                    "dictation": "apple", "dictation_toggle": None,
                    "dictation_ptt": None,
                    "display_mode": "current",
                    "pointer_mode": core.POINTER_MODE,
                    "scroll_mode": core.SCROLL_MODE}
WISPR_APP = "/Applications/Wispr Flow.app"
DISPLAY_MODES = (("current", "Current display"),
                 ("all", "All displays"))
POINTER_MODES = (("relative", "Trackpad: cursor follows your hand's movement"),
                 ("absolute", "Aim: hand position is screen position"))
SCROLL_MODES = (("joystick", "Gas pedal: hold below or above to scroll"),
                ("drag", "Drag the page, flick to glide"))
PREVIEW_W, PREVIEW_H = 280, 210        # floating corner preview (points)
PREVIEW_SIZES = (("small", "Small", (200, 150)),
                 ("medium", "Medium (default)", (280, 210)),
                 ("large", "Large", (400, 300)))
PREVIEW_PX = [PREVIEW_W, PREVIEW_H]    # current panel size, read by the camera thread
PREVIEW_MARGIN = theme.SPACE[3]
PRIVACY_LINE = "Runs on your Mac. Nothing leaves it."
SUPPORT_LINE = "Cenno is free. If it helps you, you can support it on Ko-fi."


def gesture_lines():
    """Menu list in the 'Gesture · Action' pattern (swipe direction follows
    the engine's natural-swipe setting)."""
    prev_dir, next_dir = ("right", "left") if core.NATURAL_SWIPE else ("left", "right")
    return (f"Slap {prev_dir} · Previous Space",
            f"Slap {next_dir} · Next Space",
            "Swipe up · Mission Control",
            "Swipe down · Minimize window",
            "Two fingers below or above start · Scroll",
            "Two fingers swipe · Back or forward",
            "Point sideways · Move cursor",
            "Pinch thumb + index · Click, twice to double click, hold to drag",
            "OK sign and twist · Volume",
            "Thumbs up, hold · Play or pause",
            "Thumbs down, hold · Undo dictated text",
            "Thumb left or right · Arrow key, hold to repeat",
            "Hang loose, hold · Dictation on or off",
            "Hang loose by your ear · Push to talk",
            "Open hand, gather fingertips · Spotlight",
            "Wave, short strokes side to side · Lock screen, wave again to wake it",
            "Rock horns, hold · Pause or resume gestures")
CORNERS = (("top_right", "Top right (default)"), ("top_left", "Top left"),
           ("bottom_right", "Bottom right"), ("bottom_left", "Bottom left"),
           ("free", "Anywhere (drag to move)"))

POINTER_EVENTS = ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up",
                  "display_step")

# The engine events the welcome tour listens to (the groups in onboarding.py).
ONBOARDING_EVENTS = frozenset(onboarding.SPACE_EVENTS + onboarding.PAUSE_EVENTS
                               + onboarding.SCROLL_EVENTS + onboarding.PINCH_EVENTS
                               + (onboarding.EVENT_PLAY_PAUSE,))


# =============================================================================
# Logging (an app has no Terminal: send prints to a log file)
# =============================================================================

def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        if os.path.getsize(LOG_PATH) > 2_000_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    f = open(LOG_PATH, "a", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n===== {APP_NAME} {VERSION} started {time.ctime()} =====")


def load_settings():
    """The user's settings, and whether the settings file was already there.

    An existing settings file means an existing user: the welcome tour
    only opens for a brand-new one.
    """
    existed = os.path.exists(SETTINGS_PATH)
    try:
        with open(SETTINGS_PATH) as f:
            raw = json.load(f)
    except Exception:
        return dict(DEFAULT_SETTINGS), existed
    migrated = shortcuts.migrate_dictation(raw, "Darwin", os.path.isdir(WISPR_APP))
    s = {**DEFAULT_SETTINGS, **migrated}
    for key in ("dictation_toggle", "dictation_ptt"):
        if not shortcuts.is_valid(s[key]):
            s[key] = None
    if s["dictation"] not in ("apple", "shortcut"):
        s["dictation"] = "apple"
    if migrated != raw:
        save_settings(s)
    return s, existed


def save_settings(s):
    try:
        os.makedirs(SUPPORT_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(s, f, indent=2)
    except Exception as exc:
        print(f"WARN: could not save settings: {exc}")


# =============================================================================
# macOS permissions
# =============================================================================

def accessibility_trusted(prompt=False):
    """True if macOS lets this app send keys / mouse events."""
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception as exc:
        print(f"WARN: pyobjc accessibility check failed ({exc}); using ctypes")
    try:
        import ctypes
        hi = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        hi.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(hi.AXIsProcessTrusted())
    except Exception as exc:
        print(f"WARN: accessibility check unavailable: {exc}")
        return False


def camera_authorized():
    """'authorized', 'denied', 'undetermined' or 'unknown'."""
    try:
        import AVFoundation
        st = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeVideo)
        return {3: "authorized", 2: "denied", 1: "denied", 0: "undetermined"}.get(st, "unknown")
    except Exception:
        return "unknown"


def request_camera():
    try:
        import AVFoundation
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
            AVFoundation.AVMediaTypeVideo, lambda granted: print(f"camera granted={granted}"))
    except Exception as exc:
        print(f"WARN: camera request failed: {exc}")


def open_settings_pane(anchor):
    os.system(f"open 'x-apple.systempreferences:com.apple.preference.security?{anchor}'")


# =============================================================================
# Camera / gesture thread
# =============================================================================

class Tracker(threading.Thread):
    def __init__(self, settings):
        super().__init__(daemon=True)
        self.settings = settings
        self.engine = core.GestureEngine()
        self.dispatcher = core.Dispatcher()
        self.engine.can_step_display = self.dispatcher.can_step
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.preview_frame = None
        self.status = "Starting camera"
        self.last_action, self.last_action_time = "", -1e9
        self.fps = 0.0
        self.camera_requested = False
        self.dark = False                  # set from the main thread (tick_ui)
        self.reduce_motion = False
        # The welcome tour watches the engine and the camera from here.
        self.onboarding_events = queue.Queue()
        self.onboarding_frame = None
        self.onboarding_preview = False

    # --- helpers ---
    def set_paused(self, paused):
        self.engine.paused = paused
        self.dispatcher.submit("pointer_end", None)

    @property
    def displays_count(self):
        """How many screens macOS reports right now."""
        return self.dispatcher.layout.count

    @property
    def hand_tracked(self):
        """True when the camera sees a hand right now."""
        return self.engine.pose != "none"

    def refresh_displays(self):
        """Re-read the screen layout.  True when it changed (a display was
        plugged in, unplugged or moved)."""
        return self.dispatcher.refresh_displays()

    def run(self):
        try:
            self._loop()
        except Exception:
            print("FATAL in camera thread:\n" + traceback.format_exc())
            self.status = "Error · open the log file"

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
        hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                               model_complexity=core.MODEL_COMPLEXITY,
                               min_detection_confidence=0.6,
                               min_tracking_confidence=0.5)
        face_tracker = core.FaceTracker(mp.solutions.face_detection)
        cap = None
        frames, fps_t0 = 0, time.monotonic()
        fps_logged = fps_t0
        try:
            while not self.stop_flag.is_set():
                if not self.settings["enabled"]:
                    # Switched off: release the camera (its light goes off).
                    if cap is not None:
                        cap.release()
                        cap = None
                        self.dispatcher.submit("pointer_end", None)
                        for name, n in self.engine.end_ptt():
                            self.dispatcher.submit(name, n)
                    self.status = "Off"
                    with self.lock:
                        self.preview_frame = None
                    time.sleep(0.2)
                    continue
                if cap is None or not cap.isOpened():
                    perm = camera_authorized()
                    if perm == "denied":
                        self.status = "Camera access denied"
                        time.sleep(1.0)
                        continue
                    if perm == "undetermined":
                        self.status = "Waiting for camera permission"
                        if not self.camera_requested:
                            self.camera_requested = True
                            request_camera()
                        time.sleep(1.0)
                        continue
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
                face = face_tracker.update(rgb, w, h, now)

                pts = None
                if res.multi_hand_landmarks:
                    hl = res.multi_hand_landmarks[0]
                    pts = [(p.x * w, p.y * h) for p in hl.landmark]
                    events = self.engine.update(pts, w, h, now, face=face)
                else:
                    hl = None
                    events = self.engine.no_hand(now)
                events = self.dispatcher.while_locked(events, now)

                for name, n in events:
                    if name in POINTER_EVENTS and not self.settings["mouse"]:
                        continue
                    self.dispatcher.submit(name, n)
                    if name in ONBOARDING_EVENTS:
                        # The tour watches the same events; they still do
                        # their real job.
                        self.onboarding_events.put(name)
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
                    self.fps, frames, fps_t0 = frames / (now - fps_t0), 0, now
                    if now - fps_logged >= 60.0:
                        print(f"fps: {self.fps:.1f}")   # for diagnosing slow tracking
                        fps_logged = now

                if self.settings["preview"] or self.onboarding_preview:
                    jpg = self._make_preview(cv2, drawing, mp_hands, frame, hl, now)
                    with self.lock:
                        self.preview_frame = jpg
                        self.onboarding_frame = jpg
        finally:
            if cap is not None:
                cap.release()
            hands.close()
            face_tracker.close()

    def _make_preview(self, cv2, drawing, mp_hands, frame, hl, now):
        """Small preview with status pills, encoded as JPEG for the panel."""
        dark = self.dark
        col = lambda name: theme.bgr(name, dark)
        h, w = frame.shape[:2]
        if hl is not None:
            drawing.draw_landmarks(
                frame, hl, mp_hands.HAND_CONNECTIONS,
                drawing.DrawingSpec(color=col("trace"), thickness=2, circle_radius=2),
                drawing.DrawingSpec(color=col("ink"), thickness=1))
            face = self.engine.debug.get("face_box")
            if self.engine.ptt_active and face is not None:
                cv2.rectangle(frame, (int(face[0]), int(face[1])),
                              (int(face[2]), int(face[3])), col("trace"), 2)
            style = pointer_box_style(self.engine.pose, self.settings["mouse"],
                                      self.engine.pointer_mode, self.engine.pinched)
            if style is not None:
                thick, color_name = style
                x0, y0, x1, y1 = core.POINTER_BOX
                cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), col(color_name), thick)
        # Render at 2x the panel size so it stays sharp on Retina screens.
        pw, ph = PREVIEW_PX
        small = cv2.resize(frame, (pw * 2, ph * 2), interpolation=cv2.INTER_AREA)
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
            wd = pill(x0, y0, "PAUSED", col("paper-raised"), col("ink"), col("line-strong"))
            if pose != "none":
                # Still show what is read, so a misread horns is visible.
                pill(x0 + wd + gap, y0, pose.upper(), col("paper-raised"), col("ink"),
                     col("line-strong"))
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


_DRAG_VIEW = None


def _drag_view_class():
    """Transparent view that lets a mouse drag move the preview window."""
    global _DRAG_VIEW
    if _DRAG_VIEW is None:
        import AppKit

        class CennoDragView(AppKit.NSView):
            # Cenno is a menu bar app, so it is never the active app and the
            # panel never becomes key. Without these, the first click is
            # eaten and background dragging never starts. Move the window
            # ourselves instead of relying on mouseDownCanMoveWindow.
            def acceptsFirstMouse_(self, event):
                return True

            def mouseDownCanMoveWindow(self):
                return True

            def mouseDown_(self, event):
                win = self.window()
                if win is not None and not win.ignoresMouseEvents():
                    win.performWindowDragWithEvent_(event)

        _DRAG_VIEW = CennoDragView
    return _DRAG_VIEW


class MiniPreview:
    """Borderless floating panel in a screen corner: above all apps, on
    every Space (also over full-screen apps), and clicks pass through it."""

    def __init__(self, corner="top_right", dark=False, size=(PREVIEW_W, PREVIEW_H), pos=None):
        import AppKit
        self.AK = AppKit
        self.corner = corner
        self.w, self.h = size
        self.pos = tuple(pos) if pos else None
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (self.w, self.h)), style, AppKit.NSBackingStoreBuffered, False)
        panel.setLevel_(AppKit.NSStatusWindowLevel)
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        view = AppKit.NSImageView.alloc().initWithFrame_(((0, 0), (self.w, self.h)))
        view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(theme.RADIUS_MD)
        view.layer().setMasksToBounds_(True)
        view.layer().setBorderWidth_(1)
        container = AppKit.NSView.alloc().initWithFrame_(((0, 0), (self.w, self.h)))
        container.setAutoresizesSubviews_(True)
        view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        container.addSubview_(view)
        grip = _drag_view_class().alloc().initWithFrame_(((0, 0), (self.w, self.h)))
        grip.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        container.addSubview_(grip)              # on top: lets the panel be dragged
        panel.setContentView_(container)
        self.panel, self.view = panel, view
        self.visible = False
        self.apply_theme(dark)
        self.place()

    def apply_theme(self, dark):
        layer = self.view.layer()
        layer.setBackgroundColor_(theme.ns_color("paper-sunk", dark).CGColor())
        layer.setBorderColor_(theme.ns_color("line", dark).CGColor())

    def _corner_origin(self, corner):
        vf = self.AK.NSScreen.mainScreen().visibleFrame()
        left = corner.endswith("left")
        top = corner.startswith("top")
        x = vf.origin.x + (PREVIEW_MARGIN if left
                           else vf.size.width - self.w - PREVIEW_MARGIN)
        y = vf.origin.y + (vf.size.height - self.h - PREVIEW_MARGIN if top
                           else PREVIEW_MARGIN)
        return x, y

    def _on_screen(self, x, y):
        """Keep a dragged position visible, e.g. after a monitor is unplugged."""
        for screen in self.AK.NSScreen.screens():
            vf = screen.visibleFrame()
            cx, cy = x + self.w / 2, y + self.h / 2
            if (vf.origin.x <= cx <= vf.origin.x + vf.size.width
                    and vf.origin.y <= cy <= vf.origin.y + vf.size.height):
                x = min(max(x, vf.origin.x), vf.origin.x + vf.size.width - self.w)
                y = min(max(y, vf.origin.y), vf.origin.y + vf.size.height - self.h)
                return x, y
        return None

    def place(self):
        """Chosen corner of the main screen (top corners sit under the menu
        bar, bottom corners above the Dock), or the spot it was dragged to."""
        free = self.corner == "free"
        # Click-through in corner mode; draggable in free mode.
        self.panel.setIgnoresMouseEvents_(not free)
        self.panel.setMovableByWindowBackground_(free)
        origin = None
        if free and self.pos:
            origin = self._on_screen(*self.pos)
        if origin is None:
            origin = self._corner_origin("top_right" if free else self.corner)
        self.panel.setFrameOrigin_(origin)

    def origin(self):
        o = self.panel.frame().origin
        return (round(o.x), round(o.y))

    def set_corner(self, corner):
        if corner == "free" and self.corner != "free":
            self.pos = self.origin()             # start from where it is now
        self.corner = corner
        self.place()

    def set_size(self, size):
        old_top = self.panel.frame().origin.y + self.h
        x = self.panel.frame().origin.x
        self.w, self.h = size
        self.panel.setContentSize_((self.w, self.h))
        if self.corner == "free":
            self.pos = (x, old_top - self.h)     # keep the top-left corner in place
        self.place()

    def show(self):
        if not self.visible:
            self.place()
            self.panel.orderFrontRegardless()
            self.visible = True

    def hide(self):
        if self.visible:
            self.panel.orderOut_(None)
            self.visible = False

    def set_jpeg(self, data):
        nsdata = self.AK.NSData.dataWithBytes_length_(data, len(data))
        img = self.AK.NSImage.alloc().initWithData_(nsdata)
        if img is not None:
            self.view.setImage_(img)


# =============================================================================
# Menu bar app
# =============================================================================

class CennoApp(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME, title=APP_NAME, quit_button=None)
        self.settings, settings_existed = load_settings()
        # A brand-new user gets the welcome tour, once the app is up.
        self.tour_pending = onboarding.needs_onboarding(self.settings, settings_existed)
        PREVIEW_PX[0], PREVIEW_PX[1] = self._preview_size()
        self.tracker = Tracker(self.settings)
        self.preview = None
        self.icon_set = False
        self.ax_ok = None
        self.onboarding_window = None

        self.status_item = rumps.MenuItem("Starting...")
        self.pause_item = rumps.MenuItem("Pause gestures", callback=self.toggle_pause, key="p")
        self.enabled_item = rumps.MenuItem("Cenno on", callback=self.toggle_enabled, key="o")
        self.preview_menu = rumps.MenuItem("Camera preview")
        self.preview_item = rumps.MenuItem("Show preview", callback=self.toggle_preview)
        self.preview_menu.add(self.preview_item)
        self.preview_menu.add(rumps.MenuItem("Position:"))
        self.corner_items = {}
        for key, label in CORNERS:
            item = rumps.MenuItem(label, callback=self.set_corner)
            item.corner_key = key
            self.preview_menu.add(item)
            self.corner_items[key] = item
        self.preview_menu.add(rumps.separator)
        self.preview_menu.add(rumps.MenuItem("Size:"))
        self.size_items = {}
        for key, label, _ in PREVIEW_SIZES:
            item = rumps.MenuItem(label, callback=self.set_preview_size)
            item.size_key = key
            self.preview_menu.add(item)
            self.size_items[key] = item
        self.mouse_item = rumps.MenuItem("Mouse control (point + pinch)", callback=self.toggle_mouse)
        self.displays_menu = None
        self.display_items = {}
        if self.tracker.displays_count > 1:
            self.displays_menu = self._make_display_menu()
        self.pointer_menu, self.pointer_items = self._make_mode_menu(
            "Pointer", POINTER_MODES, self.set_pointer_mode)
        self.scroll_menu, self.scroll_items = self._make_mode_menu(
            "Scrolling", SCROLL_MODES, self.set_scroll_mode)
        self.dictation_menu = rumps.MenuItem("Dictation (hang loose)")
        self.apple_item = rumps.MenuItem("Apple Dictation",
                                         callback=self.use_apple_dictation)
        self.app_item = rumps.MenuItem("Dictation app (record shortcut)...",
                                       callback=self.use_dictation_app)
        self.toggle_item = rumps.MenuItem("Record toggle shortcut...",
                                          callback=self.record_toggle)
        self.ptt_item = rumps.MenuItem("Record push-to-talk key...",
                                       callback=self.record_ptt)
        self.clear_ptt_item = rumps.MenuItem("Clear push-to-talk key",
                                             callback=self.clear_ptt)
        for item in (self.apple_item, self.app_item, rumps.separator,
                     self.toggle_item, self.ptt_item):
            self.dictation_menu.add(item)
        self.ax_item = rumps.MenuItem("Allow Accessibility...", callback=self.fix_accessibility)
        self.login_item = rumps.MenuItem("Open at login", callback=self.toggle_login)
        self.tour_item = rumps.MenuItem("Show the welcome tour again",
                                       callback=self.show_onboarding)
        gestures = rumps.MenuItem("Gestures")
        for line in gesture_lines():
            gestures.add(rumps.MenuItem(line))
        self.gestures_menu = gestures
        perms = rumps.MenuItem("Permissions")
        perms.add(rumps.MenuItem("Open Camera settings",
                                 callback=lambda _: open_settings_pane("Privacy_Camera")))
        perms.add(rumps.MenuItem("Open Accessibility settings",
                                 callback=lambda _: open_settings_pane("Privacy_Accessibility")))
        perms.add(rumps.MenuItem("Open log file",
                                 callback=lambda _: os.system(f"open -a Console '{LOG_PATH}'")))
        self.perms_menu = perms
        self._build_menu()
        self._sync_checks()

        self._register_url_handler()
        self.tracker.start()
        self.ui_timer = rumps.Timer(self.tick_ui, 0.25)
        self.ui_timer.start()
        self.preview_timer = rumps.Timer(self.tick_preview, 1 / 30)
        self.preview_timer.start()
        self.perm_checked = False
        self.dark = None

    def _make_mode_menu(self, title, modes, callback):
        menu = rumps.MenuItem(title)
        items = {}
        for key, label in modes:
            item = rumps.MenuItem(label, callback=callback)
            item.mode_key = key
            menu.add(item)
            items[key] = item
        return menu, items

    def _make_display_menu(self):
        """Submenu with the pointer mode, for setups with more than one
        screen.  With a single display there is nothing to choose, so it is
        not built at all."""
        menu = rumps.MenuItem("Displays")
        self.display_items = {}
        for key, label in DISPLAY_MODES:
            item = rumps.MenuItem(label, callback=self.set_display_mode)
            item.mode_key = key
            menu.add(item)
            self.display_items[key] = item
        menu.add(rumps.separator)
        menu.add(rumps.MenuItem("Move pointer to next display",
                                callback=self.next_display))
        return menu

    def _build_menu(self):
        menu = [self.status_item, self.ax_item, None, self.enabled_item,
                self.pause_item, self.preview_menu, self.mouse_item,
                self.pointer_menu, self.scroll_menu]
        if self.displays_menu is not None:
            menu.append(self.displays_menu)
        menu += [self.dictation_menu, None, self.gestures_menu, self.perms_menu,
                 self.login_item, self.tour_item, None,
                 rumps.MenuItem("Support Cenno on Ko-fi",
                                callback=lambda _: os.system(f"open '{SUPPORT_URL}'")),
                 rumps.MenuItem(f"About {APP_NAME} {VERSION}", callback=self.show_about),
                 rumps.MenuItem("Quit Cenno", callback=self.quit_app, key="q")]
        # rumps only adds to the menu it already has, so a rebuild (a screen
        # plugged in or out) failed halfway with "already in another menu"
        # and dropped everything after the Displays submenu, Dictation too.
        self.menu.clear()
        self.menu = menu

    def _sync_display_menu(self):
        """Show the Displays submenu while more than one screen is on, hide it
        again when the last extra one goes away."""
        if (self.tracker.displays_count > 1) == (self.displays_menu is not None):
            return
        self.displays_menu = (self._make_display_menu()
                              if self.tracker.displays_count > 1 else None)
        self._build_menu()
        self._sync_checks()

    # --- menu state ---
    def _sync_checks(self):
        self.pause_item.state = int(self.tracker.engine.paused)
        self.preview_item.state = int(self.settings["preview"])
        self.enabled_item.state = int(self.settings["enabled"])
        self._sync_dictation()
        d = self.tracker.dispatcher
        mode = self.settings.get("display_mode", core.DISPLAY_MODE_CURRENT)
        d.set_display_mode(mode)
        for key, item in self.display_items.items():
            item.state = int(mode == key)
        for key, item in self.corner_items.items():
            item.state = int(self.settings["preview_corner"] == key)
        for key, item in self.size_items.items():
            item.state = int(self.settings["preview_size"] == key)
        self.mouse_item.state = int(self.settings["mouse"])
        engine = self.tracker.engine
        engine.pointer_mode = self.settings["pointer_mode"]
        engine.scroll_mode = self.settings["scroll_mode"]
        for key, item in self.pointer_items.items():
            item.state = int(engine.pointer_mode == key)
        for key, item in self.scroll_items.items():
            item.state = int(engine.scroll_mode == key)
        self.login_item.state = int(login_item_enabled())

    def _sync_dictation(self):
        """Dictation menu texts and checks, and the dispatcher's copy."""
        mode = self.settings["dictation"]
        toggle, ptt = self.settings["dictation_toggle"], self.settings["dictation_ptt"]
        hotkeys = shortcuts.read_mac_hotkeys()

        def shown(sc):
            return shortcuts.menu_label(sc, "Darwin", hotkeys)

        self.apple_item.state = int(mode == "apple")
        self.app_item.state = int(mode == "shortcut")
        self.app_item.title = (f"Dictation app shortcut: {shown(toggle)}" if toggle
                               else "Dictation app (record shortcut)...")
        self.toggle_item.title = (f"Record toggle shortcut... ({shown(toggle)})"
                                  if toggle else "Record toggle shortcut...")
        self.ptt_item.title = ("Record push-to-talk key... "
                               f"({shown(ptt) if ptt else 'none: toggles'})")
        try:
            if ptt and self.clear_ptt_item.title not in self.dictation_menu:
                self.dictation_menu.add(self.clear_ptt_item)
            elif not ptt and self.clear_ptt_item.title in self.dictation_menu:
                del self.dictation_menu[self.clear_ptt_item.title]
        except Exception as exc:
            print(f"WARN: could not update the dictation menu: {exc}")
        d = self.tracker.dispatcher
        d.dictation_mode = mode
        d.dictation_toggle = toggle
        d.dictation_ptt = ptt

    def _set_icon(self, paused):
        """SF Symbol in the menu bar (falls back to the emoji title)."""
        try:
            import AppKit
            name = "hand.raised.slash" if paused else "hand.raised"
            img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, APP_NAME)
            if img is None:
                return
            img.setTemplate_(True)
            button = self._nsapp.nsstatusitem.button()
            button.setImage_(img)
            button.setTitle_("")
            self.icon_set = True
        except Exception as exc:
            print(f"WARN: could not set menu bar icon: {exc}")
            self.icon_set = True

    # --- timers (main thread) ---
    def tick_ui(self, _):
        dark = theme.system_is_dark()
        self.tracker.reduce_motion = theme.reduce_motion()
        # 4 Hz is enough to notice a screen being plugged in, unplugged or
        # dragged to another spot, and cheap enough to leave running.
        if self.tracker.refresh_displays():
            self._sync_display_menu()
        if dark != self.dark:
            self.dark = self.tracker.dark = dark
            if self.preview:
                self.preview.apply_theme(dark)
        if self.ax_ok is None:
            # First tick: ask macOS (shows its own prompt if it can) and,
            # if still not allowed, explain and offer to open the settings.
            self.ax_ok = accessibility_trusted(prompt=True)
            print(f"accessibility trusted at start: {self.ax_ok}")
            if not self.ax_ok:
                self.fix_accessibility(None)
        else:
            ok = accessibility_trusted()
            if ok and not self.ax_ok:
                print("accessibility granted")
                self._notify("Cenno is ready", "Accessibility is on. Gestures can now control your Mac.")
            self.ax_ok = ok
        self.ax_item.title = ("Allow Accessibility... (required)" if not self.ax_ok
                              else "Accessibility: allowed")
        self.status_item.title = self.tracker.status
        paused = self.tracker.engine.paused
        if self.pause_item.state != int(paused):
            self.pause_item.state = int(paused)
        dim = paused or not self.settings["enabled"]
        if dim:                      # no hand can let go of a held key now
            self.tracker.dispatcher.release_dictation()
        if not self.icon_set or getattr(self, "_icon_paused", None) != dim:
            self._icon_paused = dim
            self._set_icon(dim)
        self._feed_onboarding()
        if self.onboarding_window is not None:
            self.onboarding_window.tick()
        elif self.tour_pending:
            # The first tick: the app is up, so the tour can open.
            self.tour_pending = False
            self.show_onboarding(None)

    def tick_preview(self, _):
        if self.preview is None:
            try:
                self.preview = MiniPreview(self.settings["preview_corner"], bool(self.dark),
                                           self._preview_size(), self.settings.get("preview_pos"))
            except Exception:
                print("WARN: preview unavailable:\n" + traceback.format_exc())
                self.settings["preview"] = False
                self._sync_checks()
                self.preview = False
                return
        if self.preview is False:
            return
        if not (self.settings["preview"] and self.settings["enabled"]):
            self.preview.hide()
            return
        with self.tracker.lock:
            jpg = self.tracker.preview_frame
            self.tracker.preview_frame = None
        if jpg:
            self.preview.set_jpeg(jpg)
            self.preview.show()
        self._remember_drag()

    def _remember_drag(self):
        """Save the preview's spot after it has been dragged (and let go)."""
        if self.settings["preview_corner"] != "free" or not self.preview.visible:
            return
        pos = list(self.preview.origin())
        if pos == self.settings.get("preview_pos"):
            self._drag_since = None
            return
        now = time.time()
        if getattr(self, "_drag_since", None) is None:
            self._drag_since = now
        elif now - self._drag_since > 0.7:      # stopped moving: save once
            self.settings["preview_pos"] = pos
            self.preview.pos = tuple(pos)
            save_settings(self.settings)
            self._drag_since = None

    def _preview_size(self):
        for key, _, size in PREVIEW_SIZES:
            if key == self.settings.get("preview_size"):
                return size
        return (PREVIEW_W, PREVIEW_H)

    def _notify(self, title, msg):
        try:
            rumps.notification(APP_NAME, title, msg)
        except Exception as exc:
            print(f"WARN: notification failed: {exc}")

    def show_about(self, _):
        choice = rumps.alert(title=f"{APP_NAME} {VERSION}",
                             message=f"{PRIVACY_LINE}\n\n{SUPPORT_LINE}",
                             ok="Support on Ko-fi", cancel="Close")
        if choice == 1:
            os.system(f"open '{SUPPORT_URL}'")

    def fix_accessibility(self, _):
        if accessibility_trusted():
            rumps.alert(APP_NAME, "Accessibility is already allowed.")
            return
        choice = rumps.alert(
            title="Allow Cenno to control your Mac",
            message=("Cenno needs Accessibility access to switch Spaces, scroll, "
                     "change volume and move the mouse.\n\n"
                     "1. Click Open Settings.\n"
                     "2. Turn on Cenno in the list (use + to add it if it is missing).\n"
                     "3. Gestures start working right away."),
            ok="Open Settings", cancel="Later")
        if choice == 1:
            open_settings_pane("Privacy_Accessibility")

    # --- the welcome tour (#40) ---
    def _feed_onboarding(self):
        """Give the engine's events to the welcome tour, when it is open."""
        events = self.tracker.onboarding_events
        while True:
            try:
                name = events.get_nowait()
            except queue.Empty:
                return
            if self.onboarding_window is not None:
                self.onboarding_window.on_event(name)

    def show_onboarding(self, _sender=None):
        """Open the welcome tour window."""
        try:
            if self.onboarding_window is None:
                self.onboarding_window = onboarding_mac.OnboardingWindow(self)
            else:
                self.onboarding_window.restart()
            self.onboarding_window.show()
        except Exception:
            print("WARN: the welcome tour could not open:\n" + traceback.format_exc())

    def persist_settings(self):
        """Write the settings back to disk."""
        save_settings(self.settings)

    def accessibility_granted(self):
        """True when macOS lets Cenno press keys and move the mouse."""
        return accessibility_trusted()

    def open_accessibility_settings(self):
        """Open the Accessibility pane of System Settings."""
        open_settings_pane("Privacy_Accessibility")

    def open_keyboard_shortcuts(self):
        """Open the Keyboard Shortcuts pane of System Settings."""
        os.system("open 'x-apple.systempreferences:com.apple.preference.keyboard?Shortcuts'")

    # --- callbacks ---
    def toggle_pause(self, _):
        self.tracker.set_paused(not self.tracker.engine.paused)
        self._sync_checks()

    def toggle_preview(self, _):
        self.settings["preview"] = not self.settings["preview"]
        save_settings(self.settings)
        self._sync_checks()

    def set_display_mode(self, sender):
        """Where the hand's pointer box reaches: the display under the cursor,
        or every display laid out side by side."""
        self.settings["display_mode"] = sender.mode_key
        save_settings(self.settings)
        self._sync_checks()

    def set_pointer_mode(self, sender):
        self.tracker.dispatcher.submit("pointer_end", None)
        self.settings["pointer_mode"] = sender.mode_key
        save_settings(self.settings)
        self._sync_checks()

    def set_scroll_mode(self, sender):
        self.settings["scroll_mode"] = sender.mode_key
        save_settings(self.settings)
        self._sync_checks()

    def next_display(self, _):
        self.tracker.dispatcher.jump_to_next_display()

    def toggle_enabled(self, _):
        self.set_enabled(not self.settings["enabled"])

    def set_enabled(self, on):
        if self.settings["enabled"] == on:
            return
        self.settings["enabled"] = on
        save_settings(self.settings)
        self._sync_checks()
        print(f"Cenno {'on' if on else 'off'}")

    def _register_url_handler(self):
        """cenno://on, cenno://off, cenno://toggle (for Voice
        Control commands, Shortcuts, Raycast, or `open` in Terminal)."""
        try:
            import Foundation
            import objc
            app = self

            def fourcc(s):
                return int.from_bytes(s.encode(), "big")

            class URLHandler(Foundation.NSObject):
                @objc.typedSelector(b"v@:@@")
                def handleURL_withReply_(self, event, reply):
                    url = str(event.paramDescriptorForKeyword_(fourcc("----")).stringValue())
                    cmd = url.split("://", 1)[-1].strip("/").lower()
                    print(f"url command: {url}")
                    if cmd == "on":
                        app.set_enabled(True)
                    elif cmd == "off":
                        app.set_enabled(False)
                    elif cmd == "toggle":
                        app.set_enabled(not app.settings["enabled"])

            self._url_handler = URLHandler.alloc().init()
            Foundation.NSAppleEventManager.sharedAppleEventManager() \
                .setEventHandler_andSelector_forEventClass_andEventID_(
                    self._url_handler, "handleURL:withReply:",
                    fourcc("GURL"), fourcc("GURL"))
        except Exception:
            print("WARN: URL handler unavailable:\n" + traceback.format_exc())

    def set_corner(self, sender):
        self.settings["preview_corner"] = sender.corner_key
        if self.preview:
            self.preview.set_corner(sender.corner_key)
            if sender.corner_key == "free":
                self.settings["preview_pos"] = list(self.preview.origin())
        save_settings(self.settings)
        self._sync_checks()

    def set_preview_size(self, sender):
        self.settings["preview_size"] = sender.size_key
        size = self._preview_size()
        PREVIEW_PX[0], PREVIEW_PX[1] = size
        if self.preview:
            self.preview.set_size(size)
            if self.settings["preview_corner"] == "free":
                self.settings["preview_pos"] = list(self.preview.origin())
        save_settings(self.settings)
        self._sync_checks()

    def use_apple_dictation(self, _):
        self.settings["dictation"] = "apple"
        self._save_dictation()

    def use_dictation_app(self, _):
        if self.settings["dictation_toggle"]:
            self.settings["dictation"] = "shortcut"
            self._save_dictation()
        else:
            self.record_toggle(None)

    def _record(self, title, other, clash):
        """Ask for a shortcut until it differs from `other`; None on cancel."""
        while True:
            hotkeys = shortcuts.read_mac_hotkeys()
            sc = recorder_mac.record_shortcut(
                title, warn=lambda s: shortcuts.clash_message(s, "Darwin", hotkeys))
            if sc and shortcuts.same(sc, other):
                rumps.alert(APP_NAME, clash)
                continue
            return sc

    def record_toggle(self, _):
        sc = self._record("Press the toggle shortcut now...",
                          self.settings["dictation_ptt"],
                          "That's already your push-to-talk key. Try another.")
        if sc:
            self.settings["dictation_toggle"] = sc
            self.settings["dictation"] = "shortcut"
            self._save_dictation()

    def record_ptt(self, _):
        sc = self._record("Press the push-to-talk key now...",
                          self.settings["dictation_toggle"],
                          "That's already your toggle shortcut. Try another.")
        if sc:
            self.tracker.dispatcher.release_dictation()
            self.settings["dictation_ptt"] = sc
            self._save_dictation()

    def clear_ptt(self, _):
        self.tracker.dispatcher.release_dictation()
        self.settings["dictation_ptt"] = None
        self._save_dictation()

    def _save_dictation(self):
        save_settings(self.settings)
        self._sync_checks()

    def toggle_mouse(self, _):
        self.settings["mouse"] = not self.settings["mouse"]
        if not self.settings["mouse"]:
            self.tracker.dispatcher.submit("pointer_end", None)
        save_settings(self.settings)
        self._sync_checks()

    def toggle_login(self, _):
        set_login_item(not login_item_enabled())
        self._sync_checks()

    def quit_app(self, _):
        self.tracker.stop_flag.set()
        self.tracker.dispatcher.submit("pointer_end", None)
        self.tracker.dispatcher.release_dictation()
        time.sleep(0.2)
        rumps.quit_application()


# =============================================================================
# Open at login (macOS 13+ ServiceManagement)
# =============================================================================

def _service():
    try:
        from ServiceManagement import SMAppService
        return SMAppService.mainAppService()
    except Exception:
        return None


def login_item_enabled():
    svc = _service()
    try:
        return svc is not None and svc.status() == 1      # SMAppServiceStatusEnabled
    except Exception:
        return False


def set_login_item(enable):
    svc = _service()
    if svc is None:
        rumps.alert(APP_NAME, "Open at login needs macOS 13 or newer.")
        return
    try:
        if enable:
            ok, err = svc.registerAndReturnError_(None)
        else:
            ok, err = svc.unregisterAndReturnError_(None)
        if not ok:
            print(f"WARN: login item change failed: {err}")
    except Exception as exc:
        print(f"WARN: login item change failed: {exc}")


def main():
    if getattr(sys, "frozen", False):
        setup_logging()
    CennoApp().run()


if __name__ == "__main__":
    main()
