"""
Cenno: display geometry.

A display is a rect (x, y, w, h) in the global desktop space the OS uses for
the mouse: pixels, origin at the top left of the primary display, y growing
downwards.  Displays left of or above the primary one therefore have negative
coordinates, which is normal and not an error.

Everything here is plain arithmetic on those rects, so it can be unit tested
without a camera, a window server or a screen API.  Only the OS-specific
functions at the bottom (quartz_displays / windows_displays) talk to the
system; system_displays() picks the right one for the platform.
"""

import platform

# How many active displays we ask the OS for.  Plenty: both macOS and
# Windows support far more than that.
DISPLAY_QUERY_MAX = 16

# Keep the cursor this far from every edge of the target rect.  1 keeps
# pyautogui's corner fail-safe quiet and stops the cursor sticking on the
# bezel; it reproduces the old single-screen clamp exactly.
EDGE_PAD = 1


# =============================================================================
# Rect helpers
# =============================================================================

def union_rect(rects):
    """Smallest rect containing all of them.  Empty input gives (0, 0, 0, 0)."""
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def center(rect):
    x, y, w, h = rect
    return (x + w / 2.0, y + h / 2.0)


def contains(rect, point):
    """True if point is inside rect (edges count as inside)."""
    x, y, w, h = rect
    return x <= point[0] <= x + w and y <= point[1] <= y + h


def clamp_point(point, rect, pad=EDGE_PAD):
    """Pull point inside rect, keeping `pad` clear of every edge."""
    x, y, w, h = rect
    return (min(x + w - 1 - pad, max(x + pad, point[0])),
            min(y + h - 1 - pad, max(y + pad, point[1])))


def normalized_to_point(n, rect):
    """Map 0..1 across rect, no clamping: (0, 0) is its top left."""
    x, y, w, h = rect
    return (x + n[0] * w, y + n[1] * h)


def normalized_to_rect(n, rect, pad=EDGE_PAD):
    """Where in rect the pointer's 0..1 position lands, edge padded."""
    return clamp_point(normalized_to_point(n, rect), rect, pad)


def clamp_to_nearest(point, rects, pad=EDGE_PAD):
    """Pull point onto the closest display, like the real mouse does at the
    edge of a shorter screen.  A point already on a display stays put."""
    best, best_d = None, None
    for r in rects:
        q = clamp_point(point, r, pad)
        d = (q[0] - point[0]) ** 2 + (q[1] - point[1]) ** 2
        if best_d is None or d < best_d:
            best, best_d = q, d
    return best if best is not None else point


def rects_equal(a, b):
    return list(a) == list(b)


def layout_summary(rects):
    return " ".join(f"[{int(r[0])},{int(r[1])} {int(r[2])}x{int(r[3])}]" for r in rects)


# =============================================================================
# Layout: the list of displays, the primary one, and the pointer's target rect
# =============================================================================

class DisplayLayout:
    """The screens as the OS reports them.

    rects[0] is always the primary display (the one with the taskbar / menu
    bar) and the rest are sorted left to right, top to bottom, so "next
    display" walks the desk instead of following an order the window server
    happens to use.  Displays that report the same rect (mirrored pairs) are
    collapsed to one.
    """

    def __init__(self, rects, primary=0):
        kept = []
        for i, r in enumerate(rects or ()):
            r = (float(r[0]), float(r[1]), float(r[2]), float(r[3]))
            if r[2] <= 0 or r[3] <= 0:
                continue                      # display is off
            if any(r == k[1] for k in kept):
                continue                      # mirrored pair: same pixels twice
            kept.append((i, r))
        if not kept:                           # nothing reported: never fail
            kept = [(0, (0.0, 0.0, 0.0, 0.0))]
        head = next((r for i, r in kept if i == primary), kept[0][1])
        rest = sorted((r for _, r in kept if r != head), key=lambda r: (r[0], r[1]))
        self.rects = [head] + rest
        self.primary = 0

    @classmethod
    def fallback(cls, size):
        """One screen the size pyautogui reports: no screen API, or nothing
        found."""
        return cls([(0.0, 0.0, float(size[0]), float(size[1]))])

    @property
    def count(self):
        return len(self.rects)

    @property
    def union(self):
        return union_rect(self.rects)

    def rect(self, index):
        if index is None or not (0 <= index < len(self.rects)):
            index = self.primary
        return self.rects[index]

    def center(self, index):
        return center(self.rect(index))

    def index_at(self, point):
        """Index of the display holding point, or -1 if it is in a gap."""
        for i, r in enumerate(self.rects):
            if contains(r, point):
                return i
        return -1

    def screen_of(self, point):
        """Display holding point; the nearest one if it is in a gap."""
        i = self.index_at(point)
        return i if i >= 0 else self.nearest(point)

    def nearest(self, point):
        """Index of the display whose centre is closest: gaps and edges too."""
        if not self.rects:
            return 0
        return min(range(len(self.rects)),
                   key=lambda i: ((center(self.rects[i])[0] - point[0]) ** 2
                                  + (center(self.rects[i])[1] - point[1]) ** 2))

    def neighbor(self, index, direction):
        """Display next to `index` in direction (dx, dy), e.g. (-1, 0) for
        the one on the left.  Picks the closest one whose centre lies on that
        side, favouring ones straight across over diagonal ones.  None when
        there is nothing that way."""
        if not (0 <= index < len(self.rects)):
            index = self.primary
        cx, cy = center(self.rects[index])
        dx, dy = direction
        best, best_score = None, None
        for i, r in enumerate(self.rects):
            if i == index:
                continue
            ox, oy = center(r)
            along = (ox - cx) * dx + (oy - cy) * dy
            if along <= 0:
                continue
            across = abs((ox - cx) * dy) + abs((oy - cy) * dx)
            if across > along * 2:
                continue                       # far more sideways than ahead
            score = along + 2 * across
            if best_score is None or score < best_score:
                best, best_score = i, score
        return best

    def next_index(self, index):
        if not self.rects:
            return 0
        if index not in range(len(self.rects)):
            index = self.primary
        return (index + 1) % len(self.rects)

    def map_rect(self, mode, index=None):
        """Rect the pointer's 0..1 space maps into.

        "all" is the whole desktop, so moving the hand sideways walks across
        monitors.  "current" is one display: the one under the cursor, or the
        primary one when we cannot tell."""
        if mode == "all":
            return self.union
        return self.rect(index)

    def equals(self, other):
        return isinstance(other, DisplayLayout) and rects_equal(self.rects, other.rects)

    def describe(self):
        return f"{self.count} display(s): {layout_summary(self.rects)}"


# =============================================================================
# macOS: Quartz.  The only part that needs pyobjc, and it takes the Quartz
# module as an argument so the maths above stays testable.
# =============================================================================

def _xy(value):
    return (float(value.x), float(value.y))


def _wh(value):
    return (float(value.width), float(value.height))


def _active_display_ids(quartz, max_displays):
    """(ids, count) of the active displays.

    pyobjc returns the C out-parameters as a tuple (err, ids, count); older
    bridges filled a ctypes array instead and returned the count.  Handle
    both, since getting this wrong silently means "one screen"."""
    res = quartz.CGGetActiveDisplayList(max_displays, None, None)
    if isinstance(res, tuple):
        err, ids, count = res
        if err != 0 or not ids:
            return [], 0
        return list(ids), int(count)
    import ctypes
    arr = (ctypes.c_uint32 * max_displays)()
    count = int(quartz.CGGetActiveDisplayList(max_displays, arr, None))
    return list(arr), count


def quartz_displays(quartz, max_displays=DISPLAY_QUERY_MAX):
    """Rects of every active display, primary first.  [] if Quartz says no."""
    if quartz is None:
        return []
    try:
        ids, count = _active_display_ids(quartz, max_displays)
        if count <= 0:
            return []
        rects, primary_rect = [], None
        for i in range(min(count, max_displays)):
            b = quartz.CGDisplayBounds(ids[i])
            rect = _xy(b.origin) + _wh(b.size)
            rects.append(rect)
            if ids[i] == quartz.CGMainDisplayID():
                primary_rect = rect
        # DisplayLayout treats index 0 as the primary one, so lead with it.
        rest = [r for r in rects if r != primary_rect]
        return ([primary_rect] if primary_rect else []) + rest
    except Exception:
        return []


# =============================================================================
# Windows: user32.  EnumDisplayMonitors gives every monitor in virtual
# desktop coordinates: the origin is the top left of the primary monitor and
# monitors to the left / above have negative x / y, exactly like macOS.
# =============================================================================

def windows_displays():
    """Rects of every active monitor, primary first.  [] on any failure."""
    if platform.system() != "Windows":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except Exception:
        return []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    MONITORINFOF_PRIMARY = 0x00000001
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                                  wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                  wintypes.LPARAM)

    rects, primary = [], []

    def _callback(hmon, hdc, lprc, lparam):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            rect = (float(r.left), float(r.top),
                    float(r.right - r.left), float(r.bottom - r.top))
            if info.dwFlags & MONITORINFOF_PRIMARY:
                primary.append(rect)
            else:
                rects.append(rect)
        return True

    try:
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                           ctypes.POINTER(MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.EnumDisplayMonitors.argtypes = [wintypes.HDC,
                                               ctypes.POINTER(wintypes.RECT),
                                               ENUMPROC, wintypes.LPARAM]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        proc = ENUMPROC(_callback)
        user32.EnumDisplayMonitors(None, None, proc, 0)
    except Exception:
        return []
    return primary + rects


def windows_virtual_screen():
    """The whole Windows desktop as one rect (x, y, w, h).  Falls back to
    the primary monitor when the metrics cannot be read."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        x = int(user32.GetSystemMetrics(76))     # SM_XVIRTUALSCREEN
        y = int(user32.GetSystemMetrics(77))     # SM_YVIRTUALSCREEN
        w = int(user32.GetSystemMetrics(78))     # SM_CXVIRTUALSCREEN
        h = int(user32.GetSystemMetrics(79))     # SM_CYVIRTUALSCREEN
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return (float(x), float(y), float(w), float(h))


# =============================================================================
# The platform-neutral entry points
# =============================================================================

def system_displays(quartz=None):
    """Rects of every active display, primary first.

    quartz: an already imported Quartz module (macOS).  On Windows it is
    ignored and user32 is asked instead."""
    system = platform.system()
    if system == "Windows":
        return windows_displays()
    if system == "Darwin":
        if quartz is None:
            try:
                import Quartz as quartz
            except Exception:
                return []
        return quartz_displays(quartz)
    return []


def virtual_desktop(quartz=None):
    """The whole desktop as one rect: every display plus the gaps between
    them.  None when the OS cannot be asked."""
    rects = system_displays(quartz)
    if rects:
        return union_rect(rects)
    return windows_virtual_screen()


def fallback_layout(size=None):
    """A one-screen layout used when the OS cannot be asked: the size
    pyautogui reports (the primary screen) or the virtual desktop."""
    if size is None:
        size = (1920, 1080)
    try:
        w, h = float(size[0]), float(size[1])
    except Exception:
        w, h = 1920.0, 1080.0
    if w <= 0 or h <= 0:
        desk = windows_virtual_screen()
        if desk:
            return DisplayLayout([desk])
        return DisplayLayout.fallback((w, h))
    return DisplayLayout.fallback((w, h))
