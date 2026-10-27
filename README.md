# Cenno

Formerly newMotion. Website: [cennoapp.com](https://cennoapp.com)

Control your Mac with hand gestures through the webcam. Runs on your Mac. Nothing leaves it.

## Install (macOS, Apple Silicon)

1. Download `Cenno-<version>.dmg` from the Releases page, open it and drag **Cenno** into **Applications**.
2. The app isn't notarized by Apple yet, so the first launch is blocked. Open it once, then go to **System Settings > Privacy & Security** and click **Open Anyway**.
3. Allow **Camera** when asked.
4. Enable Cenno under **System Settings > Privacy & Security > Accessibility** (needed to send shortcuts, scroll and move the mouse), then reopen it.
5. In **System Settings > Keyboard > Keyboard Shortcuts > Mission Control**, make sure "Move left/right a space", "Mission Control" and "Application windows" are on.

Cenno lives in the menu bar (hand icon): on/off (turns the camera off without quitting), pause, camera preview on/off and corner position, mouse control on/off, open at login, gesture list.

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
- `build_mac.sh`, `Cenno.spec`, `requirements-build.txt`: build the app and DMG (`./build_mac.sh`).

## Run from source

    pip install "mediapipe==0.10.9" opencv-python pyautogui rumps pyobjc-framework-Quartz pyobjc-framework-AVFoundation pyobjc-framework-ServiceManagement matplotlib
    python3 cenno_app.py

## Install (Windows)

1. Download `Cenno-<version>.exe` (or the installer) from the Releases page and run it.
2. Cenno lives in the system tray (hand icon): on/off, pause, camera preview on/off and corner position, mouse control on/off, open at startup, gesture list.
3. Allow **Camera** when Windows asks (Settings > Privacy & security > Camera). Cenno needs no Accessibility permission on Windows.
4. If the camera isn't detected, open Camera settings from the tray menu.

## Install from source (Windows)

    pip install "mediapipe==0.10.9" opencv-python pyautogui pystray Pillow
    python cenno_app_win.py

To build the exe:

    build_win.bat

This produces `dist\Cenno\Cenno.exe`.

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
- `build_win.bat`, `Cenno_win.spec`, `requirements-build-win.txt`: build the exe (`build_win.bat`).

## Support

Cenno is free. If it helps you, you can support it on [Ko-fi](https://ko-fi.com/sapucaialuann). You can also find it in the tray menu under Support Cenno on Ko-fi.
