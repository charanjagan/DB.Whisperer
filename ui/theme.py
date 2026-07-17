"""Which theme the window is actually wearing.

Qt follows the OS light/dark setting on Windows, so the app can be dark without
anything in this codebase asking for it. The charts are drawn by matplotlib,
which follows nothing — so something has to tell it which surface it is being
pasted onto, or a light chart lands in a dark window as a glowing white slab.

The window palette is the source of truth here rather than an OS query: it is
what the widgets around the chart are painted from, so matching it is what makes
the chart look like part of the window.
"""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

# Below this lightness (0-255) the surface is dark enough that light-theme ink
# stops being readable on it.
_DARK_THRESHOLD = 128


def is_dark() -> bool:
    """True if the app's window surface is dark."""
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Window).lightness() < _DARK_THRESHOLD


def chart_theme() -> str:
    """The nl2sql.chart_renderer theme name matching the current window."""
    return "dark" if is_dark() else "light"


def surface_color() -> str:
    """The window's own surface colour, for framing a chart to match it."""
    app = QApplication.instance()
    if app is None:
        return "#fcfcfb"
    return app.palette().color(QPalette.Window).name()
