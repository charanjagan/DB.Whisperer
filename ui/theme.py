"""Which theme the window is actually wearing, and the QSS that paints it.

Qt would otherwise follow the OS light/dark setting on Windows, so the app could
end up dark without anything in this codebase asking for it. The charts are
drawn by matplotlib, which follows nothing -- so something has to tell it which
surface it is being pasted onto, or a light chart lands in a dark window as a
glowing white slab.

The look is iOS: Apple's light system palette for the surfaces, and this app's
terracotta kept as the tint. That split is deliberate and is what iOS apps
themselves do -- the greys, the radii and the spacing are the platform's, the
accent colour is the product's. It also means nl2sql.chart_renderer needs no
changes: its LIGHT theme already draws onto a white card, and its terracotta
series still matches the tint.

Light-only for now; dark mode is deferred, so chart_theme() is pinned to "light"
rather than consulting is_dark() the way it eventually should once a dark
palette exists to match it to.
"""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

# Below this lightness (0-255) the surface is dark enough that light-theme ink
# stops being readable on it. Kept for when dark mode returns; unused by
# chart_theme() while the app is light-only.
_DARK_THRESHOLD = 128

# --- palette -----------------------------------------------------------------
# Named after the iOS semantic colours they stand in for, resolved to their
# light-mode values. Spelled out rather than derived, matching how
# nl2sql.chart_renderer's LIGHT/DARK themes are written: a colour that reads
# well against one surface does not automatically read well against another, so
# each is a value, not a formula.

PAGE_BG = "#F2F2F7"             # systemGroupedBackground
CARD_BG = "#FFFFFF"             # secondarySystemGroupedBackground
CARD_BG_SECONDARY = "#FFFFFF"   # nested cards sit on white too, separated by rule
FILL = "#E9E9EB"                # tertiarySystemFill: segment tracks, switch off
FILL_STRONG = "#D1D1D6"         # pressed state of the above
BORDER = "#C6C6C8"              # opaque separator (the iOS hairline)
TEXT_PRIMARY = "#1C1C1E"        # label
TEXT_MUTED = "#6C6C70"          # secondaryLabel
TEXT_MUTED_LIGHT = "#AEAEB2"    # tertiaryLabel, and every disabled label
ERROR = "#FF3B30"               # systemRed

# The tint. Unchanged from the cream/terracotta theme this replaced, and still
# what nl2sql.chart_renderer.LIGHT draws its series in.
ACCENT = "#C96442"
ACCENT_HOVER = "#D98C6B"
ACCENT_PRESSED = "#A94E30"

# SF Pro if the machine happens to have it, then Windows' closest relative.
# Segoe UI Variable Text is the optical size meant for body copy; plain Segoe UI
# is the fallback for Windows 10.
FONT_FAMILY = '"SF Pro Text", "Segoe UI Variable Text", "Segoe UI", sans-serif'

# --- metrics -----------------------------------------------------------------
# iOS's type scale, one step down: the phone sizes assume arm's length and a
# finger, and at a desk with a mouse they read as a zoomed-in accessibility
# setting rather than as iOS.
FONT_BODY = 14
FONT_HEADLINE = 15
FONT_FOOTNOTE = 12
FONT_CAPTION = 11

RADIUS_CARD = 12
RADIUS_CONTROL = 9
RADIUS_FIELD = 10


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
    holds the terracotta chart colours that match the tint below.
    """
    return "light"


def surface_color() -> str:
    """The window's own surface colour, for framing a chart to match it."""
    return CARD_BG


def stylesheet() -> str:
    """The application-wide QSS for the iOS visual theme.

    Applied once via QApplication.setStyleSheet() at startup (see main.py).
    Widgets that need a specific visual role beyond their Qt class carry a
    dynamic property set at construction time:

      - QPushButton with property role="primary" -> a filled terracotta capsule
        (Run, Generate, Connect). Anything without this property gets the
        default QPushButton rule below instead: a grey iOS fill button.
      - QPushButton with property role="plain"   -> no fill at all, tint-
        coloured text, the way iOS writes a secondary action into a row.
      - QLabel with property role="sectionHeader" -> the small grey caption that
        sits above a grouped card.

    Properties must be set before the widget is first shown (Qt does not
    re-poll a stylesheet for a property that changes after the fact without an
    explicit unpolish/polish), so all are set in each widget's __init__.

    Two widgets are addressed by object name instead, because there is exactly
    one of each and no role to generalise: `resultsScroll` and `resultsContent`,
    the Full Assistant's scroll area and the widget inside it (see
    ui/assistant_panel.py). Both are painted transparent so the page background
    runs underneath them uninterrupted.

    Two controls are not styled here at all -- SegmentedControl and
    ToggleSwitch in ui/controls.py paint themselves, because what makes them
    look like iOS is a moving part and QSS cannot move anything.
    """
    return f"""
    /* ---- page ------------------------------------------------------------ */
    QMainWindow, QDialog {{
        background-color: {PAGE_BG};
    }}
    QWidget {{
        font-family: {FONT_FAMILY};
        font-size: {FONT_BODY}px;
        color: {TEXT_PRIMARY};
    }}
    QMessageBox {{
        background-color: {PAGE_BG};
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel:disabled {{
        color: {TEXT_MUTED_LIGHT};
    }}
    /* The grey caption above a grouped card. iOS sets these in a size and
       weight that says "this names the box below" without competing with the
       content inside it. */
    QLabel[role="sectionHeader"] {{
        color: {TEXT_MUTED};
        font-size: {FONT_FOOTNOTE}px;
        font-weight: 600;
        padding: 0 4px 2px 4px;
    }}

    /* ---- grouped cards --------------------------------------------------- */
    /* The inset grouped list is the single most recognisable thing about an iOS
       screen: white rounded cards floating on grey, with their heading outside
       and above rather than drawn into the border the way a Qt group box does
       it. margin-top leaves the room the title is then positioned up into. */
    QGroupBox {{
        background-color: {CARD_BG};
        border: none;
        border-radius: {RADIUS_CARD}px;
        margin-top: 22px;
        padding: 14px 14px 14px 14px;
        font-size: {FONT_BODY}px;
        font-weight: 400;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 4px;
        top: 2px;
        padding: 0 2px;
        color: {TEXT_MUTED};
        font-size: {FONT_FOOTNOTE}px;
        font-weight: 600;
    }}
    /* Checkable group boxes (Generated SQL, Why this query) are disclosure
       headers, not settings, so the title carries the weight and the indicator
       stays small -- a filled tick beside a label, rather than a tinted block
       with a grey caption next to it. */
    QGroupBox[checkable="true"]::title {{
        color: {TEXT_PRIMARY};
    }}
    QGroupBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1.5px solid {BORDER};
        border-radius: 5px;
        background-color: {CARD_BG};
    }}
    QGroupBox::indicator:hover {{
        border: 1.5px solid {ACCENT_HOVER};
    }}
    QGroupBox::indicator:checked {{
        background-color: {ACCENT};
        border: 1.5px solid {ACCENT};
    }}

    /* ---- the history list: an inset grouped list ------------------------- */
    QListWidget {{
        background-color: {CARD_BG};
        border: none;
        border-radius: {RADIUS_CARD}px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        border: none;
        border-bottom: 1px solid {PAGE_BG};
        padding: 11px 10px;
        border-radius: 8px;
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:selected {{
        background-color: {FILL};
        color: {TEXT_PRIMARY};
    }}
    QListWidget::item:hover {{
        background-color: {PAGE_BG};
    }}

    /* The summary sentence. Its own card rather than bare text: it is the
       app's actual answer, and on a grouped background anything that is not in
       a card reads as a caption for something else. */
    #summaryBox {{
        background-color: {CARD_BG};
        border: none;
        border-radius: {RADIUS_CARD}px;
        padding: 14px 16px;
        color: {TEXT_PRIMARY};
        font-size: {FONT_HEADLINE}px;
    }}

    /* ---- text fields ----------------------------------------------------- */
    /* Borderless on a white fill. iOS gives a text field its edge with contrast
       against the grouped background, not with a stroke, and only draws a ring
       when the field has focus. */
    QLineEdit, QPlainTextEdit {{
        background-color: {CARD_BG};
        border: 1px solid transparent;
        border-radius: {RADIUS_FIELD}px;
        padding: 9px 12px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT_HOVER};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background-color: {FILL};
    }}
    /* A code block that sits on a white card rather than on the page. White on
       white has no edge, so this one takes the grey fill instead -- the inset
       block iOS uses for monospace content inside a grouped row. */
    QPlainTextEdit[role="code"] {{
        background-color: {FILL};
        border: 1px solid transparent;
    }}
    QPlainTextEdit[role="code"]:focus {{
        border: 1px solid {ACCENT};
    }}

    /* ---- combo boxes ----------------------------------------------------- */
    QComboBox {{
        background-color: {FILL};
        border: 1px solid transparent;
        border-radius: {RADIUS_FIELD}px;
        padding: 8px 12px;
        color: {TEXT_PRIMARY};
        min-height: 20px;
    }}
    QComboBox:hover {{
        background-color: {FILL_STRONG};
    }}
    QComboBox:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background-color: {FILL};
    }}
    QComboBox:on {{
        border: 1px solid {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 26px;
    }}
    /* The popup is a menu, so it gets the menu's shape: a rounded sheet with
       its own padding and no item borders. */
    QComboBox QAbstractItemView {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CONTROL}px;
        selection-background-color: {FILL};
        selection-color: {TEXT_PRIMARY};
        outline: none;
        padding: 4px;
    }}

    /* ---- buttons --------------------------------------------------------- */
    /* Default is iOS's grey fill button: no border, a light grey plate, tint-
       coloured label. */
    QPushButton {{
        background-color: {FILL};
        border: none;
        border-radius: {RADIUS_CONTROL}px;
        padding: 9px 18px;
        color: {ACCENT};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {FILL_STRONG};
    }}
    QPushButton:pressed {{
        background-color: {FILL_STRONG};
        color: {ACCENT_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: {FILL};
        color: {TEXT_MUTED_LIGHT};
    }}

    /* Primary: the filled capsule. The radius is half the button's height, so
       it has to track the padding above -- 9px of padding around a 14px line
       makes roughly 38px, and 19 rounds it into a capsule. */
    QPushButton[role="primary"] {{
        background-color: {ACCENT};
        border: none;
        border-radius: 19px;
        padding: 10px 24px;
        color: #ffffff;
    }}
    QPushButton[role="primary"]:hover {{
        background-color: {ACCENT_HOVER};
    }}
    QPushButton[role="primary"]:pressed {{
        background-color: {ACCENT_PRESSED};
    }}
    QPushButton[role="primary"]:disabled {{
        background-color: {FILL};
        color: {TEXT_MUTED_LIGHT};
    }}

    /* Plain: no plate at all, just tinted text. What iOS puts at the trailing
       edge of a row -- "Load .sql file…", "Copy". */
    QPushButton[role="plain"] {{
        background: transparent;
        border: none;
        border-radius: {RADIUS_CONTROL}px;
        padding: 8px 10px;
        color: {ACCENT};
        font-weight: 600;
    }}
    QPushButton[role="plain"]:hover {{
        color: {ACCENT_HOVER};
        background: transparent;
    }}
    QPushButton[role="plain"]:pressed {{
        color: {ACCENT_PRESSED};
    }}
    QPushButton[role="plain"]:disabled {{
        color: {TEXT_MUTED_LIGHT};
        background: transparent;
    }}

    QDialogButtonBox QPushButton {{
        min-width: 84px;
    }}

    /* ---- radio buttons and check boxes ----------------------------------- */
    /* Only the ones that are still Qt's. The mode toggle and "Explain query"
       are SegmentedControl and ToggleSwitch, which paint themselves and read
       none of this. */
    QRadioButton, QCheckBox {{
        color: {TEXT_PRIMARY};
        spacing: 8px;
        background: transparent;
    }}
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border: 1.5px solid {BORDER};
        border-radius: 9px;
        background-color: {CARD_BG};
    }}
    QRadioButton::indicator:checked {{
        border: 5px solid {ACCENT};
        background-color: {CARD_BG};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1.5px solid {BORDER};
        border-radius: 6px;
        background-color: {CARD_BG};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT};
        border: 1.5px solid {ACCENT};
    }}
    QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
        border-color: {ACCENT_HOVER};
    }}
    QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
        background-color: {FILL};
        border: 1.5px solid {BORDER};
    }}

    /* ---- the busy bar ----------------------------------------------------- */
    QProgressBar {{
        background-color: {FILL};
        border: none;
        border-radius: 2px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT};
        border-radius: 2px;
    }}

    /* ---- menu bar / menus ------------------------------------------------- */
    QMenuBar {{
        background-color: {PAGE_BG};
        color: {TEXT_PRIMARY};
        font-size: {FONT_FOOTNOTE}px;
    }}
    QMenuBar::item {{
        padding: 5px 10px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{
        background-color: {FILL};
    }}
    QMenu {{
        background-color: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_CONTROL}px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 7px 22px;
        border-radius: 7px;
        color: {TEXT_PRIMARY};
    }}
    QMenu::item:selected {{
        background-color: {FILL};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 8px;
    }}

    /* ---- the results scroll area ---------------------------------------- */
    /* Transparent rather than PAGE_BG-painted, so the strip of viewport left
       over beside a narrow chart is the same grey as the window around it and
       the scroll area reads as a window onto the page, not a panel on it. The
       viewport is a plain QWidget child, and the content widget a child of
       that, so both need saying -- a QWidget rule alone does not reach them. */
    #resultsScroll, #resultsScroll > QWidget, #resultsContent {{
        background: transparent;
        border: none;
    }}

    /* ---- scrollbars: iOS overlay scrollers ------------------------------- */
    /* Thin, trackless, and dark-translucent rather than tinted. iOS scrollers
       are deliberately not a brand surface -- they are a position indicator
       over the content, which is why they carry no colour of their own.
       Global rather than scoped to the results area: the SQL box, the history
       list and the generator's schema box all scroll too, and one of them
       wearing the OS default beside a styled one is worse than none matching. */
    QScrollBar:vertical {{
        background: transparent;
        width: 11px;
        margin: 0px;
        border: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 11px;
        margin: 0px;
        border: none;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: rgba(60, 60, 67, 0.35);
        border: none;
        border-radius: 3px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        min-height: 36px;
    }}
    QScrollBar::handle:horizontal {{
        min-width: 36px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover,
    QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {{
        background: rgba(60, 60, 67, 0.6);
    }}
    /* Fusion draws arrow buttons and paints the trough on the page controls.
       Both have to be zeroed explicitly or the track shows through as grey. */
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        height: 0px;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    /* The square where the two bars meet, left unpainted by the rules above. */
    QAbstractScrollArea::corner {{
        background: transparent;
        border: none;
    }}

    QSplitter::handle {{
        background-color: transparent;
    }}
    """
