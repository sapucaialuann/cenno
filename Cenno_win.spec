# PyInstaller spec for Cenno.exe (build with build_win.bat)
from PyInstaller.utils.hooks import collect_all
import os

VERSION = "0.2.0"

datas, binaries, hiddenimports = [], [], []
d, b, h = collect_all("mediapipe")
datas += d; binaries += b; hiddenimports += h
datas += [("assets", "assets")]

hiddenimports += [
    "hand_desktop_switcher",
    "displays",
    "theme",
    "pystray._win32",
    "PIL._tkinter_finder",
    "tkinter",
    "tkinter.simpledialog",
]

_icon = "assets\\icon.ico" if os.path.exists("assets\\icon.ico") else None

a = Analysis(
    ["cenno_app_win.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PySide6", "IPython", "pytest",
              "rumps", "AppKit", "Foundation", "Quartz",
              "AVFoundation", "ServiceManagement"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Cenno",
    console=False,
    icon=_icon,
    version="version.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="Cenno")
