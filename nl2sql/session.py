"""One live connection to one server, and whichever database is selected.

The UI needs somewhere to keep two connections and a database name without
putting pyodbc calls inside widgets. That is all this is: the two-connection rule
from Phase 2 and the auto-provisioning switch from Phase 3, behind an object a
window can hold.

The two connections are not interchangeable and the split is the security
boundary:

  * `admin_conn`  — Windows auth (or SQL auth as an admin). Lists databases and
                    grants db_datareader. Never runs a generated query.
  * `query_conn`  — the nl2sql_reader login, scoped to the selected database.
                    Runs every generated query, and can do nothing but SELECT.

Nothing here touches Qt, so it can be driven from a test or a worker thread.
"""

from typing import List, Optional

import pyodbc

from .app_config import AppConfig
from .db_connection import connect_server, list_databases
from .db_setup import AccessGrant, select_database


class SessionError(RuntimeError):
    """Raised when connecting or switching fails, with a message fit to show."""


class Session:
    """Holds the admin connection, the read-only connection, and the database."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.admin_conn: Optional[pyodbc.Connection] = None
        self.query_conn: Optional[pyodbc.Connection] = None
        self.database: Optional[str] = None
        self.last_grant: Optional[AccessGrant] = None
        # What the last connect saw, so reopening the settings dialog can refill
        # the dropdown without a round-trip to the server.
        self.databases: List[str] = []

    @property
    def connected(self) -> bool:
        return self.admin_conn is not None

    @property
    def ready(self) -> bool:
        """True once a database is selected and queryable."""
        return self.query_conn is not None

    def connect(self, config: Optional[AppConfig] = None) -> List[str]:
        """Connect at server level and return the user databases found.

        No database is selected yet — that is `select`'s job. Replaces any
        existing connection, so this doubles as "reconnect with new settings".
        """
        if config is not None:
            self.config = config
        self.close()

        try:
            self.admin_conn = connect_server(self.config.to_sql_config())
            self.databases = list_databases(self.admin_conn)
            return self.databases
        except (pyodbc.Error, ValueError) as exc:
            self.admin_conn = None
            raise SessionError(f"Could not connect to '{self.config.server}': {exc}") from exc

    def select(self, database: str) -> AccessGrant:
        """Switch to `database`, provisioning read-only access if it needs it.

        Silent and idempotent on the common path: the user picks a database from
        the dropdown and gets a connection, whether or not anyone ever ran
        setup_readonly_user.sql against it.
        """
        if self.admin_conn is None:
            raise SessionError("Not connected to a server yet.")

        try:
            conn, grant = select_database(self.admin_conn, self.config.to_sql_config(), database)
        except Exception as exc:  # ReadOnlyLoginError, pyodbc.Error
            raise SessionError(f"Could not open '{database}': {exc}") from exc

        # Only swap the old connection out once the new one exists, so a failed
        # switch leaves the user on the database that was working.
        self._close_query_conn()
        self.query_conn = conn
        self.database = database
        self.config.database = database
        self.last_grant = grant
        return grant

    def require_query_conn(self) -> pyodbc.Connection:
        """The read-only connection, or a message saying what to do about it."""
        if self.query_conn is None:
            raise SessionError(
                "No database selected. Open Settings, connect to a server, and pick one."
            )
        return self.query_conn

    def _close_query_conn(self) -> None:
        if self.query_conn is not None:
            try:
                self.query_conn.close()
            except pyodbc.Error:
                pass
            self.query_conn = None

    def close(self) -> None:
        """Drop both connections. Safe to call on a session that never connected."""
        self._close_query_conn()
        if self.admin_conn is not None:
            try:
                self.admin_conn.close()
            except pyodbc.Error:
                pass
            self.admin_conn = None
        self.database = None
        self.databases = []
