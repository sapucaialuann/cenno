# PyInstaller spec for Cenno.app (build with ./build_mac.sh)
from PyInstaller.utils.hooks import collect_all

VERSION = "0.1.0"

datas, binaries, hiddenimports = [], [], []
d, b, h = collect_all("mediapipe")
datas += d; binaries += b; hiddenimports += h
hiddenimports += [
    "hand_desktop_switcher", "rumps",
    "Quartz", "AppKit", "Foundation", "ApplicationServices",
    "AVFoundation", "ServiceManagement",
]

a = Analysis(
    ["cenno_app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PySide6", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Cenno",
          console=False, argv_emulation=False, target_arch="arm64",
          codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Cenno")
app = BUNDLE(
    coll,
    name="Cenno.app",
    icon="build/Cenno.icns",
    bundle_identifier="com.luannsapucaia.cenno",
    version=VERSION,
    info_plist={
        "CFBundleName": "Cenno",
        "CFBundleDisplayName": "Cenno",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,                     # menu bar only, no Dock icon
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSCameraUsageDescription":
            "Cenno uses the camera to see your hand gestures. "
            "Video is processed on your Mac and never leaves it.",
        "CFBundleURLTypes": [{"CFBundleURLName": "Cenno commands",
                              "CFBundleURLSchemes": ["cenno", "newmotion"]}],
        "NSAppleEventsUsageDescription":
            "Cenno sends keyboard shortcuts to switch Spaces and control apps.",
    },
)
