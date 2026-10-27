# Cenno for Windows — Installer & Release Notes

**Status:** documentation only. Nothing here is built, signed, or published.  
Related plan: `PLAN_WIN.md` Phase 5 ("Build, signing & release").

## Recommended tool: Inno Setup

**Inno Setup** is the better fit for Cenno over NSIS:

- Cenno is a simple tray app: a single `dist\Cenno\` folder (exe + assets + DLLs) to copy to Program Files.
- Inno Setup scripts are Pascal-like and readable; an installer for "copy folder + Start Menu shortcut" is ~30 lines.
- It handles uninstall, Start Menu shortcuts, optional desktop shortcuts, and the Program Files location natively.
- NSIS is more powerful but more complex (NSIS script language, plugin ecosystem) — overkill for a single-exe tray app whose startup behavior is already handled by the app itself.

NSIS remains a fine alternative if the maintainer already knows it, but Inno Setup is the recommended default.

## What the installer should do

1. Install the full contents of `dist\Cenno\` (i.e. `Cenno.exe` plus its side-by-side DLLs and `assets\`) into `Program Files\Cenno` (or `Program Files (x86)\Cenno` on 32-bit builds).
2. Create a Start Menu shortcut: `Start Menu\Programs\Cenno\Cenno.lnk` pointing at `Cenno.exe`, with `assets\icon.ico` as the icon.
3. Optionally create a desktop shortcut `Cenno.lnk` (user-configurable during install, default off).
4. Offer a "Launch Cenno" checkbox on the finish page.
5. **Do not** create the registry Run entry in the installer. Cenno manages its own "Open at startup" launch via `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` from within the app (tray menu), so the installer must not duplicate or conflict with that.

## Code-signing before public release

- The unsigned `Cenno.exe` (and any installer) will trigger Windows SmartScreen: "Windows protected your PC" / "Microsoft Defender SmartScreen prevented an unrecognized app from starting". This is a hard barrier to a public release.
- Code-sign `Cenno.exe` and the installer with a Windows code-signing certificate (EV cert preferred for immediate SmartScreen reputation). Sign after PyInstaller builds the exe, and sign the installer after Inno Setup compiles it.
- **Ad-hoc self-signing is fine for internal testing** (e.g. `SignTool sign /f test.pfx /p <pw> /fd SHA256 /tr http://timestamp.digicert.com Cenno.exe`), but self-signed certs still show SmartScreen warnings — they only prove the file hasn't changed since signing.
- A real publicly trusted certificate is required before the first public Windows release so SmartScreen shows the verified publisher instead of a warning.

## Out of scope for this phase

- No installer file is created here (documentation only).
- Nothing is published or shipped.
- `build_win.bat` is not extended to invoke Inno Setup or SignTool; those are manual/release steps.
