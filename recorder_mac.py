"""Record a keyboard shortcut by pressing it (macOS).

record_shortcut() opens a small "Press the shortcut now..." window, listens
to the real key events while it is open and returns a shortcut dict (see
shortcuts.py), or None if the person cancels.  Call it from the main thread,
such as from a menu callback: it runs its own modal loop.

Pressing only modifiers (for example the fn key) and letting go records a
modifier-only shortcut, which is how push-to-talk keys like fn are set.
"""

import AppKit

import shortcuts

KEY_DOWN = 10            # NSEventTypeKeyDown
FLAGS_CHANGED = 12       # NSEventTypeFlagsChanged
ESCAPE = 53
FN_FLAG = 1 << 23        # NSEventModifierFlagFunction

# Keys that macOS marks with the Function flag by themselves, so that flag
# says nothing about the fn key for them: arrows, F-keys, Home/End/Page.
NAV_CODES = (frozenset({123, 124, 125, 126, 114, 115, 116, 117, 119, 121})
             | {shortcuts.MAC_KEY_CODES[f"f{n}"] for n in range(1, 20)})

# Keys with no printable character, by key code.
KEY_NAMES = {36: "return", 48: "tab", 49: "space", 51: "delete", 123: "left",
             124: "right", 125: "down", 126: "up", 114: "Help", 115: "Home",
             116: "Page Up", 117: "Fwd Delete", 119: "End", 121: "Page Down"}
KEY_NAMES.update({code: name for name, code in shortcuts.MAC_KEY_CODES.items()
                  if name.startswith("f") and name[1:].isdigit()})


def mods_of(flags, code=None):
    """Canonical modifier names for NSEvent modifier flags.  fn is left out
    when `code` is a key that sets the Function flag on its own."""
    out = []
    if flags & AppKit.NSEventModifierFlagCommand:
        out.append("cmd")
    if flags & AppKit.NSEventModifierFlagControl:
        out.append("ctrl")
    if flags & AppKit.NSEventModifierFlagOption:
        out.append("alt")
    if flags & AppKit.NSEventModifierFlagShift:
        out.append("shift")
    if flags & FN_FLAG and code not in NAV_CODES:
        out.append("fn")
    return out


class _Buttons(AppKit.NSObject):
    """Target for the Save and Cancel buttons."""

    def save_(self, _sender):
        AppKit.NSApp.stopModalWithCode_(1)

    def cancel_(self, _sender):
        AppKit.NSApp.stopModalWithCode_(0)


def _label(text, frame, size, bold=False, center=True):
    field = AppKit.NSTextField.labelWithString_(text)
    field.setFrame_(frame)
    font = (AppKit.NSFont.boldSystemFontOfSize_(size) if bold
            else AppKit.NSFont.systemFontOfSize_(size))
    field.setFont_(font)
    if center:
        field.setAlignment_(AppKit.NSTextAlignmentCenter)
    return field


def _system_shortcuts(mode=None):
    """Read, or set, whether macOS handles its own shortcuts (⌃Space for
    input sources, ⌘Space for Spotlight and the like) before apps see them:
    0 on, 1 off.  Recording turns them off, as the shortcut fields in System
    Settings do, or the system would take the key and only the modifiers
    would be recorded.  None if unavailable."""
    import ctypes
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cid = cg.CGSMainConnectionID()
        if mode is not None:
            cg.CGSSetGlobalHotKeyOperatingMode(cid, mode)
            return mode
        out = ctypes.c_int(0)
        if cg.CGSGetGlobalHotKeyOperatingMode(cid, ctypes.byref(out)) != 0:
            return None
        return out.value
    except (OSError, AttributeError) as exc:
        print(f"WARN: could not pause system shortcuts while recording: {exc}")
        return None


def record_shortcut(title="Press the shortcut now...", warn=None):
    """`warn(sc)` may return a message shown under the shortcut (it can
    still be saved), such as a clash with a macOS shortcut."""
    app = AppKit.NSApplication.sharedApplication()
    state = {"sc": None, "peak": set(), "typed": False}

    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), (360, 220)), AppKit.NSWindowStyleMaskTitled,
        AppKit.NSBackingStoreBuffered, False)
    panel.setTitle_("Cenno")
    panel.setReleasedWhenClosed_(False)
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    view = panel.contentView()
    view.addSubview_(_label(title, ((20, 178), (320, 22)), 14, bold=True))
    shown = _label("", ((20, 130), (320, 34)), 24)
    view.addSubview_(shown)
    HINT = ("Press the keys together, or just one modifier such as fn.\n"
            "Esc on its own cancels.")
    hint = _label(HINT, ((20, 46), (320, 76)), 11)
    hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
    view.addSubview_(hint)

    targets = _Buttons.alloc().init()
    save = AppKit.NSButton.alloc().initWithFrame_(((250, 10), (90, 28)))
    save.setTitle_("Save")
    save.setBezelStyle_(AppKit.NSBezelStyleRounded)
    save.setTarget_(targets)
    save.setAction_("save:")
    save.setKeyEquivalent_("")
    save.setEnabled_(False)
    cancel = AppKit.NSButton.alloc().initWithFrame_(((150, 10), (90, 28)))
    cancel.setTitle_("Cancel")
    cancel.setBezelStyle_(AppKit.NSBezelStyleRounded)
    cancel.setTarget_(targets)
    cancel.setAction_("cancel:")
    view.addSubview_(save)
    view.addSubview_(cancel)

    def show(sc, text=None):
        shown.setStringValue_(text if text is not None else (sc["label"] if sc else ""))

    def keep(sc):
        state["sc"] = sc
        save.setEnabled_(True)
        show(sc)
        message = warn(sc) if warn else None
        hint.setStringValue_(message or HINT)
        hint.setTextColor_(AppKit.NSColor.systemOrangeColor() if message
                           else AppKit.NSColor.secondaryLabelColor())

    def on_event(event):
        flags = event.modifierFlags()
        if event.type() == KEY_DOWN:
            if event.isARepeat():
                return None
            code = event.keyCode()
            mods = mods_of(flags, code)
            if code == ESCAPE and not mods:
                app.stopModalWithCode_(0)
                return None
            key = KEY_NAMES.get(code) or (event.charactersIgnoringModifiers() or "").strip()
            if key:
                state["typed"] = True
                keep(shortcuts.make(mods, code, shortcuts.label_for(mods, key, "Darwin")))
        else:                                       # modifiers changed
            mods = mods_of(flags, event.keyCode())
            if mods:
                if not state["peak"]:
                    state["typed"] = False
                state["peak"] |= set(mods)
                show(None, shortcuts.label_for(state["peak"], None, "Darwin"))
            else:                                   # everything let go
                if state["peak"] and not state["typed"]:
                    keep(shortcuts.make(state["peak"], None,
                                        shortcuts.label_for(state["peak"], None, "Darwin")))
                elif state["sc"]:
                    show(state["sc"])
                state["peak"] = set()
        return None                                 # swallow: nothing else sees it

    mask = AppKit.NSEventMaskKeyDown | AppKit.NSEventMaskFlagsChanged
    monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, on_event)
    before = _system_shortcuts()
    if before is not None:
        _system_shortcuts(1)
    try:
        app.activateIgnoringOtherApps_(True)
        panel.center()
        panel.makeKeyAndOrderFront_(None)
        result = app.runModalForWindow_(panel)
    finally:
        if before is not None:
            _system_shortcuts(before)
        AppKit.NSEvent.removeMonitor_(monitor)
        panel.orderOut_(None)
    return state["sc"] if result == 1 else None
