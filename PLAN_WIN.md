# Cenno for Windows — Structured Port Plan

**Cenno** (formerly newMotion) is a local, privacy-first hand-gesture control app: camera → MediaPipe → gesture engine → OS shortcuts. Nothing leaves the machine.

- **macOS app** (shipped): menu bar via `rumps`/`AppKit`, settings in `~/Library/Application Support`, launch via `ServiceManagement`, `cenno://` URL handler, themed floating preview, camera + Accessibility permissions.
- **Windows port** (in progress, branch `sapucaialuann/cenno-for-windows`): system tray via `pystray`/`tkinter`, settings in `%APPDATA%\Cenno`, launch via registry `Run` key, shares the cross-platform engine `hand_desktop_switcher.py`.

The Windows port already works end to end (tray icon, gesture detection, Windows shortcut bindings, dictation via Wispr / Win+H / custom). What remains is to make it feel like a **Windows app** rather than a macOS clone — because most of the usability differs.

---

## 1. Guiding principles

| Principle | What it means for the Windows port |
|-----------|------------------------------------|
| **Windows-native, not a macOS clone** | System tray, not menu bar. `Win` key shortcuts, not `Cmd`. `%APPDATA%`, not `~/Library`. Registry `Run` key, not `ServiceManagement`. |
| **Usability differs intentionally** | macOS Spaces ↔ Windows virtual desktops (`Ctrl+Win+Left/Right`); Mission Control ↔ Task View (`Win+Tab`); App windows ↔ Show desktop (`Win+D`); lock screen `Win+L`. Follow Windows conventions. |
| **Privacy stays local** | Camera frames never leave the machine. No cloud, no telemetry. |
| **Shared engine stays shared** | `hand_desktop_switcher.py` is the single source of truth for gesture recognition. Platform-specific code lives only in the app wrappers (`cenno_app.py` vs `cenno_app_win.py`). |
| **No Accessibility permission on Windows** | Windows has no AX equivalent. Camera privacy is the only OS permission; guide the user to Windows Settings > Privacy & security > Camera. |

---

## 2. Gap analysis — macOS vs Windows

| Subsystem | macOS (`cenno_app.py`) | Windows (`cenno_app_win.py`) | Status on Windows |
|-----------|------------------------|------------------------------|-------------------|
| UI shell | Menu bar (`rumps`) with SF Symbol icon | System tray (`pystray`), static icon | Works; icon never reflects paused/off state |
| Preview window | `AppKit.NSPanel`: corner **or free/drag**, S/M/L sizes, themed pills, click-through, on every desktop | `tkinter.Toplevel`: corner only, fixed medium size, no drag, no theming | Big UX gap |
| Settings | JSON, `~/Library/Application Support/Cenno` | JSON, `%APPDATA%\Cenno` | Done |
| Logs | `~/Library/Logs/Cenno.log` | `%APPDATA%\Cenno\Cenno.log` | Done |
| Launch at login | `ServiceManagement` | Registry `HKCU\...\Run` | Done |
| Permissions | Accessibility (AX) + Camera, with prompts + settings-pane links | Camera only (via Windows Settings); no programmatic check | Needs first-run camera guidance |
| URL scheme | `cenno://on/off/toggle` (Apple events) | None | Missing |
| Dark mode | `theme.py`, follows macOS appearance | `theme.py`, follows the Windows apps theme (Light/Dark override) | Done |
| Reduce motion | Yes | Yes (Windows animations setting) | Done |
| Notifications | `rumps.notification` | None | Missing |
| About dialog | `rumps.alert` (privacy + Ko-fi) | Menu item disabled | Missing |
| Dictation | Wispr (bundle ID), Apple Dictation (AX), custom shortcut via Quartz | Wispr (tasklist), Win+H, custom via pyautogui | Mostly done; Wispr detection weaker |
| Volume | Native media keys (`NSEvent`, osascript fallback) | pyautogui `volumeup/volumedown` | Done in engine |
| Lock screen | `login.framework` `SACLockScreenImmediate` | `Win+L` | Done in engine |
| Key bindings | Cmd-based | Win/Ctrl/Alt-based | Done in engine |
| Build | `.app` + `.dmg`, codesign, layered `icns` | `.exe` via PyInstaller, `icon.ico` | Build output is stale (`dist/newMotion`) |

---

## 3. Phased plan

### Phase 0 — Stabilise the baseline

**Status: Complete**

**Goal:** The Windows app builds cleanly, runs from source and from the built `.exe`, and is usable day to day.

Tasks:
1. Fix the build output name: `build_win.bat` / `Cenno_win.spec` currently leaves a stale `dist/newMotion` folder; ensure it produces `dist/Cenno/Cenno.exe`.
2. Verify `pip install -r requirements-build-win.txt` resolves on a clean Windows machine (mediapipe wheel, opencv-python, pystray, Pillow, pyinstaller).
3. Run `build_win.bat` and launch `dist/Cenno/Cenno.exe`; confirm tray icon appears, gestures map to Windows shortcuts, preview shows, quit works.
4. Confirm settings/logs write to `%APPDATA%\Cenno` and migrate from an old `newMotion` folder (already implemented — keep it).
5. Add a quick "run from source" section to README for Windows (`python cenno_app_win.py`).

Exit criteria: `build_win.bat` ends in `BUILD_OK`; the exe launches, tracks a hand, and switches virtual desktops with a swipe.

**Intentionally different on Windows:** nothing here — pure stabilization.

---

### Phase 1 — Preview window parity

**Status: Complete**

**Goal:** The floating camera preview on Windows feels as useful as on Mac, adapted to Windows windowing.

Tasks:
1. Add `preview_size` (Small / Medium / Large) and `preview_pos` to `DEFAULT_SETTINGS` and the settings UI (tray > Camera preview > Size; keep Position > corners).
2. Make `TkPreview` draggable in "free" position (bind `<B1-Motion>` on the label/window; save position after a 0.7 s settle, like the Mac `_remember_drag`).
3. Keep click-through behavior in corner mode (Windows: `win32con.WS_EX_TRANSPARENT` / `SetWindowLong` on the tkinter hwnd, or accept that clicks pass through a borderless topmost window by default).
4. Theme the preview panel: paper/line colors from `theme.py` (read the active Windows theme, see Phase 4) or a fixed neutral theme.
5. Remember corner + position across restarts.

Exit criteria: User can set preview to Small/Medium/Large, place it in any corner or drag it free, and the position survives a restart.

**Intentionally different on Windows:** macOS preview floats over every Space and above full-screen apps via `NSWindowCollectionBehavior`; on Windows, always-on-top topmost is the practical equivalent. No per-virtual-desktop behavior exists on Windows.

---

### Phase 2 — Tray & status polish

**Status: Complete**

**Goal:** The tray icon communicates state and the app has standard Windows dialogs.

Tasks:
1. Make the tray icon reflect state: default hand icon, dimmed/gray when paused, red or dimmed when off, camera-warning when no camera. (pystray supports `icon.icon = Image` swaps; generate tinted copies from `assets/icon_1024.png` with PIL.)
2. Show a Windows toast/notification when Accessibility-equivalent state changes is not applicable; instead notify on first successful gesture and on errors ("No camera found"). Use `win10toast` or `plyer` (lightweight) — or fall back to a balloon tip via `pystray`/`ctypes`.
3. Replace the disabled "About" menu item with a real `tkinter.messagebox` about dialog: version, privacy line ("Runs on your machine. Nothing leaves it."), Ko-fi support link.
4. Add "Open log file" (already implemented via `os.startfile`) and "Open settings folder".

Exit criteria: Tray icon changes with pause/off; about dialog opens; notification appears on camera error.

**Intentionally different on Windows:** No menu bar exists; the tray is the home. No "Accessibility: allowed" state exists on Windows — do not invent one.

---

### Phase 3 — First-run & permissions

**Status: Complete**

**Goal:** A new Windows user can get Cenno running without hunting for settings.

Tasks:
1. First-run flow: if no `settings.json` exists, show a one-time welcome (tkinter dialog or tray notification) explaining: grant Camera in Windows Settings > Privacy & security > Camera; Cenno needs no Accessibility permission on Windows.
2. Add a "Camera" status state in the tray title ("Cenno: No camera found") and a tray menu item "Open Camera settings" that launches `ms-settings:privacy-webcam` via `os.startfile` / `subprocess`.
3. Validate the webcam index (`CAMERA_INDEX = 0`) and offer a fallback or settings option if multiple cameras exist.
4. Add a "Check for updates" placeholder/menu item (no-op or opens GitHub Releases).

Exit criteria: Fresh install → tray runs → user can open camera settings from the menu → gestures work once camera is allowed.

**Intentionally different on Windows:** No programmatic camera-authorization check exists (unlike `AVFoundation` on macOS). Detect "no camera" by `cv2.VideoCapture` failing, not by a permission API.

---

### Phase 4 — Windows-specific integration

**Status: Complete**

**Goal:** Cenno integrates with Windows the way users expect.

Tasks:
1. **Dark mode:** Detect Windows light/dark theme (`winreg` `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`, `AppsUseLightTheme`) and apply it to the preview panel and any tkinter dialogs. Expose a Dark/Light/System choice in settings.
2. **Reduce motion:** Detect `SPI_GETDROPSHADOW` / accessibility animations or simply respect a settings toggle; shorten/disable preview fade and gesture flash when on.
3. **`cenno://` URL protocol handler:** Register `Cenno` protocol in `HKCU\Software\Classes\cenno\shell\open\command` pointing to the exe with `%1`, so `cenno://on`, `cenno://off`, `cenno://toggle` work from Voice Access, shortcuts, or the browser. Handle the incoming URL on a second instance (activate the running tray and call `set_enabled`). This replaces the macOS Apple-events URL handler.
4. **Dictation polish:** Keep Wispr (tasklist detection), Win+H voice typing, and custom shortcut; add guidance text in the dialog pointing users to Wispr Flow Settings > Shortcut.

Exit criteria: Dark mode follows Windows; `cenno://on` toggles Cenno from outside the app; dictation shortcut dialog has Windows-appropriate examples (`ctrl+shift+space`, `win+h`).

**Intentionally different on Windows:** macOS opens `x-apple.systempreferences:` panes; Windows uses `ms-settings:` URIs. macOS uses `cenno://` via `LSUIElement`/Apple events; Windows uses a registry protocol handler + `WM_COPYDATA`/socket to talk to the running tray instance.

---

### Phase 5 — Build, signing & release

**Status: Installer built and verified. Not signed, not published.**

**Goal:** Ship a trustworthy Windows release.

Tasks:
1. [x] Clean `build_win.bat` so `dist/Cenno/Cenno.exe` is the output; remove stale `dist/newMotion`.
2. [x] Inno Setup installer (`installer/cenno.iss`): progress bar, destination folder page, desktop + Start Menu shortcuts, uninstaller in Settings > Apps, `cenno://` handler registered at install time. `build_win.bat` compiles it to `dist/Cenno-<version>-Setup.exe`.
3. [ ] Code-sign the `.exe` (and installer) with a Windows code-signing certificate so SmartScreen doesn't flag it. Ad-hoc self-sign for internal testing; real cert for public releases. `installer/make_test_cert.ps1` covers the test case.
4. [x] Version resource on the exe (`version.txt` is generated from the `VERSION` file, so the exe, the installer and the DMG cannot disagree).
5. [ ] GitHub Actions (optional): Windows build matrix on push/tag, upload the setup `.exe` as a release asset.

Exit criteria: `build_win.bat` produces a signed `Cenno.exe`; installer installs and launches; SmartScreen shows "Verified publisher" (after real cert).

---

### Phase 6 — Parity review & ship

**Status: Prepared, not shipped**

**Goal:** Confirm the Windows port delivers the same *capabilities* as macOS through Windows-appropriate *interfaces*.

Tasks:
1. Walk the gesture list (README table) and verify each action works on Windows: spaces, Task View, show desktop, back/forward, Start, scroll, cursor, click/drag, volume, play/pause, dictation, undo, Spotlight→Start, lock, pause/resume.
2. Update `README.md` with a Windows install section (download `.exe`/installer, camera permission, gesture list unchanged, `cenno://` commands).
3. Add a "Windows differences" note so users don't expect Mission Control or the menu bar.
4. Ship the first Windows release (e.g., v0.2.1) and collect feedback.

Exit criteria: All gestures from the README work on Windows; README documents Windows install + differences; release published.

---

### Phase 7 — Several displays & visual identity

**Status: Complete**

**Goal:** Bring the two-screen solution and the design system to Windows.

Tasks:

1. **Screen geometry (`displays.py`).** Port the macOS display module and make it cross-platform: the pure maths (union, clamp, nearest, next) stays the same, `quartz_displays()` stays macOS, `windows_displays()` reads the monitors from `user32` (`EnumDisplayMonitors` / `GetMonitorInfoW`), primary first, in virtual desktop coordinates. A monitor to the left of the main one has negative x, exactly like macOS.
2. **Engine (`hand_desktop_switcher.py`).** The pointer keeps its 0..1 target and converts it against the display it belongs to, so one screen behaves pixel for pixel like before and several screens work: one screen (the one under the cursor, picked once per gesture) or the whole desk. The scroll thread asks the dispatcher to move the cursor to the aimed screen before the wheel goes out.
3. **Tray menu.** A **Displays** submenu with *Current display*, *All displays* and *Move pointer to next display*. The menu is rebuilt after every action so the check marks follow the settings.
4. **Preview window.** Follows the display layout: the corner is the primary screen, a dragged preview can live on any monitor and is clamped to the desktop.
5. **Design system (`theme.py`).** `system_is_dark()` and `reduce_motion()` now work on Windows (registry + `SPI_GETCLIENTAREAANIMATION`), and the design fonts fall back to the Windows ones when they are not installed. The preview renders the same pills and colours as macOS, the panel is a rounded card, and the welcome / about windows use the same tokens.
6. **Tests.** `tests/test_displays.py`, `tests/test_pointer_mapping.py` and `tests/test_windows_displays.py` (the last one asks the real `user32` for the monitors).

Exit criteria: Two monitors are picked up automatically, the hand can reach the second one, the pointer never teleports when a monitor is plugged in, and the Windows app looks like the macOS one.

---

## 4. Platform-difference decisions register

| Decision | macOS | Windows | Rationale |
|----------|-------|---------|-----------|
| UI chrome | Menu bar (rumps) | System tray (pystray) | No menu bar on Windows |
| Shortcut modifier | `Cmd` | `Win` | Windows convention |
| Spaces | `Ctrl+Left/Right` | `Ctrl+Win+Left/Right` | Windows virtual desktops |
| Mission Control | `Ctrl+Up` | `Win+Tab` (Task View) | Closest Windows equivalent |
| App windows | `Ctrl+Down` | `Win+D` (Show desktop) | `DOWN_OPENS_OVERVIEW = False` on Windows |
| Back/forward | `Cmd+[/]` | `Alt+Left/Right` | Windows browser/File Explorer convention |
| Launcher | `Cmd+Space` (Spotlight) | `Win` (Start) | |
| Lock | `login.framework` | `Win+L` | |
| Undo | `Cmd+Z` | `Ctrl+Z` | |
| Permissions | AX + Camera prompts | Camera guidance only | No AX on Windows |
| Launch at login | `ServiceManagement` | Registry `Run` | |
| Settings dir | `~/Library/Application Support` | `%APPDATA%` | |
| URL scheme | `cenno://` via Apple events | `cenno://` via registry protocol | |
| Appearance | macOS Dark/Night + reduce motion | Windows dark theme setting + toggle | |
| Preview | Borderless panel, every Space | Borderless topmost, all monitors | Windows has no Spaces |

---

## 5. Risks & open questions

- **MediaPipe on Windows:** works, but webcam access can be blocked by Windows camera privacy even when the app runs. The first-run guidance (Phase 3) mitigates this.
- **pyautogui fail-safe:** throwing the mouse to a corner raises an exception. The pointer already stays inside `POINTER_BOX`; keep it away from corners.
- **pystray + tkinter threading:** tray callbacks run on the pystray thread; all tkinter calls already go through `root.after()`. Keep that discipline when adding dialogs/notifications.
- **SmartScreen:** unsigned exe will warn users. Plan for code-signing cost before the public release.
- **Second-instance handling for `cenno://`:** decide whether the protocol handler launches a new instance (which should exit and activate the tray) or uses a named pipe/socket to message the running tray.

---

## 6. Definition of done (Windows v1.0)

Phases 0-4 are complete. Phases 5-6 are prepared but not shipped (no release was
built, signed, or published).

- [x] `build_win.bat` produces `dist/Cenno/Cenno.exe` from a clean checkout (Phase 0)
- [x] Tray icon reflects paused/off/camera states (Phase 2)
- [x] Preview: Small/Medium/Large, corners + draggable free position, remembered on restart (Phase 1)
- [x] First-run camera guidance + "Open Camera settings" menu item (Phase 3)
- [x] Dark mode follows Windows theme (with override) (Phase 4)
- [x] `cenno://on/off/toggle` protocol handler registered and working (Phase 4)
- [x] About dialog with version, privacy line, Ko-fi link (Phase 2)
- [x] Notifications on camera error / first gesture (Phase 2)
- [x] All README gestures verified on Windows — see `GESTURE_PARITY_WIN.md` (Phase 6, prepared)
- [x] README has Windows install + differences section (Phase 6, prepared)
- [x] Several displays: the hand reaches a second monitor, and the layout survives plugging one in (Phase 7)
- [x] Visual identity: the same design tokens as macOS drive the preview, the panel and the dialogs (Phase 7)
- [x] Windows installer built and verified: installs, launches, creates the desktop + Start Menu shortcuts, uninstalls cleanly (Phase 5)
- [ ] First Windows release published (signed installer) (Phase 5 — not shipped)

---

**Maintainer note:** This plan tracks the Windows port only. The macOS app (`cenno_app.py`, `build_mac.sh`, `Cenno.spec`) is unchanged. `hand_desktop_switcher.py` and `theme.py` remain shared; any change to the engine must be tested on both platforms.
