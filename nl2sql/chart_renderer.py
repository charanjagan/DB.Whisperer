"""Render a result set as a matplotlib Figure.

Nothing here touches pyplot. pyplot keeps a global registry of figures and a GUI
event loop of its own, both of which fight the Qt loop this figure gets embedded
in during Phase 4; a bare `Figure` has neither, and `FigureCanvasQTAgg(fig)` in
the window is all it takes to display. `savefig` still works standalone because
an Agg canvas is attached on the way out, which is what test_phase3.py leans on
to check the charts before there is a window to put them in.

Styling is deliberately quiet: one accent colour, hairline horizontal gridlines,
no top/right spines, no legend for a single series, and labels only where they
say something. The data should be the most prominent thing on the surface.

Both themes are spelled out rather than derived. A dark chart is not a light
chart with the colours flipped: the same blue that reads well on white is muddy
on near-black, so the dark theme steps to a lighter blue chosen against its own
surface. Getting this wrong is not cosmetic — the first embedded chart came out
as a white slab in a dark window with a near-black summary under it that could
not be read at all.
"""

from typing import List, NamedTuple, Tuple

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from .chart_selector import (
    CHART_TYPES,
    datetime_columns,
    numeric_columns,
)


class Theme(NamedTuple):
    """The colours one chart is drawn with. See LIGHT / DARK."""

    surface: str
    accent: str
    ink: str
    muted: str
    grid: str
    baseline: str
    # Only used when a result has several measures against one time axis. Fixed
    # order, never cycled -- past the eighth series a legend is unreadable
    # anyway, and the remainder is dropped rather than recoloured.
    series: Tuple[str, ...]


LIGHT = Theme(
    # Cream/terracotta visual theme (see ui/theme.py's PAGE_BG/CARD_BG/etc for
    # the widget-side palette this matches). Chart sits inside the assistant
    # panel's white card, so its own surface is the card white, not the page
    # cream -- otherwise the chart would show as a mismatched rectangle inside
    # its own frame instead of reading as part of it.
    surface="#FFFFFF",
    accent="#C96442",
    ink="#3A3530",
    muted="#8A8375",
    grid="#E8E1D3",
    baseline="#D9CFC0",
    series=("#C96442", "#D98C6B", "#E0B79E", "#E8CBB8",
            "#B5754F", "#8C6D5A", "#A68A6B", "#6B5B4D"),
)

DARK = Theme(
    surface="#1a1a19",
    accent="#3987e5",
    ink="#ffffff",
    muted="#898781",
    grid="#2c2c2a",
    baseline="#383835",
    series=("#3987e5", "#008300", "#d55181", "#c98500",
            "#199e70", "#d95926", "#9085e9", "#e66767"),
)

THEMES = {"light": LIGHT, "dark": DARK}
DEFAULT_THEME = "light"

DEFAULT_FIGSIZE = (8.0, 4.5)

# Past this, a rotated label is a wall of text; past MAX_LABEL_CHARS it gets an
# ellipsis so the axis stays legible.
LONG_LABEL_CHARS = 8
MAX_LABEL_CHARS = 28

TABLE_MAX_ROWS = 15
TABLE_MAX_COLS = 6


class ChartError(ValueError):
    """Raised when a DataFrame cannot be drawn as the requested chart type."""


def _format_number(value, _pos=None) -> str:
    """Axis ticks with thousands separators; no trailing .0 on whole numbers."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _new_figure(theme: Theme, figsize=DEFAULT_FIGSIZE) -> Figure:
    fig = Figure(figsize=figsize, dpi=100, facecolor=theme.surface)
    FigureCanvasAgg(fig)  # lets the caller savefig() without pyplot
    return fig


def _style_axes(ax, theme: Theme, y_grid: bool = True) -> None:
    ax.set_facecolor(theme.surface)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.baseline)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=theme.muted, labelsize=9, length=0)
    if y_grid:
        ax.grid(axis="y", color=theme.grid, linewidth=0.8)
        ax.set_axisbelow(True)  # gridlines behind the data, not through it
    ax.yaxis.set_major_formatter(FuncFormatter(_format_number))


def _truncate(text: str) -> str:
    text = str(text)
    if len(text) <= MAX_LABEL_CHARS:
        return text
    return text[: MAX_LABEL_CHARS - 1] + "…"


def label_columns(df: pd.DataFrame, numeric: List[str], datetimes: List[str]) -> List[str]:
    return [c for c in df.columns if c not in numeric and c not in datetimes]


def _render_bar(df: pd.DataFrame, theme: Theme) -> Figure:
    numeric = numeric_columns(df)
    datetimes = datetime_columns(df)
    labels = label_columns(df, numeric, datetimes)
    if not numeric:
        raise ChartError("A bar chart needs a numeric column; none of these are.")

    value_col = numeric[0]
    label_col = labels[0] if labels else df.columns[0]
    categories = [_truncate(v) for v in df[label_col]]

    fig = _new_figure(theme)
    ax = fig.add_subplot(111)
    _style_axes(ax, theme)

    ax.bar(range(len(df)), df[value_col], color=theme.accent, width=0.62)
    ax.set_xticks(range(len(df)))

    # Rotate once the names stop fitting side by side. `ha="right"` pins the end
    # of each label under its own bar; without it a rotated label drifts left of
    # the bar it belongs to and reads as the neighbour's.
    longest = max((len(c) for c in categories), default=0)
    if longest > LONG_LABEL_CHARS or len(df) > 8:
        ax.set_xticklabels(categories, rotation=45, ha="right")
    else:
        ax.set_xticklabels(categories)

    ax.set_xlabel(str(label_col), color=theme.muted, fontsize=9, labelpad=8)
    ax.set_ylabel(str(value_col), color=theme.muted, fontsize=9, labelpad=8)
    fig.tight_layout()
    return fig


def _render_line(df: pd.DataFrame, theme: Theme) -> Figure:
    numeric = numeric_columns(df)
    datetimes = datetime_columns(df)
    if not numeric:
        raise ChartError("A line chart needs a numeric column; none of these are.")

    x_col = datetimes[0] if datetimes else df.columns[0]
    # A time axis out of order draws a line that doubles back on itself, and
    # `ORDER BY` is not guaranteed to be what the model wrote.
    plot_df = df.sort_values(x_col) if datetimes else df
    x = pd.to_datetime(plot_df[x_col]) if datetimes else plot_df[x_col]

    fig = _new_figure(theme)
    ax = fig.add_subplot(111)
    _style_axes(ax, theme)

    series = numeric[: len(theme.series)]
    for column, color in zip(series, theme.series):
        ax.plot(x, plot_df[column], color=color, linewidth=2, label=str(column))

    if len(series) > 1:
        legend = ax.legend(frameon=False, fontsize=9, loc="best")
        for text in legend.get_texts():
            text.set_color(theme.ink)
    else:
        # One series needs no legend box; the axis label already names it.
        ax.set_ylabel(str(series[0]), color=theme.muted, fontsize=9, labelpad=8)

    ax.set_xlabel(str(x_col), color=theme.muted, fontsize=9, labelpad=8)
    if datetimes:
        fig.autofmt_xdate(rotation=45, ha="right")
    fig.tight_layout()
    return fig


def _render_single_value(df: pd.DataFrame, theme: Theme) -> Figure:
    if df.empty or len(df.columns) == 0:
        raise ChartError("Cannot render a single value from an empty result.")

    value = df.iloc[0, 0]
    label = str(df.columns[0])
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = _format_number(value)
    else:
        text = str(value)

    fig = _new_figure(theme, figsize=(6.0, 3.0))
    ax = fig.add_subplot(111)
    ax.set_facecolor(theme.surface)
    ax.axis("off")

    # Shrink the number rather than let it run off the surface -- a COUNT and a
    # SUM of money are wildly different lengths and both land here.
    size = 72 if len(text) <= 8 else 52 if len(text) <= 14 else 36
    ax.text(0.5, 0.56, text, ha="center", va="center", fontsize=size,
            color=theme.ink, fontweight="bold", transform=ax.transAxes)

    # A bare number says nothing about what was counted; the column name is the
    # only caption the result set carries.
    if label and not label.startswith("Unnamed"):
        ax.text(0.5, 0.24, label, ha="center", va="center", fontsize=12,
                color=theme.muted, transform=ax.transAxes)

    fig.tight_layout()
    return fig


def _render_table(df: pd.DataFrame, theme: Theme) -> Figure:
    rows = df.head(TABLE_MAX_ROWS)
    columns = list(df.columns[:TABLE_MAX_COLS])
    if df.empty or not columns:
        fig = _new_figure(theme, figsize=(6.0, 2.0))
        ax = fig.add_subplot(111)
        ax.set_facecolor(theme.surface)
        ax.axis("off")
        ax.text(0.5, 0.5, "No rows", ha="center", va="center",
                fontsize=16, color=theme.muted, transform=ax.transAxes)
        return fig

    # Sized to the rows rather than fixed: `loc="upper center"` pins the table to
    # the top, so any surplus height would come out as blank surface underneath.
    height = 0.7 + 0.27 * (len(rows) + 1)
    fig = _new_figure(theme, figsize=(min(2.0 + 1.6 * len(columns), 12.0), height))
    ax = fig.add_subplot(111)
    ax.set_facecolor(theme.surface)
    ax.axis("off")

    cells = [[_truncate(v) for v in row] for row in rows[columns].values]
    table = ax.table(
        cellText=cells or [[""] * len(columns)],
        colLabels=[_truncate(c) for c in columns],
        cellLoc="left",
        loc="upper center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.4)

    for (row_idx, _), cell in table.get_celld().items():
        cell.set_edgecolor(theme.grid)
        cell.set_linewidth(0.6)
        if row_idx == 0:
            cell.set_facecolor(theme.surface)
            cell.set_text_props(color=theme.ink, fontweight="bold")
        else:
            cell.set_facecolor(theme.surface)
            cell.set_text_props(color=theme.ink)

    hidden = []
    if len(df) > len(rows):
        hidden.append(f"{len(df) - len(rows):,} more rows")
    if len(df.columns) > len(columns):
        hidden.append(f"{len(df.columns) - len(columns)} more columns")
    if hidden:
        ax.set_title(
            f"showing {len(rows)} of {len(df):,} rows — " + ", ".join(hidden),
            color=theme.muted, fontsize=9, loc="left", pad=12,
        )

    fig.tight_layout()
    return fig


_RENDERERS = {
    "bar": _render_bar,
    "line": _render_line,
    "single_value": _render_single_value,
    "table": _render_table,
}


def render_chart(df: pd.DataFrame, chart_type: str, theme: str = DEFAULT_THEME) -> Figure:
    """Draw `df` as `chart_type` and return the Figure, undisplayed.

    `chart_type` is one of chart_selector.CHART_TYPES, normally whatever
    `detect_chart_type(df)` returned. Nothing is shown or saved: the caller
    embeds the figure in a Qt canvas, or calls `fig.savefig(path)`.

    `theme` is "light" or "dark" and should match the surface the chart will sit
    on — the window's theme when embedding, not the user's OS setting in the
    abstract. It defaults to light, which is right for a .png saved to a file.
    """
    if chart_type not in _RENDERERS:
        raise ChartError(
            f"Unknown chart type {chart_type!r}. Expected one of {', '.join(CHART_TYPES)}."
        )
    if theme not in THEMES:
        raise ChartError(
            f"Unknown theme {theme!r}. Expected one of {', '.join(THEMES)}."
        )
    return _RENDERERS[chart_type](df, THEMES[theme])
