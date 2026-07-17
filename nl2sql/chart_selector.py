"""Pick a chart type from a result set's shape and dtypes.

Rule-based on purpose. The model already ran once to write the SQL; asking it
again "what chart is this?" would add seconds of latency and a failure mode to a
decision that dtypes answer outright. The columns coming back are typed by the
driver, and the question is really only "is there a time axis, one category and
one measure, one number, or none of the above" — four rules, no ambiguity.

The caller can always override: these are the four render paths chart_renderer
knows, and "table" is the safe default whenever the data does not clearly fit one
of the other three.
"""

import datetime as _dt
from typing import List

import pandas as pd

CHART_TYPES = ("line", "bar", "table", "single_value")

# Above this, a bar chart is a picket fence: the labels collide and nobody reads
# the 40th bar. A line chart has no such limit -- that is the point of a line.
MAX_BAR_ROWS = 30

# A result this wide is a record dump, not a measurement of one thing.
MAX_CHART_COLUMNS = 4


def is_datetime_column(series: pd.Series) -> bool:
    """True for real datetimes, including the object-dtype kind pyodbc returns.

    A SQL Server `date` column arrives as a column of `datetime.date` objects,
    which pandas types as `object` — so a dtype check alone misses precisely the
    columns most likely to be a time axis.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype != object:
        return False

    values = series.dropna()
    if values.empty:
        return False
    return all(isinstance(v, (_dt.date, _dt.datetime)) for v in values.head(20))


def numeric_columns(df: pd.DataFrame) -> List[str]:
    # bool is numeric to pandas but plots as a meaningless 0/1 bar.
    return [
        c
        for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])
    ]


def datetime_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if is_datetime_column(df[c])]


def detect_chart_type(df: pd.DataFrame) -> str:
    """Return "line", "bar", "single_value", or "table" for `df`.

    Falls through to "table" whenever nothing else clearly fits, which is the
    honest answer for a result that is really just rows.
    """
    if df is None or df.empty or len(df.columns) == 0:
        return "table"

    numeric = numeric_columns(df)
    datetimes = datetime_columns(df)

    # One row, one column: an aggregate. A chart of a single value is a rectangle
    # with no information in it -- show the number instead.
    if df.shape == (1, 1):
        return "single_value"

    if len(df.columns) > MAX_CHART_COLUMNS or not numeric:
        return "table"

    # A time column and something measured against it. Checked before bar so a
    # month-by-month total plots as a trend rather than as loose categories.
    if datetimes and len(df) > 1:
        return "line"

    # One label column + one measure, few enough rows to read.
    categorical = [c for c in df.columns if c not in numeric and c not in datetimes]
    if len(categorical) == 1 and len(numeric) == 1 and len(df) <= MAX_BAR_ROWS:
        return "bar"

    return "table"
