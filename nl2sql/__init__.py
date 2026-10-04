"""NL2SQL core pipeline for DB.Whisperer."""

from .config import SqlServerConfig
from .dialects import (
    DEFAULT_DIALECT,
    DIALECTS,
    EXECUTABLE_DIALECT,
    Dialect,
    get_dialect,
)
from .db_connection import (
    connect_server,
    connect_database,
    list_databases,
    test_connection,
)
from .db_setup import (
    AccessGrant,
    ReadOnlyLoginError,
    connect_readonly,
    ensure_readonly_access,
    readonly_config,
    select_database,
    verify_readonly,
)
from .schema_introspection import (
    SchemaContext,
    build_schema_context,
    expand_with_join_paths,
    get_relevant_tables,
    get_schema_summary,
    get_schema_summary_for_tables,
    get_table_list,
)
from .llm_client import (
    LLMError,
    SQLRetryError,
    explain_sql,
    generate_sql,
    generate_sql_with_retry,
    repair_sql,
)
from .sql_executor import UnsafeQueryError, validate_select_only, run_query
from .chart_selector import CHART_TYPES, detect_chart_type
from .chart_renderer import ChartError, render_chart
from .summary_generator import SummaryError, generate_summary
from .app_config import AppConfig, config_path, load_config, save_config
from .session import Session, SessionError

# Keep in step with AppVersion in installer/db_whisperer.iss (and the setup
# filenames in installer/SHARE_README.txt) when cutting a release.
__version__ = "1.0.0"

__all__ = [
    "SqlServerConfig",
    "Dialect",
    "DIALECTS",
    "DEFAULT_DIALECT",
    "EXECUTABLE_DIALECT",
    "get_dialect",
    "connect_server",
    "connect_database",
    "list_databases",
    "test_connection",
    "AccessGrant",
    "ReadOnlyLoginError",
    "connect_readonly",
    "ensure_readonly_access",
    "readonly_config",
    "select_database",
    "verify_readonly",
    "SchemaContext",
    "build_schema_context",
    "expand_with_join_paths",
    "get_relevant_tables",
    "get_schema_summary",
    "get_schema_summary_for_tables",
    "get_table_list",
    "LLMError",
    "SQLRetryError",
    "explain_sql",
    "generate_sql",
    "generate_sql_with_retry",
    "repair_sql",
    "UnsafeQueryError",
    "validate_select_only",
    "run_query",
    "CHART_TYPES",
    "detect_chart_type",
    "ChartError",
    "render_chart",
    "SummaryError",
    "generate_summary",
    "AppConfig",
    "config_path",
    "load_config",
    "save_config",
    "Session",
    "SessionError",
]
