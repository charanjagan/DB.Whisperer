"""The main window: mode toggle, question box, results, history sidebar.

Two modes share one question box and one Run button, and differ in what Run
means:

  * Full Assistant  — Phases 1-3: generate, validate, execute read-only, chart,
                      summarise. Always SQL Server; it runs what it writes.
  * Query Generator — generate only, in the settings dialect, from a live or a
                      pasted schema. Nothing executes.

Everything slow happens in ui.workers. This file's job is to keep the widgets
consistent with whatever state the session is in, and to make sure Run cannot be
pressed twice at once.
"""

import time
from datetime import datetime
from typing import List, NamedTuple, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nl2sql.app_config import AppConfig, load_config, save_config
from nl2sql.dialects import get_dialect
from nl2sql.session import Session

from .assistant_panel import AssistantPanel
from .generator_panel import GeneratorPanel
from .settings_dialog import SettingsDialog
from .workers import AssistantWorker, GeneratorWorker, SchemaFetchWorker

MODE_ASSISTANT = "Full Assistant"
MODE_GENERATOR = "Query Generator"

_MUTED = "#898781"


class HistoryEntry(NamedTuple):
    """One question the user asked, and when, and in which mode.

    Session-only: the list dies with the window. Persisting it would mean writing
    a user's questions to disk, which is a decision worth making deliberately
    rather than as a side effect of wanting a sidebar.
    """

    question: str
    mode: str
    at: datetime

    def label(self) -> str:
        head = self.question if len(self.question) <= 60 else self.question[:59] + "…"
        return f"{head}\n{self.at:%H:%M}  ·  {self.mode}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DB.Whisperer")
        self.resize(1180, 780)

        self.config: AppConfig = load_config()
        self.session = Session(self.config)
        self.history: List[HistoryEntry] = []
        self._worker = None

        self._build_ui()
        self._build_menu()
        self._sync_dialect_label()
        self._update_status()

        # Reconnecting on launch would freeze the window before it is even
        # visible, and the saved server may be gone. The user opens Settings.
        if self.config.database:
            self.status_label.setText(
                f"Last used {self.config.database} on {self.config.server}. "
                f"Open Settings to connect."
            )

    # ------------------------------------------------------------------- build

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_main())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 940])
        root.addWidget(splitter)

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)

        header = QLabel("History")
        header.setStyleSheet("font-weight: 600; padding: 2px;")
        layout.addWidget(header)

        self.history_list = QListWidget()
        self.history_list.setWordWrap(True)
        # Refills the box; deliberately does not re-run. Re-asking costs a minute
        # of model time, so that stays the user's decision, not a click's.
        self.history_list.itemClicked.connect(self._history_clicked)
        layout.addWidget(self.history_list, 1)

        hint = QLabel("Click to reuse a question.\nThis session only.")
        hint.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        layout.addWidget(hint)
        return panel

    def _build_main(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- mode toggle ------------------------------------------------------
        mode_row = QHBoxLayout()
        self.assistant_radio = QRadioButton(MODE_ASSISTANT)
        self.generator_radio = QRadioButton(MODE_GENERATOR)
        self.assistant_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.assistant_radio, 0)
        self.mode_group.addButton(self.generator_radio, 1)
        self.mode_group.idClicked.connect(self._mode_changed)
        mode_row.addWidget(self.assistant_radio)
        mode_row.addWidget(self.generator_radio)
        mode_row.addStretch(1)

        self.settings_button = QPushButton("⚙  Settings")
        self.settings_button.clicked.connect(self.open_settings)
        mode_row.addWidget(self.settings_button)
        layout.addLayout(mode_row)

        self.mode_hint = QLabel("")
        self.mode_hint.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        layout.addWidget(self.mode_hint)

        # --- question ---------------------------------------------------------
        self.question_input = QPlainTextEdit()
        self.question_input.setPlaceholderText("Ask a question about your data…")
        self.question_input.setFixedHeight(64)
        layout.addWidget(self.question_input)

        run_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        self.status_label.setWordWrap(True)
        run_row.addWidget(self.status_label, 1)
        self.run_button = QPushButton("Run")
        self.run_button.setMinimumWidth(110)
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self.run)
        run_row.addWidget(self.run_button)
        layout.addLayout(run_row)

        # --- results ----------------------------------------------------------
        self.assistant_panel = AssistantPanel()
        self.generator_panel = GeneratorPanel()
        self.generator_panel.schema_requested.connect(self._fetch_schema)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.assistant_panel)
        self.stack.addWidget(self.generator_panel)
        layout.addWidget(self.stack, 1)

        self._mode_changed(0)
        return panel

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        settings_action = QAction("&Settings…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)

        run_action = QAction("&Run", self)
        run_action.setShortcut(QKeySequence("Ctrl+Return"))
        run_action.triggered.connect(self.run)
        file_menu.addAction(run_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    # -------------------------------------------------------------------- mode

    @property
    def mode(self) -> str:
        return MODE_ASSISTANT if self.assistant_radio.isChecked() else MODE_GENERATOR

    def _mode_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.mode_hint.setText(
                "Generates SQL, runs it read-only against SQL Server, charts it, and summarises it."
            )
            self.run_button.setText("Run")
        else:
            self.mode_hint.setText(
                "Writes SQL only — nothing is executed. Uses the dialect set in Settings."
            )
            self.run_button.setText("Generate")
            self._sync_dialect_label()
            if self.generator_panel.use_connected.isChecked():
                self._fetch_schema()

    def _sync_dialect_label(self) -> None:
        self.generator_panel.set_dialect_label(get_dialect(self.config.dialect).label)

    # ---------------------------------------------------------------- settings

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self.session, parent=self)
        if dialog.exec() != SettingsDialog.Accepted:
            return

        self.config = dialog.result_config()
        self.session.config = self.config
        try:
            save_config(self.config)
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not save settings",
                f"Your settings apply to this session but were not saved:\n{exc}",
            )

        self._sync_dialect_label()
        self._update_status()
        if self.mode == MODE_GENERATOR and self.generator_panel.use_connected.isChecked():
            self._fetch_schema()

    def _update_status(self) -> None:
        if self.session.ready:
            self.status_label.setText(
                f"Connected: {self.session.database} on {self.config.server} (read-only)"
            )
        elif self.session.connected:
            self.status_label.setText(
                f"Connected to {self.config.server}. Pick a database in Settings."
            )
        else:
            self.status_label.setText("Not connected. Open Settings to connect.")

    # --------------------------------------------------------------------- run

    def run(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            self.status_label.setText("Type a question first.")
            return
        if self._worker is not None and self._worker.isRunning():
            # Returning silently here made Run look broken: the schema fetch that
            # starts when you switch to Query Generator holds the worker slot for
            # a second or two, and a click landing in that window did nothing at
            # all while the old result sat in the output box looking like a new one.
            self.status_label.setText("Still finishing the last step — try again in a moment.")
            return

        self._remember(question)
        if self.mode == MODE_ASSISTANT:
            self._run_assistant(question)
        else:
            self._run_generator(question)

    def _run_assistant(self, question: str) -> None:
        if not self.session.ready:
            self.assistant_panel.set_error(
                "No database selected. Open Settings, connect to a server, and pick a database."
            )
            return

        self.assistant_panel.clear()
        self.assistant_panel.set_busy("Starting…")
        self._set_running(True)

        worker = AssistantWorker(self.session, question, model=self.config.model, parent=self)
        worker.progress.connect(self.assistant_panel.set_progress)
        worker.done.connect(self.assistant_panel.show_result)
        worker.failed.connect(self.assistant_panel.set_error)
        worker.finished.connect(lambda: self._set_running(False))
        self._worker = worker
        worker.start()

    def _run_generator(self, question: str) -> None:
        schema = self.generator_panel.schema_text()
        if not schema:
            self.generator_panel.set_error(
                "No schema to work from. Connect a database, or paste one in."
                if self.generator_panel.use_connected.isChecked()
                else "Paste a schema, or load a .sql file, first."
            )
            return

        dialect = get_dialect(self.config.dialect)
        self.generator_panel.set_busy(f"Generating {dialect.label}…")
        self._set_running(True)
        started = time.time()

        worker = GeneratorWorker(
            question, schema, dialect=dialect.key, model=self.config.model, parent=self
        )
        worker.progress.connect(self.generator_panel.set_busy)
        worker.done.connect(
            lambda sql: self.generator_panel.show_sql(sql, dialect.label, time.time() - started)
        )
        worker.failed.connect(self.generator_panel.set_error)
        worker.finished.connect(lambda: self._set_running(False))
        self._worker = worker
        worker.start()

    def _fetch_schema(self) -> None:
        if not self.session.ready:
            self.generator_panel.set_connected_schema("", None)
            return
        if self._worker is not None and self._worker.isRunning():
            return

        # Holds the same lock Run does: it is a worker on the same connection, so
        # Generate has to stay disabled until the schema it would use is loaded.
        self._set_running(True)
        self.generator_panel.set_busy("Reading the database schema…")

        worker = SchemaFetchWorker(self.session, parent=self)
        worker.done.connect(self._schema_fetched)
        worker.failed.connect(self.generator_panel.set_schema_error)
        worker.finished.connect(lambda: self._set_running(False))
        self._worker = worker
        worker.start()

    def _schema_fetched(self, schema: str) -> None:
        self.generator_panel.set_connected_schema(schema, self.session.database)
        self.generator_panel.set_idle(
            f"Live schema loaded from {self.session.database} ({len(schema):,} characters)."
        )

    def _set_running(self, running: bool) -> None:
        # One worker at a time: two pipelines sharing one pyodbc connection is a
        # bug waiting to happen, and the model would be queueing behind itself.
        self.run_button.setEnabled(not running)
        self.run_button.setText(
            "Working…" if running else ("Run" if self.mode == MODE_ASSISTANT else "Generate")
        )
        self.settings_button.setEnabled(not running)
        self.assistant_radio.setEnabled(not running)
        self.generator_radio.setEnabled(not running)

    # ----------------------------------------------------------------- history

    def _remember(self, question: str) -> None:
        entry = HistoryEntry(question=question, mode=self.mode, at=datetime.now())
        self.history.insert(0, entry)
        item = QListWidgetItem(entry.label())
        item.setData(Qt.UserRole, entry.question)
        self.history_list.insertItem(0, item)

    def _history_clicked(self, item: QListWidgetItem) -> None:
        self.question_input.setPlainText(item.data(Qt.UserRole))
        self.question_input.setFocus()

    # ------------------------------------------------------------------ close

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            # A QThread still running when the interpreter tears down its parent
            # takes the process out with an abort, not a clean exit.
            self._worker.wait(2000)
        self.session.close()
        super().closeEvent(event)
