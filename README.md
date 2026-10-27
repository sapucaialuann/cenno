# Cenno

Formerly newMotion. Website: [cennoapp.com](https://cennoapp.com)

Control your Mac with hand gestures through the webcam. Runs on your Mac. Nothing leaves it.

## Install (macOS, Apple Silicon)

1. Download `Cenno-<version>.dmg` from the Releases page, open it and drag **Cenno** into **Applications**.
2. The app isn't notarized by Apple yet, so the first launch is blocked. Open it once, then go to **System Settings > Privacy & Security** and click **Open Anyway**.
3. Allow **Camera** when asked.
4. Enable Cenno under **System Settings > Privacy & Security > Accessibility** (needed to send shortcuts, scroll and move the mouse), then reopen it.
5. In **System Settings > Keyboard > Keyboard Shortcuts > Mission Control**, make sure "Move left/right a space", "Mission Control" and "Application windows" are on.

Cenno lives in the menu bar (hand icon): on/off (turns the camera off without quitting), pause, camera preview on/off and corner position, mouse control on/off, open at login, gesture list. With two or more displays connected there is also a **Displays** menu: **Current display** keeps the cursor on the screen it is already on, **All displays** lets the hand reach every screen, and **Move pointer to next display** hops the cursor over. Scrolling and Space switching follow the screen your hand is on.

## Several displays

- The cursor stays on one screen by default: whichever one it is on when you start pointing. That display is picked once per gesture, so crossing an edge mid-gesture never moves the target under your hand.
- Choose **Displays > All displays** to have the hand span the whole desk instead: moving it sideways walks from one monitor to the next, at the cost of a smaller movement range per screen.
- Plugging a display in or rearranging the desk is picked up within a quarter of a second. The cursor glides to its new spot instead of jumping.
- Scrolling and Space switching are sent to the screen the hand is on: Cenno moves the cursor there first (no click) so macOS gives that screen the focus.

## Voice and URL commands

Cenno responds to `cenno://on`, `cenno://off` and `cenno://toggle`.
To use your voice, add Voice Control commands (System Settings > Accessibility >
Voice Control > Commands > +): phrase "Cenno on", action **Open URL**,
`cenno://on`; same for "Cenno off".

## Gestures

| Gesture | Action |
|---|---|
| Open hand swipe right / left | Previous / next Space |
| Open hand swipe up / down | Mission Control / App windows (down again closes) |
| Two fingers up/down, flick | Scroll with momentum |
| Two-finger swipe right / left | Back / Forward |
| Point with index | Move the cursor |
| Pinch while pointing | Click; twice = double-click; hold = drag |
| OK sign + twist | Volume |
| Thumbs up (hold) | Play / pause |
| Thumbs down (hold) | Undo (deletes the last dictated text) |
| Hang loose (hold) | Dictation on / off (pick the tool in menu bar > Dictation: Wispr Flow, Apple Dictation, or any app via its shortcut) |
| Open hand then gather fingertips | Spotlight |
| Wave, open hand side to side | Lock screen |
| Rock horns (hold 1 s) | Pause / resume gestures (a fist does nothing, so you can rest your hand) |

## Files

- `cenno_app.py`: the menu bar app.
- `theme.py`: design tokens (colour, type, space, radius, motion) for Day and Night. The only place these values live.
- `hand_desktop_switcher.py`: gesture engine (also runs standalone with a preview window).
- `displays.py`: screen geometry (plain maths, tested without a camera).
- `tests/`: `python tests/test_displays.py` and `python tests/test_pointer_mapping.py`.
- `build_mac.sh`, `Cenno.spec`, `requirements-build.txt`: build the app and DMG (`./build_mac.sh`).

## Run from source

    pip install "mediapipe==0.10.9" opencv-python pyautogui rumps pyobjc-framework-Quartz pyobjc-framework-AVFoundation pyobjc-framework-ServiceManagement matplotlib
    python3 cenno_app.py

## Install (Windows)

1. Download `Cenno-<version>.exe` (or the installer) from the Releases page and run it.
2. Cenno lives in the system tray (hand icon): on/off, pause, camera preview on/off and corner position, mouse control on/off, displays, open at startup, gesture list.
3. Allow **Camera** when Windows asks (Settings > Privacy & security > Camera). Cenno needs no Accessibility permission on Windows.
4. If the camera isn't detected, open Camera settings from the tray menu.

## Several displays (Windows)

The same two-screen solution as on macOS, using the Windows monitors:

- **Displays > Current display** (default): the hand stays on the screen the cursor is on when it starts pointing. The screen is picked once per gesture, so crossing an edge mid-gesture never moves the target under your hand.
- **Displays > All displays**: the hand spans the whole desk. Moving it sideways walks from one monitor to the next, at the cost of a smaller movement range per screen.
- **Displays > Move pointer to next display**: hops the cursor to the next monitor without clicking anything.
- Plugging a monitor in or rearranging the desk is picked up within a quarter of a second; the cursor glides to its new spot instead of jumping.
- Scrolling is sent to the screen the hand is on: Cenno moves the cursor there first (no click), so the window under it gets the wheel.

Windows monitors are read straight from `user32` (`EnumDisplayMonitors`), so a monitor to the left of the main one — with negative coordinates — works exactly like the one on the right. The camera preview can be dragged onto any monitor and is remembered there.

## Look and feel (Windows)

The Windows app uses the same design system as the macOS one (`theme.py`), so both look like the same product:

- The camera preview is a rounded card in the Day / Night colours, with the hand drawn in the brand lime and the state in pills (**TRACKING**, **NO HAND**, **PAUSED**) instead of loose text.
- The preview follows the Windows apps theme (Settings > Personalization > Colours) and can be forced to Light or Dark from the tray menu.
- The welcome and about windows are styled with the same colours, type and spacing as the macOS dialogs.
- The tray icon dims when Cenno is paused or off and turns red when no camera is found.

## Install from source (Windows)

    pip install "mediapipe==0.10.9" opencv-python pyautogui pystray Pillow
    python cenno_app_win.py

To build the exe:

    build_win.bat

This produces `dist\Cenno\Cenno.exe`.

Run the tests:

    python tests\test_displays.py
    python tests\test_pointer_mapping.py
    python tests\test_dispatcher_displays.py
    python tests\test_windows_displays.py

## Windows differences

Cenno on Windows is intentionally Windows-native rather than a macOS clone:

- **System tray, not a menu bar.** Windows has no menu bar, so Cenno lives in the system tray (hand icon): on/off, pause, camera preview, mouse control, open at startup, gesture list.
- **Virtual desktops instead of Spaces.** Swipe left/right switches virtual desktops (`Ctrl+Win+Left/Right`). There is no slide animation like macOS Spaces.
- **Task View instead of Mission Control.** Swipe up opens Task View (`Win+Tab`), not Mission Control.
- **Show desktop instead of App windows.** Swipe down shows the desktop (`Win+D`), since Windows has no app-windows overview.
- **Start menu instead of Spotlight.** Gathering fingertips opens the Start menu (`Win`), not Spotlight.
- **Lock screen `Win+L`.** Waving locks the screen with `Win+L`.
- **Undo is `Ctrl+Z`.** Thumbs down sends `Ctrl+Z` (not `Cmd+Z`).
- **Back / Forward is `Alt+Left/Right`.** Two-finger swipe uses the Windows browser / File Explorer convention.
- **No Accessibility permission.** Windows has no Accessibility equivalent; the only OS permission is Camera (Settings > Privacy & security > Camera).
- **Settings in `%APPDATA%\Cenno`.** Settings and logs live in `%APPDATA%\Cenno`, not `~/Library/Application Support`.
- **Launch at startup via registry.** Cenno starts via the `HKCU\...\Run` registry key, not `ServiceManagement`.
- **`cenno://` via registry.** The `cenno://on/off/toggle` protocol is registered via the Windows registry protocol handler, not Apple events / `LSUIElement`.
- **Displays are always in the tray menu.** Windows has no menu bar to rebuild, so the **Displays** submenu is always there; on a single screen both modes do the same thing and "Move pointer to next display" tells you that only one screen is connected.

## Gestures

| Gesture | Action |
|---|---|
| Open hand swipe right / left | Previous / next virtual desktop |
| Open hand swipe up | Task View (`Win+Tab`) |
| Open hand swipe down | Show desktop (`Win+D`) |
| Two fingers up/down, flick | Scroll with momentum |
| Two-finger swipe right / left | Back / Forward (`Alt+Left/Right`) |
| Point with index | Move the cursor |
| Pinch while pointing | Click; twice = double-click; hold = drag |
| OK sign + twist | Volume |
| Thumbs up (hold) | Play / pause |
| Thumbs down (hold) | Undo (deletes the last dictated text) |
| Hang loose (hold) | Dictation on / off (Win+H voice typing, Wispr Flow, or custom shortcut) |
| Open hand then gather fingertips | Start menu (`Win`) |
| Wave, open hand side to side | Lock screen (`Win+L`) |
| Rock horns (hold 1 s) | Pause / resume gestures (a fist does nothing, so you can rest your hand) |

## Files

- `cenno_app_win.py`: the system-tray app for Windows.
- `hand_desktop_switcher.py`: gesture engine (shared with macOS).
- `theme.py`: design tokens (colour, type, space, radius, motion) for Day and Night, shared with macOS.
- `displays.py`: screen geometry for macOS (Quartz) and Windows (user32).
- `tests/`: `python tests/test_displays.py`, `python tests/test_pointer_mapping.py`, `python tests/test_dispatcher_displays.py` and `python tests/test_windows_displays.py`.
- `build_win.bat`, `Cenno_win.spec`, `requirements-build-win.txt`: build the exe (`build_win.bat`).

## Support

Cenno is free. If it helps you, you can support it on [Ko-fi](https://ko-fi.com/sapucaialuann). You can also find it in the tray menu under Support Cenno on Ko-fi.
