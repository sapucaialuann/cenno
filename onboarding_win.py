"""The Windows welcome tour (#40).

A small tkinter window that walks a new user through the first gesture.
The steps themselves live in onboarding.py, so the Mac and the Windows
app show the same tour; this file is the Windows window only.

Tkinter is only touched from the tkinter main thread: the camera thread
hands the engine's events over through a queue.Queue, and the app drains
that queue in its own root.after tick.
"""

import io
import time

import displays as dpy
import onboarding
import theme

try:
    import tkinter as tk
except ImportError:      # pragma: no cover - a Python without tkinter
    tk = None


# =============================================================================
# Constants
# =============================================================================

WINDOW_W = 460                    # pixels
WINDOW_H = 440
BTN_H = 30                        # button height
PREVIEW_W, PREVIEW_H = 280, 210   # the camera preview inside the window

# A hand on camera this long without the gesture counts as a missed try.
MISS_AFTER_TRACKED_S = 4.0

# The camera step moves on once the hand has been seen this long.
HAND_SEEN_S = 2.0

# The steps that wait for a gesture.
GESTURE_STEPS = ("first_win", "pause", "second_gesture")

# The second gesture the user can pick: the key, then the button text.
SECOND_CHOICES = (("scroll", "Scroll"),
                  ("pointer", "Pointer + pinch"),
                  ("play_pause", "Play / pause"))

# The buttons, by style: (background, text, hover background, hover text).
BUTTON_STYLES = {
    "trace": ("trace", "on-trace", "trace-soft", "on-trace"),
    "quiet": ("paper-raised", "ink", "line", "ink"),
    "link": ("paper", "ember-ink", "paper", "ember-ink"),
}

# =============================================================================
# The text of the steps
# =============================================================================

STEP_TITLE = {
    "welcome": "Welcome to Cenno",
    "camera": "Show us your hand",
    "first_win": "Your first gesture",
    "pause": "Take a break",
    "second_gesture": "One more gesture",
    "done": "That is everything",
}

STEP_BODY = {
    "welcome": "Control your computer with your hand.\n"
               "Nothing leaves this computer.",
    "camera": "Hold your hand up to the camera, so Cenno can see it.\n"
              "If Windows blocks the camera, open Camera settings from the tray.",
    "first_win": "Slap your hand to the left or right. Your PC switches to the next window.",
    "pause": "Rock horns to pause, then again to resume.\n"
             "A closed fist does nothing: rest your hand anytime.\n\n"
             "The on/off switch is the hand icon in the tray, bottom right.",
    "second_gesture": "Pick the gesture you want to try next.",
    "done": "You know 3 gestures. The rest are in the menu under Gestures.",
}

# What the step says once the gesture worked.
STEP_DONE = {
    "first_win": "Your PC switched to the next window. That is the whole idea.",
    "pause": "You can stop Cenno any time now.",
    "second_gesture": "One more gesture is yours.",
}


# =============================================================================
# Pure helpers
# =============================================================================

def hint_for(step, choice=None):
    """The one hint for a step, or "" when the step has none."""
    if step == "second_gesture":
        return onboarding.HINTS["second_gesture"].get(choice, "")
    return onboarding.HINTS.get(step, "")


# =============================================================================
# The window
# =============================================================================

class OnboardingWindow:
    """The welcome tour window (Windows / tkinter).

    `host` is the app: it gives the settings, the gesture engine's events
    and the camera frames.
    """

    def __init__(self, host):
        self.host = host
        self.ob = onboarding.Onboarding("windows")
        self.succeeded = False
        self._dark = bool(getattr(host, "dark", False))
        self._tracked_since = None  # when the hand came on camera
        self._seen_since = None     # when the hand was first seen
        self._photo = None          # the preview picture, kept alive
        self._rows = []             # the widgets shown under the body text
        self._buttons = []          # the buttons shown in the button row
        self._build()
        self.show_step(self.ob.step)

    # --- building ---

    def _build(self):
        if tk is None:
            raise RuntimeError("this Python has no tkinter")
        paper = theme.hex_of("paper", self._dark)

        self.window = tk.Toplevel(self.host.root)
        self.window.title("Cenno")
        self.window.configure(bg=paper)
        self.window.resizable(False, False)
        # No transient() here: the main window is withdrawn, and a transient
        # window of a withdrawn window never gets mapped on Windows.
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        inner = tk.Frame(self.window, bg=paper)
        inner.pack(fill=tk.BOTH, expand=True,
                   padx=theme.SPACE[6], pady=theme.SPACE[4])

        self.title_label = tk.Label(
            inner, text="", bg=paper, fg=theme.hex_of("ink", self._dark),
            font=theme.type_font("display", "title"), justify="left", anchor="w")
        self.title_label.pack(fill=tk.X)

        self.body_label = tk.Label(
            inner, text="", bg=paper, fg=theme.hex_of("ink-muted", self._dark),
            font=theme.type_font("sans", "body"), justify="left", anchor="w",
            wraplength=WINDOW_W - 2 * theme.SPACE[6])
        self.body_label.pack(fill=tk.X, pady=(theme.SPACE[2], theme.SPACE[3]))

        # The button row is packed before the rows above it, so the buttons
        # keep their place at the bottom of the window.
        buttons = tk.Frame(inner, bg=paper)
        buttons.pack(side=tk.BOTTOM, fill=tk.X)

        self.rows = tk.Frame(inner, bg=paper)
        self.rows.pack(fill=tk.BOTH, expand=True)

        self.primary_btn = self._button(buttons, "", self.primary_pressed, "trace")
        self.secondary_btn = self._button(buttons, "", self.secondary_pressed, "quiet")
        self.skip_btn = self._button(buttons, "Skip", self.skip_step_pressed, "quiet")
        self.link_btn = self._button(buttons, "Skip tour", self.skip_pressed, "link")
        self.link_btn.pack(side=tk.LEFT)

        self.preview = tk.Label(self.rows, bg=theme.hex_of("paper-sunk", self._dark),
                                bd=0, highlightthickness=0)
        self.check_label = tk.Label(
            self.rows, text="", bg=paper, fg=theme.hex_of("trace-ink", self._dark),
            font=theme.type_font("sans", "body-sm"), justify="left", anchor="w")
        self.choice_frame = tk.Frame(self.rows, bg=paper)
        self.choice_buttons = [
            self._button(self.choice_frame, label,
                         lambda key=key: self.choice_pressed(key), "quiet")
            for key, label in SECOND_CHOICES
        ]
        for button in self.choice_buttons:
            button.pack(side=tk.LEFT, padx=(0, theme.SPACE[2]))
        self.hint_label = tk.Label(
            self.rows, text="", bg=paper, fg=theme.hex_of("ember-ink", self._dark),
            font=theme.type_font("sans", "body-sm"), justify="left", anchor="w")

        # The order the rows are stacked in, under the body text.
        self._row_widgets = (self.preview, self.check_label,
                             self.choice_frame, self.hint_label)

        # Always on top: the app has no other window, so the tour would
        # otherwise open behind whatever the user was doing.
        try:
            self.window.attributes("-topmost", True)
        except Exception:
            pass
        self._place()

    def _button(self, parent, text, command, style):
        """A flat button in the theme colours."""
        button = tk.Button(parent, text=text, command=command,
                           font=theme.type_font("sans", "label"),
                           relief=tk.FLAT, bd=0, padx=theme.SPACE[4],
                           pady=theme.SPACE[2], cursor="hand2")
        button._cenno_style = style
        self._style_button(button, style, self._dark)
        return button

    def _style_button(self, button, style, dark):
        """The colours of one button."""
        bg, fg, hover_bg, hover_fg = BUTTON_STYLES[style]
        button.configure(bg=theme.hex_of(bg, dark), fg=theme.hex_of(fg, dark),
                         activebackground=theme.hex_of(hover_bg, dark),
                         activeforeground=theme.hex_of(hover_fg, dark))

    def _place(self):
        """Centre the window on the primary screen."""
        self.window.update_idletasks()
        try:
            lay = dpy.system_displays()
            rect = lay[0] if lay else (0, 0, self.window.winfo_screenwidth(),
                                       self.window.winfo_screenheight())
            x = int(rect[0] + (rect[2] - WINDOW_W) / 2)
            y = int(rect[1] + (rect[3] - WINDOW_H) / 2)
            self.window.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")
        except Exception:
            self.window.geometry(f"{WINDOW_W}x{WINDOW_H}")

    # --- look ---

    def apply_theme(self, dark):
        """The day and night colours."""
        self._dark = dark
        paper = theme.hex_of("paper", dark)
        self.window.configure(bg=paper)
        self.title_label.configure(bg=paper, fg=theme.hex_of("ink", dark))
        self.body_label.configure(bg=paper, fg=theme.hex_of("ink-muted", dark))
        self.check_label.configure(bg=paper, fg=theme.hex_of("trace-ink", dark))
        self.hint_label.configure(bg=paper, fg=theme.hex_of("ember-ink", dark))
        self.rows.configure(bg=paper)
        self.choice_frame.configure(bg=paper)
        self.preview.configure(bg=theme.hex_of("paper-sunk", dark))
        for button in (self.primary_btn, self.secondary_btn, self.skip_btn,
                       self.link_btn, *self.choice_buttons):
            self._style_button(button, button._cenno_style, dark)

    # --- the steps ---

    def show_step(self, step):
        """Put a step on screen."""
        self.succeeded = False
        self._tracked_since = None
        self._seen_since = None
        self.host.tracker.onboarding_preview = (step == "camera")
        self.title_label.configure(text=STEP_TITLE.get(step, ""))
        self.body_label.configure(text=STEP_BODY.get(step, ""))
        self.check_label.configure(text="")
        self.hint_label.configure(text="")
        self._rows = []
        self._buttons = []

        if step == "welcome":
            self.primary_btn.configure(text="Let's try it")
            self._buttons.append(self.primary_btn)
            self.secondary_btn.configure(text="Later")
            self._buttons.append(self.secondary_btn)
        elif step == "camera":
            self.primary_btn.configure(text="Continue")
            self._buttons.append(self.primary_btn)
            self._rows.append(self.preview)
        elif step in GESTURE_STEPS:
            if step == "second_gesture":
                self._rows.append(self.choice_frame)
                self._reset_choices()
            self._rows.append(self.hint_label)
        elif step == "done":
            self.primary_btn.configure(text="Close")
            self._buttons.append(self.primary_btn)

        if step != "done":
            self._buttons.append(self.skip_btn)
        self._relayout()

    def _relayout(self):
        """Put the rows and the buttons where they belong."""
        for widget in self._row_widgets:
            widget.pack_forget()
        for widget in self._row_widgets:
            if widget in self._rows:
                widget.pack(fill=tk.X, pady=(0, theme.SPACE[2]))

        for button in (self.primary_btn, self.secondary_btn, self.skip_btn):
            button.pack_forget()
        # The main button on the right, the others to the left of it.
        for button in (self.primary_btn, self.secondary_btn, self.skip_btn):
            if button in self._buttons:
                button.pack(side=tk.RIGHT, padx=(theme.SPACE[2], 0))

    # --- what the user does ---

    def primary_pressed(self):
        """The main button: on to the next step, or close the tour."""
        if self.ob.step == "done":
            self.finish()
        else:
            self.advance()

    def secondary_pressed(self):
        """The 'Later' button on the welcome step: no tour today."""
        self.ob.skip_all()
        self.finish()

    def skip_pressed(self):
        """The 'Skip tour' link: leave the whole tour."""
        self.ob.skip_all()
        self.finish()

    def skip_step_pressed(self):
        """The 'Skip' button: leave this step, keep the tour."""
        self.ob.skip()
        self.show_step(self.ob.step)

    def choice_pressed(self, key):
        """The user picked the second gesture to try."""
        if not self.ob.choose_second(key):
            return
        for button, (choice, label) in zip(self.choice_buttons, SECOND_CHOICES):
            button.configure(text=("✓ " if choice == key else "") + label)
        self.show_hint(hint_for("second_gesture", key))

    def _reset_choices(self):
        """The second gesture is picked again in every new tour."""
        for button, (_key, label) in zip(self.choice_buttons, SECOND_CHOICES):
            button.configure(text=label)

    def _on_close(self):
        """The window was closed: remember that the tour is over."""
        self.finish()

    # --- moving on ---

    def advance(self):
        """Go to the next step."""
        if self.ob.finished:
            self.finish()
            return
        self.ob.advance()
        self.show_step(self.ob.step)

    def finish(self):
        """The tour is over: remember it and close the window."""
        onboarding.mark_onboarding_done(self.host.settings)
        self.host.persist_settings()
        self.host.tracker.onboarding_preview = False
        self.window.withdraw()

    def show(self):
        """Bring the window on screen."""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def restart(self):
        """Start the tour again from the first step."""
        self.ob = onboarding.Onboarding("windows")
        self.show_step(self.ob.step)

    # --- what happens while the window is open ---

    def tick(self):
        """Called from the app's timer, on the main thread."""
        if self.host.dark is not None and bool(self.host.dark) != self._dark:
            self.apply_theme(bool(self.host.dark))

        step = self.ob.step
        if step == "camera":
            self._update_preview()
            self._update_camera()
        elif step in GESTURE_STEPS:
            self._update_misses()

    def on_event(self, name):
        """An engine event: it completes the step when it is the right one."""
        if self.ob.on_event(name):
            self.step_succeeded()

    def step_succeeded(self):
        """The gesture worked: show it and offer the next step."""
        self.succeeded = True
        self.body_label.configure(text=STEP_DONE.get(self.ob.step, "That worked."))
        self.check_label.configure(text="✓ That worked")
        if self.check_label not in self._rows:
            self._rows.append(self.check_label)
        self.primary_btn.configure(text="Continue")
        if self.primary_btn not in self._buttons:
            self._buttons.append(self.primary_btn)
        self._relayout()

    def show_hint(self, text):
        """One hint at a time."""
        self.hint_label.configure(text=text or "")

    def _update_preview(self):
        """Show what the camera sees."""
        tracker = self.host.tracker
        with tracker.lock:
            data = tracker.onboarding_frame
        if not data:
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(data)).convert("RGB").resize(
                (PREVIEW_W, PREVIEW_H), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.preview.configure(image=self._photo)
        except Exception as exc:
            print(f"WARN: the tour preview could not be drawn: {exc}")

    def _update_camera(self):
        """Move on once the camera has seen a hand."""
        now = time.monotonic()
        if not self.host.tracker.hand_tracked:
            self._seen_since = None
            return
        if self._seen_since is None:
            self._seen_since = now
            return
        if now - self._seen_since >= HAND_SEEN_S:
            self.advance()

    def _update_misses(self):
        """A hand held on camera without the gesture is a missed try."""
        if self.succeeded:
            return
        now = time.monotonic()
        if not self.host.tracker.hand_tracked:
            self._tracked_since = None
            return
        if self._tracked_since is None:
            self._tracked_since = now
            return
        if now - self._tracked_since < MISS_AFTER_TRACKED_S:
            return
        self._tracked_since = now
        if self.ob.note_miss():
            self.show_hint(hint_for(self.ob.step, self.ob.second_gesture))
