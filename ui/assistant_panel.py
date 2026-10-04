"""Full Assistant results: the chart, the summary, and the SQL behind them.

Reading order is deliberate — chart, then sentence, then SQL. The chart answers
the question, the summary says what it shows, and the SQL is the receipt: folded
away by default, one click from view, because the user is trusting a 7B model's
statement about their data and is entitled to see it whenever they want to.

Everything below the status line lives in a QScrollArea. A result is not a fixed
amount of content: a six-column table figure is 11.6 inches wide, a fifteen-row
one is five inches tall, and a summary of a wide result is several wrapped lines.
Laid out directly in the window those all competed for the same few hundred
pixels and lost. Now each part asks for the size it actually wants and the
scroll area is what runs out of room instead.
"""

from math import ceil
from typing import Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nl2sql import ChartError, render_chart
from nl2sql.chart_renderer import DEFAULT_FIGSIZE, THEMES

from .theme import (
    ERROR,
    FONT_CAPTION,
    FONT_FOOTNOTE,
    RADIUS_CARD,
    TEXT_MUTED,
    chart_theme,
)
from .workers import AssistantResult

_MUTED = TEXT_MUTED
_ERROR = ERROR

# Enough to hold the "No results yet" placeholder and a small chart without the
# frame collapsing to a sliver before the first run. A real canvas sets its own
# floor on top of this, so it only ever governs the empty state.
_CHART_MIN_HEIGHT = 260

# The SQL box grows to fit its query rather than scrolling inside the scroll
# area. The cap is a backstop for a pathological generation; past it the widget
# keeps its own scrollbar, which is the lesser evil against a 4,000px box.
_SQL_MIN_HEIGHT = 110
_SQL_MAX_HEIGHT = 480


class AssistantPanel(QWidget):
    """Shows one Full Assistant run: loading, then result, or an error."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas: Optional[FigureCanvasQTAgg] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # --- status / loading -------------------------------------------------
        # Pinned above the scroll area, not inside it: it carries the per-step
        # progress of a run that takes a minute, and it would be useless if it
        # scrolled off while the user was reading the previous result.
        self.status = QLabel("Ask a question to get started.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {_MUTED};")
        outer.addWidget(self.status)

        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)  # indeterminate: the model gives no progress
        self.spinner.setTextVisible(False)
        self.spinner.setFixedHeight(3)
        self.spinner.hide()
        outer.addWidget(self.spinner)

        # --- the scrollable result --------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setObjectName("resultsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # The window already frames its content in cards; a frame around the
        # viewport would draw a second box around the first.
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll, 1)

        content = QWidget()
        content.setObjectName("resultsContent")
        # Left on the default Preferred policy deliberately, and it matters
        # which one: QScrollArea sizes this widget through qSmartMinSize, which
        # floors it at minimumSizeHint when the policy can shrink and at the
        # larger of sizeHint and minimumSizeHint when it cannot. Preferred can
        # shrink, so the floor is the children's real minimums -- a wide table
        # still forces a scrollbar, while an ordinary chart, whose sizeHint is
        # its preferred 800px but whose minimum is nothing, narrows to the
        # window instead of pinning the content 800px wide forever.
        self.scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)

        # --- chart ------------------------------------------------------------
        self.chart_frame = QFrame()
        # Framed in the chart's own surface, not the window's, so the figure and
        # the few pixels of padding around it read as one object. No stroke: on
        # a grouped background a white card is already an edge, and iOS does not
        # outline one.
        palette = THEMES[chart_theme()]
        self.chart_frame.setStyleSheet(
            f"QFrame {{ background: {palette.surface}; border: none; "
            f"border-radius: {RADIUS_CARD}px; }}"
        )
        # Expanding both ways, which can shrink: the real height floor is the
        # canvas's own minimum (see show_result), and _CHART_MIN_HEIGHT below
        # only has to hold the empty state up. A non-shrinking policy here would
        # floor the frame at its preferred size instead of its minimum, which is
        # the trap the content widget above documents.
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chart_frame.setMinimumHeight(_CHART_MIN_HEIGHT)
        self.chart_layout = QVBoxLayout(self.chart_frame)
        self.chart_layout.setContentsMargins(6, 6, 6, 6)
        self.chart_placeholder = QLabel("No results yet")
        self.chart_placeholder.setAlignment(Qt.AlignCenter)
        self.chart_placeholder.setStyleSheet(f"color: {_MUTED}; border: none;")
        self.chart_layout.addWidget(self.chart_placeholder)
        layout.addWidget(self.chart_frame, 1)

        # --- summary ----------------------------------------------------------
        self.summary = QLabel("")
        self.summary.setObjectName("summaryBox")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.hide()  # see the sql_box comment below
        # Size and surface both come from the #summaryBox rule in ui/theme.py --
        # a widget stylesheet here would win over it and silently undo the type
        # scale.
        layout.addWidget(self.summary)

        # --- why this query, folded away -------------------------------------
        # Sits between the summary and the SQL on purpose: it is the bridge
        # between "here is what the data says" and "here is the query that got
        # it". Hidden entirely unless a run was asked to explain itself, so a
        # user with the toggle off never sees an empty box.
        self.explain_box = QGroupBox("Why this query")
        self.explain_box.setCheckable(True)
        self.explain_box.setChecked(True)
        self.explain_box.toggled.connect(self._toggle_explain)
        explain_layout = QVBoxLayout(self.explain_box)

        self.explain_view = QLabel("")
        self.explain_view.setWordWrap(True)
        self.explain_view.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.explain_view.setStyleSheet(f"font-size: {FONT_FOOTNOTE}px;")
        explain_layout.addWidget(self.explain_view)

        self.explain_box.hide()
        layout.addWidget(self.explain_box)

        # --- the SQL, folded away --------------------------------------------
        self.sql_box = QGroupBox("Generated SQL")
        self.sql_box.setCheckable(True)
        self.sql_box.setChecked(False)
        self.sql_box.toggled.connect(self._toggle_sql)
        sql_layout = QVBoxLayout(self.sql_box)

        self.sql_view = QPlainTextEdit()
        self.sql_view.setReadOnly(True)
        # Sized to its query by _fit_sql_height() rather than fixed at 110px:
        # a scroll area whose contents each scroll on their own is worse than no
        # scroll area at all, so the box grows and the outer area does the
        # scrolling. Wraps at the widget width, so it never scrolls sideways.
        self.sql_view.setMinimumHeight(_SQL_MIN_HEIGHT)
        self.sql_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # role="code" makes it a grey inset block rather than the default white
        # field: this one sits on a white card, so white on white would leave it
        # with no edge at all. See ui/theme.py.
        self.sql_view.setProperty("role", "code")
        self.sql_view.setStyleSheet(f"font-family: Consolas, monospace; font-size: {FONT_FOOTNOTE}px;")
        self.sql_view.document().documentLayout().documentSizeChanged.connect(
            lambda _size: self._schedule_sql_fit()
        )
        sql_layout.addWidget(self.sql_view)

        self.meta = QLabel("")
        # Must wrap: it lists every table in context, and unwrapped a long list
        # sets the minimum width of everything in the scroll area -- the summary
        # then lays out on one line and the chart runs off the right edge.
        self.meta.setWordWrap(True)
        self.meta.setStyleSheet(f"color: {_MUTED}; font-size: {FONT_CAPTION}px;")
        sql_layout.addWidget(self.meta)

        self.sql_view.hide()
        self.meta.hide()
        # Hidden until there is a query to put in it, the way explain_box is.
        # An empty card was tolerable when cards were faint cream outlines; on a
        # grouped background a card is a solid white slab, and an empty one
        # reads as content that failed to load rather than as a container
        # waiting for content.
        self.sql_box.hide()
        layout.addWidget(self.sql_box)

    def _schedule_sql_fit(self) -> None:
        """Re-fit the SQL box once Qt has finished the layout pass in progress.

        Deferred rather than immediate because both of the moments worth
        re-fitting at -- the text changing, and the box being unfolded -- ask
        the question before Qt has answered it. A hidden widget is left out of
        its layout entirely, so it has no width to wrap against and no viewport
        to measure the frame from; measuring then yields the minimum height and
        no later signal to correct it.
        """
        QTimer.singleShot(0, self._fit_sql_height)

    def _fit_sql_height(self) -> None:
        """Match the SQL box's height to the query in it, within the bounds."""
        doc = self.sql_view.document()
        layout = doc.documentLayout()

        # QPlainTextDocumentLayout reports documentSize().height() in wrapped
        # lines, not pixels, so it needs a line height to multiply by. Taken
        # from a laid-out block rather than from fontMetrics().lineSpacing():
        # the two disagree by a pixel per line here (15 against 14), which over
        # a dozen lines is enough to leave the box one line short and scrolling.
        block = doc.firstBlock()
        text_layout = block.layout()
        line_count = text_layout.lineCount() if text_layout is not None else 0
        if line_count:
            line_height = layout.blockBoundingRect(block).height() / line_count
        else:
            line_height = self.sql_view.fontMetrics().lineSpacing()

        # Frame plus the stylesheet's padding, measured rather than assumed --
        # QSS padding does not show up in contentsMargins() reliably, but the
        # gap between the widget and its viewport is exactly what it costs.
        chrome = self.sql_view.height() - self.sql_view.viewport().height()

        # The +2 is slack. QPlainTextEdit's own scrollbar arithmetic rounds
        # against us at the exact fitting height -- give it precisely the pixels
        # the text needs and it still reports one line of overflow and shows a
        # scrollbar. Two pixels of headroom is invisible and settles it.
        needed = ceil(
            doc.size().height() * line_height + doc.documentMargin() * 2 + chrome
        ) + 2
        self.sql_view.setFixedHeight(max(_SQL_MIN_HEIGHT, min(needed, _SQL_MAX_HEIGHT)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_sql_fit()

    def _toggle_sql(self, shown: bool) -> None:
        self.sql_view.setVisible(shown)
        self.meta.setVisible(shown)
        if shown:
            self._schedule_sql_fit()

    def _toggle_explain(self, shown: bool) -> None:
        self.explain_view.setVisible(shown)

    def set_explanation(self, text: Optional[str]) -> None:
        """Show the reasoning panel, or hide it when there is nothing to show.

        Expanded rather than collapsed when it does appear: a user who ticked
        "Explain query" and waited the extra generation for it should not have
        to click again to read the thing they asked for.
        """
        if not text:
            self.explain_box.hide()
            self.explain_view.clear()
            return
        self.explain_view.setText(text)
        self.explain_box.setChecked(True)
        self.explain_view.setVisible(True)
        self.explain_box.show()

    # ------------------------------------------------------------------ state

    def set_busy(self, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {_MUTED};")
        self.spinner.show()

    def set_progress(self, message: str) -> None:
        self.status.setText(message)

    def set_error(self, message: str) -> None:
        self.spinner.hide()
        # Retry-loop failures arrive as several lines listing every attempt. The
        # first line is the headline; the rest belongs where SQL belongs.
        headline, _, detail = message.partition("\n")
        self.status.setText(headline)
        self.status.setStyleSheet(f"color: {_ERROR}; font-weight: 600;")
        if detail.strip():
            self.sql_view.setPlainText(detail.strip())
            self.sql_box.setTitle("What was tried")
            self.sql_box.show()
            self.sql_box.setChecked(True)

    def clear(self) -> None:
        # A new run starts at the top of the new result, not wherever the last
        # one was left scrolled to.
        self.scroll.verticalScrollBar().setValue(0)
        self.scroll.horizontalScrollBar().setValue(0)
        self.summary.setText("")
        self.summary.hide()
        self.sql_view.setPlainText("")
        self.meta.setText("")
        self.sql_box.setTitle("Generated SQL")
        self.sql_box.hide()
        self.set_explanation(None)
        self._clear_canvas()

    def _clear_canvas(self) -> None:
        if self._canvas is not None:
            self.chart_layout.removeWidget(self._canvas)
            self._canvas.setParent(None)
            self._canvas.deleteLater()
            self._canvas = None

    def show_result(self, result: AssistantResult) -> None:
        self.spinner.hide()
        # run_query stops at its row cap; say so rather than let the count read
        # as the size of the whole answer.
        rows = f"{len(result.df):,} rows"
        if result.df.attrs.get("truncated"):
            rows = f"First {len(result.df):,} rows (result capped)"
        self.status.setText(
            f"{rows} × {len(result.df.columns)} columns · "
            f"{result.chart_type.replace('_', ' ')} · {result.seconds:.1f}s"
        )
        self.status.setStyleSheet(f"color: {_MUTED};")

        self.summary.setText(result.summary)
        self.summary.setVisible(bool(result.summary))
        self.set_explanation(result.explanation)
        self.sql_view.setPlainText(result.sql)
        self.sql_box.setTitle("Generated SQL")
        self.sql_box.show()
        self.meta.setText(
            f"Schema context: {len(result.tables)} of {result.total_tables} tables"
            + (f" ({', '.join(result.tables)})" if result.tables else "")
        )

        self._clear_canvas()
        self.chart_placeholder.hide()
        try:
            # Rendered here, on the GUI thread: FigureCanvasQTAgg must be built
            # where the widgets live, and drawing is milliseconds either way.
            # The theme is read now rather than at construction so a chart drawn
            # after the user flips their OS theme matches the repainted window.
            figure = render_chart(result.df, result.chart_type, theme=chart_theme())
        except ChartError as exc:
            self.chart_placeholder.setText(f"Could not draw this result: {exc}")
            self.chart_placeholder.show()
            return

        canvas = FigureCanvasQTAgg(figure)
        canvas.setStyleSheet("border: none;")
        # Height is floored at the figure's own, always: a chart squeezed into a
        # couple of hundred pixels is unreadable whatever it is drawing, and
        # scrolling down to it beats that.
        #
        # Width is floored only for a figure the renderer grew past the default
        # to fit its content, which today means the table -- it sizes itself to
        # 1.6in per column precisely because its cells do not reflow, so taking
        # width away from it overlaps them. Every other chart re-lays out at
        # whatever width it is given, and flooring those too would make the
        # window scroll sideways at any size below about 1060px rather than just
        # drawing a narrower chart, which is worse than what it replaced.
        dpi = figure.dpi
        natural_width = round(figure.get_figwidth() * dpi)
        grew_for_content = natural_width > round(DEFAULT_FIGSIZE[0] * dpi)
        canvas.setMinimumSize(
            QSize(
                natural_width if grew_for_content else 0,
                round(figure.get_figheight() * dpi),
            )
        )
        self.chart_layout.addWidget(canvas)
        self._canvas = canvas
        canvas.draw_idle()
