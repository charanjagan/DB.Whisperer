"""Phase 4 UI driver: clicks through the real window and screenshots what it drew.

Not a substitute for using the app, but it fails loudly on the things a human
would only notice by accident: a worker that never emits, a signal wired to the
wrong slot, a chart that silently doesn't get added to the layout. It builds the
actual MainWindow, drives the actual widgets, waits on the actual QThreads, and
saves what the window looks like at each step to screenshots/.

    python test_phase4.py            # everything (slow: several LLM calls)
    python test_phase4.py --fast     # skip Full Assistant's two questions
    python test_phase4.py --keep-open

Uses a throwaway config file so it cannot overwrite your real settings.
"""

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QApplication

from nl2sql import AppConfig
from nl2sql.session import SessionError

SERVER = "localhost"
SHOTS = Path(__file__).parent / "screenshots"

ASSISTANT_QUESTIONS = [
    ("AdventureWorks", "How many products are in each product category?"),
    # Genuinely time-series: exercises detect_chart_type's "line" path end to
    # end, which nothing but synthetic data touched before. The prompt now asks
    # for a real DATE bucket, so this comes back as a date column, not split
    # year/month integers that would fall through to a table.
    ("AdventureWorks", "Show total sales by month"),
    ("IBM HR Dataset", "What is the average monthly income by job role?"),
]

# Chart type each question is expected to produce, so the driver fails loudly if
# the line path silently regresses to a table again.
EXPECTED_CHART = {
    "How many products are in each product category?": "bar",
    "Show total sales by month": "line",
    "What is the average monthly income by job role?": "bar",
}

PASTED_SCHEMA = """Table: employees
  id int NOT NULL
  full_name varchar(100) NULL
  department_id int NULL
  monthly_income decimal NULL
  hired_on date NULL

Table: departments
  id int NOT NULL
  name varchar(100) NULL

Foreign Keys:
  employees.department_id -> departments.id"""

GENERATOR_QUESTION = "Show the 5 highest paid employees with their department name"


def rule(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    return ok


def pump(ms=120):
    """Let Qt paint and deliver queued signals."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for_worker(window, timeout=420):
    """Block until the window's current worker finishes, keeping the UI alive.

    A plain QThread.wait() would freeze the event loop and the queued signals
    carrying the result would never be delivered -- so this pumps instead.
    """
    deadline = time.time() + timeout
    while window._worker is not None and window._worker.isRunning():
        pump(100)
        if time.time() > deadline:
            return False
    pump(250)  # let the done signal land and the panel repaint
    return True


def shot(window, name):
    SHOTS.mkdir(exist_ok=True)
    pump(150)
    path = SHOTS / f"{name}.png"
    window.grab().save(str(path))
    print(f"       screenshot: {path.name}")


def connect_session(window, database):
    """What the settings dialog does, without driving the dialog itself."""
    if not window.session.connected:
        window.session.connect(window.config)
    return window.session.select(database)


def _slug(text):
    keep = [c if c.isalnum() else "_" for c in text.lower()]
    return "".join(keep).strip("_")[:36]


def test_assistant(window, database, question):
    rule(f"Full Assistant — {database} — {question!r}")

    grant = connect_session(window, database)
    passed = check("database opened", window.session.ready, grant.describe())
    window._update_status()

    window.assistant_radio.setChecked(True)
    window._mode_changed(0)
    window.question_input.setPlainText(question)
    name = f"assistant_{database.replace(' ', '_')}_{_slug(question)}"

    print(f"  asking: {question!r}")
    window.run()
    passed &= check("Run disabled while working", not window.run_button.isEnabled())
    passed &= check("spinner visible", window.assistant_panel.spinner.isVisible())

    if not wait_for_worker(window):
        return check("finished", False, "timed out")

    panel = window.assistant_panel
    passed &= check("SQL shown", bool(panel.sql_view.toPlainText()),
                    panel.sql_view.toPlainText()[:60].replace("\n", " "))
    passed &= check("chart embedded", panel._canvas is not None,
                    type(panel._canvas).__name__ if panel._canvas else "no canvas")
    passed &= check("summary shown", bool(panel.summary.text()))
    passed &= check("Run re-enabled", window.run_button.isEnabled())

    # The point of the time-series case: confirm it actually drew a line, not a
    # table. The last worker result carries the detected type in the status line.
    expected = EXPECTED_CHART.get(question)
    if expected:
        passed &= check(
            f"chart type is {expected}",
            expected.replace("_", " ") in panel.status.text(),
            panel.status.text(),
        )
    print(f"\n  status:  {panel.status.text()}")
    print(f"  summary: {panel.summary.text()}")

    panel.sql_box.setChecked(True)  # expand it for the screenshot
    shot(window, f"{name}_result")
    return passed


def test_generator_connected(window):
    rule("Query Generator — connected database schema")

    window.generator_radio.setChecked(True)
    window._mode_changed(1)
    window.generator_panel.use_connected.setChecked(True)
    window._fetch_schema()
    if not wait_for_worker(window):
        return check("schema fetched", False, "timed out")

    schema = window.generator_panel.schema_text()
    passed = check("live schema loaded", bool(schema), f"{len(schema):,} chars")

    window.question_input.setPlainText("How many employees are in each department?")
    window.run()
    if not wait_for_worker(window):
        return check("generated", False, "timed out")

    sql = window.generator_panel.sql_output.toPlainText()
    passed &= check("SQL generated", bool(sql))
    passed &= check("Copy enabled", window.generator_panel.copy_button.isEnabled())
    print(f"\n  {sql}")
    shot(window, "generator_connected")
    return passed


def test_generator_dialects(window):
    """The paste path, with no connection involved, across all three dialects."""
    rule("Query Generator — pasted schema, dialect switching")

    window.generator_radio.setChecked(True)
    window._mode_changed(1)
    window.generator_panel.use_manual.setChecked(True)
    window.generator_panel.schema_input.setPlainText(PASTED_SCHEMA)
    window.question_input.setPlainText(GENERATOR_QUESTION)

    # Switching into this mode may have kicked off a live-schema fetch. Letting it
    # finish is the point: a Run landing mid-fetch is exactly the case that used
    # to no-op silently and leave the previous result on screen looking new.
    wait_for_worker(window)
    window.generator_panel.sql_output.clear()

    results = {}
    passed = True
    for dialect, expect, reject in [
        ("sqlserver", "TOP", "LIMIT"),
        ("postgresql", "LIMIT", None),
        ("mysql", "LIMIT", None),
    ]:
        window.config.dialect = dialect
        window._sync_dialect_label()
        window.run()
        if not wait_for_worker(window):
            passed &= check(f"{dialect} generated", False, "timed out")
            continue

        sql = window.generator_panel.sql_output.toPlainText()
        upper = sql.upper()
        results[dialect] = sql
        passed &= check(f"{dialect}: uses {expect}", expect in upper)
        if reject:
            passed &= check(f"{dialect}: avoids {reject}", reject not in upper)
        print(f"\n  --- {dialect} ---\n  " + sql.replace("\n", "\n  ") + "\n")
        shot(window, f"generator_{dialect}")

    passed &= check(
        "dialects produced different SQL",
        len(set(results.values())) > 1,
        f"{len(set(results.values()))} distinct of {len(results)}",
    )
    return passed


def test_history(window, expect_both_modes=True):
    rule("History sidebar")

    count = window.history_list.count()
    passed = check("history recorded", count > 0, f"{count} entries")

    first = window.history_list.item(0)
    modes = {e.mode for e in window.history}
    if expect_both_modes:
        passed &= check("records both modes", len(modes) > 1, ", ".join(sorted(modes)))
    else:
        print(f"  [SKIP] records both modes - only {', '.join(modes)} ran under --fast")

    window.question_input.clear()
    window._history_clicked(first)
    passed &= check(
        "clicking refills the question box",
        window.question_input.toPlainText() == first.data(Qt.UserRole),
    )
    passed &= check(
        "clicking does not auto-run",
        window._worker is None or not window._worker.isRunning(),
    )
    shot(window, "history")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="skip Full Assistant questions")
    parser.add_argument("--keep-open", action="store_true", help="leave the window up at the end")
    args = parser.parse_args()

    app = QApplication(sys.argv)

    from ui import MainWindow

    window = MainWindow()
    # A throwaway config: this test must not clobber real saved settings.
    window.config = AppConfig(server=SERVER, use_windows_auth=True)
    window.session.config = window.config
    window.show()
    pump(200)

    results = {}
    try:
        if not args.fast:
            for database, question in ASSISTANT_QUESTIONS:
                key = f"assistant / {database} / {question[:34]}"
                try:
                    results[key] = test_assistant(window, database, question)
                except SessionError as exc:
                    results[key] = check("connected", False, str(exc))
        else:
            try:
                connect_session(window, ASSISTANT_QUESTIONS[0][0])
            except SessionError as exc:
                print(f"  (no database: {exc})")

        if window.session.ready:
            results["generator / connected schema"] = test_generator_connected(window)
        results["generator / pasted schema + dialects"] = test_generator_dialects(window)
        results["history"] = test_history(window, expect_both_modes=not args.fast)
    finally:
        rule("Summary")
        for name, ok in results.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"\n  Screenshots in {SHOTS}")

    if args.keep_open:
        return app.exec()
    window.close()
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
