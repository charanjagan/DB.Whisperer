"""Schema extraction for the currently connected database.

Output is deliberately compact: it is spent as LLM context on every question.

On a small database the whole schema fits in the prompt and this stays simple.
On AdventureWorks (74 base tables) it does not: the full summary is tens of
thousands of characters, which makes generation slow and buries the three tables
that actually matter under seventy that do not. `build_schema_context` handles
that by asking the model which tables are relevant first, then sending only
those. See `get_relevant_tables`.
"""

import re
from typing import Dict, Iterable, List, NamedTuple, Sequence, Set

import pyodbc

from .llm_client import DEFAULT_MODEL, LLMError, complete

# Above this many tables, sending the whole schema costs more than the extra
# round-trip to narrow it down. AdventureWorks sits well above; a toy database
# sits well below, and skips filtering entirely.
DEFAULT_TABLE_THRESHOLD = 20

# Enough tables to cover a join path, few enough to stay cheap as context.
DEFAULT_MAX_RELEVANT_TABLES = 8

_COLUMNS_QUERY = """
SELECT
    c.TABLE_SCHEMA,
    c.TABLE_NAME,
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH,
    c.IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS AS c
JOIN INFORMATION_SCHEMA.TABLES AS t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
 AND t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
  {filter}
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION;
"""

_COLUMNS_FILTER = "AND c.TABLE_SCHEMA + '.' + c.TABLE_NAME IN ({placeholders})"

_FOREIGN_KEYS_QUERY = """
SELECT
    ps.name  AS parent_schema,
    pt.name  AS parent_table,
    pc.name  AS parent_column,
    rs.name  AS ref_schema,
    rt.name  AS ref_table,
    rc.name  AS ref_column
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc
  ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables  AS pt ON pt.object_id = fkc.parent_object_id
JOIN sys.schemas AS ps ON ps.schema_id = pt.schema_id
JOIN sys.columns AS pc
  ON pc.object_id = fkc.parent_object_id
 AND pc.column_id = fkc.parent_column_id
JOIN sys.tables  AS rt ON rt.object_id = fkc.referenced_object_id
JOIN sys.schemas AS rs ON rs.schema_id = rt.schema_id
JOIN sys.columns AS rc
  ON rc.object_id = fkc.referenced_object_id
 AND rc.column_id = fkc.referenced_column_id
{filter}
ORDER BY ps.name, pt.name, pc.name;
"""

# Only keys where both ends survived the filter. An FK pointing at a table the
# model cannot see is an invitation to join against something absent from the
# prompt.
_FK_FILTER = """
WHERE ps.name + '.' + pt.name IN ({placeholders})
  AND rs.name + '.' + rt.name IN ({placeholders})
"""

_TABLES_QUERY = """
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_SCHEMA, TABLE_NAME;
"""

_FK_EDGES_QUERY = """
SELECT DISTINCT
    ps.name + '.' + pt.name AS parent_table,
    rs.name + '.' + rt.name AS ref_table
FROM sys.foreign_keys AS fk
JOIN sys.tables  AS pt ON pt.object_id = fk.parent_object_id
JOIN sys.schemas AS ps ON ps.schema_id = pt.schema_id
JOIN sys.tables  AS rt ON rt.object_id = fk.referenced_object_id
JOIN sys.schemas AS rs ON rs.schema_id = rt.schema_id;
"""

_TABLE_SELECT_PROMPT = """### Task
Below is a list of tables in a Microsoft SQL Server database, and a question.
List only the tables needed to answer the question.

### Tables
{tables}

### Rules
- Reply with table names from the list above, one per line.
- Include tables needed for joins, not only the ones named in the question.
- Pick at most {max_tables} tables. Fewer is better.
- No explanation.

### Question
{question}

### Tables needed
"""

_WORD_RE = re.compile(r"[A-Za-z]+")


class SchemaContext(NamedTuple):
    """What `build_schema_context` decided to send to the SQL-generation call."""

    summary: str
    tables: List[str]
    filtered: bool  # True if the LLM narrowed the list; False if it went whole.
    total_tables: int


def _format_type(data_type: str, max_length) -> str:
    if max_length is None:
        return data_type
    length = "max" if max_length == -1 else str(max_length)
    return f"{data_type}({length})"


def _render(column_rows: Sequence, fk_rows: Sequence) -> str:
    lines: List[str] = []
    current_table = None
    for row in column_rows:
        table = f"{row.TABLE_SCHEMA}.{row.TABLE_NAME}"
        if table != current_table:
            if current_table is not None:
                lines.append("")
            lines.append(f"Table: {table}")
            current_table = table
        col_type = _format_type(row.DATA_TYPE, row.CHARACTER_MAXIMUM_LENGTH)
        null_flag = "NULL" if row.IS_NULLABLE == "YES" else "NOT NULL"
        lines.append(f"  {row.COLUMN_NAME} {col_type} {null_flag}")

    if not lines:
        return "(no base tables found in this database)"

    lines.append("")
    lines.append("Foreign Keys:")
    if fk_rows:
        for row in fk_rows:
            lines.append(
                f"  {row.parent_schema}.{row.parent_table}.{row.parent_column}"
                f" -> {row.ref_schema}.{row.ref_table}.{row.ref_column}"
            )
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def get_table_list(conn: pyodbc.Connection) -> List[str]:
    """Return schema-qualified base table names, for a future UI list."""
    cursor = conn.cursor()
    cursor.execute(_TABLES_QUERY)
    return [f"{row.TABLE_SCHEMA}.{row.TABLE_NAME}" for row in cursor.fetchall()]


def get_schema_summary(conn: pyodbc.Connection) -> str:
    """Compact plain-text schema: tables with columns, then a Foreign Keys section."""
    cursor = conn.cursor()
    cursor.execute(_COLUMNS_QUERY.format(filter=""))
    column_rows = cursor.fetchall()
    if not column_rows:
        return "(no base tables found in this database)"
    cursor.execute(_FOREIGN_KEYS_QUERY.format(filter=""))
    return _render(column_rows, cursor.fetchall())


def get_schema_summary_for_tables(
    conn: pyodbc.Connection, table_names: Iterable[str]
) -> str:
    """Same output as get_schema_summary, restricted to `table_names`.

    Names are schema-qualified ("Sales.SalesOrderHeader") and are passed as
    parameters, so a hallucinated name yields no rows rather than injecting SQL.
    """
    names = list(dict.fromkeys(table_names))  # de-dupe, keep order
    if not names:
        return "(no tables selected)"

    cursor = conn.cursor()
    placeholders = ",".join("?" * len(names))

    cursor.execute(
        _COLUMNS_QUERY.format(filter=_COLUMNS_FILTER.format(placeholders=placeholders)),
        names,
    )
    column_rows = cursor.fetchall()
    if not column_rows:
        return f"(none of the selected tables exist: {', '.join(names)})"

    cursor.execute(
        _FOREIGN_KEYS_QUERY.format(filter=_FK_FILTER.format(placeholders=placeholders)),
        names + names,  # the filter references the list twice
    )
    return _render(column_rows, cursor.fetchall())


def _match_tables(response: str, table_list: Sequence[str]) -> List[str]:
    """Pull known table names out of whatever the model replied with.

    Deliberately lenient about format. A chat model returns a bullet list, a
    JSON array, or prose; sqlcoder is fine-tuned to emit SQL and tends to answer
    this prompt with a SELECT. Scanning the response for names we already know
    handles all of those, and cannot invent a table that does not exist.

    Bare names are matched too ("SalesOrderHeader" for "Sales.SalesOrderHeader"),
    since models routinely drop the schema prefix.
    """
    found: List[str] = []
    for qualified in table_list:
        bare = qualified.split(".", 1)[-1]
        if re.search(rf"\b{re.escape(qualified)}\b", response, re.IGNORECASE) or (
            re.search(rf"\b{re.escape(bare)}\b", response, re.IGNORECASE)
        ):
            found.append(qualified)
    return found


def _lexical_matches(question: str, table_list: Sequence[str]) -> List[str]:
    """Tables whose name shares a word with the question.

    A safety net under the model's choice, not a replacement for it. Filtering
    is only worth doing if it cannot drop the one table the question is
    obviously about: asked "how many products are there of each color",
    sqlcoder picked Production.Culture and Production.ProductCategory and left
    out Production.Product, which is strictly worse than not filtering at all.
    Matching "products" to Production.Product costs nothing and prevents that.

    Matching is on the whole table name, not on its individual words. Per-word
    matching looks more thorough and is worse: "products in each product
    category" would then hit Product, ProductModel, ProductReview,
    ProductVendor and every other Product* table, re-inflating the very context
    this module exists to shrink. Whole-name matching adds the subject of the
    question and nothing else.
    """
    words = {w.lower() for w in _WORD_RE.findall(question)}
    words |= {w.rstrip("s") for w in words}  # crude singular/plural

    matches = []
    for table in table_list:
        bare = table.split(".", 1)[-1].lower()
        if bare in words or bare.rstrip("s") in words:
            matches.append(table)
    return matches


def get_relevant_tables(
    question: str,
    table_list: Sequence[str],
    model: str = DEFAULT_MODEL,
    max_tables: int = DEFAULT_MAX_RELEVANT_TABLES,
    timeout: int = 120,
) -> List[str]:
    """Ask the model which of `table_list` the question needs.

    One cheap call: the prompt carries table names only, no columns, so it is a
    fraction of the size of the full schema and returns quickly.

    The model's answer is unioned with a lexical name match rather than trusted
    outright. `model` defaults to the SQL generator, but this is a
    pick-from-a-list task, not a SQL task — a small instruction-following model
    is both cheaper and much better at it, which is why `model` is a parameter.

    Falls back to the full `table_list` whenever the answer is unusable — an
    unfiltered prompt is slow, but a prompt missing the table the question is
    about cannot be answered at all. Degrade toward the Phase 1 behaviour, not
    toward a wrong answer.
    """
    tables = list(table_list)
    if not tables:
        return []

    prompt = _TABLE_SELECT_PROMPT.format(
        tables="\n".join(tables), question=question, max_tables=max_tables
    )

    try:
        response = complete(prompt, model=model, timeout=timeout)
    except LLMError:
        return tables

    picked = _match_tables(response, tables)

    # Union, model's picks first, capped. A lexical match the model missed is
    # usually the subject of the question; one it found is already in the list.
    for table in _lexical_matches(question, tables):
        if table not in picked:
            picked.append(table)

    if not picked:
        return tables

    return picked[:max_tables]


def expand_with_join_paths(
    conn: pyodbc.Connection, table_names: Sequence[str], max_extra: int = 4
) -> List[str]:
    """Add tables that bridge two selected tables via foreign keys.

    The table-selection call answers the question "which tables does this ask
    about", which is not the same as "which tables does the SQL need". Asked to
    count products per category in AdventureWorks, a model picks Product and
    ProductCategory — and those two have no FK between them. The join runs
    through ProductSubcategory, which the question never mentions and the model
    never names. Without this step the generated SQL invents a join key.

    Only tables adjacent to at least *two* selected tables are added, so this
    pulls in connectors rather than everything one hop out.
    """
    selected = list(dict.fromkeys(table_names))
    if len(selected) < 2:
        return selected

    lookup = {t.lower(): t for t in selected}

    cursor = conn.cursor()
    cursor.execute(_FK_EDGES_QUERY)
    edges = [(row.parent_table, row.ref_table) for row in cursor.fetchall()]

    # For each unselected table, which selected tables does an FK connect it to?
    neighbours: Dict[str, Set[str]] = {}
    for parent, ref in edges:
        parent_selected = parent.lower() in lookup
        ref_selected = ref.lower() in lookup
        if parent_selected and not ref_selected:
            neighbours.setdefault(ref, set()).add(parent.lower())
        elif ref_selected and not parent_selected:
            neighbours.setdefault(parent, set()).add(ref.lower())

    bridges = sorted(t for t, linked in neighbours.items() if len(linked) >= 2)
    return selected + bridges[:max_extra]


def build_schema_context(
    conn: pyodbc.Connection,
    question: str,
    model: str = DEFAULT_MODEL,
    table_threshold: int = DEFAULT_TABLE_THRESHOLD,
    max_tables: int = DEFAULT_MAX_RELEVANT_TABLES,
) -> SchemaContext:
    """Assemble the schema text for one question, filtering only if it pays off.

    At or below `table_threshold` tables the whole schema goes through as it did
    in Phase 1 — the filtering round-trip would cost more than it saves. Above
    it, the model picks the relevant tables first and only those are described.
    """
    tables = get_table_list(conn)
    total = len(tables)

    if total <= table_threshold:
        return SchemaContext(get_schema_summary(conn), tables, False, total)

    relevant = get_relevant_tables(
        question, tables, model=model, max_tables=max_tables
    )

    # The fallback path in get_relevant_tables hands back everything; that is
    # not a filtered context, and saying so keeps the caller honest.
    if len(relevant) == total:
        return SchemaContext(get_schema_summary(conn), tables, False, total)

    relevant = expand_with_join_paths(conn, relevant)

    return SchemaContext(
        get_schema_summary_for_tables(conn, relevant), relevant, True, total
    )
