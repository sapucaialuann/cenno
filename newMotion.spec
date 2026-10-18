# PyInstaller spec for newMotion.app (build with ./build_mac.sh)
from PyInstaller.utils.hooks import collect_all

VERSION = "0.1.0"

datas, binaries, hiddenimports = [], [], []
d, b, h = collect_all("mediapipe")
datas += d; binaries += b; hiddenimports += h
hiddenimports += [
    "hand_desktop_switcher_claude", "rumps",
    "Quartz", "AppKit", "Foundation", "ApplicationServices",
    "AVFoundation", "ServiceManagement",
]

a = Analysis(
    ["newmotion_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PySide6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="newMotion",
          console=False, argv_emulation=False, target_arch="arm64",
          codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="newMotion")
app = BUNDLE(
    coll,
    name="newMotion.app",
    icon="build/newMotion.icns",
    bundle_identifier="com.luannsapucaia.newmotion",
    version=VERSION,
    info_plist={
        "CFBundleName": "newMotion",
        "CFBundleDisplayName": "newMotion",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,                     # menu bar only, no Dock icon
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription":
            "newMotion uses the camera to see your hand gestures. "
            "Video is processed on your Mac and never leaves it.",
        "CFBundleURLTypes": [{"CFBundleURLName": "newMotion commands",
                              "CFBundleURLSchemes": ["newmotion"]}],
        "NSAppleEventsUsageDescription":
            "newMotion sends keyboard shortcuts to switch Spaces and control apps.",
    },
)
