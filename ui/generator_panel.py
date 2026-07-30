"""Query Generator: a question and a schema in, SQL text out. Nothing runs.

This mode has no execution path at all — not a guarded one, not a validated one.
There is no connection to run against for two of the three dialects, and for the
third the deliberate absence is the feature: a user pasting a production schema
they cannot even reach from here gets a query to take away, and this app cannot
touch that database whether the SQL is right or not.

The schema comes from one of two places: the connected database (Phase 1's
introspection) or the user's clipboard/`.sql` file. The paste path needs no
connection whatsoever, which is the whole reason it exists.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_MUTED = "#8A8375"
_ERROR = "#d03b3b"

# A schema far past this is mostly context the model cannot use anyway, and it
# is usually a sign someone pasted a whole database dump rather than its DDL.
LARGE_SCHEMA_CHARS = 60_000


class GeneratorPanel(QWidget):
    """Schema source picker, generated-SQL box, and a Copy button."""

    schema_requested = Signal()  # "fetch the connected database's schema for me"

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- where the schema comes from --------------------------------------
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Schema:"))
        self.use_connected = QRadioButton("Use connected database")
        self.use_manual = QRadioButton("Paste or upload schema")
        self.use_connected.setChecked(True)
        self.use_connected.toggled.connect(self._source_changed)
        source_row.addWidget(self.use_connected)
        source_row.addWidget(self.use_manual)
        source_row.addStretch(1)

        self.dialect_label = QLabel("")
        self.dialect_label.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        source_row.addWidget(self.dialect_label)
        layout.addLayout(source_row)

        # --- the schema itself ------------------------------------------------
        self.source_stack = QStackedWidget()

        connected = QWidget()
        connected_layout = QVBoxLayout(connected)
        connected_layout.setContentsMargins(0, 0, 0, 0)
        self.connected_status = QLabel("")
        self.connected_status.setWordWrap(True)
        self.connected_status.setStyleSheet(f"color: {_MUTED};")
        connected_layout.addWidget(self.connected_status)
        self.schema_preview = QPlainTextEdit()
        self.schema_preview.setReadOnly(True)
        self.schema_preview.setPlaceholderText(
            "Connect to a database in Settings, then its schema appears here."
        )
        self.schema_preview.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        connected_layout.addWidget(self.schema_preview)
        self.source_stack.addWidget(connected)

        manual = QWidget()
        manual_layout = QVBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Paste CREATE TABLE statements, or describe the tables:"))
        manual_row.addStretch(1)
        self.load_file_button = QPushButton("Load .sql file…")
        self.load_file_button.clicked.connect(self._load_file)
        manual_row.addWidget(self.load_file_button)
        manual_layout.addLayout(manual_row)
        self.schema_input = QPlainTextEdit()
        self.schema_input.setPlaceholderText(
            "CREATE TABLE employees (\n"
            "    id INT PRIMARY KEY,\n"
            "    name VARCHAR(100),\n"
            "    department_id INT REFERENCES departments(id),\n"
            "    monthly_income DECIMAL(10, 2)\n"
            ");"
        )
        self.schema_input.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        manual_layout.addWidget(self.schema_input)
        self.source_stack.addWidget(manual)

        layout.addWidget(self.source_stack, 1)

        # --- status -----------------------------------------------------------
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {_MUTED};")
        layout.addWidget(self.status)

        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)
        self.spinner.setTextVisible(False)
        self.spinner.setFixedHeight(3)
        self.spinner.hide()
        layout.addWidget(self.spinner)

        # --- the output -------------------------------------------------------
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Generated SQL"))
        output_row.addStretch(1)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)
        output_row.addWidget(self.copy_button)
        layout.addLayout(output_row)

        self.sql_output = QPlainTextEdit()
        self.sql_output.setReadOnly(True)
        self.sql_output.setPlaceholderText("The generated query appears here. It is never executed.")
        self.sql_output.setFixedHeight(150)
        self.sql_output.setStyleSheet("font-family: Consolas, monospace; font-size: 13px;")
        layout.addWidget(self.sql_output)

        note = QLabel("This mode only writes SQL. Nothing here is executed against any database.")
        note.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        layout.addWidget(note)

    # ------------------------------------------------------------------ source

    def _source_changed(self) -> None:
        connected = self.use_connected.isChecked()
        self.source_stack.setCurrentIndex(0 if connected else 1)
        if connected and not self.schema_preview.toPlainText():
            self.schema_requested.emit()

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a schema file", "", "SQL files (*.sql);;Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        try:
            # A .sql file from a foreign server is not guaranteed to be UTF-8, and
            # a stray byte should not lose the user their file.
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, "Could not read file", str(exc))
            return

        if len(text) > LARGE_SCHEMA_CHARS:
            answer = QMessageBox.question(
                self,
                "Large file",
                f"{Path(path).name} is {len(text):,} characters. Sending all of it as "
                f"context will be slow and may exceed the model's context window.\n\n"
                f"Load it anyway?",
            )
            if answer != QMessageBox.Yes:
                return

        self.schema_input.setPlainText(text)
        self.status.setText(f"Loaded {Path(path).name} ({len(text):,} characters).")

    def schema_text(self) -> str:
        if self.use_connected.isChecked():
            return self.schema_preview.toPlainText().strip()
        return self.schema_input.toPlainText().strip()

    def set_connected_schema(self, schema: str, database: Optional[str]) -> None:
        self.schema_preview.setPlainText(schema)
        self.connected_status.setText(
            f"Live schema from {database}." if database else "No database connected."
        )

    def set_schema_error(self, message: str) -> None:
        self.spinner.hide()
        self.connected_status.setText(message)
        self.connected_status.setStyleSheet(f"color: {_ERROR};")
        self.status.setText("Could not load the live schema. Paste one instead, or fix the connection.")
        self.status.setStyleSheet(f"color: {_ERROR};")

    def set_dialect_label(self, label: str) -> None:
        self.dialect_label.setText(f"Dialect: {label}  (change in Settings)")

    # ------------------------------------------------------------------ output

    def set_busy(self, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {_MUTED};")
        self.spinner.show()

    def set_idle(self, message: str = "") -> None:
        self.spinner.hide()
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {_MUTED};")

    def set_error(self, message: str) -> None:
        self.spinner.hide()
        self.status.setText(message)
        self.status.setStyleSheet(f"color: {_ERROR}; font-weight: 600;")

    def show_sql(self, sql: str, dialect_label: str, seconds: float) -> None:
        self.spinner.hide()
        self.sql_output.setPlainText(sql)
        self.copy_button.setEnabled(bool(sql))
        self.copy_button.setText("Copy")
        self.status.setText(f"Generated for {dialect_label} in {seconds:.1f}s. Not executed.")
        self.status.setStyleSheet(f"color: {_MUTED};")

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.sql_output.toPlainText())
        self.copy_button.setText("Copied")
