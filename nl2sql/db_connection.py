"""pyodbc connection helpers: server-level connect, database discovery, scoped connect."""

from typing import List, Tuple

import pyodbc

from .config import SqlServerConfig

# sys.databases ids 1-4 are master, tempdb, model, msdb.
_USER_DATABASE_QUERY = """
SELECT name
FROM sys.databases
WHERE database_id > 4
  AND state = 0
  AND HAS_DBACCESS(name) = 1
ORDER BY name;
"""


def connect_server(config: SqlServerConfig, timeout: int = 5) -> pyodbc.Connection:
    """Connect at server level, without scoping to any database."""
    return pyodbc.connect(
        config.to_connection_string(include_database=False), timeout=timeout
    )


def connect_database(config: SqlServerConfig, timeout: int = 5) -> pyodbc.Connection:
    """Connect scoped to config.database. Raises if no database is selected."""
    if not config.database:
        raise ValueError("config.database is not set; nothing to connect to.")
    return pyodbc.connect(
        config.to_connection_string(include_database=True), timeout=timeout
    )


def list_databases(conn: pyodbc.Connection) -> List[str]:
    """Return user database names only; system DBs are filtered out."""
    cursor = conn.cursor()
    cursor.execute(_USER_DATABASE_QUERY)
    return [row[0] for row in cursor.fetchall()]


def test_connection(config: SqlServerConfig) -> Tuple[bool, str]:
    """Health check. Returns (ok, human-readable message)."""
    include_db = bool(config.database)
    try:
        conn = pyodbc.connect(
            config.to_connection_string(include_database=include_db), timeout=5
        )
    except pyodbc.Error as exc:
        sqlstate = exc.args[0] if exc.args else "?"
        return False, f"Connection failed [{sqlstate}]: {exc}"
    except ValueError as exc:
        return False, f"Invalid config: {exc}"

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION;")
        version = cursor.fetchone()[0].splitlines()[0].strip()
        scope = config.database or "(server level)"
        return True, f"Connected to {config.server} / {scope} - {version}"
    except pyodbc.Error as exc:
        return False, f"Connected but probe query failed: {exc}"
    finally:
        conn.close()
