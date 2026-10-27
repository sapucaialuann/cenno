"""Checks that a built Cenno is self-contained.

The user must not need Python, pip, OpenCV, mediapipe or the Visual C++
redistributable installed on their machine. PyInstaller's one-folder build
ships all of it next to the exe, but a broken or half-finished build would
look like "the app needs Python", which is the worst first impression there
is.

Two things are checked:

  * the binaries and data files that have to sit next to the exe
  * the pure Python packages, which PyInstaller puts inside the archive in
    Cenno.exe itself (they never appear as folders)

Usage:
    python installer/check_bundle.py [path-to-folder-containing-Cenno.exe]

The folder defaults to dist\\Cenno. Exits non-zero when something is missing.
"""

import os
import re
import subprocess
import sys

# (relative path, what it is)
REQUIRED_FILES = [
    ("Cenno.exe", "the program itself"),
    ("_internal/python311.dll", "the Python runtime"),
    ("_internal/python3.dll", "the Python runtime"),
    ("_internal/base_library.zip", "the Python standard library"),
    ("_internal/cv2/cv2.pyd", "OpenCV (camera and image processing)"),
    ("_internal/mediapipe", "mediapipe (hand tracking)"),
    ("_internal/numpy", "numpy (used by mediapipe)"),
    ("_internal/tcl86t.dll", "tkinter (the welcome and about windows)"),
    ("_internal/tk86t.dll", "tkinter (the welcome and about windows)"),
    ("_internal/VCRUNTIME140.dll", "the Visual C++ runtime"),
    ("_internal/VCRUNTIME140_1.dll", "the Visual C++ runtime"),
    ("_internal/MSVCP140.dll", "the Visual C++ runtime"),
    ("_internal/assets/icon_1024.png", "the app icon"),
]

# Pure Python packages: these live inside the archive in Cenno.exe.
REQUIRED_MODULES = [
    ("pystray", "the system tray icon"),
    ("pystray._win32", "the system tray icon on Windows"),
    ("PIL", "Pillow (the tray icon and the preview)"),
    ("numpy", "numpy (used by mediapipe)"),
    ("mediapipe", "mediapipe (hand tracking)"),
    ("tkinter", "tkinter (the welcome and about windows)"),
    ("pyautogui", "pyautogui (mouse and keyboard)"),
    ("hand_desktop_switcher", "the gesture engine"),
    ("displays", "the screen geometry"),
    ("theme", "the design tokens"),
]

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def archive_entries(exe):
    """The module names inside the exe archive, or None if PyInstaller is gone."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer", exe, "-r"],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    text = ANSI.sub("", out.stdout)
    return set(re.findall(r"'([A-Za-z_][A-Za-z0-9_.]*)'", text))


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "Cenno")
    root = os.path.abspath(root)

    print(f"== checking that {root} is self-contained")

    if not os.path.isdir(root):
        print(f"FAIL: {root} does not exist. Build it first: build_win.bat")
        return 1

    missing = []

    for rel, what in REQUIRED_FILES:
        if os.path.exists(os.path.join(root, rel)):
            print(f"  ok      {rel}  ({what})")
        else:
            print(f"  MISSING {rel}  ({what})")
            missing.append(what)

    exe = os.path.join(root, "Cenno.exe")
    entries = archive_entries(exe) if os.path.exists(exe) else None
    if entries is None:
        print("  (skipped the archive check: PyInstaller is not available here)")
    else:
        for module, what in REQUIRED_MODULES:
            if module in entries:
                print(f"  ok      {module}  ({what}, inside the exe)")
            else:
                print(f"  MISSING {module}  ({what}, inside the exe)")
                missing.append(what)

    if missing:
        print()
        print("FAIL: the build is not self-contained. These are missing:")
        for what in missing:
            print(f"  - {what}")
        print("A user without Python would not be able to run this.")
        return 1

    print()
    print("OK: everything the app needs is inside the bundle.")
    print("     The user does not need Python, pip, OpenCV, mediapipe")
    print("     or the Visual C++ redistributable installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
