"""Phase 3 end-to-end: pick a database, ask, chart it, summarise it.

The point of this test is the database *switch*. AdventureWorks was provisioned
by hand with setup_readonly_user.sql back in Phase 2; the second database in the
list has never been touched. If both answer questions through the read-only login
without anyone opening SSMS in between, auto-provisioning works.

Each question runs the whole pipeline the app will run:

    select database (grant access if needed)
        -> filter the schema to the question
        -> generate SQL, retry on error
        -> validate + run as the read-only login
        -> detect a chart type from the result's shape
        -> render it to charts/*.png (stands in for the Phase 4 window)
        -> summarise the result back in English

Run it as:

    python test_phase3.py                      # both databases
    python test_phase3.py --db AdventureWorks  # just one
    python test_phase3.py --no-llm             # provisioning + charts only, no Ollama
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import pyodbc

from nl2sql import (
    ReadOnlyLoginError,
    SqlServerConfig,
    build_schema_context,
    connect_server,
    detect_chart_type,
    ensure_readonly_access,
    generate_sql_with_retry,
    generate_summary,
    list_databases,
    render_chart,
    select_database,
    verify_readonly,
)
from nl2sql.llm_client import LLMError, SQLRetryError

SERVER = "localhost"
MODEL = "qwen2.5-coder:7b"
CHART_DIR = Path(__file__).parent / "charts"

# Two databases with nothing in common but the server they sit on: different
# schemas, different table names, different questions. AdventureWorks was
# provisioned manually in Phase 2; IBM HR Dataset never was, which is the case
# worth proving.
PLAN = [
    (
        "AdventureWorks",
        [
            "How many products are in each product category?",
            "How many products are there in total?",
        ],
    ),
    (
        "IBM HR Dataset",
        [
            "How many employees are in each department?",
            "What is the average monthly income by job role?",
        ],
    ),
]


def rule(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    return ok


def slugify(text: str) -> str:
    keep = [c if c.isalnum() else "_" for c in text.lower()]
    return "".join(keep).strip("_")[:48]


def switch_to(admin_conn, base, database):
    """The database picker's job, start to finish."""
    rule(f"Switching to: {database}")

    started = time.time()
    try:
        conn, grant = select_database(admin_conn, base, database)
    except ReadOnlyLoginError as exc:
        check("switched", False, str(exc))
        return None, False

    passed = check("provisioned", True, grant.describe())
    print(f"       {'granted on the fly' if grant.changed else 'nothing to do'} "
          f"in {time.time() - started:.2f}s")

    # Calling it twice must be free and must not re-grant anything: the picker
    # calls this on every switch, including switches back.
    second = ensure_readonly_access(admin_conn, database)
    passed &= check("idempotent on re-select", not second.changed, second.describe())

    ok, message = verify_readonly(conn)
    passed &= check("query connection is read-only", ok, message)

    cursor = conn.cursor()
    cursor.execute("SELECT DB_NAME(), SUSER_NAME()")
    actual_db, actual_login = cursor.fetchone()
    passed &= check(
        "queries run as the reader, scoped to this database",
        actual_db == database and actual_login != "",
        f"{actual_login} @ {actual_db}",
    )
    return conn, passed


def ask(conn, database, question, use_llm=True):
    """One question, all the way through to a .png and a sentence."""
    print(f"\n  {'-' * 64}\n  Q: {question}\n  {'-' * 64}")

    if not use_llm:
        print("  (--no-llm: skipping generation)")
        return True

    started = time.time()
    context = build_schema_context(conn, question, model=MODEL)
    print(f"  schema: {len(context.tables)} of {context.total_tables} tables "
          f"({', '.join(context.tables) or 'all'})")

    def narrate(attempt, sql, error):
        print(f"  attempt {attempt}: {'OK' if error is None else 'failed: ' + error}")

    try:
        sql, df = generate_sql_with_retry(
            question, context.summary, conn, max_retries=2, model=MODEL, on_attempt=narrate
        )
    except (SQLRetryError, LLMError) as exc:
        return check("answered", False, str(exc).splitlines()[0])

    print(f"  SQL: {sql}")
    passed = check("query returned rows", len(df) > 0, f"{len(df)} rows x {len(df.columns)} cols")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print("\n  " + df.head(6).to_string(index=False).replace("\n", "\n  ") + "\n")

    chart_type = detect_chart_type(df)
    print(f"  chart type: {chart_type}")

    CHART_DIR.mkdir(exist_ok=True)
    path = CHART_DIR / f"{slugify(database)}__{slugify(question)}__{chart_type}.png"
    figure = render_chart(df, chart_type)
    figure.savefig(path, facecolor=figure.get_facecolor(), bbox_inches="tight")
    passed &= check("chart rendered", path.exists(), str(path.relative_to(Path.cwd())))

    try:
        summary = generate_summary(question, df, model=MODEL)
    except LLMError as exc:
        return passed & check("summary", False, str(exc))

    passed &= check("summary generated", bool(summary.strip()))
    print(f"\n  Summary: {summary}")
    print(f"  ({time.time() - started:.1f}s end to end)")
    return passed


# Deterministic SQL, not the model: a monthly total whose bucket is a real DATE.
# This is the shape the line path exists for, and the object-dtype date column it
# returns (SQL Server `date` arrives as datetime.date in an object column) is the
# exact case is_datetime_column was written to catch. Kept model-free so it is a
# stable regression guard, not another thing that flakes when the LLM wanders.
_LINE_SQL = """
SELECT DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1) AS OrderMonth,
       SUM(TotalDue) AS TotalSales
FROM Sales.SalesOrderHeader
GROUP BY DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1)
ORDER BY OrderMonth;
"""

# The realistic degraded case: the bucket is a month *name*, not a date. It
# cannot be a time axis, and the honest fallback is a labelled bar, not a line
# pretending an alphabetical x-axis is chronological.
_MONTHNAME_SQL = """
SELECT DATENAME(MONTH, OrderDate) AS MonthName,
       SUM(TotalDue) AS TotalSales
FROM Sales.SalesOrderHeader
WHERE OrderDate >= '2023-01-01' AND OrderDate < '2024-01-01'
GROUP BY DATENAME(MONTH, OrderDate), MONTH(OrderDate)
ORDER BY MONTH(OrderDate);
"""


def section_line_chart(conn, database):
    """The line path, on real rows, without the model in the loop."""
    from nl2sql.chart_selector import is_datetime_column

    rule(f"Line chart path (real data, deterministic SQL) — {database}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_sql(_LINE_SQL, conn)

    if df.empty:
        return check("time-series query returned rows", False, "no sales rows found")

    date_col = df["OrderMonth"]
    passed = check("query returned multiple months", len(df) > 1, f"{len(df)} months")
    passed &= check(
        "is_datetime_column identifies the object-dtype date column",
        is_datetime_column(date_col),
        f"dtype={date_col.dtype}, first={type(date_col.iloc[0]).__name__}",
    )
    chart_type = detect_chart_type(df)
    passed &= check("detect_chart_type returns 'line'", chart_type == "line", chart_type)

    # The renderer sorts internally; prove the x-axis it drew is chronological
    # even if the rows had arrived unsorted.
    shuffled = df.sample(frac=1.0, random_state=1).reset_index(drop=True)
    figure = render_chart(shuffled, "line")
    ax = figure.axes[0]
    xs = [t for t in ax.lines[0].get_xdata()]
    passed &= check("x-axis is sorted chronologically", list(xs) == sorted(xs))

    CHART_DIR.mkdir(exist_ok=True)
    for theme in ("light", "dark"):
        fig = render_chart(df, "line", theme=theme)
        path = CHART_DIR / f"{slugify(database)}__line_real__{theme}.png"
        fig.savefig(path, facecolor=fig.get_facecolor(), bbox_inches="tight")
        passed &= check(f"line chart rendered ({theme})", path.exists(), path.name)

    # Month names cannot be a time axis; a readable bar is the graceful fallback.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        names = pd.read_sql(_MONTHNAME_SQL, conn)
    if not names.empty:
        name_type = detect_chart_type(names)
        passed &= check(
            "month-name buckets fall back to a bar, not a broken line",
            name_type == "bar",
            name_type,
        )
        fig = render_chart(names, name_type, theme="dark")
        fig.savefig(CHART_DIR / f"{slugify(database)}__monthname_bar.png",
                    facecolor=fig.get_facecolor(), bbox_inches="tight")

    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", action="append", help="only test this database (repeatable)")
    parser.add_argument("--no-llm", action="store_true", help="skip generation and summaries")
    args = parser.parse_args()

    base = SqlServerConfig(server=SERVER, use_windows_auth=True)
    try:
        # Server level, no database: this is the state the app starts in, before
        # the user has picked anything.
        admin_conn = connect_server(base)
    except pyodbc.Error as exc:
        print(f"Could not connect to {SERVER} as admin: {exc}")
        return 1

    rule("0. Server-level admin connection")
    available = list_databases(admin_conn)
    check("listed databases", bool(available), ", ".join(available))

    plan = [(db, qs) for db, qs in PLAN if not args.db or db in args.db]
    missing = [db for db, _ in plan if db not in available]
    if missing:
        print(f"\n  Not on this server, skipping: {', '.join(missing)}")
        plan = [(db, qs) for db, qs in plan if db not in missing]
    if not plan:
        print("  Nothing to test.")
        return 1

    results = {}
    for database, questions in plan:
        conn, ok = switch_to(admin_conn, base, database)
        results[f"switch to {database}"] = ok
        if conn is None:
            continue
        for question in questions:
            results[f"{database}: {question[:38]}"] = ask(
                conn, database, question, use_llm=not args.no_llm
            )

        # Model-free, so it runs even under --no-llm. Only AdventureWorks has the
        # Sales schema this query needs.
        if database == "AdventureWorks":
            try:
                results[f"{database}: line chart path"] = section_line_chart(conn, database)
            except pyodbc.Error as exc:
                results[f"{database}: line chart path"] = check(
                    "line chart section", False, str(exc).splitlines()[0]
                )

        conn.close()

    admin_conn.close()

    rule("Summary")
    for name, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not args.no_llm:
        print(f"\n  Charts written to {CHART_DIR}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
