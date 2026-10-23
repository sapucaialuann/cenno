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

## Support

Cenno is free. If it helps you, you can support it on [Ko-fi](https://ko-fi.com/sapucaialuann). You can also find it in the menu bar under Support Cenno on Ko-fi.
