"""Validation and execution of generated SQL.

`validate_select_only` is defense in depth, not the security boundary. It is a
regex pass over a string the LLM wrote, and any such pass can be fooled — by a
keyword split across a comment, an encoding trick, or simply a construct nobody
thought to add to the list. It exists to reject obvious junk early and give a
clear error, not to be the thing that saves the database.

The security boundary is the read-only SQL login: see setup_readonly_user.sql
and db_setup.py. That login is in db_datareader and nothing else, so a DELETE
that slips past every check here is still refused by the server. Run queries
through `connect_readonly` and treat anything this module catches as a bug
worth logging, not as an attack that was successfully repelled.
"""

import re
import warnings

import pandas as pd
import pyodbc

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "TRUNCATE",
    "MERGE",
    "GRANT",
    "REVOKE",
    "DENY",
    "BACKUP",
    "RESTORE",
    "SHUTDOWN",
    # `\bEXEC\b` does not match EXECUTE, so both spellings are listed.
    "EXEC",
    "EXECUTE",
    # SELECT ... INTO t FROM ... creates a table. It starts with SELECT and
    # contains none of the keywords above, so without this it reads as a plain
    # read. INSERT INTO is already caught by INSERT; no legitimate read-only
    # SELECT uses INTO.
    "INTO",
    # Reads a file/remote source from the server's context, and OPENROWSET can
    # run a statement on the far side.
    "OPENROWSET",
    "OPENQUERY",
    "OPENDATASOURCE",
    # Not a write, but a free denial of service: WAITFOR DELAY '23:59:59'.
    "WAITFOR",
)

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class UnsafeQueryError(Exception):
    """Raised when generated SQL is not a plain read-only SELECT."""


def _strip_comments(sql: str) -> str:
    return _COMMENT_RE.sub(" ", sql)


def validate_select_only(sql: str) -> str:
    """Raise UnsafeQueryError unless `sql` is a single read-only SELECT.

    Defense in depth only — see the module docstring. The read-only login is
    what actually prevents writes.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("Query is empty.")

    stripped = _strip_comments(sql).strip()

    if not stripped.lstrip("( \t\r\n").upper().startswith("SELECT"):
        raise UnsafeQueryError(
            f"Query must start with SELECT. Got: {stripped[:60]!r}"
        )

    # Reject multi-statement input outright, before the keyword scan, so
    # "SELECT 1; DROP TABLE x" is reported as what it is. One trailing
    # semicolon is normal and allowed; anything after it is not.
    if ";" in stripped.rstrip().rstrip(";"):
        raise UnsafeQueryError("Multiple statements are not allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        # Word boundaries so a column named `updated_at` does not trip `UPDATE`.
        if re.search(rf"\b{keyword}\b", stripped, flags=re.IGNORECASE):
            raise UnsafeQueryError(f"Query contains forbidden keyword: {keyword}")

    return sql


def run_query(conn: pyodbc.Connection, sql: str) -> pd.DataFrame:
    """Validate then execute. Returns results as a DataFrame."""
    validate_select_only(sql)
    with warnings.catch_warnings():
        # pandas nags about non-SQLAlchemy connections. Passing pyodbc directly
        # is deliberate here; we read only, so the untested paths don't apply.
        warnings.filterwarnings(
            "ignore",
            message="pandas only supports SQLAlchemy connectable",
            category=UserWarning,
        )
        return pd.read_sql(sql, conn)
