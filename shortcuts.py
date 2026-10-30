"""Recorded keyboard shortcuts for dictation.

A shortcut is stored in settings.json as a plain dict, recorded by pressing
the keys (never typed in), so it replays the same physical keys whatever the
keyboard layout:

    {"mods": ["ctrl", "alt"],   # canonical names, see MODS
     "code": 2,                 # macOS virtual key code / Windows VK code,
                                # None for a modifier-only shortcut ("fn")
     "label": "⌃⌥D"}            # what the menu shows

Each settings file belongs to one platform, so "code" is always the code of
the platform that recorded it.
"""

MODS = ("cmd", "ctrl", "alt", "shift", "fn", "win")


def make(mods, code, label):
    """Build a shortcut dict, with mods in canonical order."""
    return {"mods": [m for m in MODS if m in mods], "code": code, "label": label}


def is_valid(sc):
    """True for a dict that tap() and hold() can send."""
    raise NotImplementedError


def from_legacy(spec, os_name):
    """Convert a typed shortcut from settings before version 2, such as
    "ctrl+option+d" or "fn+space", into a shortcut dict.  None if any part
    is unknown (never return a partial combo)."""
    raise NotImplementedError


def tap(sc):
    """Press and release the shortcut: modifiers down, key down/up,
    modifiers up.  Returns False if it could not be sent."""
    raise NotImplementedError


def hold(sc, down):
    """Push-to-talk: down=True presses and keeps the shortcut held,
    down=False releases it (key first, then modifiers in reverse)."""
    raise NotImplementedError
