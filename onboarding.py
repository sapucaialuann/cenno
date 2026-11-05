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

# Every event the tour listens to.
ONBOARDING_EVENTS = frozenset(SPACE_EVENTS + PAUSE_EVENTS + SCROLL_EVENTS
                               + PINCH_EVENTS + (EVENT_PLAY_PAUSE,))

# The steps that wait for a gesture.
GESTURE_STEPS = ("first_win", "pause", "second_gesture")

# The second gesture the user can pick: the key, then the button text.
SECOND_CHOICES = (("scroll", "Scroll"),
                  ("pointer", "Pointer + pinch"),
                  ("play_pause", "Play / pause"))
SECOND_GESTURE_CHOICES = tuple(key for key, _label in SECOND_CHOICES)

SECOND_GESTURE_EVENTS = {
    "scroll": SCROLL_EVENTS,
    "pointer": PINCH_EVENTS,
    "play_pause": (EVENT_PLAY_PAUSE,),
}

MISSES_BEFORE_HINT = 3                 # failed tries before the one hint


# =============================================================================
# Hints and the text of a finished step
# =============================================================================

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


def hint_for(step, choice=None):
    """The one hint for a step, or "" when the step has none."""
    if step == "second_gesture":
        return HINTS["second_gesture"].get(choice, "")
    return HINTS.get(step, "")


# What the step says once the gesture worked.  The first gesture moves
# between Spaces on macOS and between windows on Windows, so that line
# stays in the app's own file.
STEP_DONE = {
    "pause": "You can stop Cenno any time now.",
    "second_gesture": "One more gesture is yours.",
}


# =============================================================================
# Timing
# =============================================================================

# A hand on camera this long without the gesture counts as a missed try.
MISS_AFTER_TRACKED_S = 4.0

# The camera step moves on once the hand has been seen this long.
HAND_SEEN_S = 2.0


class HandTimer:
    """How long the hand has been on camera.

    The camera step moves on once the hand has been seen for HAND_SEEN_S;
    a hand that stays up for MISS_AFTER_TRACKED_S without the gesture is a
    missed try.  Both windows time the hand the same way.
    """

    def __init__(self, seconds):
        self.seconds = seconds
        self.since = None      # when the hand came on camera

    def reset(self):
        """Forget the hand: a new step starts the count again."""
        self.since = None

    def reached(self, now, hand_tracked):
        """True when the hand has been on camera for the whole time.

        The count starts again, so the next time is another `seconds`
        later.
        """
        if not hand_tracked:
            self.since = None
            return False
        if self.since is None:
            self.since = now
            return False
        if now - self.since < self.seconds:
            return False
        self.since = now
        return True


# =============================================================================
# The tour
# =============================================================================

class Onboarding:
    """Which step is on screen and what completes it."""

    def __init__(self, os_name):
        self.steps = steps_for(os_name)
        self.index = 0
        self.second_gesture = None
        self._misses = 0
        self._paused = False
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
        self.advance()

    def skip_all(self):
        """Leave the whole tour."""
        self.index = len(self.steps)
        self._reset_step_state()

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
            return self._on_pause_event(name)
        if self.step == "second_gesture":
            events = SECOND_GESTURE_EVENTS.get(self.second_gesture)
            if events and name in events:
                self._step_done = True
                return True
        return False

    def _on_pause_event(self, name):
        """The pause step ends when the user has paused and then resumed."""
        if name == EVENT_PAUSE_ON:
            self._paused = True
            return False
        if name != EVENT_PAUSE_OFF:
            return False
        if not self._paused:
            # Cenno was paused before this step, so the user has not
            # paused it yet: the step is not done.
            return False
        self._paused = False
        self._step_done = True
        return True

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
        self._paused = False
        self._step_done = False


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
