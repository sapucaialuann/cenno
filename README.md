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

## Support

Cenno is free. If it helps you, you can support it on [Ko-fi](https://ko-fi.com/sapucaialuann). You can also find it in the menu bar under Support Cenno on Ko-fi.
