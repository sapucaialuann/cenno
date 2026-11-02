"""The app version, read from the VERSION file.

The VERSION file is the one place the version lives: the builds, the app
bundle and the installer all read it, so the app must read it too instead of
keeping its own copy.  The builds bundle VERSION next to the app, hence the
frozen case below.
"""

import os
import sys

UNKNOWN_VERSION = "unknown"


def read_version(base=None):
    """Return the version from <base>/VERSION, or "unknown" if there is none.

    base defaults to the bundle root of a frozen app (sys._MEIPASS) and to
    this file's folder when running from source.
    """
    if base is None:
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", "")
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, "VERSION"), encoding="utf-8") as fh:
            return fh.readline().strip() or UNKNOWN_VERSION
    except OSError:
        # A missing or unreadable VERSION must not stop the app from starting.
        return UNKNOWN_VERSION
