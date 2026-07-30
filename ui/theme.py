"""Which theme the window is actually wearing, and the QSS that paints it.

Qt would otherwise follow the OS light/dark setting on Windows, so the app could
end up dark without anything in this codebase asking for it. The charts are
drawn by matplotlib, which follows nothing -- so something has to tell it which
surface it is being pasted onto, or a light chart lands in a dark window as a
glowing white slab.

The cream/terracotta visual theme below is light-only for now; dark mode is
deferred, so chart_theme() is pinned to "light" rather than consulting is_dark()
the way it eventually should once a dark palette exists to match it to.
"""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

# Below this lightness (0-255) the surface is dark enough that light-theme ink
# stops being readable on it. Kept for when dark mode returns; unused by
# chart_theme() while the app is light-only.
_DARK_THRESHOLD = 128

# --- palette -----------------------------------------------------------------
# Spelled out here rather than derived, matching how nl2sql.chart_renderer's
# LIGHT/DARK themes are written: a colour that reads well against one surface
# does not automatically read well against another, so each is a value, not a
# formula.

PAGE_BG = "#FAF6EF"
CARD_BG = "#FFFFFF"
CARD_BG_SECONDARY = "#F3EDE0"
BORDER = "#E8E1D3"
TEXT_PRIMARY = "#3A3530"
TEXT_MUTED = "#8A8375"
TEXT_MUTED_LIGHT = "#A39C8C"
ACCENT = "#C96442"
ACCENT_HOVER = "#D98C6B"

FONT_FAMILY = '"Segoe UI", "Segoe UI Variable", "Segoe UI Semibold", sans-serif'


def is_dark() -> bool:
    """True if the app's window surface is dark.

    Not currently consulted by chart_theme() -- see the module docstring --
    kept so a future dark palette has a live check to switch on.
    """
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().color(QPalette.Window).lightness() < _DARK_THRESHOLD


def chart_theme() -> str:
    """The nl2sql.chart_renderer theme name matching the current window.

    Pinned to "light" while the app is light-only; nl2sql.chart_renderer.LIGHT
    holds the cream/terracotta chart colours that match the QSS below.
    """
    return "light"


def surface_color() -> str:
    """The window's own surface colour, for framing a chart to match it."""
    return CARD_BG


def stylesheet() -> str:
    """The application-wide QSS for the cream/terracotta visual theme.

    Applied once via QApplication.setStyleSheet() at startup (see main.py).
    Widgets that need a specific visual role beyond their Qt class carry a
    dynamic property set at construction time:

      - QPushButton with property role="primary"   -> terracotta, filled (Run,
        Generate, Connect). Anything without this property gets the default
        QPushButton rule below instead: white, bordered, muted text.
      - QRadioButton with property role="pill"      -> the mode toggle
        (Full Assistant / Query Generator), rendered as rounded pill buttons
        rather than a radio dot + label.

    Properties must be set before the widget is first shown (Qt does not
    re-poll a stylesheet for a property that changes after the fact without an
    explicit unpolish/polish), so both are set in each widget's __init__.
    """
    return f"""
    /* ---- page background --------------------------------------------- */
    QMainWindow, QDialog {{
        background-color: {PAGE_BG};
    }}
    QWidget {{
        font-family: {FONT_FAMILY};
        color: {TEXT_PRIMARY};
    }}
    QMessageBox {{
        background-color: {PAGE_BG};
    }}
    QLabel {{
        background: transparent;
    }}

    /* ---- cards: group boxes, the history list, chart frame ------------ */
    QGroupBox {{
        background-color: {CARD_BG_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 14px;
        margin-top: 14px;
        padding: 14px 10px 10px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 4px;
        color: {TEXT_PRIMARY};
    }}
    QGroupBox::indicator {{
        width: 16px;
        height: 16px;
    }}

    QListWidget {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 14px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        border-bottom: 1px solid {BORDER};
        padding: 10px 8px;
        border-radius: 0px;
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:selected {{
        background-color: {CARD_BG_SECONDARY};
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:hover {{
        background-color: {PAGE_BG};
    }}

    #summaryBox {{
        background-color: {CARD_BG_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 12px 14px;
        color: {TEXT_PRIMARY};
    }}

    /* ---- text inputs ---------------------------------------------------- */
    QLineEdit, QPlainTextEdit {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 10px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT_HOVER};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background-color: {CARD_BG_SECONDARY};
    }}

    /* ---- combo boxes: database picker, dialect picker ------------------- */
    QComboBox {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 6px 10px;
        color: {TEXT_PRIMARY};
        min-height: 20px;
    }}
    QComboBox:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background-color: {CARD_BG_SECONDARY};
    }}
    QComboBox:on {{
        border: 1px solid {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
        selection-background-color: {CARD_BG_SECONDARY};
        selection-color: {TEXT_PRIMARY};
        outline: none;
        padding: 4px;
    }}

    /* ---- buttons: default = secondary (white, bordered, muted) --------- */
    QPushButton {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 16px;
        color: {TEXT_MUTED};
        font-weight: 600;
    }}
    QPushButton:hover {{
        border: 1px solid {ACCENT_HOVER};
        color: {TEXT_PRIMARY};
    }}
    QPushButton:pressed {{
        background-color: {CARD_BG_SECONDARY};
    }}
    QPushButton:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background-color: {CARD_BG_SECONDARY};
        border: 1px solid {BORDER};
    }}

    /* primary action buttons: Run, Generate, Connect */
    QPushButton[role="primary"] {{
        background-color: {ACCENT};
        border: 1px solid {ACCENT};
        color: #ffffff;
    }}
    QPushButton[role="primary"]:hover {{
        background-color: {ACCENT_HOVER};
        border: 1px solid {ACCENT_HOVER};
        color: #ffffff;
    }}
    QPushButton[role="primary"]:pressed {{
        background-color: {ACCENT};
    }}
    QPushButton[role="primary"]:disabled {{
        background-color: {CARD_BG_SECONDARY};
        border: 1px solid {BORDER};
        color: {TEXT_MUTED_LIGHT};
    }}

    /* ---- mode toggle: rendered as pill buttons, not radio dots --------- */
    QRadioButton[role="pill"] {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 16px;
        padding: 7px 18px;
        color: {TEXT_MUTED};
        font-weight: 600;
    }}
    QRadioButton[role="pill"]::indicator {{
        width: 0px;
        height: 0px;
    }}
    QRadioButton[role="pill"]:hover {{
        border: 1px solid {ACCENT_HOVER};
    }}
    QRadioButton[role="pill"]:checked {{
        background-color: {ACCENT};
        border: 1px solid {ACCENT};
        color: #ffffff;
    }}

    /* plain (non-pill) radio buttons: Generator panel's schema source pick */
    QRadioButton {{
        color: {TEXT_PRIMARY};
        spacing: 6px;
    }}

    QCheckBox {{
        color: {TEXT_PRIMARY};
        spacing: 6px;
    }}

    /* ---- progress bar: the busy spinner --------------------------------- */
    QProgressBar {{
        background-color: {CARD_BG_SECONDARY};
        border: none;
        border-radius: 2px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 2px;
    }}

    /* ---- menu bar / menus ------------------------------------------------ */
    QMenuBar {{
        background-color: {PAGE_BG};
        color: {TEXT_PRIMARY};
    }}
    QMenuBar::item:selected {{
        background-color: {CARD_BG_SECONDARY};
        border-radius: 6px;
    }}
    QMenu {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 20px;
        border-radius: 6px;
        color: {TEXT_PRIMARY};
    }}
    QMenu::item:selected {{
        background-color: {CARD_BG_SECONDARY};
    }}

    QSplitter::handle {{
        background-color: transparent;
    }}
    """
