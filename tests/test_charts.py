"""Chart choice from a result's shape, and that every choice actually renders."""

import datetime as dt

import matplotlib

matplotlib.use("Agg")

import pandas as pd
import pytest

from nl2sql.chart_renderer import ChartError, render_chart
from nl2sql.chart_selector import MAX_BAR_ROWS, detect_chart_type

MONTHS = [dt.date(2023, m, 1) for m in range(1, 13)]


@pytest.mark.parametrize(
    "df, expected",
    [
        (pd.DataFrame(), "table"),
        (pd.DataFrame({"n": [42]}), "single_value"),
        (pd.DataFrame({"cat": ["a", "b", "c"], "n": [1, 2, 3]}), "bar"),
        # pyodbc hands SQL Server `date` back as object-dtype datetime.date.
        (pd.DataFrame({"month": MONTHS, "total": range(12)}), "line"),
        (pd.DataFrame({"month": pd.to_datetime(MONTHS), "total": range(12)}), "line"),
        (pd.DataFrame({"cat": [f"c{i}" for i in range(MAX_BAR_ROWS + 1)], "n": range(MAX_BAR_ROWS + 1)}), "table"),
        (pd.DataFrame({"a": ["x"], "b": ["y"]}), "table"),  # nothing numeric
        (pd.DataFrame({f"c{i}": [1, 2] for i in range(5)}), "table"),  # too wide
        (pd.DataFrame({"cat": ["a", "b"], "flag": [True, False]}), "table"),  # bool is not a measure
    ],
)
def test_detect_chart_type(df, expected):
    assert detect_chart_type(df) == expected


@pytest.mark.parametrize(
    "df",
    [
        pd.DataFrame({"n": [42]}),
        pd.DataFrame({"cat": ["a", "b", "c"], "n": [1, 2, 3]}),
        pd.DataFrame({"month": MONTHS, "total": range(12)}),
        pd.DataFrame({f"c{i}": range(15) for i in range(6)}),
    ],
)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_detected_type_renders(df, theme):
    figure = render_chart(df, detect_chart_type(df), theme=theme)
    assert figure.get_axes()


def test_unknown_chart_type_raises():
    with pytest.raises(ChartError):
        render_chart(pd.DataFrame({"n": [1]}), "pie")
