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

`run_query` also bounds what a query can cost: a statement timeout, and a row
cap so a runaway join cannot pull millions of rows into memory. db_datareader
stops writes, but nothing on the server stops an expensive read.
"""

import re

import pandas as pd
import pyodbc

# Generous next to any real question against these databases (AdventureWorks'
# aggregates come back in well under a second); short enough that an accidental
# cross join gives the app back instead of hanging it.
QUERY_TIMEOUT_SECONDS = 60

# Far past what a chart or the summary prompt can use, so a legitimate result is
# never cut; low enough that a missing WHERE clause cannot exhaust memory.
MAX_RESULT_ROWS = 10_000

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

# One left-to-right pass over everything that is not SQL code: comments, string
# literals, and quoted identifiers. They have to be matched together, not in
# separate passes, because each can contain the others' delimiters -- a '--'
# inside a string is not a comment, and a quote inside a comment opens nothing.
# Whichever starts first wins, which is how the server tokenises it too.
#
# An unterminated literal matches none of these and is left in place, so its
# contents still get scanned. Erring that way costs a retry, not a bypass.
_NON_CODE_RE = re.compile(
    r"""
      (?P<comment> --[^\n]* | /\*.*?\*/ )
    | (?P<string>  '(?:[^']|'')*' )
    | (?P<ident>   \[(?:[^\]]|\]\])*\] | "(?:[^"]|"")*" )
    """,
    re.DOTALL | re.VERBOSE,
)

# The statement kinds a read can open with. A CTE (WITH ...) is still a read:
# any write it could end in -- INSERT, UPDATE, DELETE, MERGE -- is caught by the
# keyword scan, which runs on every query regardless of how it starts.
_READ_STARTS = ("SELECT", "WITH")


class UnsafeQueryError(Exception):
    """Raised when generated SQL is not a plain read-only SELECT."""


def _mask(match: "re.Match") -> str:
    # Placeholders keep the token boundary (so "a'x'b" does not fuse into one
    # word) while dropping the contents the keyword scan must not read.
    if match.group("comment") is not None:
        return " "
    if match.group("string") is not None:
        return "''"
    return "[_]"


def _code_only(sql: str) -> str:
    """`sql` with comments removed and literal/identifier contents blanked."""
    return _NON_CODE_RE.sub(_mask, sql)


def validate_select_only(sql: str) -> str:
    """Raise UnsafeQueryError unless `sql` is a single read-only SELECT (or CTE).

    Defense in depth only — see the module docstring. The read-only login is
    what actually prevents writes.

    Runs on the code alone, with string literals and quoted identifiers blanked:
    WHERE Name = 'Delete me' is a filter, not a DELETE, and 'a;b' is one
    statement, not two.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("Query is empty.")

    code = _code_only(sql).strip()

    if not code.lstrip("( \t\r\n").upper().startswith(_READ_STARTS):
        raise UnsafeQueryError(
            f"Query must start with SELECT or WITH. Got: {code[:60]!r}"
        )

    # Reject multi-statement input outright, before the keyword scan, so
    # "SELECT 1; DROP TABLE x" is reported as what it is. One trailing
    # semicolon is normal and allowed; anything after it is not.
    if ";" in code.rstrip().rstrip(";"):
        raise UnsafeQueryError("Multiple statements are not allowed.")

    for keyword in FORBIDDEN_KEYWORDS:
        # Word boundaries so a column named `updated_at` does not trip `UPDATE`.
        if re.search(rf"\b{keyword}\b", code, flags=re.IGNORECASE):
            raise UnsafeQueryError(f"Query contains forbidden keyword: {keyword}")

    return sql


def run_query(
    conn: pyodbc.Connection,
    sql: str,
    max_rows: int = MAX_RESULT_ROWS,
    timeout: int = QUERY_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Validate then execute. Returns at most `max_rows` rows as a DataFrame.

    A result cut at the cap carries df.attrs["truncated"] = True, so the UI and
    the summary can say "first 10,000 rows" instead of passing a partial answer
    off as the whole one. A query running past `timeout` seconds raises
    pyodbc.OperationalError (SQLSTATE HYT00), which the retry loop feeds back to
    the model like any other server error.
    """
    validate_select_only(sql)

    # pyodbc applies the connection's timeout to cursors created after it is
    # set; 0 means no limit, so a caller can still opt out explicitly.
    conn.timeout = timeout
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        if cursor.description is None:  # no result set; nothing to show
            return pd.DataFrame()
        columns = [col[0] for col in cursor.description]
        # One past the cap: the only way to know there was more without
        # counting the whole result on the server.
        rows = cursor.fetchmany(max_rows + 1)
    finally:
        cursor.close()

    truncated = len(rows) > max_rows
    # coerce_float matches what pd.read_sql did here before: SQL Server
    # decimal/money arrive as Decimal, which pandas would otherwise keep as
    # object dtype and the chart selector would not see as numeric.
    df = pd.DataFrame.from_records(
        [tuple(row) for row in rows[:max_rows]], columns=columns, coerce_float=True
    )
    df.attrs["truncated"] = truncated
    df.attrs["max_rows"] = max_rows
    return df
