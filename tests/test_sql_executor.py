"""validate_select_only: what must run, and what must never get as far as the server."""

import pytest

from nl2sql.sql_executor import FORBIDDEN_KEYWORDS, UnsafeQueryError, validate_select_only

ALLOWED = [
    "SELECT 1",
    "select * from t",
    "  (SELECT a FROM t)",
    "SELECT a FROM t;",
    "SELECT updated_at, created_by FROM t",  # keywords as part of a name
    # CTEs are reads.
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    # Keywords and semicolons inside literals and quoted identifiers are data.
    "SELECT * FROM t WHERE name = 'Delete me'",
    "SELECT * FROM t WHERE name = N'it''s; DROP TABLE x'",
    'SELECT [Update], "Into" FROM t',
    "SELECT [Order]]Details] FROM t",
    "SELECT '--' AS a, b FROM t WHERE c = 1",
    "SELECT a FROM t -- DELETE this later\nWHERE b = 1",
    "SELECT a /* DROP */ FROM t",
]

BLOCKED = [
    "",
    "   ",
    "DELETE FROM t",
    "UPDATE t SET a = 1",
    "EXEC('SELECT 1')",
    "SELECT 1; DROP TABLE x",
    "SELECT a INTO t FROM b",
    "WITH x AS (SELECT 1 AS a) DELETE FROM t",
    "WITH x AS (SELECT 1 AS a) UPDATE t SET a = 1",
    "WITH x AS (SELECT 1 AS a) INSERT INTO t SELECT a FROM x",
    "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
    "SELECT 1 WAITFOR DELAY '00:01'",
    # A quote inside a comment opens nothing; what follows is still code.
    "SELECT 1 /* ' */ ; DELETE FROM t",
    "SELECT 1 -- '\n; DROP TABLE t",
    # Unterminated literal: not masked, so its contents are still scanned.
    "SELECT 'unterminated DELETE",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    assert validate_select_only(sql) == sql


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocked(sql):
    with pytest.raises(UnsafeQueryError):
        validate_select_only(sql)


@pytest.mark.parametrize("keyword", FORBIDDEN_KEYWORDS)
def test_every_forbidden_keyword_is_caught(keyword):
    with pytest.raises(UnsafeQueryError, match=keyword):
        validate_select_only(f"SELECT a FROM t {keyword} x")


@pytest.mark.parametrize("keyword", FORBIDDEN_KEYWORDS)
def test_forbidden_keyword_inside_a_literal_is_data(keyword):
    validate_select_only(f"SELECT a FROM t WHERE note = '{keyword} me'")


def test_multi_statement_reported_as_such():
    with pytest.raises(UnsafeQueryError, match="Multiple statements"):
        validate_select_only("SELECT 1; SELECT 2")
