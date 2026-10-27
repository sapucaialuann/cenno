"""
Cenno design tokens: the single source for colour, type, space, radius,
shadow and motion. Nothing else in the app hardcodes these values.

Two themes, Day (light) and Night (dark), picked from the macOS appearance.
"""

# =============================================================================
# Colour: name -> (Day, Night)
# =============================================================================

COLORS = {
    "paper":        ("#f4f1ea", "#14130f"),   # window background
    "paper-raised": ("#ffffff", "#1e1c17"),   # cards, panels, pills on video
    "paper-sunk":   ("#e9e4d8", "#0d0c0a"),   # camera preview frame, inputs
    "ink":          ("#16140f", "#f2eee4"),   # primary text and icons
    "ink-muted":    ("#5f5a4e", "#a8a293"),   # secondary text
    "on-ink":       ("#f4f1ea", "#14130f"),   # text on ink fill
    "line":         ("#d9d3c4", "#2e2b24"),   # hairlines, card outlines
    "line-strong":  ("#847d6b", "#6e685a"),   # control borders
    "trace":        ("#C9EB2E", "#C9EB2E"),   # brand fill, live hand things
    "trace-soft":   ("#e4f0af", "#2b3013"),   # selected rows, cursor hover zone, recognised-spell flash
    "trace-ink":    ("#526209", "#c9eb2e"),   # trace as text/icon/stroke on paper; success wording
    "on-trace":     ("#16140f", "#16140f"),   # text on trace and trace-soft
    "ember":        ("#ff5a1f", "#ff6b35"),   # held moment (pinch, drag)
    "ember-ink":    ("#ae3303", "#ff8a5c"),   # ember as text, warnings
    "on-ember":     ("#16140f", "#16140f"),   # text on ember
    "danger":       ("#a3122a", "#ff7d8e"),   # errors, always with a word
}
COLORS["focus"] = COLORS["ember-ink"]

# =============================================================================
# Type
# =============================================================================

FONT_DISPLAY = '"Bricolage Grotesque", "Instrument Sans", system-ui, sans-serif'
FONT_SANS = '"Instrument Sans", -apple-system, BlinkMacSystemFont, system-ui, sans-serif'
FONT_MONO = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace'

# name -> (size, line height, weight, letter spacing in em)
TYPE = {
    "display-xl": (72, 72, 600, -0.03),
    "display-l":  (44, 48, 600, -0.02),
    "display-m":  (30, 36, 600, -0.01),
    "title":      (18, 24, 600, 0),
    "body":       (15, 22, 400, 0),
    "body-sm":    (13, 18, 400, 0),
    "label":      (12, 16, 600, 0.04),      # always uppercase
    "caption":    (12, 16, 400, 0),
    "kbd":        (12, 16, 500, 0),         # mono
    "code":       (13, 20, 400, 0),         # mono
}

# =============================================================================
# Space, radius, shadow, motion
# =============================================================================

SPACE = {1: 4, 2: 8, 3: 12, 4: 16, 6: 24, 8: 32, 12: 48, 20: 80}

RADIUS_SM = 6
RADIUS_MD = 12
RADIUS_LG = 20
RADIUS_PILL = 999

# shadow-hud: (offset x, offset y, blur, colour hex, alpha) per theme
SHADOW_HUD = (
    (0, 8, 24, "#16140f", 0.18),
    (0, 8, 24, "#000000", 0.55),
)

FOCUS_WIDTH = 2
FOCUS_OFFSET = 2

MOTION_STATE_S = 0.120      # UI state changes, ease-out
MOTION_OVERLAY_S = 0.200    # overlays appearing
FLASH_S = 0.400             # recognised spell: trace-soft, then settle


# =============================================================================
# Appearance
# =============================================================================

def system_is_dark():
    """True when macOS is in Dark appearance (False on any failure)."""
    try:
        import AppKit
        app = AppKit.NSApp
        if app is not None:
            name = app.effectiveAppearance().bestMatchFromAppearancesWithNames_(
                ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
            return str(name) == "NSAppearanceNameDarkAqua"
    except Exception:
        pass
    try:
        from Foundation import NSUserDefaults
        style = NSUserDefaults.standardUserDefaults().stringForKey_("AppleInterfaceStyle")
        return str(style) == "Dark" if style else False
    except Exception:
        return False


def reduce_motion():
    """True when the user asked macOS to reduce motion."""
    try:
        import AppKit
        return bool(AppKit.NSWorkspace.sharedWorkspace()
                    .accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


# =============================================================================
# Colour accessors
# =============================================================================

def hex_of(name, dark=False):
    return COLORS[name][1 if dark else 0]


def rgb(name, dark=False):
    h = hex_of(name, dark).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bgr(name, dark=False):
    """OpenCV order."""
    r, g, b = rgb(name, dark)
    return (b, g, r)


def ns_color(name, dark=False, alpha=1.0):
    import AppKit
    r, g, b = rgb(name, dark)
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, alpha)
