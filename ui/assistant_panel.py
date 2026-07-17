"""Full Assistant results: the chart, the summary, and the SQL behind them.

Reading order is deliberate — chart, then sentence, then SQL. The chart answers
the question, the summary says what it shows, and the SQL is the receipt: folded
away by default, one click from view, because the user is trusting a 7B model's
statement about their data and is entitled to see it whenever they want to.
"""

from typing import Optional

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nl2sql import ChartError, render_chart
from nl2sql.chart_renderer import THEMES

from .theme import chart_theme
from .workers import AssistantResult

# Muted reads on both surfaces, so it is safe to hard-code. Ink is not: the
# summary is the one line of real prose in the window, and setting it to
# near-black made it invisible against a dark Qt palette. It now inherits the
# palette's text colour, which is correct in both themes by construction.
_MUTED = "#898781"
_ERROR = "#d03b3b"


class AssistantPanel(QWidget):
    """Shows one Full Assistant run: loading, then result, or an error."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._canvas: Optional[FigureCanvasQTAgg] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- status / loading -------------------------------------------------
        self.status = QLabel("Ask a question to get started.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {_MUTED};")
        layout.addWidget(self.status)

        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)  # indeterminate: the model gives no progress
        self.spinner.setTextVisible(False)
        self.spinner.setFixedHeight(3)
        self.spinner.hide()
        layout.addWidget(self.spinner)

        # --- chart ------------------------------------------------------------
        self.chart_frame = QFrame()
        # Framed in the chart's own surface, not the window's, so the figure and
        # the few pixels of padding around it read as one object.
        palette = THEMES[chart_theme()]
        self.chart_frame.setStyleSheet(
            f"QFrame {{ background: {palette.surface}; border: 1px solid {palette.grid}; "
            f"border-radius: 6px; }}"
        )
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chart_layout = QVBoxLayout(self.chart_frame)
        self.chart_layout.setContentsMargins(6, 6, 6, 6)
        self.chart_placeholder = QLabel("No results yet")
        self.chart_placeholder.setAlignment(Qt.AlignCenter)
        self.chart_placeholder.setStyleSheet(f"color: {_MUTED}; border: none;")
        self.chart_layout.addWidget(self.chart_placeholder)
        layout.addWidget(self.chart_frame, 1)

        # --- summary ----------------------------------------------------------
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setStyleSheet("font-size: 14px; padding: 4px 2px;")
        layout.addWidget(self.summary)

        # --- the SQL, folded away --------------------------------------------
        self.sql_box = QGroupBox("Generated SQL")
        self.sql_box.setCheckable(True)
        self.sql_box.setChecked(False)
        self.sql_box.toggled.connect(self._toggle_sql)
        sql_layout = QVBoxLayout(self.sql_box)

        self.sql_view = QPlainTextEdit()
        self.sql_view.setReadOnly(True)
        self.sql_view.setFixedHeight(110)
        self.sql_view.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        sql_layout.addWidget(self.sql_view)

        self.meta = QLabel("")
        self.meta.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        sql_layout.addWidget(self.meta)

        self.sql_view.hide()
        self.meta.hide()
        layout.addWidget(self.sql_box)

    def _toggle_sql(self, shown: bool) -> None:
        self.sql_view.setVisible(shown)
        self.meta.setVisible(shown)

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
            self.sql_box.setChecked(True)
            self.sql_box.setTitle("What was tried")

    def clear(self) -> None:
        self.summary.setText("")
        self.sql_view.setPlainText("")
        self.meta.setText("")
        self.sql_box.setTitle("Generated SQL")
        self._clear_canvas()

    def _clear_canvas(self) -> None:
        if self._canvas is not None:
            self.chart_layout.removeWidget(self._canvas)
            self._canvas.setParent(None)
            self._canvas.deleteLater()
            self._canvas = None

    def show_result(self, result: AssistantResult) -> None:
        self.spinner.hide()
        self.status.setText(
            f"{len(result.df):,} rows × {len(result.df.columns)} columns · "
            f"{result.chart_type.replace('_', ' ')} · {result.seconds:.1f}s"
        )
        self.status.setStyleSheet(f"color: {_MUTED};")

        self.summary.setText(result.summary)
        self.sql_view.setPlainText(result.sql)
        self.sql_box.setTitle("Generated SQL")
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
        self.chart_layout.addWidget(canvas)
        self._canvas = canvas
        canvas.draw_idle()
