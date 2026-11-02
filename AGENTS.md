# Cenno: notes for coding agents

Cenno controls macOS and Windows with hand gestures through the webcam
(MediaPipe hand landmarks, no network). This file is for any coding agent or
person working on the repo. User-facing docs are in README.md.

## Layout

| Path | What it is |
|---|---|
| `hand_desktop_switcher.py` | The core. `classify_pose` (landmarks -> pose), `GestureEngine` (poses and motion -> abstract events, no OS calls, fully testable), `Dispatcher` / `PointerAnimator` / `ScrollAnimator` (events -> keys, mouse and scroll on background threads). All tuning constants are at the top. Also runs standalone: `python3 hand_desktop_switcher.py`. |
| `cenno_app.py` | macOS menu bar app (rumps): camera thread, preview panel, settings, menu. |
| `cenno_app_win.py` | Windows tray app, same structure. Keep the two in step. |
| `displays.py`, `headzone.py`, `shortcuts.py`, `recorder_*.py`, `pointer_box.py`, `theme.py` | Multi-display layout, "held like a phone by the ear" check, recorded keyboard shortcuts, shortcut recorders, preview box style, design tokens. |
| `tests/` | Plain-assert tests on synthetic landmarks, no camera. `tests/run_all.py` runs every `test_*.py`. |
| `tools/` | Developer tools (not shipped): gesture check, gesture demos, slap scorer. See below. |
| `checks/` | Recordings of real hands. Git-ignored: they stay on the machine that made them. |
| `build_mac.sh`, `Cenno.spec`, `build_win.bat`, `Cenno_win.spec`, `installer/` | Builds. |

## Run, test, build

- Tests: `python3 tests/run_all.py` must print `all tests passed` before any merge. It needs no camera and no cv2.
- Build the Mac app: `./build_mac.sh` makes `dist/Cenno.app` and `dist/Cenno-<VERSION>.dmg`, using its own venv `.venv-build` (Python with mediapipe 0.10.9 and OpenCV). It signs with a local certificate when one exists (`installer/make_dev_cert_mac.sh`), so Camera and Accessibility permissions survive rebuilds.
- Anything that needs cv2 or MediaPipe (the gesture tools) runs with `.venv-build/bin/python`.
- The app logs to `~/Library/Logs/Cenno.log` (each action, `fps:` once a minute, `gather missed: <reason>` for Spotlight attempts that did not fire). Settings: `~/Library/Application Support/Cenno/settings.json`.

## Gesture work: real recordings are the standard

Gestures are tuned on recordings of the user's real hand, not on synthetic hands
alone, and the recordings that count are **natural** ones: the user does each
gesture the way they would, with no feedback on screen. A coached session (live
"what Cenno sees" panel, demos) makes people adapt to the test, so it measures the
adaptation. People also use both hands, and gestures look different from each side.

- Record (camera; switch the Cenno app off first, the tool refuses otherwise):
  `.venv-build/bin/python tools/gesture_check.py natural --only slap_right,slap_left --hand both`
- Score any recording, natural or guided: `python3 tools/gesture_check.py report checks/<file>.json`.
  Natural reports give per gesture and hand: hits, misses, wrong actions, wrong hand seen.
- Guided mode (`record`) has demos and a live explanation of why a gesture is not
  recognised. It is good for diagnosis, not for tuning targets.
- `tools/gesture_demos.py <step>` shows the intended gesture; every demo is tested to fire its own step.
- `tools/slap_score.py` counts Space switches across guided recordings.

A gesture change is accepted when it raises the natural hit rate for the gestures
it targets and does not make any recorded step that passed before fail. Then it
gets tried in real use: the user's experience there beats any score.

## Every piece of work starts from a GitHub issue

- A new request, a bug found along the way, or an idea becomes an issue *before* work starts. Search the open issues first; extend an existing one instead of duplicating it.
- Each issue gets exactly one **type**, at least one **area**, one **priority**, and its **OS** label(s):
  - type: `type: bug` (does not work as intended), `type: feature` (something new), `type: improvement` (make what exists work better, incl. tuning), `type: chore` (build, release, docs, tools, process)
  - area: `area: spaces`, `area: pointer`, `area: spotlight`, `area: scroll`, `area: dictation`, `area: gestures` (other poses), `area: app` (menu, preview, settings, permissions), `area: tools`
  - os, one or both: `os: macos`, `os: windows`. Both labels = affects both systems, so filtering by one OS shows everything that affects it. Shared code (the gesture engine, both apps) gets both, even if it was only seen on one; say in the issue where it was observed.
  - priority, exactly one: `P0: critical` (unusable or harmful: drop everything), `P1: high` (a main gesture unreliable in daily use: next up), `P2: medium` (noticeable, or needed for the next release), `P3: low` (minor, rarely used, or watch only). The developer has the final say; work on the highest priority first.
- Put it in the **release milestone** it ships in. One theme per release: `0.3.0` ship what is on `dev`, `0.4.0` pointer, `0.5.0` other gestures. New issues go into the release they fit, or stay without a milestone until the developer schedules them. Releases are worked on in order; within a release, by priority.
- The issue says what is wrong or wanted, the evidence (measurements, recording, log lines), and what "done" means.
- Branches name the issue (`fix/10-ghost-drag`, `feat/16-stay-awake`).

## Every issue is finished by a pull request

No issue is closed without a PR, and no code reaches `dev` without one (small fixes included).

1. **Todo**: the issue exists, nobody works on it.
2. **Doing**: a branch from `dev` exists for it (pushed), and the issue is assigned or commented "working on it".
3. **Ready to merge**: a PR into `dev` is open, its description says `Fixes #N` and the measured result, `python3 tests/run_all.py` passes, and the review routine is done (code review, then simplify on new code only).
4. **Done**: the PR is merged into `dev` and the issue is closed.

The project board ("Cenno") shows these four columns; move the card when the state changes. One PR per issue; a PR that needs several issues lists them all (`Fixes #9, fixes #10`).

## Branches, issues, releases

- `main` = released. Releases come from tags: pushing `vX.Y.Z` runs `.github/workflows/release.yml`, which builds the .dmg, the Windows installer and the file the website serves.
- `dev` = integration branch, pushed to GitHub. All work lands here; it should stay usable.
- Work branches are short-lived and branch from `dev`. They reach `dev` only through a PR (see above), then get deleted. Push anything that lives longer than a working session; nothing should exist only on one machine.
- Bigger projects (the pointer: issue #7) get their own pushed branch; their issues get PRs into that branch, and the branch reaches `dev` by one final PR.
- The Windows app shares the engine. A change to the engine or to `cenno_app.py` usually needs the same change in `cenno_app_win.py`, and Windows builds must be tested on Windows before a release (#4).

## Code style

These rules apply to all **new** code. Existing code does not have to be rewritten.

- **KISS.** The simplest thing that works. No abstraction, option or layer until a second real use needs it. Small functions that do one thing, with names that say what.
- **Best practices.** Clear names, no duplication, early returns over deep nesting, no magic numbers (named constants), errors handled where they can be acted on, no dead code or commented-out code.
- **Comments: concise, but they explain.** One or two short lines on *why*, not a restatement of *what*. Constants carry their unit and what raising or lowering them does.
- Thresholds are measured in palms (relative to the hand's size in the frame), so they work at any distance from the camera.
- Engine logic stays free of OS calls, so it can be replayed from recordings and tested.
- New behaviour comes with a test in `tests/`; a gesture fix also comes with its score on a real recording.
- No new dependencies without a reason.

**Touching old code:** when a change goes through an existing function that is hard to read, it may be rewritten for readability, but **only after the developer approves it**. Propose the rewrite (what and why) first; never mix an unapproved refactor into a fix.
