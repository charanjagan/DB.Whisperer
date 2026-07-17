"""Background threads for the two pipelines.

Every one of these runs a local 7B model over Ollama, which takes tens of
seconds. On the GUI thread that is not a slow app, it is a hung one: Windows
greys the title bar out and offers to kill it. So each pipeline runs in a
QThread and reports back with signals, and the window only ever touches widgets
on the main thread.

The rule these workers keep to: emit data, not widgets. `AssistantWorker` hands
back a DataFrame and a chart type rather than a Figure, and the window renders it
after — matplotlib's Qt canvas has to be built on the GUI thread, and rendering
is milliseconds anyway. The expensive, slow, thread-worthy parts are the LLM
calls and the query.

pyodbc serialises access to a connection internally, and the window disables Run
while a worker is alive, so the connection handed to a worker is never touched
from two threads at once.
"""

from typing import List, Optional

import pandas as pd
import pyodbc
from PySide6.QtCore import QThread, Signal

from nl2sql import (
    build_schema_context,
    detect_chart_type,
    generate_sql,
    generate_sql_with_retry,
    generate_summary,
)
from nl2sql.dialects import DEFAULT_DIALECT
from nl2sql.llm_client import DEFAULT_MODEL, LLMError, SQLRetryError
from nl2sql.session import Session, SessionError
from nl2sql.sql_executor import UnsafeQueryError


class AssistantResult:
    """What one Full Assistant run produced, for the window to display."""

    def __init__(self, question, sql, df, chart_type, summary, tables, total_tables, seconds):
        self.question = question
        self.sql = sql
        self.df: pd.DataFrame = df
        self.chart_type = chart_type
        self.summary = summary
        self.tables: List[str] = tables
        self.total_tables = total_tables
        self.seconds = seconds


class _BaseWorker(QThread):
    """Common shape: progress text, one result, one failure message.

    Exceptions never escape `run` — a traceback on a worker thread would take the
    whole app down without ever showing the user what went wrong.
    """

    progress = Signal(str)
    failed = Signal(str)

    def _fail(self, message: str) -> None:
        self.failed.emit(message)


class AssistantWorker(_BaseWorker):
    """Phase 1-3 end to end: schema -> SQL -> execute -> chart type -> summary."""

    done = Signal(object)  # AssistantResult

    def __init__(self, session: Session, question: str, model: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self.session = session
        self.question = question
        self.model = model

    def run(self) -> None:
        import time

        started = time.time()
        try:
            conn = self.session.require_query_conn()
        except SessionError as exc:
            return self._fail(str(exc))

        try:
            self.progress.emit("Reading the database schema…")
            context = build_schema_context(conn, self.question, model=self.model)
        except (pyodbc.Error, LLMError) as exc:
            return self._fail(f"Could not read the schema: {exc}")

        if context.filtered:
            self.progress.emit(
                f"Generating SQL… ({len(context.tables)} of {context.total_tables} tables in context)"
            )
        else:
            self.progress.emit(f"Generating SQL… ({context.total_tables} tables in context)")

        def on_attempt(attempt: int, sql: str, error: Optional[str]) -> None:
            if error is not None:
                self.progress.emit(f"Attempt {attempt} failed: {error} — asking for a fix…")

        try:
            sql, df = generate_sql_with_retry(
                self.question,
                context.summary,
                conn,
                max_retries=2,
                model=self.model,
                on_attempt=on_attempt,
            )
        except SQLRetryError as exc:
            # Every attempt is in the message; the user should see what was tried
            # rather than a bare "it failed".
            return self._fail(str(exc))
        except UnsafeQueryError as exc:
            return self._fail(f"The generated query was blocked as unsafe: {exc}")
        except LLMError as exc:
            return self._fail(str(exc))
        except pyodbc.Error as exc:
            return self._fail(f"The query failed: {exc}")

        chart_type = detect_chart_type(df)

        self.progress.emit("Summarising the result…")
        try:
            summary = generate_summary(self.question, df, model=self.model)
        except LLMError as exc:
            # A missing summary is not worth throwing away a correct answer and a
            # chart the user can already read.
            summary = f"(Could not generate a summary: {exc})"

        self.done.emit(
            AssistantResult(
                question=self.question,
                sql=sql,
                df=df,
                chart_type=chart_type,
                summary=summary,
                tables=list(context.tables),
                total_tables=context.total_tables,
                seconds=time.time() - started,
            )
        )


class GeneratorWorker(_BaseWorker):
    """Query Generator: schema text in, SQL text out. Never executes anything.

    Note what is missing: no connection is used to run anything, no validator, no
    DataFrame. The generated SQL is a string this app only ever puts in a
    read-only box, which is what makes the dialect free to be one this app cannot
    even connect to.
    """

    done = Signal(str)  # the generated SQL

    def __init__(self, question: str, schema_text: str, dialect: str = DEFAULT_DIALECT,
                 model: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self.question = question
        self.schema_text = schema_text
        self.dialect = dialect
        self.model = model

    def run(self) -> None:
        self.progress.emit("Generating SQL…")
        try:
            sql = generate_sql(
                self.question, self.schema_text, model=self.model, dialect=self.dialect
            )
        except (LLMError, ValueError) as exc:
            return self._fail(str(exc))
        self.done.emit(sql)


class SchemaFetchWorker(_BaseWorker):
    """Pull the connected database's full schema for Query Generator mode.

    Unfiltered on purpose: this mode has no question-specific filtering step to
    hang it on, and the user asked to see what the database looks like.
    """

    done = Signal(str)

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session

    def run(self) -> None:
        from nl2sql import get_schema_summary

        try:
            conn = self.session.require_query_conn()
        except SessionError as exc:
            return self._fail(str(exc))

        self.progress.emit("Reading the database schema…")
        try:
            self.done.emit(get_schema_summary(conn))
        except pyodbc.Error as exc:
            self._fail(f"Could not read the schema: {exc}")


class ConnectWorker(_BaseWorker):
    """Connect at server level and list databases.

    Off-thread because a wrong server name blocks for the full connect timeout,
    and a settings dialog that freezes while you fix a typo is worse than the typo.
    """

    done = Signal(list)  # database names

    def __init__(self, session: Session, config, parent=None):
        super().__init__(parent)
        self.session = session
        self.config = config

    def run(self) -> None:
        self.progress.emit("Connecting…")
        try:
            self.done.emit(self.session.connect(self.config))
        except SessionError as exc:
            self._fail(str(exc))


class SelectDatabaseWorker(_BaseWorker):
    """Switch database, provisioning read-only access if this one is new."""

    done = Signal(object)  # AccessGrant

    def __init__(self, session: Session, database: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.database = database

    def run(self) -> None:
        self.progress.emit(f"Opening {self.database}…")
        try:
            self.done.emit(self.session.select(self.database))
        except SessionError as exc:
            self._fail(str(exc))
