"""Phase 1 smoke test: connect -> pick DB -> introspect -> ask -> generate -> run."""

import sys

import pandas as pd

from nl2sql import (
    SqlServerConfig,
    connect_server,
    connect_database,
    list_databases,
    generate_sql,
    get_schema_summary,
    run_query,
)
from nl2sql.llm_client import LLMError
from nl2sql.sql_executor import UnsafeQueryError

SERVER = "localhost"
MODEL = "qwen2.5-coder:7b"


def rule(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def pick_database(names):
    print("\nAvailable databases:")
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name}")
    while True:
        choice = input(f"\nPick a database [1-{len(names)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            return names[int(choice) - 1]
        print("Not a valid choice.")


def main():
    config = SqlServerConfig(server=SERVER, use_windows_auth=True)

    rule(f"1. Connecting to {SERVER} (server level)")
    try:
        server_conn = connect_server(config)
    except Exception as exc:
        print(f"FAILED: {exc}")
        print("\nCheck: is SQL Server running? Is the instance name right?")
        return 1
    print("Connected.")

    rule("2. Listing user databases")
    names = list_databases(server_conn)
    server_conn.close()
    if not names:
        print("No user databases found. Create one, then rerun.")
        return 1
    config.database = pick_database(names)

    rule(f"3. Connecting to {config.database}")
    db_conn = connect_database(config)
    print("Connected.")

    rule("4. Fetching schema")
    schema = get_schema_summary(db_conn)
    print(schema)
    print(f"\n(~{len(schema) // 4} tokens of context)")

    rule("5. Ask a question")
    question = input("Question (blank to quit): ").strip()
    if not question:
        return 0

    rule(f"6. Generating SQL via {MODEL}")
    try:
        sql = generate_sql(question, schema, model=MODEL)
    except LLMError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(sql)

    rule("7. Validating + executing")
    try:
        df = run_query(db_conn, sql)
    except UnsafeQueryError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    except Exception as exc:
        print(f"Execution failed: {exc}")
        print("\nThe model likely hallucinated a column or table. Try rephrasing.")
        return 1

    rule(f"8. Results ({len(df)} rows)")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df.head(50).to_string(index=False) if len(df) else "(no rows)")

    db_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
