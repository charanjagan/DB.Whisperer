"""Phase 2 smoke test, run against AdventureWorks through the read-only login.

Covers the three things Phase 2 added:

  1. the read-only login is real (the server refuses writes, not just our regex)
  2. schema filtering shrinks AdventureWorks' 74 tables to the handful a
     question needs, which is what made Phase 1 slow and inaccurate
  3. the retry loop recovers from a query that fails against the server

Run setup_readonly_user.sql first. Usage:

    python test_phase2.py                # sections 1-5
    python test_phase2.py --compare      # also time an unfiltered generation
"""

import sys
import time

import pandas as pd
import pyodbc

from nl2sql import (
    SqlServerConfig,
    build_schema_context,
    connect_readonly,
    get_schema_summary,
    get_table_list,
    generate_sql_with_retry,
    validate_select_only,
    verify_readonly,
)
from nl2sql import llm_client
from nl2sql.db_setup import ReadOnlyLoginError
from nl2sql.llm_client import LLMError, SQLRetryError
from nl2sql.sql_executor import UnsafeQueryError

SERVER = "localhost"
DATABASE = "AdventureWorks"  # the schema that exposed the Phase 1 slowness
MODEL = "qwen2.5-coder:7b"
QUESTION = "How many products are in each product category?"

RETRY_QUESTION = "List product names and their list prices"

# The single most common way an LLM gets a schema wrong: pluralising the table
# name. SQL Server answers "Invalid object name 'Production.Products'", which
# names the exact problem, and the schema in the prompt shows the real spelling
# one line away — so this is a fair test of the loop rather than of the model.
BAD_SQL = "SELECT Name, ListPrice FROM Production.Products"


def rule(title):
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    return ok


def section_readonly_login(conn):
    """The security boundary: prove the server itself refuses writes."""
    rule("1. Read-only login")

    ok, message = verify_readonly(conn)
    passed = check("verify_readonly", ok, message)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM Person.Person")
    passed &= check("can SELECT", True, f"Person.Person has {cursor.fetchone()[0]} rows")

    # WHERE 1=0 / bogus names so that if this ever *does* get through on a
    # misconfigured server, the test still cannot damage anything.
    writes = [
        ("DELETE", "DELETE FROM Person.Password WHERE 1 = 0"),
        ("UPDATE", "UPDATE Person.Password SET PasswordSalt = PasswordSalt WHERE 1 = 0"),
        ("CREATE", "CREATE TABLE dbo.phase2_should_not_exist (i int)"),
        ("SELECT INTO", "SELECT TOP 0 * INTO dbo.phase2_nope FROM Person.Person"),
    ]
    for label, statement in writes:
        try:
            cursor.execute(statement)
            conn.commit()
            passed &= check(f"{label} refused by server", False, "IT WAS ALLOWED")
        except pyodbc.Error as exc:
            reason = str(exc.args[1]).split("]")[-1][:60]
            passed &= check(f"{label} refused by server", True, reason)
        try:
            conn.rollback()
        except pyodbc.Error:
            pass

    return passed


def section_validator():
    """Defense in depth. Cheap, no database or model needed."""
    rule("2. validate_select_only (defense in depth)")

    should_pass = [
        "SELECT TOP 10 Name FROM Production.Product",
        "SELECT COUNT(*) FROM Person.Person;",  # one trailing semicolon is fine
    ]
    should_block = [
        ("stacked statements", "SELECT 1; SELECT 2"),
        ("stacked with DROP", "SELECT 1; DROP TABLE Production.Product"),
        ("SELECT INTO is a write", "SELECT * INTO dbo.copy FROM Production.Product"),
        ("EXECUTE spelled out", "SELECT 1 UNION ALL EXECUTE sp_who"),
        ("WAITFOR denial of service", "SELECT 1 WAITFOR DELAY '23:59:59'"),
        ("not a SELECT", "DROP TABLE Production.Product"),
        ("empty", "   "),
    ]

    passed = True
    for sql in should_pass:
        try:
            validate_select_only(sql)
            passed &= check(f"allows {sql[:44]!r}", True)
        except UnsafeQueryError as exc:
            passed &= check(f"allows {sql[:44]!r}", False, str(exc))

    for label, sql in should_block:
        try:
            validate_select_only(sql)
            passed &= check(f"blocks {label}", False, "NOT BLOCKED")
        except UnsafeQueryError as exc:
            passed &= check(f"blocks {label}", True, str(exc))

    return passed


def section_filtering(conn, compare=False):
    """The Phase 1 fix: don't send 74 tables when the question needs 3."""
    rule(f"3. Schema filtering on {DATABASE}")

    tables = get_table_list(conn)
    full = get_schema_summary(conn)
    print(f"  {DATABASE}: {len(tables)} base tables")
    print(f"  full schema: {len(full):,} chars (~{len(full) // 4:,} tokens)")
    print(f"  question:    {QUESTION!r}\n")

    started = time.time()
    context = build_schema_context(conn, QUESTION, model=MODEL)
    elapsed = time.time() - started

    passed = check("filtering engaged", context.filtered, f"{context.total_tables} tables > threshold")
    passed &= check(
        "narrowed the table set",
        len(context.tables) < context.total_tables,
        f"{context.total_tables} -> {len(context.tables)}",
    )
    passed &= check(
        "context got smaller",
        len(context.summary) < len(full),
        f"{len(full):,} -> {len(context.summary):,} chars "
        f"({len(full) / max(len(context.summary), 1):.0f}x less)",
    )
    print(f"\n  selection took {elapsed:.1f}s")
    print(f"  tables sent: {', '.join(context.tables)}")

    # The join path matters more than the count: Product and ProductCategory
    # have no FK between them, so a filtered context without ProductSubcategory
    # cannot answer this question no matter how good the model is.
    fk_section = context.summary[context.summary.find("Foreign Keys:") :]
    passed &= check(
        "join path survived filtering",
        "(none)" not in fk_section,
        "FK section is non-empty",
    )
    print("\n  " + fk_section.replace("\n", "\n  "))

    if compare:
        print("\n  --- unfiltered comparison (slow, this is the Phase 1 path) ---")
        started = time.time()
        try:
            llm_client.generate_sql(QUESTION, full, model=MODEL)
            print(f"  unfiltered generation: {time.time() - started:.1f}s")
        except LLMError as exc:
            print(f"  unfiltered generation failed after {time.time() - started:.1f}s: {exc}")

    return passed, context


def section_retry(conn, context):
    """Feed a known-bad query in and watch the loop repair it."""
    rule("4. Error-feedback retry loop")

    print(f"  seeding a deliberately broken query:\n    {BAD_SQL}")
    print("  (the table is Production.Product, not Production.Products)\n")

    # Patch the module-level generate_sql that generate_sql_with_retry calls, so
    # attempt 1 is guaranteed to fail. repair_sql and run_query stay real, which
    # is the whole point: the recovery path is what's under test.
    original = llm_client.generate_sql
    llm_client.generate_sql = lambda *a, **k: BAD_SQL

    def narrate(attempt, sql, error):
        status = "OK" if error is None else f"failed: {error}"
        print(f"  attempt {attempt}: {status}")
        if error is not None:
            print(f"    {sql}")

    try:
        sql, df = generate_sql_with_retry(
            RETRY_QUESTION,
            context.summary,
            conn,
            max_retries=2,
            model=MODEL,
            on_attempt=narrate,
        )
    except SQLRetryError as exc:
        print(f"\n  retries exhausted: {exc}")
        return check("retry loop recovered", False, "never produced a working query")
    except LLMError as exc:
        print(f"\n  LLM error: {exc}")
        return check("retry loop recovered", False, str(exc))
    finally:
        llm_client.generate_sql = original

    print(f"\n  repaired SQL: {sql}")
    passed = check("retry loop recovered", True, f"returned {len(df)} rows")
    passed &= check("repaired query differs from the broken one", sql.strip() != BAD_SQL)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print("\n  " + df.head(5).to_string(index=False).replace("\n", "\n  "))
    return passed


def section_pipeline(conn):
    """Everything together: filter -> generate -> retry -> run, as the app would."""
    rule("5. Full pipeline (filtered schema + retry, read-only connection)")

    started = time.time()
    context = build_schema_context(conn, QUESTION, model=MODEL)
    print(f"  schema context: {len(context.tables)} of {context.total_tables} tables, "
          f"{len(context.summary):,} chars")

    def narrate(attempt, sql, error):
        print(f"  attempt {attempt}: {'OK' if error is None else 'failed: ' + error}")

    try:
        sql, df = generate_sql_with_retry(
            QUESTION, context.summary, conn, max_retries=2, model=MODEL, on_attempt=narrate
        )
    except (SQLRetryError, LLMError) as exc:
        print(f"  FAILED: {exc}")
        return False

    print(f"\n  total: {time.time() - started:.1f}s")
    print(f"  SQL: {sql}\n")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print("  " + df.head(20).to_string(index=False).replace("\n", "\n  "))
    return check("pipeline returned rows", len(df) > 0, f"{len(df)} rows")


def main():
    compare = "--compare" in sys.argv

    base = SqlServerConfig(server=SERVER, use_windows_auth=True, database=DATABASE)
    try:
        conn = connect_readonly(base)
    except ReadOnlyLoginError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"Connected to {SERVER}/{DATABASE} as the read-only login.")

    results = {}
    results["read-only login"] = section_readonly_login(conn)
    results["validator"] = section_validator()

    passed, context = section_filtering(conn, compare=compare)
    results["schema filtering"] = passed
    results["retry loop"] = section_retry(conn, context)
    results["full pipeline"] = section_pipeline(conn)

    conn.close()

    rule("Summary")
    for name, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
