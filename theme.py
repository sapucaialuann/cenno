"""
Cenno design tokens: the single source for colour, type, space, radius,
shadow and motion. Nothing else in the app hardcodes these values.

Two themes, Day (light) and Night (dark), picked from the OS appearance:
macOS reads the Aqua / Dark Aqua appearance, Windows reads the Apps theme.

The tokens are platform neutral.  Only the helpers that have to ask the OS
(system_is_dark, reduce_motion) are platform specific, and they degrade to
a sane default when the OS says nothing.
"""

import platform

OS_NAME = platform.system()

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
    "trace":        ("#c8f03c", "#c8f03c"),   # brand fill, live hand things
    "trace-soft":   ("#e6f7a8", "#2a3310"),   # recognised-gesture flash
    "trace-ink":    ("#4f6b00", "#c8f03c"),   # trace as text on paper
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

# Fonts by role, best first.  The design fonts are not installed on every
# machine, so each role falls back to the closest one the platform has.
FONT_ROLES = {
    "display": ("Bricolage Grotesque", "Instrument Sans",
                "Segoe UI Variable Display", "Segoe UI", "Tahoma",
                "Helvetica Neue", "Arial"),
    "sans":    ("Instrument Sans", "Segoe UI Variable Text", "Segoe UI",
                "Helvetica Neue", "Arial"),
    "mono":    ("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"),
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
FLASH_S = 0.400             # recognised gesture: trace-soft, then settle


# =============================================================================
# Appearance
# =============================================================================

def _windows_is_dark():
    """Windows apps theme: the AppsUseLightTheme setting under Personalize."""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(val) == 0
    except Exception:
        return False


def _macos_is_dark():
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


def system_is_dark():
    """True when the OS is in Dark appearance (False on any failure)."""
    if OS_NAME == "Windows":
        return _windows_is_dark()
    if OS_NAME == "Darwin":
        return _macos_is_dark()
    return False


def _windows_reduce_motion():
    """Windows: animations turned off in the system settings."""
    # 1. The system wide "animate windows" switch.
    try:
        import ctypes
        SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = ctypes.c_bool()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        if ok and not enabled.value:
            return True
    except Exception:
        pass
    # 2. The classic "animate minimize / maximize" switch.
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\Desktop\WindowMetrics") as key:
            val, _ = winreg.QueryValueEx(key, "MinAnimate")
        if str(val) == "0":
            return True
    except Exception:
        pass
    return False


def reduce_motion():
    """True when the user asked the OS to reduce motion."""
    if OS_NAME == "Windows":
        return _windows_reduce_motion()
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


# =============================================================================
# Fonts
# =============================================================================

_installed_families = None


def installed_families():
    """The font families this machine has.  Empty when they cannot be
    listed (no Tk yet, or no tkinter at all)."""
    global _installed_families
    if _installed_families is None:
        try:
            import tkinter.font as tkfont
            _installed_families = {f.lower() for f in tkfont.families()}
        except Exception:
            _installed_families = set()
    return _installed_families


def font_family(role="sans"):
    """The best family for a role: the design font when it is installed, the
    platform's own otherwise."""
    candidates = FONT_ROLES.get(role, FONT_ROLES["sans"])
    families = installed_families()
    for name in candidates:
        if not families or name.lower() in families:
            return name
    return candidates[0]


def type_font(role, style):
    """A Tk font tuple for a type style, e.g. type_font("sans", "title")."""
    size, _line_height, weight, _spacing = TYPE.get(style, TYPE["body"])
    return (font_family(role), size, "bold" if weight >= 600 else "normal")
