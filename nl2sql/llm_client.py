"""Ollama client. Uses urllib so the package stays dependency-light."""

import json
import re
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

import pandas as pd
import pyodbc

from .dialects import DEFAULT_DIALECT, get_dialect
from .sql_executor import UnsafeQueryError, run_query

OLLAMA_URL = "http://localhost:11434/api/generate"

# sqlcoder (Phase 1's model) is defog's Postgres model. It reads a schema well
# but writes Postgres: ILIKE, to_char(), NULLS LAST, none of which SQL Server
# accepts, and no prompt rule reliably suppresses them. It also cannot follow a
# plain instruction, so it answers get_relevant_tables' "list the tables" with a
# SELECT. qwen2.5-coder is multi-dialect and instruction-following, which is
# what this pipeline needs on both counts.
DEFAULT_MODEL = "qwen2.5-coder:7b"

# The dialect rules are injected rather than written in, so Query Generator mode
# can target Postgres or MySQL through this same function. See dialects.py.
_PROMPT_TEMPLATE = """### Task
Generate a {dialect_label} SELECT statement that answers the question below.

### Database Schema
{schema}

### Rules
- Target dialect is {dialect_label}.
{dialect_rules}
- Only use tables and columns that appear in the schema above.
- When the question asks for a value over time (per month, per day, per year), return one real DATE column for that period (for example the first day of each month), not separate year and month number columns. This lets the result be drawn as a time series.
- Output ONLY the SQL statement. No explanation, no markdown, no code fences.

### Question
{question}

### SQL
"""

# Deliberately the same shape as _PROMPT_TEMPLATE, with the failure injected as
# an extra section rather than rephrased as a "fix this query" instruction.
# A completion-style model fine-tuned on one prompt layout (sqlcoder, say) stops
# emitting SQL entirely when handed a differently-shaped instruction, so the
# repair path keeps the layout the generation path already uses.
_REPAIR_TEMPLATE = """### Task
Generate a {dialect_label} SELECT statement that answers the question below.

### Database Schema
{schema}

### Previous Attempt
This query was already tried and {dialect_label} rejected it:
{sql}

The error was:
{error}

Write a different query that avoids that error. Do not repeat the rejected query.

### Rules
- Target dialect is {dialect_label}.
{dialect_rules}
- Only use tables and columns that appear in the schema above.
- Follow the Foreign Keys section when joining; do not invent join columns.
- When the question asks for a value over time (per month, per day, per year), return one real DATE column for that period (for example the first day of each month), not separate year and month number columns.
- Output ONLY the SQL statement. No explanation, no markdown, no code fences.

### Question
{question}

### SQL
"""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")

# The model routinely restates the question as a title before the statement:
# "# of products in each product category SELECT ProductCategory.Name ...".
# The preamble is not valid SQL and made validate_select_only reject an
# otherwise correct query, so the statement is sliced out by keyword.
_SQL_START_RE = re.compile(r"\b(?:SELECT|WITH)\b", re.IGNORECASE)


class LLMError(RuntimeError):
    """Raised when Ollama is unreachable or returns an unusable response."""


class SQLRetryError(RuntimeError):
    """Raised when generate_sql_with_retry exhausts its attempts.

    `attempts` holds the (sql, error) pair for every try, oldest first, so the
    caller can show the user what was tried rather than just the last failure.
    """

    def __init__(self, message: str, attempts: List[Tuple[str, str]]):
        super().__init__(message)
        self.attempts = attempts


def _clean_sql(raw: str) -> str:
    text = raw.strip()

    # Model sometimes wraps the answer in ```sql ... ``` despite instructions.
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    if text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    # Drop a leading label like "SQL:" if the model adds one.
    text = re.sub(r"^(?:sql|answer|query)\s*:\s*", "", text, flags=re.IGNORECASE)

    # Drop any remaining preamble ahead of the statement itself. Matching WITH
    # as well as SELECT matters: slicing a CTE to its first inner SELECT would
    # hand back a broken fragment instead of something the validator can reject
    # cleanly.
    start = _SQL_START_RE.search(text)
    if start:
        text = text[start.start() :]

    return text.rstrip(";").strip()


def complete(
    prompt: str,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 300,
    temperature: float = 0.0,
) -> str:
    """Send a raw prompt to Ollama and return the raw completion text.

    Shared by SQL generation, SQL repair, and table selection.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        # Not a URLError subclass, so it needs its own arm.
        raise LLMError(
            f"Ollama did not respond within {timeout}s. A large schema on a 7B "
            f"model is slow on first call while weights load; retry, or trim the "
            f"schema passed as context."
        ) from exc
    except urllib.error.URLError as exc:
        raise LLMError(
            f"Could not reach Ollama at {url} ({exc}). Is `ollama serve` running?"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LLMError(f"Ollama returned malformed JSON: {exc}") from exc

    if "error" in body:
        raise LLMError(f"Ollama error: {body['error']}")

    return body.get("response", "")


def generate_sql(
    question: str,
    schema_summary: str,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 300,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    """Ask the local model for a SELECT statement. Returns cleaned SQL text.

    `dialect` is a key from dialects.DIALECTS. It defaults to SQL Server, which
    is what the Full Assistant pipeline executes against; Query Generator mode
    passes whatever the user picked in settings.
    """
    target = get_dialect(dialect)
    prompt = _PROMPT_TEMPLATE.format(
        schema=schema_summary,
        question=question,
        dialect_label=target.label,
        dialect_rules=target.rules_block(),
    )
    sql = _clean_sql(complete(prompt, model=model, url=url, timeout=timeout))
    if not sql:
        raise LLMError("Model returned an empty response.")
    return sql


def repair_sql(
    question: str,
    schema_summary: str,
    sql: str,
    error: str,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 300,
    temperature: float = 0.0,
    dialect: str = DEFAULT_DIALECT,
) -> str:
    """Show the model its own broken SQL plus the server's error; get a fix back."""
    target = get_dialect(dialect)
    prompt = _REPAIR_TEMPLATE.format(
        schema=schema_summary,
        question=question,
        sql=sql,
        error=error,
        dialect_label=target.label,
        dialect_rules=target.rules_block(),
    )
    fixed = _clean_sql(
        complete(prompt, model=model, url=url, timeout=timeout, temperature=temperature)
    )
    if not fixed:
        raise LLMError("Model returned an empty response while repairing SQL.")
    return fixed


# Leading "[42S22] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]" and a
# trailing "(SQLExecDirectW)".
_ODBC_PREFIX_RE = re.compile(r"^\s*\[[^\]]*\]")
_ODBC_SUFFIX_RE = re.compile(r"\s*\(SQL\w+\)\s*$")

# pyodbc joins multiple diagnostic records with "; ", each starting with its own
# SQLSTATE. One bad column in a GROUP BY is reported twice — once for the select
# list, once for the grouping — so the records need splitting before cleanup,
# not just trimming off the ends.
_ODBC_RECORD_RE = re.compile(r";\s*(?=\[[0-9A-Za-z]{5}\]\s*\[)")


def _error_text(exc: Exception) -> str:
    """Condense a pyodbc error to the part a model can act on.

    pyodbc wraps the real message in the SQLSTATE, driver name, and ODBC entry
    point, and repeats itself when the server returns more than one diagnostic
    record. The model only needs "Invalid column name 'ProductName'. (207)";
    the rest is prompt budget spent on nothing, and the duplicate halves make
    the model think two different things went wrong.
    """
    if not isinstance(exc, pyodbc.Error) or len(exc.args) < 2:
        return str(exc)

    records = []
    for record in _ODBC_RECORD_RE.split(str(exc.args[1])):
        # Strip one bracket group at a time. A single pass is not enough (there
        # are four) and each strip leaves a space, so the anchor allows leading
        # whitespace rather than testing startswith("[").
        while True:
            shortened = _ODBC_PREFIX_RE.sub("", record, count=1)
            if shortened == record:
                break
            record = shortened

        record = _ODBC_SUFFIX_RE.sub("", record).strip()
        if record and record not in records:
            records.append(record)

    return " ".join(records) if records else str(exc)


def generate_sql_with_retry(
    question: str,
    schema_summary: str,
    conn: pyodbc.Connection,
    max_retries: int = 2,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 300,
    on_attempt: Optional[callable] = None,
    retry_temperature: float = 0.3,
) -> Tuple[str, pd.DataFrame]:
    """Generate SQL, run it, and feed any error back to the model to fix.

    Makes up to `max_retries` + 1 executions: the first generation, then one
    repair per retry. Returns (working_sql, results) on the first attempt that
    executes cleanly, and raises SQLRetryError once the budget is spent.

    `on_attempt(n, sql, error)` is called after each try (error is None on
    success) so a caller can narrate progress without this function printing.

    Errors are fed back verbatim because they are specific enough to act on:
    "Invalid column name 'ProductName'" tells the model exactly what to look up
    in the schema. UnsafeQueryError is fed back the same way — a model that
    wandered into a non-SELECT should be told so, not silently retried.

    Generation stays at temperature 0, but repairs step the temperature up per
    retry. At temperature 0 the model is deterministic, so a repair prompt that
    barely shifts the context reproduces the identical broken query and every
    retry burns 40s to fail the same way. The escalation is what makes a second
    attempt a genuinely different attempt.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0.")

    attempts: List[Tuple[str, str]] = []
    sql = generate_sql(
        question, schema_summary, model=model, url=url, timeout=timeout
    )

    for attempt in range(max_retries + 1):
        try:
            df = run_query(conn, sql)
        except (pyodbc.Error, UnsafeQueryError) as exc:
            error = _error_text(exc)
            attempts.append((sql, error))
            if on_attempt:
                on_attempt(attempt + 1, sql, error)

            if attempt == max_retries:
                break

            # A failed statement can leave the pyodbc connection in a state
            # where the next execute re-raises the old error. Roll back the
            # implicit transaction so the retry starts clean.
            try:
                conn.rollback()
            except pyodbc.Error:
                pass

            sql = repair_sql(
                question,
                schema_summary,
                sql,
                error,
                model=model,
                url=url,
                timeout=timeout,
                temperature=min(retry_temperature * (attempt + 1), 0.8),
            )
        else:
            if on_attempt:
                on_attempt(attempt + 1, sql, None)
            return sql, df

    tried = "\n\n".join(
        f"Attempt {i}:\n  SQL:   {s}\n  Error: {e}"
        for i, (s, e) in enumerate(attempts, 1)
    )
    raise SQLRetryError(
        f"Gave up after {len(attempts)} attempt(s); the model could not produce "
        f"a query that runs.\n\n{tried}",
        attempts,
    )
