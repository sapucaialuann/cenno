# Task: apply the Cenno design system to the codebase

Restyle Cenno (macOS app and, if it lives in this repo, the landing page) to match the design system below. This is a visual and copy pass only. Do not change gesture detection, tracking, latency or any behaviour.

## Step 1: survey first, then plan
1. Identify the UI stack (SwiftUI/AppKit, Python + Qt/Tk/PyObjC, Electron, web, etc.) and list every place colours, fonts, spacing, radii, shadows and user-facing strings are defined or hardcoded.
2. Write a short plan: where the single token source will live, which files change, anything ambiguous. Then proceed.

## Step 2: one token source
Create one central theme module for the stack (e.g. `Theme.swift`, `theme.py`, `tokens.css`) holding every token below by its exact name. Replace all hardcoded values with references to it. No raw hex values anywhere else.

Two themes: Day (light) and Night (dark). Follow the macOS system appearance and switch live when it changes.

### Colour (Day / Night)
| token | Day | Night | use |
|---|---|---|---|
| paper | #f4f1ea | #14130f | window/page background |
| paper-raised | #ffffff | #1e1c17 | cards, panels, popovers, menu bar dropdown |
| paper-sunk | #e9e4d8 | #0d0c0a | camera preview frame, inputs, inactive toggle track |
| ink | #16140f | #f2eee4 | primary text/icons; primary button fill |
| ink-muted | #5f5a4e | #a8a293 | secondary text, captions |
| on-ink | #f4f1ea | #14130f | text on ink fill |
| line | #d9d3c4 | #2e2b24 | hairline dividers, card outlines (decorative only) |
| line-strong | #847d6b | #6e685a | borders of controls (inputs, secondary buttons, toggle outlines) |
| trace | #C9EB2E | #C9EB2E | brand fill: hand cursor, Tracking pill, selected toggle |
| trace-soft | #e4f0af | #2b3013 | selected rows, cursor hover zone, recognised-spell flash |
| trace-ink | #526209 | #c9eb2e | trace as text/icon/stroke on paper; success wording |
| on-trace | #16140f | #16140f | text on trace and trace-soft |
| ember | #ff5a1f | #ff6b35 | held moment (pinch/drag in progress, a spell firing). Fill only, small |
| ember-ink | #ae3303 | #ff8a5c | ember as text; warnings |
| on-ember | #16140f | #16140f | text on ember |
| danger | #a3122a | #ff7d8e | errors and destructive actions, always with a word |
| focus | = ember-ink | = ember-ink | focus ring, 2px solid, 2px offset |

Rules:
- Never use `trace` as text or a thin line on Day paper (invisible). Use `trace-ink`.
- Only live, hand-driven things get `trace` or `ember`. Static chrome stays ink/paper/line.
- States differ by word and shape first, colour second: Tracking = trace fill pill; Paused = outline pill; No hand = ember-ink text; Error = danger text.
- No gradients, glows or particle effects.

### Type
Families:
- display: "Bricolage Grotesque", "Instrument Sans", system-ui, sans-serif
- sans: "Instrument Sans", -apple-system, BlinkMacSystemFont, system-ui, sans-serif
- mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace

Styles (size / line height / weight / letter spacing):
- display-xl 72/72/600/-0.03em (site hero only)
- display-l 44/48/600/-0.02em (site sections, onboarding titles)
- display-m 30/36/600/-0.01em (settings page titles). Display is never below 30px.
- title 18/24/600 (spell names, panel headings, dialog titles)
- body 15/22/400 (default)
- body-sm 13/18/400 (helper text, menu items)
- label 12/16/600/0.04em, ALWAYS uppercase (status pills, small labels). Nothing else is uppercase.
- caption 12/16/400 (version strings, footnotes)
- kbd 12/16/500 mono (keycaps, shortcuts)
- code 13/20/400 mono (spell definitions, logs, latency)

In the native app, system font fallback for sans is fine if the fonts are not bundled. If bundling, use the official woff2/ttf files from Google Fonts (all three are OFL). On the web, load from Google Fonts.

### Space, radius, shadow
- Spacing (4px base): space-1 4, space-2 8, space-3 12, space-4 16, space-6 24, space-8 32, space-12 48, space-20 80. App cards pad space-4, panels space-6, settings window margins space-8. Site: space-8 inside cards, space-20 between sections (space-12 on mobile).
- Radius: radius-sm 6 (keycaps, inputs), radius-md 12 (buttons, rows, camera preview), radius-lg 20 (cards, panels), radius-pill 999 (pills, toggles, the hand cursor). Nothing sharp.
- Depth comes from 1px `line` outlines, not shadows. `shadow-hud` only for things floating over other apps (hand cursor, spell toast): Day `0 8px 24px rgba(22,20,15,0.18)`, Night `0 8px 24px rgba(0,0,0,0.55)`.
- Every interactive element gets the 2px `focus` ring with 2px offset.

### Motion
- Cursor and trace follow the hand with NO added easing or smoothing from the UI layer. Do not touch existing tracking filters.
- UI state changes 120ms ease-out; overlays appearing 200ms. No bounce or overshoot.
- Recognised spell: flash `trace-soft` behind its row/toast for 400ms, then settle.
- Respect macOS Reduce Motion: drop the flash, keep the state change.

## Step 3: components
Build or restyle these as reusable pieces (web: classes with the `nm-` prefix for new components):
- **Button**: primary = ink fill + on-ink text; secondary = line-strong outline + ink text. radius-md, space-3 horizontal padding. Labels are verbs.
- **Toggle**: pill; off = paper-sunk track with line-strong outline; on = trace fill.
- **Kbd**: mono kbd style, radius-sm, paper-sunk, line outline.
- **StatusPill**: label style, pill radius. Tracking / Paused / No hand / Error as described above.
- **SpellRow**: title for spell name, then "Spell · Action" pattern, e.g. "Swipe left · Next Space", optional Kbd for the shortcut. Flashes trace-soft on recognition.
- **HandCursor**: trace-filled circle, radius-pill, shadow-hud; switches to ember fill while a pinch/drag is held.

## Step 4: copy pass
Update every user-facing string:
- The name is always **Cenno** (capital C). Fix any "newMotion", "NewMotion", "New Motion", "newmotion", "Jarvis".
- Second person, sentence case, short sentences. Buttons are verbs ("Start tracking", "Pause", "Add spell").
- A spell = a hand movement that triggers an action on the computer. Use this word consistently, on the site and in the app. Do not use "gesture", "shortcut" or "command" in user-facing copy.
- Privacy copy states facts: "Runs on your Mac. Nothing leaves it."
- Support copy: "Cenno is free. If it helps you, you can support it on Ko-fi." No guilt.
- No emoji in UI. No exclamation marks in system messages. No em dashes anywhere (use full stop, comma or middle dot ·).

## Logo and icons
- The mark exists and is the hand: `assets/hand.svg` is the master vector, `assets/Cenno.icon/` is the layered macOS icon, `assets/icon_1024.png` is the raster for `Cenno.icns`. Use them as they are. Never redraw the hand. Set the name in display, weight 600, ink, next to the mark.
- Native app: SF Symbols, regular weight, ink or ink-muted. Web: simple 1.5px-stroke line icons in ink. Spell glyphs are arrows and dots, never hands or faces.

## Step 5: verify
- Build and run. Screenshot the main surfaces (menu bar dropdown, settings window, overlays/toast, cursor, landing page) in both Day and Night.
- Check every text/background pair hits 4.5:1 contrast (3:1 for control borders, focus rings, icons and text 24px+).
- Grep for leftover raw hex values, old font names and em dashes.
- Confirm detection behaviour and latency are unchanged.
- Report: files changed, anything you could not map to a token, and any open questions.
