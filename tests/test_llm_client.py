"""Model-output cleanup and server-error condensing -- the text handling around the model."""

import pyodbc
import pytest

from nl2sql.llm_client import _clean_sql, _error_text


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SELECT 1", "SELECT 1"),
        ("SELECT 1;", "SELECT 1"),
        ("```sql\nSELECT a FROM t\n```", "SELECT a FROM t"),
        ("```\nSELECT a FROM t;\n```", "SELECT a FROM t"),
        ("SQL: SELECT a FROM t", "SELECT a FROM t"),
        # A restated question ahead of the statement is sliced off.
        ("# of products in each category SELECT COUNT(*) FROM p", "SELECT COUNT(*) FROM p"),
        # A CTE is kept whole, not cut down to its first inner SELECT.
        ("```sql\nWITH x AS (SELECT 1) SELECT * FROM x;\n```", "WITH x AS (SELECT 1) SELECT * FROM x"),
        ("", ""),
    ],
)
def test_clean_sql(raw, expected):
    assert _clean_sql(raw) == expected


def test_error_text_strips_odbc_wrapping():
    exc = pyodbc.ProgrammingError(
        "42S22",
        "[42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]"
        "Invalid column name 'ProductName'. (207) (SQLExecDirectW)",
    )
    assert _error_text(exc) == "Invalid column name 'ProductName'. (207)"


def test_error_text_dedupes_repeated_diagnostic_records():
    record = (
        "[42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]"
        "Invalid column name 'Colour'. (207)"
    )
    exc = pyodbc.ProgrammingError("42S22", f"{record}; {record} (SQLExecDirectW)")
    assert _error_text(exc) == "Invalid column name 'Colour'. (207)"


def test_error_text_timeout():
    exc = pyodbc.OperationalError(
        "HYT00",
        "[HYT00] [Microsoft][ODBC Driver 17 for SQL Server]Query timeout expired (0) (SQLExecDirectW)",
    )
    assert _error_text(exc) == "Query timeout expired (0)"


def test_error_text_passes_non_odbc_errors_through():
    assert _error_text(ValueError("nope")) == "nope"
