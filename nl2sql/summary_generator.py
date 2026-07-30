"""Turn a result set back into a sentence.

The user asked a question in English and got a grid of numbers. This closes the
loop: the same local model that wrote the SQL reads the answer back.

The result is capped at MAX_SUMMARY_ROWS before it goes into the prompt. A
question like "list every order" returns tens of thousands of rows, which would
blow the context window, take minutes on a 7B model, and buy nothing — the shape
of the answer is visible in the first twenty rows and the row count, and the row
count is stated separately so the model can still say "of 31,465 orders" without
having seen them.

`complete()` (imported below) already routes through llm_backend.get_backend(),
so this module needs no direct backend awareness to work under both
LLM_BACKEND=ollama and LLM_BACKEND=local.
"""

import pandas as pd

from .llm_client import DEFAULT_MODEL, OLLAMA_URL, LLMError, complete

# Enough to show the shape of the result; small enough to stay cheap.
MAX_SUMMARY_ROWS = 20

# Wide results are truncated by column too: a 40-column record dump is unreadable
# to the model for the same reason it is unreadable in the grid.
MAX_SUMMARY_COLUMNS = 8

_SUMMARY_TEMPLATE = """### Task
Summarise what the query result below shows, in plain English.

### Question
{question}

### Result
{result}

### Rules
- 1 to 2 sentences. No preamble, no bullet points, no markdown.
- Describe what the data shows, and quote the specific numbers that matter.
- Only state what is in the result. Do not guess at causes or add advice.
- Do not mention SQL, tables, columns, or that this came from a database.

### Summary
"""


class SummaryError(LLMError):
    """Raised when the model cannot produce a usable summary."""


def format_result_for_prompt(
    df: pd.DataFrame,
    max_rows: int = MAX_SUMMARY_ROWS,
    max_columns: int = MAX_SUMMARY_COLUMNS,
) -> str:
    """Render `df` as compact text, truncated, with a note about what was cut.

    The note matters: without it the model reads twenty rows as the whole answer
    and confidently says "there are 20 customers" when there were nine thousand.
    """
    if df is None or df.empty:
        return "(no rows)"

    shown = df.iloc[:max_rows, :max_columns]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        text = shown.to_string(index=False)

    notes = []
    if len(df) > len(shown):
        notes.append(
            f"showing the first {len(shown)} of {len(df):,} rows"
        )
    if len(df.columns) > len(shown.columns):
        notes.append(
            f"showing {len(shown.columns)} of {len(df.columns)} columns"
        )
    if notes:
        text += "\n\n(" + "; ".join(notes) + ")"
    elif len(df) > 1:
        text += f"\n\n({len(df)} rows in total)"

    return text


def generate_summary(
    question: str,
    df: pd.DataFrame,
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    timeout: int = 300,
    temperature: float = 0.0,
) -> str:
    """Ask the model what `df` says about `question`. Returns 1-2 sentences.

    Raises SummaryError if the model returns nothing. A summary is a nicety, not
    the answer — a caller that would rather show the grid than an error should
    catch LLMError and carry on.
    """
    if df is None or df.empty:
        return "The query ran but returned no rows."

    prompt = _SUMMARY_TEMPLATE.format(
        question=question, result=format_result_for_prompt(df)
    )
    text = complete(
        prompt, model=model, url=url, timeout=timeout, temperature=temperature
    ).strip()

    # The model occasionally opens with the label it was asked not to use.
    for prefix in ("Summary:", "summary:", "Answer:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()

    if not text:
        raise SummaryError("Model returned an empty summary.")
    return text
