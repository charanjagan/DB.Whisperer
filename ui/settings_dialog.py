"""Connection, database, and dialect settings.

Three things live here, and only one of them is about connecting:

  * the server and how to authenticate to it
  * which database to query — populated from the live server, and switching it
    provisions read-only access via Phase 3's select_database
  * which SQL dialect Query Generator writes

The dialect is here rather than in the Query Generator panel because it is a
saved preference, not a per-question choice, and because a user who has never
opened that mode should still be able to see and set it. Full Assistant ignores
it: it executes what it generates, and SQL Server is the only server this app
connects to.
"""

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from nl2sql.app_config import AppConfig, config_path
from nl2sql.dialects import DIALECTS
from nl2sql.session import Session

from .workers import ConnectWorker, SelectDatabaseWorker


class SettingsDialog(QDialog):
    """Edits an AppConfig in place against a live Session.

    Connecting and switching databases happen here and now rather than on OK, so
    the database dropdown can be filled from the server and the user finds out
    about a bad password while the fields are still in front of them.
    """

    def __init__(self, config: AppConfig, session: Session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(520, 0)

        self.config = config
        self.session = session
        self._worker = None

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_database_group())
        layout.addWidget(self._build_dialect_group())

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        hint = QLabel(f"Settings are saved to {config_path()}")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #898781; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_from_config()

    # ---------------------------------------------------------------- widgets

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("SQL Server connection")
        form = QFormLayout(group)

        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("localhost  or  HOST\\INSTANCE")
        form.addRow("Server", self.server_edit)

        self.auth_combo = QComboBox()
        self.auth_combo.addItem("Windows Authentication", True)
        self.auth_combo.addItem("SQL Server Authentication", False)
        self.auth_combo.currentIndexChanged.connect(self._auth_changed)
        form.addRow("Authentication", self.auth_combo)

        self.username_edit = QLineEdit()
        form.addRow("Username", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Password", self.password_edit)

        # Saying so beats a user assuming either way. The file holds no secrets;
        # keeping it that way means it needs no protection beyond the filesystem.
        note = QLabel("The password is kept for this session only and is never written to the config file.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #898781; font-size: 11px;")
        form.addRow("", note)

        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect)
        form.addRow("", self.connect_button)
        return group

    def _build_database_group(self) -> QGroupBox:
        group = QGroupBox("Database")
        box = QVBoxLayout(group)

        row = QHBoxLayout()
        self.database_combo = QComboBox()
        self.database_combo.setEnabled(False)
        self.database_combo.activated.connect(self._database_chosen)
        row.addWidget(self.database_combo, 1)
        box.addLayout(row)

        note = QLabel(
            "Read-only access is granted automatically the first time you pick a database. "
            "Queries never run as your admin login."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #898781; font-size: 11px;")
        box.addWidget(note)
        return group

    def _build_dialect_group(self) -> QGroupBox:
        group = QGroupBox("SQL dialect (Query Generator)")
        box = QVBoxLayout(group)

        self.dialect_combo = QComboBox()
        for key, dialect in DIALECTS.items():
            self.dialect_combo.addItem(dialect.label, key)
        box.addWidget(self.dialect_combo)

        note = QLabel(
            "Used by Query Generator mode. Full Assistant always targets SQL Server, "
            "because it executes what it generates."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #898781; font-size: 11px;")
        box.addWidget(note)
        return group

    # ------------------------------------------------------------------ state

    def _load_from_config(self) -> None:
        self.server_edit.setText(self.config.server)
        self.auth_combo.setCurrentIndex(0 if self.config.use_windows_auth else 1)
        self.username_edit.setText(self.config.username)
        self.password_edit.setText(self.config.password)

        index = self.dialect_combo.findData(self.config.dialect)
        self.dialect_combo.setCurrentIndex(max(index, 0))

        self._auth_changed()

        # An already-connected session keeps its database list, so reopening
        # settings does not mean connecting again.
        if self.session.connected:
            self._fill_databases(self.session.databases)
            self._say(f"Connected to {self.session.config.server}.")

    def _auth_changed(self) -> None:
        sql_auth = not self.auth_combo.currentData()
        self.username_edit.setEnabled(sql_auth)
        self.password_edit.setEnabled(sql_auth)

    def _current_config(self) -> AppConfig:
        """The config as the fields currently read, without committing it."""
        config = AppConfig(
            server=self.server_edit.text().strip() or "localhost",
            use_windows_auth=bool(self.auth_combo.currentData()),
            username=self.username_edit.text().strip(),
            password=self.password_edit.text(),
            database=self.config.database,
            dialect=self.dialect_combo.currentData(),
            model=self.config.model,
            driver=self.config.driver,
        )
        return config

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.connect_button.setEnabled(not busy)
        self.database_combo.setEnabled(not busy and self.database_combo.count() > 0)
        if message:
            self._say(message)

    def _say(self, message: str, error: bool = False) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(
            "color: #d03b3b; font-size: 12px;" if error else "color: #52514e; font-size: 12px;"
        )

    # --------------------------------------------------------------- actions

    def _connect(self) -> None:
        config = self._current_config()
        self._set_busy(True, "Connecting…")

        worker = ConnectWorker(self.session, config, parent=self)
        worker.progress.connect(self._say)
        worker.done.connect(self._connected)
        worker.failed.connect(self._connect_failed)
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        worker.start()

    def _connected(self, databases: List[str]) -> None:
        self.config = self.session.config
        self._fill_databases(databases)
        if not databases:
            self._say("Connected, but this server has no user databases.", error=True)
            return
        self._say(f"Connected to {self.session.config.server}. {len(databases)} databases.")

        # Re-select whatever was saved, so a restart lands back where the user was.
        if self.config.database in databases:
            self.database_combo.setCurrentText(self.config.database)
            self._database_chosen(self.database_combo.currentIndex())

    def _connect_failed(self, message: str) -> None:
        self.database_combo.clear()
        self.database_combo.setEnabled(False)
        self._say(message, error=True)

    def _fill_databases(self, databases: List[str]) -> None:
        self.database_combo.clear()
        self.database_combo.addItems(databases)
        self.database_combo.setEnabled(bool(databases))
        if self.session.database in databases:
            self.database_combo.setCurrentText(self.session.database)

    def _database_chosen(self, _index: int) -> None:
        database = self.database_combo.currentText()
        if not database or database == self.session.database:
            return

        self._set_busy(True, f"Opening {database}…")
        worker = SelectDatabaseWorker(self.session, database, parent=self)
        worker.progress.connect(self._say)
        worker.done.connect(self._database_opened)
        worker.failed.connect(lambda m: self._say(m, error=True))
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        worker.start()

    def _database_opened(self, grant) -> None:
        self.config.database = self.session.database
        # `grant.describe()` says whether access had to be granted just now. It is
        # the only visible trace of provisioning, and it is worth one line.
        self._say(f"Using {self.session.database}. {grant.describe()}")

    # ---------------------------------------------------------------- result

    def result_config(self) -> AppConfig:
        """The settings as accepted. Read this after exec() returns Accepted."""
        config = self._current_config()
        config.database = self.session.database or config.database
        return config

    def accept(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._say("Still working — one moment.", error=True)
            return
        super().accept()
