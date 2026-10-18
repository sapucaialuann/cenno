# newMotion

Control your Mac with hand gestures through the webcam. Runs fully on your Mac (MediaPipe + OpenCV); video never leaves the machine.

## Install (macOS, Apple Silicon)

1. Download `newMotion-<version>.dmg` from the Releases page, open it and drag **newMotion** into **Applications**.
2. The app isn't notarized by Apple yet, so the first launch is blocked. Open it once, then go to **System Settings > Privacy & Security** and click **Open Anyway**.
3. Allow **Camera** when asked.
4. Enable newMotion under **System Settings > Privacy & Security > Accessibility** (needed to send shortcuts, scroll and move the mouse), then reopen it.
5. In **System Settings > Keyboard > Keyboard Shortcuts > Mission Control**, make sure "Move left/right a space", "Mission Control" and "Application windows" are on.

newMotion lives in the menu bar (hand icon): on/off (turns the camera off without quitting), pause, camera preview on/off and corner position, mouse control on/off, open at login, gesture list.

## Voice and URL commands

newMotion responds to `newmotion://on`, `newmotion://off` and `newmotion://toggle`.
To use your voice, add Voice Control commands (System Settings > Accessibility >
Voice Control > Commands > +): phrase "newMotion on", action **Open URL**,
`newmotion://on`; same for "newMotion off".

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
| Rock horns (hold 1 s) | Pause / resume gestures (a fist does nothing, so you can rest your hand) |

## Files

- `newmotion_app.py`: the menu bar app.
- `hand_desktop_switcher_claude.py`: gesture engine (also runs standalone with a preview window).
- `hand_desktop_switcher.py`: simpler baseline version.
- `build_mac.sh`, `newMotion.spec`, `requirements-build.txt`: build the app and DMG (`./build_mac.sh`).

## Run from source

    pip install "mediapipe==0.10.9" opencv-python pyautogui rumps pyobjc-framework-Quartz pyobjc-framework-AVFoundation pyobjc-framework-ServiceManagement matplotlib
    python3 newmotion_app.py

## Support

newMotion is free. If you enjoy it, you can support it at [ko-fi.com/sapucaialuann](https://ko-fi.com/sapucaialuann) (also in the menu bar: Support newMotion).
