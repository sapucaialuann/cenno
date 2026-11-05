"""The macOS welcome tour (#40).

A small AppKit window that walks a new user through the permissions and
teaches the first gesture.  The steps themselves live in onboarding.py, so
the Mac and the Windows app show the same tour; this file is the Mac
window and the Mac-only checks.

The window is built in code (no xib) and laid out by hand: it is one
small window, and the frames are easier to reason about than constraints.
AppKit is imported inside the methods so this file stays importable on a
machine without PyObjC (the tests use the pure helpers below).
"""

import time

import onboarding
import shortcuts
import theme

# =============================================================================
# The window
# =============================================================================

WINDOW_W = 460                    # points
WINDOW_H = 440
PAD = theme.SPACE[4]              # 16 from the edge to the text
BTN_H = 30                        # button height
PREVIEW_W, PREVIEW_H = 280, 210   # the camera preview inside the window

# A hand on camera this long without the gesture counts as a missed try.
MISS_AFTER_TRACKED_S = 4.0

# The camera step moves on once the hand has been seen this long.
HAND_SEEN_S = 2.0

# How long the check mark stays up before the step moves on.
AX_CHECK_DELAY_S = 1.0

# The steps that wait for a gesture.
GESTURE_STEPS = ("first_win", "pause", "second_gesture")

# The second gesture the user can pick: the key, then the button text.
SECOND_CHOICES = (("scroll", "Scroll"),
                  ("pointer", "Pointer + pinch"),
                  ("play_pause", "Play / pause"))

# =============================================================================
# The text of the steps
# =============================================================================

STEP_TITLE = {
    "welcome": "Welcome to Cenno",
    "camera": "Show us your hand",
    "accessibility": "Allow Cenno to control your Mac",
    "first_win": "Your first gesture",
    "pause": "Take a break",
    "second_gesture": "One more gesture",
    "done": "That is everything",
}

STEP_BODY = {
    "welcome": "Control your computer with your hand.\n"
               "Nothing leaves this computer.",
    "camera": "Hold your hand up to the camera, so Cenno can see it.",
    "accessibility": "Cenno needs this to press keys, scroll and move the pointer.",
    "first_win": "Slap your hand to the left or right. Your Mac moves to the next Space.",
    "pause": "Rock horns to pause, then again to resume.\n"
             "A closed fist does nothing: rest your hand anytime.\n\n"
             "The on/off switch is the hand icon in the menu bar, top right.",
    "second_gesture": "Pick the gesture you want to try next.",
    "done": "You know 3 gestures. The rest are in the menu under Gestures.",
}

# What the step says once the gesture worked.
STEP_DONE = {
    "first_win": "Your Mac moved to the next Space. That is the whole idea.",
    "pause": "You can stop Cenno any time now.",
    "second_gesture": "One more gesture is yours.",
}

# Why the Mission Control shortcuts matter, when they are off.
MC_REASON = ("Cenno moves between Spaces with the Mission Control shortcuts. "
             "They are off, so the swipe would do nothing.")


# =============================================================================
# Pure helpers
# =============================================================================

def space_shortcuts_off(hotkeys):
    """The Mission Control "move a space" shortcuts that are switched off.

    macOS keeps them in com.apple.symbolichotkeys: 79 is "Move left a
    space" and 81 is "Move right a space".  A missing entry means the
    default (on), so only an entry that says "enabled: false" counts as
    off.
    """
    off = []
    for num, name in (("79", "Move left a space"), ("81", "Move right a space")):
        entry = hotkeys.get(num) or {}
        if hasattr(entry, "get") and not entry.get("enabled", True):
            off.append(name)
    return off


def hint_for(step, choice=None):
    """The one hint for a step, or "" when the step has none."""
    if step == "second_gesture":
        return onboarding.HINTS["second_gesture"].get(choice, "")
    return onboarding.HINTS.get(step, "")


# =============================================================================
# AppKit bridge
# =============================================================================

_CONTROLLER_CLASS = None


def _controller_class():
    """The class that takes the buttons' clicks and the window's close.

    AppKit needs an Objective-C object as the target of a button and the
    delegate of a window, so this small NSObject forwards to the plain
    Python window object.
    """
    global _CONTROLLER_CLASS
    if _CONTROLLER_CLASS is None:
        import Foundation

        class OnboardingController(Foundation.NSObject):
            def do_primary_(self, sender):
                self._cenno_owner.primary_pressed()

            def do_secondary_(self, sender):
                self._cenno_owner.secondary_pressed()

            def do_skip_(self, sender):
                self._cenno_owner.skip_pressed()

            def do_skip_step_(self, sender):
                self._cenno_owner.skip_step_pressed()

            def do_choice_(self, sender):
                self._cenno_owner.choice_pressed(sender.tag())

            def do_open_ax_(self, sender):
                self._cenno_owner.open_accessibility()

            def do_open_mc_(self, sender):
                self._cenno_owner.open_keyboard_shortcuts()

            def windowWillClose_(self, notification):
                self._cenno_owner.window_closed()

        _CONTROLLER_CLASS = OnboardingController
    return _CONTROLLER_CLASS


# =============================================================================
# The window
# =============================================================================

class OnboardingWindow:
    """The welcome tour window (macOS).

    `host` is the app: it gives the settings, the gesture engine's events
    and the permission helpers.
    """

    def __init__(self, host):
        import AppKit
        self.AK = AppKit
        self.host = host
        self.ob = onboarding.Onboarding("macos")
        self.succeeded = False
        self._rows = []             # (view, height) shown under the body text
        self._dark = bool(getattr(host, "dark", False))
        self._tracked_since = None  # when the hand came on camera
        self._seen_since = None     # when the hand was first seen
        self._ax_granted_at = None  # when the permission came
        self._mc_off = []
        self._build()
        self.show_step(self.ob.step)

    # --- building ---

    def _build(self):
        AK = self.AK
        mask = AK.NSWindowStyleMaskTitled | AK.NSWindowStyleMaskClosable
        self.window = AK.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0, 0), (WINDOW_W, WINDOW_H)), mask, AK.NSBackingStoreBuffered, False)
        self.window.setTitle_("Cenno")
        self.window.setReleasedWhenClosed_(False)
        self.window.setLevel_(AK.NSFloatingWindowLevel)

        self.controller = _controller_class().alloc().init()
        self.controller._cenno_owner = self
        self.window.setDelegate_(self.controller)

        self.title = self._label("title")
        self.body = self._label("body")
        self.hint_label = self._label("body-sm")
        self.check = self._label("body-sm")
        self.mc_reason = self._label("body-sm")
        self.preview = AK.NSImageView.alloc().initWithFrame_((0, 0, PREVIEW_W, PREVIEW_H))
        self.preview.setImageScaling_(AK.NSImageScaleAxesIndependently)

        self.primary = self._button("Continue", "do_primary:")
        self.secondary = self._button("Later", "do_secondary:")
        self.skip_button = self._button("Skip", "do_skip_step:", link=True)
        self.link = self._button("Skip tour", "do_skip:", link=True)
        self.ax_button = self._button("Open Accessibility settings", "do_open_ax:")
        self.mc_button = self._button("Open Keyboard Shortcuts settings", "do_open_mc:")

        self.choice_row = AK.NSView.alloc().initWithFrame_((0, 0, WINDOW_W, BTN_H))
        self.choice_buttons = []
        for tag, (_key, label) in enumerate(SECOND_CHOICES):
            button = self._button(label, "do_choice:")
            button.setTag_(tag)
            self.choice_row.addSubview_(button)
            self.choice_buttons.append(button)

        content = self.window.contentView()
        for view in (self.title, self.body, self.hint_label, self.check,
                     self.mc_reason, self.preview, self.primary, self.secondary,
                     self.skip_button, self.link, self.ax_button, self.mc_button,
                     self.choice_row):
            content.addSubview_(view)
        self.apply_theme(self._dark)

    def _label(self, style):
        """A wrapping text label."""
        AK = self.AK
        label = AK.NSTextField.labelWithString_("")
        label.setFont_(self._font(style))
        label.setLineBreakMode_(AK.NSLineBreakByWordWrapping)
        label.setMaximumNumberOfLines_(0)
        label.setUsesSingleLineMode_(False)
        label.cell().setWraps_(True)
        return label

    def _button(self, title, action, link=False):
        """A button that calls back into the controller."""
        AK = self.AK
        button = AK.NSButton.alloc().initWithFrame_((0, 0, 100, BTN_H))
        button.setTitle_(title)
        button.setBezelStyle_(AK.NSBezelStyleInline if link else AK.NSBezelStyleRounded)
        button.setFont_(self._font("body-sm"))
        button.setTarget_(self.controller)
        button.setAction_(action)
        if link:
            button.setContentTintColor_(theme.ns_color("ember-ink", self._dark))
        return button

    def _font(self, style):
        """The font for a type style from the design tokens."""
        AK = self.AK
        size, _line_height, weight, _spacing = theme.TYPE[style]
        bold = getattr(AK, "NSFontWeightSemibold", 0.3)
        return AK.NSFont.systemFontOfSize_weight_(size, bold if weight >= 600 else 0.0)

    def _text_height(self, text, width, font):
        """How tall a text block is when it is this wide."""
        AK = self.AK
        if not text:
            return 0.0
        styled = AK.NSAttributedString.alloc().initWithString_attributes_(
            text, {self._font_key(): font})
        rect = styled.boundingRectWithSize_options_(
            (width, 10000.0), AK.NSStringDrawingUsesLineFragmentOrigin)
        return rect.size.height

    def _button_width(self, button):
        """How wide the button has to be for its title."""
        AK = self.AK
        styled = AK.NSAttributedString.alloc().initWithString_attributes_(
            button.title(), {self._font_key(): button.font()})
        return styled.size().width + theme.SPACE[4] * 2

    def _font_key(self):
        """The attribute name for a font (the constant, or its plain name)."""
        return getattr(self.AK, "NSFontAttributeName", "NSFont")

    # --- look ---

    def apply_theme(self, dark):
        """The day and night colours."""
        self._dark = dark
        self.window.setBackgroundColor_(theme.ns_color("paper", dark))
        self.title.setTextColor_(theme.ns_color("ink", dark))
        self.body.setTextColor_(theme.ns_color("ink-muted", dark))
        self.hint_label.setTextColor_(theme.ns_color("ember-ink", dark))
        self.check.setTextColor_(theme.ns_color("trace-ink", dark))
        self.mc_reason.setTextColor_(theme.ns_color("ember-ink", dark))
        self.link.setContentTintColor_(theme.ns_color("ember-ink", dark))
        self.skip_button.setContentTintColor_(theme.ns_color("ember-ink", dark))
        if hasattr(self.primary, "setBezelColor_"):
            self.primary.setBezelColor_(theme.ns_color("trace", dark))
        self.primary.setContentTintColor_(theme.ns_color("on-trace", dark))

    # --- the steps ---

    def show_step(self, step):
        """Put a step on screen."""
        self.succeeded = False
        self._rows = []
        self._tracked_since = None
        self._seen_since = None
        self._ax_granted_at = None
        self._mc_off = []
        self.host.tracker.onboarding_preview = (step == "camera")
        self.title.setStringValue_(STEP_TITLE.get(step, ""))
        self.body.setStringValue_(STEP_BODY.get(step, ""))
        self.hint_label.setStringValue_("")
        self.check.setStringValue_("")
        self.mc_reason.setStringValue_("")
        self._hide_all()

        if step == "welcome":
            self.primary.setTitle_("Let's try it")
            self._show(self.primary)
            self.secondary.setTitle_("Later")
            self._show(self.secondary)
        elif step == "camera":
            self.primary.setTitle_("Continue")
            self._show(self.primary)
            self._rows.append((self.preview, PREVIEW_H))
            self._show(self.preview)
        elif step == "accessibility":
            self.primary.setTitle_("Continue")
            self._show(self.primary)
            self._rows.append((self.check, 20))
            self._show(self.check)
            self._rows.append((self.ax_button, BTN_H))
            self._show(self.ax_button)
        elif step in GESTURE_STEPS:
            if step == "second_gesture":
                self._rows.append((self.choice_row, BTN_H))
                self._show(self.choice_row)
            self._rows.append((self.hint_label, 20))
        elif step == "done":
            self.primary.setTitle_("Close")
            self._show(self.primary)
        if step != "done":
            self._show(self.skip_button)
        self._layout()

    def _hide_all(self):
        """Hide every view that a step does not use."""
        for view in (self.primary, self.secondary, self.skip_button, self.preview,
                     self.hint_label, self.check, self.mc_reason, self.ax_button,
                     self.mc_button, self.choice_row):
            view.setHidden_(True)

    def _show(self, view):
        """Show a view and put the column back in place."""
        view.setHidden_(False)
        self._layout()

    def _set_row(self, view, height):
        """Put a view in the column under the body text."""
        self._rows = [row for row in self._rows if row[0] is not view]
        self._rows.append((view, height))

    def _drop_row(self, view):
        """Take a view out of the column."""
        self._rows = [row for row in self._rows if row[0] is not view]

    def _layout(self):
        """Put every view where it belongs."""
        width = WINDOW_W - 2 * PAD
        y = WINDOW_H - PAD

        title_h = self._text_height(self.title.stringValue(), width, self.title.font())
        y -= title_h
        self.title.setFrame_((PAD, y, width, title_h))

        y -= theme.SPACE[2]
        body_h = self._text_height(self.body.stringValue(), width, self.body.font())
        y -= body_h
        self.body.setFrame_((PAD, y, width, body_h))

        y -= theme.SPACE[3]
        for view, height in self._rows:
            if view.isHidden():
                continue
            view.setFrame_((PAD, y - height, width, height))
            y -= height + theme.SPACE[2]
        if self.choice_row in [row[0] for row in self._rows]:
            self._layout_choice_row(width)

        # Buttons, right to left: the main one first, then the others.
        x = WINDOW_W - PAD
        for button in (self.primary, self.secondary, self.skip_button):
            if button.isHidden():
                continue
            button_w = self._button_width(button)
            button.setFrame_((x - button_w, PAD, button_w, BTN_H))
            x -= button_w + theme.SPACE[2]
        self.link.setFrame_((PAD, PAD + (BTN_H - 20) / 2, 100, 20))

    def _layout_choice_row(self, width):
        """The three buttons of the second gesture, side by side."""
        gap = theme.SPACE[2]
        widths = [self._button_width(button) for button in self.choice_buttons]
        x = 0.0
        for button, button_w in zip(self.choice_buttons, widths):
            button.setFrame_((x, 0, button_w, BTN_H))
            x += button_w + gap

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

    def choice_pressed(self, tag):
        """The user picked the second gesture to try."""
        key = SECOND_CHOICES[tag][0]
        if not self.ob.choose_second(key):
            return
        for index, (choice, label) in enumerate(SECOND_CHOICES):
            self.choice_buttons[index].setTitle_(("✓ " if choice == key else "") + label)
        self.show_hint(hint_for("second_gesture", key))

    def open_accessibility(self):
        """Send the user to the Accessibility pane."""
        self.host.open_accessibility_settings()

    def open_keyboard_shortcuts(self):
        """Send the user to the Keyboard Shortcuts pane."""
        self.host.open_keyboard_shortcuts()

    def window_closed(self):
        """The window was closed: remember that the tour is over."""
        self.finish(close=False)

    # --- moving on ---

    def advance(self):
        """Go to the next step."""
        if self.ob.finished:
            self.finish()
            return
        self.ob.advance()
        self.show_step(self.ob.step)

    def finish(self, close=True):
        """The tour is over: remember it and close the window."""
        onboarding.mark_onboarding_done(self.host.settings)
        self.host.persist_settings()
        self.host.tracker.onboarding_preview = False
        if close:
            self.window.orderOut_(None)

    def show(self):
        """Bring the window on screen."""
        self.AK.NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)

    def restart(self):
        """Start the tour again from the first step."""
        self.ob = onboarding.Onboarding("macos")
        self.show_step(self.ob.step)

    # --- what happens while the window is open ---

    def tick(self):
        """Called from the app's timer, on the main thread."""
        if self.host.dark is not None and bool(self.host.dark) != self._dark:
            self.apply_theme(bool(self.host.dark))
            self._layout()
        step = self.ob.step
        if step == "camera":
            self._update_preview()
            self._update_camera()
        elif step == "accessibility":
            self._update_accessibility()
        elif step in GESTURE_STEPS:
            self._update_misses()

    def on_event(self, name):
        """An engine event: it completes the step when it is the right one."""
        if self.ob.on_event(name):
            self.step_succeeded()

    def step_succeeded(self):
        """The gesture worked: show it and offer the next step."""
        self.succeeded = True
        self.body.setStringValue_(STEP_DONE.get(self.ob.step, "That worked."))
        self.check.setStringValue_("✓ That worked")
        self._set_row(self.check, 20)
        self._show(self.check)
        self.primary.setTitle_("Continue")
        self._show(self.primary)
        self._layout()

    def show_hint(self, text):
        """One hint at a time."""
        self.hint_label.setStringValue_(text or "")
        self._show(self.hint_label)

    def _update_preview(self):
        """Show what the camera sees."""
        tracker = self.host.tracker
        with tracker.lock:
            data = tracker.onboarding_frame
        if not data:
            return
        nsdata = self.AK.NSData.dataWithBytes_length_(data, len(data))
        image = self.AK.NSImage.alloc().initWithData_(nsdata)
        if image is not None:
            self.preview.setImage_(image)

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

    def _update_accessibility(self):
        """Wait for the Accessibility permission, then move on."""
        now = time.monotonic()
        if self.host.accessibility_granted():
            self.check.setStringValue_("✓ Accessibility is on")
            if not self.ax_button.isHidden():
                self.ax_button.setHidden_(True)
                self._layout()
            if self._ax_granted_at is None:
                self._ax_granted_at = now
            elif now - self._ax_granted_at >= AX_CHECK_DELAY_S:
                self.advance()
                return
        else:
            self.check.setStringValue_("Waiting for the permission...")
            self._ax_granted_at = None
        self._update_space_shortcuts()

    def _update_space_shortcuts(self):
        """Warn when the Mission Control shortcuts are off."""
        off = space_shortcuts_off(shortcuts.read_mac_hotkeys())
        if off == self._mc_off:
            return
        self._mc_off = off
        if off:
            self.mc_reason.setStringValue_(MC_REASON)
            self._set_row(self.mc_reason, 40)
            self._set_row(self.mc_button, BTN_H)
            self._show(self.mc_reason)
            self._show(self.mc_button)
        else:
            self.mc_reason.setStringValue_("")
            self._drop_row(self.mc_reason)
            self._drop_row(self.mc_button)
        self._layout()

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
