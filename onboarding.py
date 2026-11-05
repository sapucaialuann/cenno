"""Onboarding: the first-run tour that teaches one working gesture (#40).

Pure Python on purpose: no camera, no OS calls, no UI.  The macOS and the
Windows app drive the same steps and feed the gesture engine's event names
in, so the flow cannot drift between the two platforms.
"""

# =============================================================================
# Steps
# =============================================================================

STEPS_MACOS = ["welcome", "camera", "accessibility", "first_win", "pause",
               "second_gesture", "done"]
STEPS_WINDOWS = ["welcome", "camera", "first_win", "pause", "second_gesture",
                 "done"]


def steps_for(os_name):
    """The step names for "macos" or "windows"."""
    if os_name == "macos":
        return list(STEPS_MACOS)
    if os_name == "windows":
        return list(STEPS_WINDOWS)
    raise ValueError(f"unknown os: {os_name}")


# =============================================================================
# Gesture engine events
# =============================================================================

# Event names the engine hands to the Dispatcher (hand_desktop_switcher.py).
EVENT_SPACE_LEFT = "space_left"        # slap: switch Space
EVENT_SPACE_RIGHT = "space_right"      # slap: the other way round
EVENT_PAUSE_ON = "pause_on"            # rock horns: pause the gestures
EVENT_PAUSE_OFF = "pause_off"          # rock horns again: resume
EVENT_SCROLL_DRAG = "scroll_drag"      # two fingers held together: scroll
EVENT_SCROLL_FLING = "scroll_fling"    # a fast flick: scroll on
EVENT_CLICK = "click"                  # pinch: click
EVENT_MOUSE_DOWN = "mouse_down"        # pinch held: drag
EVENT_PLAY_PAUSE = "play_pause"        # thumbs up: play / pause

# Windows drives Alt+Tab from the same slap events, so one group covers both.
SPACE_EVENTS = (EVENT_SPACE_LEFT, EVENT_SPACE_RIGHT)
PAUSE_EVENTS = (EVENT_PAUSE_ON, EVENT_PAUSE_OFF)
SCROLL_EVENTS = (EVENT_SCROLL_DRAG, EVENT_SCROLL_FLING)
PINCH_EVENTS = (EVENT_CLICK, EVENT_MOUSE_DOWN)

PAUSE_TOGGLES_NEEDED = 2               # pause once, then resume again
MISSES_BEFORE_HINT = 3                 # failed tries before the one hint

# The second gesture the user can pick to try.
SECOND_GESTURE_CHOICES = ("scroll", "pointer", "play_pause")

SECOND_GESTURE_EVENTS = {
    "scroll": SCROLL_EVENTS,
    "pointer": PINCH_EVENTS,
    "play_pause": (EVENT_PLAY_PAUSE,),
}


# =============================================================================
# The tour
# =============================================================================

class Onboarding:
    """Which step is on screen, what completes it and what was skipped."""

    def __init__(self, os_name):
        self.os_name = os_name
        self.steps = steps_for(os_name)
        self.index = 0
        self.skipped = []
        self.second_gesture = None
        self._misses = 0
        self._pause_toggles = 0
        self._step_done = False

    @property
    def step(self):
        """Name of the step on screen ("done" once the tour is over)."""
        if self.finished:
            return "done"
        return self.steps[self.index]

    @property
    def finished(self):
        """True when there is no step left to show."""
        return self.index >= len(self.steps)

    def advance(self):
        """Move on to the next step."""
        if self.finished:
            return
        self.index += 1
        self._reset_step_state()

    def skip(self):
        """Leave the current step without doing it."""
        if self.finished:
            return
        self.skipped.append(self.step)
        self.advance()

    def skip_all(self):
        """Leave the whole tour; every step left over counts as skipped."""
        while not self.finished:
            self.skipped.append(self.step)
            self.advance()

    def choose_second(self, gesture):
        """Pick the second gesture to try.  False for an unknown gesture."""
        if gesture not in SECOND_GESTURE_CHOICES:
            return False
        self.second_gesture = gesture
        return True

    def on_event(self, name):
        """True when this engine event completes the current step."""
        if self.finished or self._step_done:
            return False
        if self.step == "first_win":
            if name in SPACE_EVENTS:
                self._step_done = True
                return True
            return False
        if self.step == "pause":
            if name not in PAUSE_EVENTS:
                return False
            self._pause_toggles += 1
            if self._pause_toggles >= PAUSE_TOGGLES_NEEDED:
                self._step_done = True
                return True
            return False
        if self.step == "second_gesture":
            events = SECOND_GESTURE_EVENTS.get(self.second_gesture)
            if events and name in events:
                self._step_done = True
                return True
        return False

    def note_miss(self):
        """Count a failed try.  True on the miss that should show the hint."""
        self._misses += 1
        if self._misses < MISSES_BEFORE_HINT:
            return False
        self._misses = 0
        return True

    def _reset_step_state(self):
        """Per-step counters belong to the step that just ended."""
        self._misses = 0
        self._pause_toggles = 0
        self._step_done = False


# =============================================================================
# Teaching order and hints
# =============================================================================

# The README gesture table, in order.  The lock-screen wave is left out: it
# is not something a new user should be taught to do on purpose.
TEACH_ORDER = [
    "space",           # slap: switch Space (Alt+Tab on Windows)
    "overview",        # swipe up: Mission Control / Task View
    "scroll",          # two fingers: scroll
    "back_forward",    # two-finger swipe: back / forward
    "pointer",         # point sideways: move the cursor
    "click",           # pinch: click
    "volume",          # OK sign + twist: volume
    "play_pause",      # thumbs up: play / pause
    "undo",            # thumbs down: undo
    "arrow",           # thumb left / right: arrow keys
    "dictation",       # hang loose: dictation on / off
    "push_to_talk",    # hang loose by the ear: push to talk
    "launcher",        # gather fingertips: Spotlight / Start menu
    "pause",           # rock horns: pause / resume
]

# One short hint per step with a gesture, in plain English.
HINTS = {
    "first_win": "Slap your open hand sideways across the camera.",
    "pause": "Hold your rock horns sign to pause, then again to resume.",
    "second_gesture": {
        "scroll": "Hold two fingers together and tilt them up or down.",
        "pointer": "Point sideways with your index, then pinch to click.",
        "play_pause": "Hold your thumb up to play or pause the music.",
    },
}


# =============================================================================
# Settings helpers
# =============================================================================

def needs_onboarding(settings, settings_file_existed):
    """True for a brand-new user only.

    An existing user never sees the tour again, and the Windows first_run
    flag still counts as a new user even when the settings file is old.
    """
    if settings.get("onboarding_done"):
        return False
    if settings.get("first_run") is True:
        return True
    return not settings_file_existed


def mark_onboarding_done(settings):
    """Remember that the tour ran, so it never opens again."""
    settings["onboarding_done"] = True
    settings["first_run"] = False


def record_gesture_used(settings, gesture):
    """Remember that the user has used a gesture.  No duplicates."""
    used = settings.get("gestures_used") or []
    if gesture not in used:
        used.append(gesture)
    settings["gestures_used"] = used


def next_gesture_to_teach(settings):
    """The next gesture to teach, or None when they are all used."""
    used = settings.get("gestures_used") or []
    for gesture in TEACH_ORDER:
        if gesture not in used:
            return gesture
    return None
