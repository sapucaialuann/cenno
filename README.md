# newMotion

Hand-gesture control for macOS using the webcam (MediaPipe + OpenCV).

Two versions:

- `hand_desktop_switcher.py`: baseline. Four-finger swipe between Spaces, OK-sign twist for volume, two-finger scroll.
- `hand_desktop_switcher_claude.py`: swipes between Spaces, Mission Control and App windows, two-finger scroll with momentum, back/forward, OK-sign volume knob, thumbs-up play/pause, gather for Spotlight, fist to pause, and mouse control (point to move, pinch to click, hold to drag).

## Run

    pip install "mediapipe<0.10.10" opencv-python pyautogui
    python3 hand_desktop_switcher_claude.py

Grant Camera and Accessibility permission to the terminal running Python, and enable the Mission Control keyboard shortcuts (Ctrl+Arrow) in System Settings.
