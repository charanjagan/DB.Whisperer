"""The SQL dialects the generator can write.

Phase 1-3 only ever spoke to SQL Server, so "use TOP, not LIMIT" was hard-coded
into the prompt. Query Generator mode writes SQL for databases this app cannot
connect to, so the dialect became a parameter.

Each dialect is a label plus the handful of rules the model actually gets wrong
when it drifts between them. These are deliberately short: the model knows all
three dialects, it just needs telling which one it is writing today. Every rule
here is one that showed up as a real defect — sqlcoder emitting Postgres LIMIT
against SQL Server is what motivated the whole list.

Only SQL Server is executable (see EXECUTABLE_DIALECT). The other two are
generate-and-copy, because the app has no connection to a Postgres or MySQL
server to run anything against, which is also why Query Generator mode never
executes.
"""

from typing import Dict, List, NamedTuple

# Full Assistant always generates for this one: it is the only dialect the app
# holds a live connection to, so it is the only one it can validate and run.
EXECUTABLE_DIALECT = "sqlserver"

DEFAULT_DIALECT = EXECUTABLE_DIALECT


class Dialect(NamedTuple):
    """One target dialect: how to name it, and what the model gets wrong."""

    key: str
    label: str
    rules: List[str]

    def rules_block(self) -> str:
        """The rules as prompt lines, ready to drop into a template."""
        return "\n".join(f"- {rule}" for rule in self.rules)


DIALECTS: Dict[str, Dialect] = {
    "sqlserver": Dialect(
        key="sqlserver",
        label="Microsoft SQL Server (T-SQL)",
        rules=[
            "Use TOP instead of LIMIT.",
            "Do not use LIMIT or OFFSET; SQL Server does not support them.",
            "Do not use NULLS FIRST or NULLS LAST; SQL Server does not support them.",
            "Quote identifiers with square brackets when they need quoting: [Order Details].",
            "Use GETDATE() for the current time, not NOW().",
        ],
    ),
    "postgresql": Dialect(
        key="postgresql",
        label="PostgreSQL",
        rules=[
            "Use LIMIT instead of TOP.",
            "Quote identifiers with double quotes when they need quoting: \"Order Details\".",
            "Unquoted identifiers fold to lower case, so quote any name that is not all lower case.",
            "Use NOW() or CURRENT_DATE for the current time, not GETDATE().",
            "String concatenation is ||, not +.",
        ],
    ),
    "mysql": Dialect(
        key="mysql",
        label="MySQL",
        rules=[
            "Use LIMIT instead of TOP.",
            "Quote identifiers with backticks when they need quoting: `Order Details`.",
            "Do not use FULL OUTER JOIN or NULLS FIRST / NULLS LAST; MySQL does not support them.",
            "Use NOW() or CURDATE() for the current time, not GETDATE().",
            "Use CONCAT() to join strings, not + or ||.",
        ],
    ),
}


def get_dialect(key: str) -> Dialect:
    """Look up a dialect by key. Raises ValueError on an unknown one.

    Raising rather than defaulting is deliberate: a typo'd key silently falling
    back to T-SQL would hand a Postgres user a query with TOP in it and no
    indication anything went wrong.
    """
    try:
        return DIALECTS[key]
    except KeyError:
        raise ValueError(
            f"Unknown SQL dialect {key!r}. Known dialects: {', '.join(DIALECTS)}."
        ) from None
