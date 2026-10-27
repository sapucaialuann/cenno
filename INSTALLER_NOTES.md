# Cenno for Windows — Installer & Release Notes

The Windows installer is **Inno Setup 6** and it is built by `build_win.bat`.
The script lives in `installer/cenno.iss`.

## What the user gets

`dist\Cenno-<version>-Setup.exe` is a normal Windows installer: double-click
it, follow the wizard, and Cenno is installed.

| What the user asked for | Where it comes from |
|---|---|
| Progress bar | Inno's modern wizard shows one on the *Installing* page |
| Choose where to install | the *Destination folder* page (enabled by default) |
| Confirmation it is installed | the *Finish* page: "Cenno has been installed on your computer" |
| An executable on the Desktop | `desktopicon` task, checked by default |
| An executable in the Start Menu | always created, in the `Cenno` folder |
| A way to remove it | uninstaller, registered in Settings > Apps > Installed apps |
| It just works | the `cenno://` URL handler is registered at install time |

## Build it

    build_win.bat

That builds `dist\Cenno\Cenno.exe` with PyInstaller, checks that the result
is self-contained, and then compiles the installer with `ISCC.exe`.
`build_win.bat exe-only` stops after the exe.

The version comes from the `VERSION` file at the repository root. It is the
single source of truth: the exe resource, the installer and the macOS DMG all
read it.

### The app has to be self-contained

The user will not have Python, pip, OpenCV, mediapipe or the Visual C++
redistributable installed. All of it ships inside the app folder (PyInstaller
puts the Python runtime and the compiled libraries next to the exe, and the
pure Python packages inside the archive in the exe).

`installer/check_bundle.py` checks that, and the build fails if anything is
missing:

    python installer\check_bundle.py dist\Cenno

It also runs against an installed copy, to prove the installer shipped
everything:

    python installer\check_bundle.py "%LOCALAPPDATA%\Programs\Cenno"

### Inno Setup

Inno Setup 6 is free and installs in a minute:

    winget install JRSoftware.InnoSetup

`build_win.bat` finds `ISCC.exe` in the usual places. If it lives somewhere
else, point the build at it:

    set CENNO_ISCC=C:\path\to\ISCC.exe
    build_win.bat

## Install or not: the user's choice

`PrivilegesRequired=lowest` with `PrivilegesRequiredOverridesAllowed=dialog`
means:

- **Just me** (the default): installs to
  `%LOCALAPPDATA%\Programs\Cenno`, no administrator prompt, no UAC. This is
  the path an everyday user should get.
- **All users**: installs to `Program Files\Cenno` and asks for the
  administrator password, like any Windows program.

Both produce the same shortcuts and the same uninstaller.

## Registry

The installer writes **only** `HKCU\Software\Classes\cenno`, the `cenno://`
URL handler (`cenno://on`, `cenno://off`, `cenno://toggle`). It is per-user,
needs no admin rights, and the uninstaller removes it again.

The installer deliberately does **not** touch
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Cenno manages its own
"Open at startup" from the tray menu, and a second copy of that entry would
fight with the app.

The same handler can be (re)registered from the app at any time:
tray menu > **Register cenno:// protocol**.

## Code signing

An unsigned `Cenno.exe` and an unsigned installer both trigger Windows
SmartScreen: "Windows protected your PC". This is a hard barrier to a public
release: people download the file, Windows blocks it, and they never get to
try the app.

Sign both binaries with a Windows code-signing certificate. An EV certificate
is the one that gets instant SmartScreen reputation.

    set CENNO_SIGN_PFX=C:\certs\cenno.pfx
    set CENNO_SIGN_PWD=the-password
    build_win.bat

The build signs `dist\Cenno\Cenno.exe` and the installer, both with a
timestamp (so the signature survives certificate expiry).

### Testing the signing flow without a certificate

    powershell -ExecutionPolicy Bypass -File installer\make_test_cert.ps1

This creates a self-signed certificate, trusts it on this machine and signs
the built binaries. It proves the signing step works. It does not remove the
SmartScreen warning on other people's machines: only a real, publicly trusted
certificate does that.

## Release checklist

1. Bump the `VERSION` file and commit it.
2. Tag it and push the tag: `git tag v0.2.1 && git push origin v0.2.1`.
3. The `Release` workflow builds the `.dmg` and the installer, signs the
   Windows binaries when a certificate is in the secrets, publishes the
   GitHub release and puts the `.dmg` in the bucket the website serves.
4. Check the release page and https://cennoapp.com/download/latest.

To release by hand, build both, sign them and upload them to the release
page. `scripts/upload_release.sh` in the website repository puts the `.dmg`
in the bucket on its own.

## Troubleshooting

**"Inno Setup 6 not found"** — install it (`winget install JRSoftware.InnoSetup`)
or set `CENNO_ISCC`.

**SmartScreen says the app is unrecognized** — the file is unsigned. See
*Code signing* above.

**The app does not start after installing** — look at
`%APPDATA%\Cenno\Cenno.log`. The tray menu has "Open log file" too.
