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

This module has no app or UI imports, so it can be tested anywhere.
"""

import time

MODS = ("cmd", "ctrl", "alt", "shift", "fn", "win")

# --- macOS ------------------------------------------------------------------
# Typed names from settings before version 2 (macOS virtual key codes, US
# layout).  Only used to migrate old settings; new shortcuts are recorded.
MAC_KEY_CODES = dict(zip("asdfhgzxcv", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
MAC_KEY_CODES.update({
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25,
    "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
    "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "escape": 53,
    "esc": 53, "delete": 51, "backspace": 51, "`": 50, "grave": 50,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103,
    "f12": 111, "f13": 105, "f14": 107, "f15": 113, "f16": 106,
    "f17": 64, "f18": 79, "f19": 80, "[": 33, "]": 30})

# canonical modifier -> (key code, Quartz flag mask name)
MAC_MODS = {
    "cmd": (55, "kCGEventFlagMaskCommand"),
    "shift": (56, "kCGEventFlagMaskShift"),
    "alt": (58, "kCGEventFlagMaskAlternate"),
    "ctrl": (59, "kCGEventFlagMaskControl"),
    "fn": (63, "kCGEventFlagMaskSecondaryFn"),
}
MAC_ALIASES = {"command": "cmd", "option": "alt", "opt": "alt", "control": "ctrl"}
MAC_SYMBOLS = (("ctrl", "⌃"), ("alt", "⌥"), ("shift", "⇧"),
               ("cmd", "⌘"))
MAC_KEY_NAMES = {"return": "Return", "enter": "Return", "tab": "Tab",
                 "space": "Space", "escape": "Esc", "esc": "Esc",
                 "delete": "Delete", "backspace": "Delete",
                 "left": "←", "right": "→", "up": "↑",
                 "down": "↓"}

# --- Windows ----------------------------------------------------------------
WIN_MODS = {"win": 0x5B, "ctrl": 0x11, "shift": 0x10, "alt": 0x12}
WIN_ALIASES = {"control": "ctrl", "option": "alt", "opt": "alt",
               "windows": "win", "super": "win"}
WIN_LABELS = (("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("win", "Win"))
WIN_KEY_CODES = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
                 "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
                 "delete": 0x2E, "left": 0x25, "up": 0x26, "right": 0x27,
                 "down": 0x28}
WIN_KEY_CODES.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
WIN_KEY_CODES.update({f"f{n}": 0x70 + n - 1 for n in range(1, 25)})
WIN_EXTENDED = frozenset(range(0x21, 0x29)) | {0x2D, 0x2E}   # nav block, arrows

KEY_GAP = 0.04      # seconds between synthetic events, so apps see each one


def make(mods, code, label):
    """Build a shortcut dict, with mods in canonical order."""
    return {"mods": [m for m in MODS if m in mods], "code": code, "label": label}


def is_valid(sc):
    """True for a dict that tap() and hold() can send."""
    if not isinstance(sc, dict):
        return False
    mods, code = sc.get("mods"), sc.get("code")
    if not isinstance(mods, (list, tuple)) or any(m not in MODS for m in mods):
        return False
    if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
        return False
    return bool(mods) or code is not None


def same(a, b):
    """True when two shortcuts press the same keys (the label is ignored)."""
    return (is_valid(a) and is_valid(b) and a["code"] == b["code"]
            and set(a["mods"]) == set(b["mods"]))


def label_for(mods, key, os_name):
    """Menu text for a shortcut: "⌃⌥D" on a Mac, "Ctrl+Alt+D" on Windows.
    `key` is the key's name or character, or None for modifiers only."""
    k = str(key).lower() if key else ""
    if os_name == "Darwin":
        out = "fn " if "fn" in mods else ""
        out += "".join(sym for m, sym in MAC_SYMBOLS if m in mods)
        out += MAC_KEY_NAMES.get(k, k.upper())
        return out.strip()
    parts = [name for m, name in WIN_LABELS if m in mods]
    if k:
        short = len(k) == 1 or (k[0] == "f" and k[1:].isdigit())
        parts.append(k.upper() if short else k.capitalize())
    return "+".join(parts)


def from_legacy(spec, os_name):
    """Convert a typed shortcut from settings before version 2, such as
    "ctrl+option+d" or "fn+space", into a shortcut dict.  None if any part
    is unknown (never return a partial combo)."""
    if not isinstance(spec, str):
        return None
    parts = spec.replace(" ", "").lower().split("+")
    if not all(parts):                      # empty, or "ctrl+" with the key missing
        return None
    mac = os_name == "Darwin"
    keys = MAC_KEY_CODES if mac else WIN_KEY_CODES
    known = MAC_MODS if mac else WIN_MODS
    aliases = MAC_ALIASES if mac else WIN_ALIASES

    def as_mod(name):
        name = aliases.get(name, name)
        return name if name in known else None

    mods = []
    for p in parts[:-1]:
        m = as_mod(p)
        if m is None:
            return None
        mods.append(m)
    last = parts[-1]
    if as_mod(last):                        # modifier-only, e.g. "fn"
        mods.append(as_mod(last))
        key, code = None, None
    elif last in keys:
        key, code = last, keys[last]
    else:
        return None
    return make(mods, code, label_for(mods, key, os_name))


def migrate_dictation(settings, os_name, wispr_installed=False):
    """Move settings from before version 2 (typed shortcuts, "auto" and
    "wispr" modes) to the recorded format.  Returns a new dict; settings
    already at version 2 come back unchanged."""
    s = dict(settings)
    if s.get("settings_version", 1) >= 2:
        return s
    mac = os_name == "Darwin"
    old = s.get("dictation", "auto")
    custom = s.get("dictation_shortcut") or ""
    wispr_sc = s.get("wispr_shortcut") or ""
    fallback = "apple" if mac else "winvoice"
    mode, toggle, ptt = fallback, None, None
    if mac and (old == "wispr" or (old == "auto" and wispr_installed)):
        mode = "shortcut"
        toggle, ptt = make(["fn"], 49, "fn Space"), make(["fn"], None, "fn")
    elif not mac and (old == "wispr" or (old == "auto" and wispr_sc)):
        # Wispr Flow's Windows defaults: Ctrl+Win+Space hands-free, Ctrl+Win to talk
        toggle = (from_legacy(wispr_sc, os_name) if wispr_sc else
                  make(["ctrl", "win"], WIN_KEY_CODES["space"], "Ctrl+Win+Space"))
        if toggle is None:
            print(f"WARN: Wispr Flow shortcut {wispr_sc!r} not understood; "
                  "using the built-in dictation. Record it again from the menu.")
        else:
            mode, ptt = "shortcut", make(["ctrl", "win"], None, "Ctrl+Win")
    elif old == "custom":
        toggle = from_legacy(custom, os_name)
        if toggle is None:
            print(f"WARN: dictation shortcut {custom!r} not understood; "
                  "using the built-in dictation. Record it again from the menu.")
        else:
            mode = "shortcut"
    if same(toggle, ptt):                   # one key cannot be both
        ptt = None
    s["dictation"] = mode
    s["dictation_toggle"] = toggle if mode == "shortcut" else None
    s["dictation_ptt"] = ptt if mode == "shortcut" else None
    s["settings_version"] = 2
    s.pop("dictation_shortcut", None)
    s.pop("wispr_shortcut", None)
    return s


# --- clashes with the system ----------------------------------------------
# macOS keeps its own shortcuts in com.apple.symbolichotkeys, by number:
# {"60": {"enabled": True, "value": {"parameters": [char, code, flags]}}}.
# An entry with no parameters (or no entry) means the default keys below.
MAC_FLAG_BITS = {"shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19,
                 "cmd": 1 << 20, "fn": 1 << 23}
MAC_SYSTEM_SHORTCUTS = {   # number: (name, default parameters)
    "28": ("Save picture of screen as a file", (51, 20, 1179648)),
    "29": ("Copy picture of screen to the clipboard", (51, 20, 1441792)),
    "30": ("Save picture of selected area as a file", (52, 21, 1179648)),
    "31": ("Copy picture of selected area to the clipboard", (52, 21, 1441792)),
    "184": ("Screenshot and recording options", (53, 23, 1179648)),
    "32": ("Mission Control", (65535, 126, 8650752)),
    "33": ("Application windows", (65535, 125, 8650752)),
    "36": ("Show Desktop", (65535, 103, 8388608)),
    "60": ("Select the previous input source", (32, 49, 262144)),
    "61": ("Select next source in Input menu", (32, 49, 786432)),
    "64": ("Show Spotlight search", (32, 49, 1048576)),
    "65": ("Show Finder search window", (32, 49, 1572864)),
    "79": ("Move left a space", (65535, 123, 8650752)),
    "81": ("Move right a space", (65535, 124, 8650752)),
}

# Windows combos the system keeps for itself: (mods, VK) -> (what it does,
# whether an app can send it at all).
WIN_RESERVED = {
    (frozenset({"win"}), 0x4C): ("locks the PC", False),
    (frozenset({"ctrl", "alt"}), 0x2E): ("opens the security screen", False),
    (frozenset({"win"}), None): ("opens the Start menu", True),
    (frozenset({"win"}), 0x44): ("shows the desktop", True),
    (frozenset({"win"}), 0x45): ("opens File Explorer", True),
    (frozenset({"win"}), 0x52): ("opens Run", True),
    (frozenset({"win"}), 0x09): ("opens Task View", True),
    (frozenset({"win"}), 0x20): ("switches the input language", True),
    (frozenset({"win"}), 0x48): ("starts Windows Voice Typing (pick that option "
                                 "in the menu instead)", True),
    (frozenset({"alt"}), 0x09): ("switches windows", True),
    (frozenset({"alt"}), 0x73): ("closes the window", True),
    (frozenset({"ctrl", "shift"}), 0x1B): ("opens Task Manager", True),
    (frozenset({"ctrl", "win"}), 0x25): ("switches desktops", True),
    (frozenset({"ctrl", "win"}), 0x27): ("switches desktops", True),
}


def read_mac_hotkeys():
    """macOS's own shortcut settings, or {} when they can't be read."""
    try:
        import Foundation
        d = Foundation.CFPreferencesCopyAppValue(
            "AppleSymbolicHotKeys", "com.apple.symbolichotkeys")
        return {str(k): v for k, v in (d or {}).items()}
    except Exception as exc:
        print(f"WARN: could not read the macOS keyboard shortcuts: {exc}")
        return {}


def mac_system_clash(sc, hotkeys):
    """Name of the switched-on macOS shortcut that uses the same keys, or
    None.  fn is ignored: macOS adds it to arrow and F-keys by itself."""
    if not is_valid(sc) or sc["code"] is None:
        return None
    want = sum(MAC_FLAG_BITS[m] for m in sc["mods"] if m in MAC_FLAG_BITS)
    fn = MAC_FLAG_BITS["fn"]
    for num in set(hotkeys) | set(MAC_SYSTEM_SHORTCUTS):
        entry = hotkeys.get(num) or {}
        name, default = MAC_SYSTEM_SHORTCUTS.get(num, ("a macOS keyboard shortcut", None))
        if not entry.get("enabled", default is not None):
            continue
        params = list((entry.get("value") or {}).get("parameters") or []) or default
        if not params or len(params) < 3:
            continue
        if params[1] == sc["code"] and (params[2] & ~fn) == (want & ~fn):
            return name
    return None


def clash_message(sc, os_name, hotkeys=None):
    """A warning to show while recording when the system already uses this
    shortcut, or None."""
    if not is_valid(sc):
        return None
    if os_name == "Darwin":
        name = mac_system_clash(sc, hotkeys or {})
        if name:
            return (f"macOS uses {sc['label']} for \u201c{name}\u201d, so Cenno's "
                    f"{sc['label']} would do that instead of reaching your "
                    "dictation app. Turn it off in System Settings > Keyboard > "
                    "Keyboard Shortcuts, or press another.")
        return None
    hit = WIN_RESERVED.get((frozenset(sc["mods"]), sc["code"]))
    if hit:
        what, sendable = hit
        if not sendable:
            return f"Windows keeps {sc['label']} for itself (it {what}). No app can send it. Press another."
        return f"In Windows {sc['label']} {what}, so Cenno's {sc['label']} would do that too. Press another unless your dictation app took it over."
    return None


def menu_label(sc, os_name, hotkeys=None):
    """The shortcut's label for a menu, flagged when the system uses it."""
    clash = clash_message(sc, os_name, hotkeys)
    return sc["label"] + (" \u26a0\ufe0e used by the system" if clash else "")


def escape():
    """The Esc key (macOS code), which stops Apple Dictation."""
    return make([], 53, "Esc")


# --- sending ----------------------------------------------------------------

def tap(sc):
    """Press and release the shortcut: modifiers down, key down/up,
    modifiers up.  Returns False if it could not be sent."""
    return hold(sc, True) and hold(sc, False)


def hold(sc, down):
    """Push-to-talk: down=True presses and keeps the shortcut held,
    down=False releases it (key first, then modifiers in reverse)."""
    if not is_valid(sc):
        return False
    import platform
    system = platform.system()
    try:
        if system == "Darwin":
            return _mac_send(sc, down)
        if system == "Windows":
            return _win_send(sc, down)
    except Exception as exc:
        print(f"WARN: could not send shortcut {sc.get('label')!r}: {exc}")
    return False


def _mac_send(sc, down):
    import Quartz as Q
    if any(m not in MAC_MODS for m in sc["mods"]):
        return False
    mods = [MAC_MODS[m] for m in sc["mods"]]
    src = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)

    def post(code, key_down, flags, flags_event=False):
        e = Q.CGEventCreateKeyboardEvent(src, code, key_down)
        if flags_event:
            Q.CGEventSetType(e, Q.kCGEventFlagsChanged)
        Q.CGEventSetFlags(e, flags)
        Q.CGEventPost(Q.kCGHIDEventTap, e)
        time.sleep(KEY_GAP)

    if down:
        flags = 0
        for code, mask in mods:                     # modifiers down
            flags |= getattr(Q, mask)
            post(code, True, flags, True)
        if sc["code"] is not None:
            post(sc["code"], True, flags)
    else:
        flags = 0
        for _, mask in mods:
            flags |= getattr(Q, mask)
        if sc["code"] is not None:
            post(sc["code"], False, flags)
        for code, mask in reversed(mods):           # modifiers up
            flags &= ~getattr(Q, mask)
            post(code, False, flags, True)
    return True


_win_types = None


def _win_input_types():
    """ctypes structures for SendInput, built on first use."""
    global _win_types
    if _win_types is None:
        import ctypes
        from ctypes import wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):     # makes the union the right size
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class _Union(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _Union)]

        _win_types = (KEYBDINPUT, INPUT)
    return _win_types


def _win_send(sc, down):
    import ctypes
    if any(m not in WIN_MODS for m in sc["mods"]):
        return False                        # fn never reaches Windows
    KEYBDINPUT, INPUT = _win_input_types()
    keyup, extended = 0x0002, 0x0001

    def post(vk, key_down):
        flags = (0 if key_down else keyup) | (extended if vk in WIN_EXTENDED else 0)
        inp = INPUT(type=1, ki=KEYBDINPUT(wVk=vk, dwFlags=flags))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(KEY_GAP)

    vks = [WIN_MODS[m] for m in sc["mods"]]
    if down:
        for vk in vks:
            post(vk, True)
        if sc["code"] is not None:
            post(sc["code"], True)
    else:
        if sc["code"] is not None:
            post(sc["code"], False)
        for vk in reversed(vks):
            post(vk, False)
    return True
