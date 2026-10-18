"""
newMotion: menu bar app for macOS.

Wraps the gesture engine from hand_desktop_switcher_claude.py in a normal Mac
app: a menu bar icon, no Terminal, optional camera preview, pause, mouse
control on/off, launch at login and permission helpers.

Threads
  * main thread   : the menu bar (rumps / AppKit) and the preview window
  * camera thread : capture -> MediaPipe -> GestureEngine -> Dispatcher
  * dispatcher    : its own worker / scroll / pointer threads (see core)
"""

import json
import os
import sys
import threading
import time
import traceback

import rumps

import hand_desktop_switcher_claude as core

APP_NAME = "newMotion"
VERSION = "0.1.0"
SUPPORT_DIR = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
LOG_PATH = os.path.expanduser(f"~/Library/Logs/{APP_NAME}.log")
SETTINGS_PATH = os.path.join(SUPPORT_DIR, "settings.json")
SUPPORT_URL = "https://ko-fi.com/sapucaialuann"
DEFAULT_SETTINGS = {"enabled": True, "preview": True, "mouse": True,
                    "preview_corner": "top_right",
                    "dictation": "auto", "dictation_shortcut": ""}
DICTATION_MODES = (("auto", "Automatic (Wispr Flow if running, else Apple)"),
                   ("wispr", "Wispr Flow"), ("apple", "Apple Dictation"),
                   ("custom", "Other app (custom shortcut)..."))
PREVIEW_W, PREVIEW_H = 280, 210        # floating corner preview (points)
PREVIEW_MARGIN = 12
CORNERS = (("top_right", "Top right (default)"), ("top_left", "Top left"),
           ("bottom_right", "Bottom right"), ("bottom_left", "Bottom left"))

POINTER_EVENTS = ("pointer_move", "pointer_end", "click", "mouse_down", "mouse_up")


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
    try:
        with open(SETTINGS_PATH) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return dict(DEFAULT_SETTINGS)


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
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.preview_frame = None
        self.status = "Starting camera..."
        self.last_action, self.last_action_time = "", -1e9
        self.fps = 0.0
        self.camera_requested = False

    # --- helpers ---
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
        hands = mp_hands.Hands(static_image_mode=False, max_num_hands=1,
                               model_complexity=core.MODEL_COMPLEXITY,
                               min_detection_confidence=0.6,
                               min_tracking_confidence=0.5)
        cap = None
        frames, fps_t0 = 0, time.monotonic()
        try:
            while not self.stop_flag.is_set():
                if not self.settings["enabled"]:
                    # Switched off: release the camera (its light goes off).
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

                pts = None
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
                    self.fps, frames, fps_t0 = frames / (now - fps_t0), 0, now

                if self.settings["preview"]:
                    jpg = self._make_preview(cv2, drawing, mp_hands, frame, hl, now)
                    with self.lock:
                        self.preview_frame = jpg
        finally:
            if cap is not None:
                cap.release()
            hands.close()

    def _make_preview(self, cv2, drawing, mp_hands, frame, hl, now):
        """Small preview with a compact HUD, encoded as JPEG for the panel."""
        h, w = frame.shape[:2]
        if hl is not None:
            drawing.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)
            if self.engine.pose == "point" and self.settings["mouse"]:
                x0, y0, x1, y1 = core.POINTER_BOX
                cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), (0, 255, 255), 2)
        # Render at 2x the panel size so it stays sharp on Retina screens.
        small = cv2.resize(frame, (PREVIEW_W * 2, PREVIEW_H * 2), interpolation=cv2.INTER_AREA)
        sh, sw = small.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX

        def text(s, x, y, scale, color, thick):
            cv2.putText(small, s, (x + 2, y + 2), font, scale, (0, 0, 0), thick, cv2.LINE_AA)
            cv2.putText(small, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

        paused = self.engine.paused
        pose = self.engine.pose if self.engine.pose != "none" else "no hand"
        text("PAUSED" if paused else pose, 16, 38, 0.9,
             (80, 80, 255) if paused else (255, 255, 255), 2)
        if now - self.last_action_time < core.ACTION_FLASH_SECONDS:
            (tw, _), _ = cv2.getTextSize(self.last_action, font, 1.1, 3)
            text(self.last_action, max(10, (sw - tw) // 2), sh - 24, 1.1, (90, 255, 90), 3)
        if paused:
            cv2.rectangle(small, (0, 0), (sw - 1, sh - 1), (80, 80, 255), 6)
        ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return jpg.tobytes() if ok else None


class MiniPreview:
    """Borderless floating panel in a screen corner: above all apps, on
    every Space (also over full-screen apps), and clicks pass through it."""

    def __init__(self, corner="top_right"):
        import AppKit
        self.AK = AppKit
        self.corner = corner
        style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (PREVIEW_W, PREVIEW_H)), style, AppKit.NSBackingStoreBuffered, False)
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
        panel.setAlphaValue_(0.94)
        view = AppKit.NSImageView.alloc().initWithFrame_(((0, 0), (PREVIEW_W, PREVIEW_H)))
        view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(14)
        view.layer().setMasksToBounds_(True)
        view.layer().setBackgroundColor_(AppKit.NSColor.blackColor().CGColor())
        panel.setContentView_(view)
        self.panel, self.view = panel, view
        self.visible = False
        self.place()

    def place(self):
        """Chosen corner of the main screen (top corners sit under the menu
        bar, bottom corners above the Dock)."""
        vf = self.AK.NSScreen.mainScreen().visibleFrame()
        left = self.corner.endswith("left")
        top = self.corner.startswith("top")
        x = vf.origin.x + (PREVIEW_MARGIN if left
                           else vf.size.width - PREVIEW_W - PREVIEW_MARGIN)
        y = vf.origin.y + (vf.size.height - PREVIEW_H - PREVIEW_MARGIN if top
                           else PREVIEW_MARGIN)
        self.panel.setFrameOrigin_((x, y))

    def set_corner(self, corner):
        self.corner = corner
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

class NewMotionApp(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME, title="✋", quit_button=None)
        self.settings = load_settings()
        self.tracker = Tracker(self.settings)
        self.preview = None
        self.icon_set = False
        self.ax_ok = None

        self.status_item = rumps.MenuItem("Starting...")
        self.pause_item = rumps.MenuItem("Pause gestures", callback=self.toggle_pause, key="p")
        self.enabled_item = rumps.MenuItem("newMotion on", callback=self.toggle_enabled, key="o")
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
        self.mouse_item = rumps.MenuItem("Mouse control (point + pinch)", callback=self.toggle_mouse)
        self.dictation_menu = rumps.MenuItem("Dictation (hang loose)")
        self.dictation_items = {}
        for key, label in DICTATION_MODES:
            item = rumps.MenuItem(label, callback=self.set_dictation)
            item.mode_key = key
            self.dictation_menu.add(item)
            self.dictation_items[key] = item
        self.ax_item = rumps.MenuItem("Allow Accessibility...", callback=self.fix_accessibility)
        self.login_item = rumps.MenuItem("Open at login", callback=self.toggle_login)
        gestures = rumps.MenuItem("Gestures")
        for line in core.HELP_LINES:
            gestures.add(rumps.MenuItem(line))
        perms = rumps.MenuItem("Permissions")
        perms.add(rumps.MenuItem("Open Camera settings",
                                 callback=lambda _: open_settings_pane("Privacy_Camera")))
        perms.add(rumps.MenuItem("Open Accessibility settings",
                                 callback=lambda _: open_settings_pane("Privacy_Accessibility")))
        perms.add(rumps.MenuItem("Open log file",
                                 callback=lambda _: os.system(f"open -a Console '{LOG_PATH}'")))
        self.menu = [self.status_item, self.ax_item, None, self.enabled_item,
                     self.pause_item, self.preview_menu,
                     self.mouse_item, self.dictation_menu, None, gestures, perms,
                     self.login_item, None,
                     rumps.MenuItem("Support newMotion ☕",
                                    callback=lambda _: os.system(f"open '{SUPPORT_URL}'")),
                     rumps.MenuItem(f"About {APP_NAME} {VERSION}"),
                     rumps.MenuItem("Quit newMotion", callback=self.quit_app, key="q")]
        self._sync_checks()

        self._register_url_handler()
        self.tracker.start()
        self.ui_timer = rumps.Timer(self.tick_ui, 0.25)
        self.ui_timer.start()
        self.preview_timer = rumps.Timer(self.tick_preview, 1 / 30)
        self.preview_timer.start()
        self.perm_checked = False

    # --- menu state ---
    def _sync_checks(self):
        self.pause_item.state = int(self.tracker.engine.paused)
        self.preview_item.state = int(self.settings["preview"])
        self.enabled_item.state = int(self.settings["enabled"])
        for key, item in self.dictation_items.items():
            item.state = int(self.settings["dictation"] == key)
        sc = self.settings.get("dictation_shortcut") or ""
        self.dictation_items["custom"].title = (
            f"Other app: {sc}  (change...)" if sc else "Other app (custom shortcut)...")
        d = self.tracker.dispatcher
        d.dictation_mode = self.settings["dictation"]
        d.dictation_shortcut = sc
        for key, item in self.corner_items.items():
            item.state = int(self.settings["preview_corner"] == key)
        self.mouse_item.state = int(self.settings["mouse"])
        self.login_item.state = int(login_item_enabled())

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
                self._notify("newMotion is ready", "Accessibility is on. Gestures can now control your Mac.")
            self.ax_ok = ok
        self.ax_item.title = ("Allow Accessibility... (required)" if not self.ax_ok
                              else "Accessibility: allowed")
        self.status_item.title = self.tracker.status
        paused = self.tracker.engine.paused
        if self.pause_item.state != int(paused):
            self.pause_item.state = int(paused)
        dim = paused or not self.settings["enabled"]
        if not self.icon_set or getattr(self, "_icon_paused", None) != dim:
            self._icon_paused = dim
            self._set_icon(dim)

    def tick_preview(self, _):
        if self.preview is None:
            try:
                self.preview = MiniPreview(self.settings["preview_corner"])
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

    def _notify(self, title, msg):
        try:
            rumps.notification(APP_NAME, title, msg)
        except Exception as exc:
            print(f"WARN: notification failed: {exc}")

    def fix_accessibility(self, _):
        if accessibility_trusted():
            rumps.alert(APP_NAME, "Accessibility is already allowed.")
            return
        choice = rumps.alert(
            title="Allow newMotion to control your Mac",
            message=("newMotion needs Accessibility access to switch Spaces, scroll, "
                     "change volume and move the mouse.\n\n"
                     "1. Click Open Settings.\n"
                     "2. Turn on newMotion in the list (use + to add it if it is missing).\n"
                     "3. Gestures start working right away."),
            ok="Open Settings", cancel="Later")
        if choice == 1:
            open_settings_pane("Privacy_Accessibility")

    # --- callbacks ---
    def toggle_pause(self, _):
        self.tracker.set_paused(not self.tracker.engine.paused)
        self._sync_checks()

    def toggle_preview(self, _):
        self.settings["preview"] = not self.settings["preview"]
        save_settings(self.settings)
        self._sync_checks()

    def toggle_enabled(self, _):
        self.set_enabled(not self.settings["enabled"])

    def set_enabled(self, on):
        if self.settings["enabled"] == on:
            return
        self.settings["enabled"] = on
        save_settings(self.settings)
        self._sync_checks()
        print(f"newMotion {'on' if on else 'off'}")

    def _register_url_handler(self):
        """newmotion://on, newmotion://off, newmotion://toggle (for Voice
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
        save_settings(self.settings)
        if self.preview:
            self.preview.set_corner(sender.corner_key)
        self._sync_checks()

    def set_dictation(self, sender):
        mode = sender.mode_key
        if mode == "custom":
            w = rumps.Window(
                title="Dictation shortcut",
                message=("Type the shortcut your dictation app uses to start and stop "
                         "(toggle / hands-free mode), for example:\n"
                         "  ctrl+option+d    cmd+shift+space    fn+space    f5\n\n"
                         "Modifiers: cmd, ctrl, option, shift, fn."),
                default_text=self.settings.get("dictation_shortcut") or "",
                ok="Save", cancel="Cancel", dimensions=(260, 24))
            r = w.run()
            if not r.clicked or not r.text.strip():
                return
            self.settings["dictation_shortcut"] = r.text.strip().lower()
        self.settings["dictation"] = mode
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
    NewMotionApp().run()


if __name__ == "__main__":
    main()
