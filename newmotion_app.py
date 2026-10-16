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
DEFAULT_SETTINGS = {"preview": True, "mouse": True, "help_overlay": False}

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
        print(f"WARN: accessibility check unavailable: {exc}")
        return True


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
                if cap is None or not cap.isOpened():
                    perm = camera_authorized()
                    if perm == "denied":
                        self.status = "Camera access denied"
                        time.sleep(1.0)
                        continue
                    if perm == "undetermined":
                        self.status = "Waiting for camera permission"
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
                    self._draw_hud(cv2, drawing, mp_hands, frame, hl, pts, now)
                    with self.lock:
                        self.preview_frame = frame
        finally:
            if cap is not None:
                cap.release()
            hands.close()

    def _draw_hud(self, cv2, drawing, mp_hands, frame, hl, pts, now):
        h, w = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX

        def text(s, y, scale=0.5, color=(230, 230, 230), thick=1, x=10):
            cv2.putText(frame, s, (x + 1, y + 1), font, scale, (0, 0, 0), thick, cv2.LINE_AA)
            cv2.putText(frame, s, (x, y), font, scale, color, thick, cv2.LINE_AA)

        if hl is not None:
            drawing.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)
            if self.engine.pose == "point" and self.settings["mouse"]:
                x0, y0, x1, y1 = core.POINTER_BOX
                cv2.rectangle(frame, (int(x0 * w), int(y0 * h)),
                              (int(x1 * w), int(y1 * h)), (0, 255, 255), 1)
        paused = self.engine.paused
        text(f"{'PAUSED' if paused else 'ACTIVE'}  {self.engine.pose}", 25, 0.6,
             (80, 80, 255) if paused else (255, 255, 255), 2)
        if now - self.last_action_time < core.ACTION_FLASH_SECONDS:
            text(self.last_action, 55, 0.8, (0, 255, 0), 2)
        if self.settings["help_overlay"]:
            y0 = h - 20 - 18 * len(core.HELP_LINES)
            for i, line in enumerate(core.HELP_LINES):
                text(line, y0 + 18 * i, 0.45)
        text(f"{self.fps:4.1f} fps", h - 10, 0.4, (180, 180, 180))


# =============================================================================
# Menu bar app
# =============================================================================

class NewMotionApp(rumps.App):
    def __init__(self):
        super().__init__(APP_NAME, title="✋", quit_button=None)
        self.settings = load_settings()
        self.tracker = Tracker(self.settings)
        self.preview_open = False
        self.icon_set = False

        self.status_item = rumps.MenuItem("Starting...")
        self.pause_item = rumps.MenuItem("Pause gestures", callback=self.toggle_pause, key="p")
        self.preview_item = rumps.MenuItem("Show camera preview", callback=self.toggle_preview)
        self.mouse_item = rumps.MenuItem("Mouse control (point + pinch)", callback=self.toggle_mouse)
        self.help_item = rumps.MenuItem("Gesture help on preview", callback=self.toggle_help)
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
        self.menu = [self.status_item, None, self.pause_item, self.preview_item,
                     self.mouse_item, self.help_item, None, gestures, perms,
                     self.login_item, None,
                     rumps.MenuItem(f"About {APP_NAME} {VERSION}"),
                     rumps.MenuItem("Quit newMotion", callback=self.quit_app, key="q")]
        self._sync_checks()

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
        self.mouse_item.state = int(self.settings["mouse"])
        self.help_item.state = int(self.settings["help_overlay"])
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
        if not self.perm_checked:
            self.perm_checked = True
            if not accessibility_trusted(prompt=True):
                try:
                    rumps.notification(APP_NAME, "Allow Accessibility",
                                       "newMotion needs Accessibility access to switch Spaces, "
                                       "scroll and move the mouse. Enable it in System Settings, "
                                       "then reopen newMotion.")
                except Exception as exc:
                    print(f"WARN: notification failed: {exc}")
        status = self.tracker.status
        if not accessibility_trusted():
            status += " (needs Accessibility)"
        self.status_item.title = status
        paused = self.tracker.engine.paused
        if self.pause_item.state != int(paused):
            self.pause_item.state = int(paused)
        if not self.icon_set or getattr(self, "_icon_paused", None) != paused:
            self._icon_paused = paused
            self._set_icon(paused)

    def tick_preview(self, _):
        import cv2
        if not self.settings["preview"]:
            if self.preview_open:
                cv2.destroyWindow(core.WINDOW_TITLE)
                cv2.waitKey(1)
                self.preview_open = False
            return
        with self.tracker.lock:
            frame = self.tracker.preview_frame
            self.tracker.preview_frame = None
        if frame is None:
            return
        cv2.imshow(core.WINDOW_TITLE, frame)
        self.preview_open = True
        key = cv2.waitKey(1) & 0xFF
        if key == ord("p"):
            self.toggle_pause(None)
        # Closing the window with the red button turns the preview off.
        try:
            if cv2.getWindowProperty(core.WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                self.settings["preview"] = False
                save_settings(self.settings)
                self._sync_checks()
                self.preview_open = False
        except cv2.error:
            pass

    # --- callbacks ---
    def toggle_pause(self, _):
        self.tracker.set_paused(not self.tracker.engine.paused)
        self._sync_checks()

    def toggle_preview(self, _):
        self.settings["preview"] = not self.settings["preview"]
        save_settings(self.settings)
        self._sync_checks()

    def toggle_mouse(self, _):
        self.settings["mouse"] = not self.settings["mouse"]
        if not self.settings["mouse"]:
            self.tracker.dispatcher.submit("pointer_end", None)
        save_settings(self.settings)
        self._sync_checks()

    def toggle_help(self, _):
        self.settings["help_overlay"] = not self.settings["help_overlay"]
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
