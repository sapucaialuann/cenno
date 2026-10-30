"""Record a keyboard shortcut by pressing it (Windows).

record_shortcut() opens a small "Press the shortcut now..." window and
returns a shortcut dict (see shortcuts.py), or None if the person cancels.
Call it from the tkinter thread: it waits for the window to close.

While the window is open a low-level keyboard hook sees every key first and
swallows it, so combinations the shell would take, like Win+H, are recorded
instead of acting.  If the hook cannot be installed the window falls back to
tkinter key events, which cannot catch the Windows key reliably.

Pressing only modifiers (Ctrl+Win, say) and letting go records a
modifier-only shortcut, which is how push-to-talk keys are set.
"""

import tkinter as tk

import shortcuts
import theme

VK_ESCAPE = 0x1B
# Virtual key -> canonical modifier.  Left and right keys are the same
# modifier; 0x10/0x11/0x12 are the generic codes tkinter reports.
MOD_VKS = {0x10: "shift", 0xA0: "shift", 0xA1: "shift",
           0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
           0x12: "alt", 0xA4: "alt", 0xA5: "alt",
           0x5B: "win", 0x5C: "win"}
# Names for keys the shortcuts table knows; the first alias wins.
_NAMES = {}
for _name, _vk in shortcuts.WIN_KEY_CODES.items():
    _NAMES.setdefault(_vk, _name)


class KeyState:
    """Turns key down / up events into a recorded shortcut.  No UI, no
    Windows calls, so it can be tested anywhere.  Each call returns None or
    an event: ("preview", mods), ("keep", shortcut) or ("cancel", None)."""

    def __init__(self, key_name=None):
        self.key_name = key_name or (lambda vk: _NAMES.get(vk, ""))
        self.down = set()          # modifier keys down (left and right count apart)
        self.peak = set()          # every modifier seen since all were up
        self.typed = False         # a real key was pressed in this stretch

    @property
    def held(self):
        return {MOD_VKS[v] for v in self.down}

    def key_down(self, vk):
        mod = MOD_VKS.get(vk)
        if mod:
            if not self.peak:
                self.typed = False
            self.down.add(vk)
            self.peak.add(mod)
            return ("preview", set(self.peak))
        if vk == VK_ESCAPE and not self.held:
            return ("cancel", None)
        name = self.key_name(vk)
        if not name:
            return None
        self.typed = True
        return ("keep", shortcuts.make(
            self.held, vk, shortcuts.label_for(self.held, name, "Windows")))

    def key_up(self, vk):
        mod = MOD_VKS.get(vk)
        if not mod:
            return None
        self.down.discard(vk)
        if self.down:
            return None
        peak, typed = self.peak, self.typed
        self.peak = set()
        if peak and not typed:
            return ("keep", shortcuts.make(
                peak, None, shortcuts.label_for(peak, None, "Windows")))
        return ("release", None)


def _vk_name(vk):
    """Name of a key that shortcuts.py has no name for, from Windows."""
    name = _NAMES.get(vk)
    if name:
        return name
    import ctypes
    user32 = ctypes.windll.user32
    scan = user32.MapVirtualKeyW(vk, 0)
    if not scan:
        return ""
    extended = 1 << 24 if vk in shortcuts.WIN_EXTENDED else 0
    buf = ctypes.create_unicode_buffer(64)
    n = user32.GetKeyNameTextW((scan << 16) | extended, buf, 64)
    return buf.value if n else ""


class _Hook:
    """WH_KEYBOARD_LL hook that feeds a KeyState and swallows the keys."""

    WH_KEYBOARD_LL = 13
    DOWN, UP = (0x100, 0x104), (0x101, 0x105)
    INJECTED = 0x10

    def __init__(self, handler):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.handler = handler
        self.seen = set()             # keys we saw go down, and so swallow the up of
        self.handle = None

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                        ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                       ctypes.c_size_t, ctypes.c_ssize_t)
        user32 = ctypes.windll.user32
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_size_t, ctypes.c_ssize_t]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type,
                                             ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        def proc(code, wparam, lparam):
            try:
                if code >= 0:
                    info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if not info.flags & self.INJECTED:      # leave our own keys alone
                        vk = info.vkCode
                        if wparam in self.DOWN:
                            self.seen.add(vk)
                            self.handler(vk, True)
                            return 1
                        if wparam in self.UP and vk in self.seen:
                            self.seen.discard(vk)
                            self.handler(vk, False)
                            return 1
            except Exception:
                pass
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._proc = proc_type(proc)      # keep alive, or Windows calls freed memory
        module = ctypes.windll.kernel32.GetModuleHandleW(None)
        self.handle = user32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._proc,
                                               module, 0)
        self._user32 = user32

    @property
    def ok(self):
        return bool(self.handle)

    def remove(self):
        if self.handle:
            self._user32.UnhookWindowsHookEx(self.handle)
            self.handle = None


def record_shortcut(root, title="Press the shortcut now...", dark=True, reject=None):
    """Show the window and wait.  `reject(sc)` may return a message (the
    shortcut is refused and the person presses again) or None to accept."""
    paper = theme.hex_of("paper", dark)
    ink = theme.hex_of("ink", dark)
    muted = theme.hex_of("ink-muted", dark)
    win = tk.Toplevel(root)
    win.title("Cenno")
    win.configure(bg=paper)
    win.resizable(False, False)
    inner = tk.Frame(win, bg=paper)
    inner.pack(fill=tk.BOTH, expand=True, padx=theme.SPACE[6], pady=theme.SPACE[4])
    tk.Label(inner, text=title, bg=paper, fg=ink,
             font=theme.type_font("display", "title")).pack()
    shown = tk.StringVar(value=" ")
    tk.Label(inner, textvariable=shown, bg=paper, fg=ink, width=24,
             font=theme.type_font("display", "title")).pack(pady=theme.SPACE[3])
    note = tk.StringVar(value="Press the keys together, or just modifiers.\n"
                              "Esc on its own cancels.")
    tk.Label(inner, textvariable=note, bg=paper, fg=muted, justify="center",
             font=theme.type_font("sans", "body-sm")).pack()

    state = {"sc": None, "done": False}
    keys = KeyState(key_name=_vk_name)
    buttons = tk.Frame(inner, bg=paper)
    buttons.pack(anchor="e", pady=(theme.SPACE[3], 0))

    def button(text, command, primary=False):
        b = tk.Button(buttons, text=text, command=command, relief=tk.FLAT, bd=0,
                      padx=theme.SPACE[4], pady=theme.SPACE[2], cursor="hand2",
                      font=theme.type_font("sans", "label"),
                      bg=theme.hex_of("trace" if primary else "paper-raised", dark),
                      fg=theme.hex_of("on-trace" if primary else "ink", dark))
        b.pack(side=tk.LEFT, padx=(theme.SPACE[2], 0))
        return b

    def close(save):
        if state["done"]:
            return
        state["done"] = True
        if not save:
            state["sc"] = None
        hook.remove()
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()

    button("Cancel", lambda: close(False))
    save_button = button("Save", lambda: close(True), primary=True)
    save_button.configure(state=tk.DISABLED)

    def apply(event):
        if event is None:
            return
        kind, value = event
        if kind == "preview":
            shown.set(shortcuts.label_for(value, None, "Windows") or " ")
        elif kind == "keep":
            message = reject(value) if reject else None
            if message:
                note.set(message)
                return
            state["sc"] = value
            note.set("Press again to change it, or Save.")
            shown.set(value["label"])
            save_button.configure(state=tk.NORMAL)
        elif kind == "release" and state["sc"]:
            shown.set(state["sc"]["label"])
        elif kind == "cancel":
            win.after(0, lambda: close(False))

    def on_key(vk, down):
        apply(keys.key_down(vk) if down else keys.key_up(vk))

    win.protocol("WM_DELETE_WINDOW", lambda: close(False))
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    win.update_idletasks()
    try:
        win.lift()
        win.focus_force()
        win.grab_set()
    except Exception:
        pass

    try:
        hook = _Hook(on_key)
    except Exception as exc:
        print(f"WARN: keyboard hook unavailable: {exc}")
        hook = None
    if hook is None or not hook.ok:
        # Fallback: tkinter key events.  event.keycode is the virtual key code.
        if hook is not None:
            hook.remove()
        print("WARN: keyboard hook not installed; the Windows key may not be recorded")
        hook = type("NoHook", (), {"remove": lambda self: None})()
        win.bind("<KeyPress>", lambda e: (on_key(e.keycode, True), "break")[1])
        win.bind("<KeyRelease>", lambda e: (on_key(e.keycode, False), "break")[1])
        win.bind("<Alt-KeyPress>", lambda e: (on_key(e.keycode, True), "break")[1])
        win.bind("<Alt-KeyRelease>", lambda e: (on_key(e.keycode, False), "break")[1])
        win.focus_set()

    root.wait_window(win)
    return state["sc"]
