# Cenno for Windows — Gesture Parity Review (Phase 6)

This document cross-checks every macOS gesture from the `README.md` gesture table
(lines 26-40) against the Windows implementation in `hand_desktop_switcher.py`
(`KEY_BINDINGS["Windows"]`, the `Dispatcher`, and `ACTION_LABELS`) and the Windows
gesture table already present in `README.md` (lines 74-89).

**Status is based on reading the code, not on live testing.** "Verified: yes (code)"
means the binding or handler exists for Windows. Nothing was actually tested and
nothing is being published or shipped.

No changes were made to `hand_desktop_switcher.py` or `cenno_app_win.py` as part of
this review.

## KEY_BINDINGS["Windows"] (hand_desktop_switcher.py, lines 841-848)

```python
"Windows": {
    "space_left":  ("ctrl", "win", "left"),
    "space_right": ("ctrl", "win", "right"),
    "overview":    ("win", "tab"),
    "app_windows": ("win", "d"),
    "close_overview": ("escape",),
    "back":        ("alt", "left"),
    "forward":     ("alt", "right"),
    "launcher":    ("win",),
    "undo":        ("ctrl", "z"),
    "lock":        ("win", "l"),
},
```

`DOWN_OPENS_OVERVIEW = OS_NAME == "Darwin"` evaluates to `False` on Windows, so an
open-hand swipe down maps to `app_windows` (`Win+D`, Show desktop) rather than
opening/closing an overview.

## Parity table

| # | Gesture (README macOS table) | macOS action | Windows action | Code location | Verified |
|---|---|---|---|---|---|
| 1 | Open hand swipe right / left | Previous / next Space (`Ctrl+Left/Right`) | Previous / next virtual desktop (`Ctrl+Win+Left/Right`) | `KEY_BINDINGS["Windows"]` space_left/space_right | yes (code) |
| 2 | Open hand swipe up | Mission Control (`Ctrl+Up`) | Task View (`Win+Tab`) | `KEY_BINDINGS["Windows"]` overview | yes (code) |
| 3 | Open hand swipe down | App windows (`Ctrl+Down`) | Show desktop (`Win+D`) | `KEY_BINDINGS["Windows"]` app_windows; `DOWN_OPENS_OVERVIEW` is `False` | yes (code) |
| 4 | Two fingers up/down, flick | Scroll with momentum | Scroll with momentum (`pyautogui` scroller thread) | `Dispatcher.submit` → `ScrollAnimator` | yes (code) |
| 5 | Two-finger swipe right / left | Back / Forward (`Cmd+[ / ]`) | Back / Forward (`Alt+Left/Right`) | `KEY_BINDINGS["Windows"]` back/forward | yes (code) |
| 6 | Point with index | Move the cursor | Move the cursor (`pyautogui` pointer, kept inside `POINTER_BOX`) | `Dispatcher.submit` → `PointerAnimator` | yes (code) |
| 7 | Pinch while pointing | Click; twice = double-click; hold = drag | Click; twice = double-click; hold = drag | `Dispatcher.submit` click/mouse_down/mouse_up | yes (code) |
| 8 | OK sign + twist | Volume | Volume up / down (`pyautogui` media keys `volumeup`/`volumedown`) | `Dispatcher._do` → `MEDIA_KEYS` → `pag.press` | yes (code) |
| 9 | Thumbs up (hold) | Play / pause | Play / pause (`pyautogui` media key `playpause`) | `Dispatcher._do` → `MEDIA_KEYS` → `pag.press` | yes (code) |
| 10 | Thumbs down (hold) | Undo | Undo (`Ctrl+Z`) | `KEY_BINDINGS["Windows"]` undo | yes (code) |
| 11 | Hang loose (hold) | Dictation on / off | Dictation on / off (Wispr Flow, Win+H voice typing, or custom shortcut) | `_toggle_dictation_windows()` | yes (code) |
| 12 | Open hand then gather fingertips | Spotlight (`Cmd+Space`) | Start menu (`Win`) | `KEY_BINDINGS["Windows"]` launcher | yes (code) |
| 13 | Wave (open hand side to side) | Lock screen (`Ctrl+Cmd+Q`) | Lock screen (`Win+L`) | `KEY_BINDINGS["Windows"]` lock (falls through to bindings on Windows) | yes (code) |
| 14 | Rock horns (hold 1 s) | Pause / resume gestures | Pause / resume gestures (a fist rests and does nothing) | `Dispatcher._do` `if name.startswith("pause")` | yes (code) |

## Summary

- All 14 gestures from the macOS `README.md` table have a Windows equivalent implemented
  in code.
- Every Windows binding lives in `KEY_BINDINGS["Windows"]`; media keys, dictation,
  pointer, scroll, click/drag, and pause/resume are handled by the shared `Dispatcher`
  with Windows-specific branches.
- This is a documentation / parity review only: no release was built, signed, or
  published, and no source was modified.
