# PyInstaller spec for Cenno.exe (build with build_win.bat)
from PyInstaller.utils.hooks import collect_all
import os
import tempfile

# The VERSION file is the single source of truth for the version: the exe,
# the installer and the DMG all read it.
VERSION = open("VERSION", encoding="utf-8").read().strip()

# PyInstaller takes the version resource from a file. Generate it from VERSION
# so it can never drift away from the installer.
_parts = [int(p) for p in VERSION.split(".")]
while len(_parts) < 4:
    _parts.append(0)
_filevers = tuple(_parts[:4])
VERSION_FILE = os.path.join(tempfile.gettempdir(), "cenno_version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as _f:
    _f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_filevers},
    prodvers={_filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Luann Sapucaia / Cenno'),
        StringStruct(u'FileDescription', u'Cenno - hand gesture control for Windows'),
        StringStruct(u'FileVersion', u'{VERSION}'),
        StringStruct(u'InternalName', u'Cenno'),
        StringStruct(u'LegalCopyright', u'Copyright (c) 2026 Luann Sapucaia'),
        StringStruct(u'OriginalFilename', u'Cenno.exe'),
        StringStruct(u'ProductName', u'Cenno'),
        StringStruct(u'ProductVersion', u'{VERSION}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)""")

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
    version=VERSION_FILE,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Cenno")
