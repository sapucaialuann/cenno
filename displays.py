"""
Cenno: display geometry.

A display is a rect (x, y, w, h) in the global desktop space macOS uses for
the mouse: points, origin at the top left of the primary display, y growing
downwards.  Displays left of or above the primary one therefore have negative
coordinates, which is normal and not an error.

Everything here is plain arithmetic on those rects, so it can be unit tested
without a camera, a window server or pyobjc.  Only quartz_displays() talks to
Quartz, and it takes the Quartz module as an argument.
"""

# How many active displays we ask Quartz for.  Plenty: macOS supports 6.
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


def rects_equal(a, b):
    return list(a) == list(b)


def layout_summary(rects):
    return " ".join(f"[{int(r[0])},{int(r[1])} {int(r[2])}x{int(r[3])}]" for r in rects)


# =============================================================================
# Layout: the list of displays, the primary one, and the pointer's target rect
# =============================================================================

class DisplayLayout:
    """The screens as macOS reports them.

    rects[0] is always the primary display (menu bar) and the rest are sorted
    left to right, top to bottom, so "next display" walks the desk instead of
    following an order the window server happens to use.  Displays that report
    the same rect (mirrored pairs) are collapsed to one.
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
        """One screen the size pyautogui reports: no Quartz, or nothing found."""
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

    def nearest(self, point):
        """Index of the display whose centre is closest: gaps and edges too."""
        if not self.rects:
            return 0
        return min(range(len(self.rects)),
                   key=lambda i: ((center(self.rects[i])[0] - point[0]) ** 2
                                  + (center(self.rects[i])[1] - point[1]) ** 2))

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
# Quartz: the only part that needs pyobjc, and it is passed in
# =============================================================================

def _xy(value):
    return (float(value.x), float(value.y))


def _wh(value):
    return (float(value.width), float(value.height))


def quartz_displays(quartz, max_displays=DISPLAY_QUERY_MAX):
    """Rects of every active display, primary first.  [] if Quartz says no."""
    if quartz is None:
        return []
    try:
        import ctypes
        ids = (ctypes.c_uint32 * max_displays)()
        count = int(quartz.CGGetActiveDisplayList(max_displays, ids, None))
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