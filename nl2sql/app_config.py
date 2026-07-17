"""Persisted UI settings: server, database, dialect, model.

Lives on disk so the app comes back up pointed at the same server and database
the user left it on. JSON on purpose — a user who needs to fix a bad server name
without launching the app should be able to open the file and read it.

The read-only login's password is deliberately NOT stored here (see
`AppConfig.to_dict`). It already has a home: db_setup resolves it from the
NL2SQL_READONLY_* env vars or its defaults. A SQL-auth *admin* password the user
types in settings is kept for the session only and never written to the file, so
this config is not a credential store and does not need to be protected like one.
"""

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional

from .config import SqlServerConfig
from .dialects import DEFAULT_DIALECT, DIALECTS
from .llm_client import DEFAULT_MODEL

APP_NAME = "DB.Whisperer"
CONFIG_FILENAME = "config.json"


def config_dir() -> Path:
    """Per-user app data directory: %APPDATA% on Windows, ~/.config elsewhere."""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


@dataclass
class AppConfig:
    """Everything the settings panel edits.

    `password` is in the dataclass because the connection needs it in memory, but
    it never reaches the file.
    """

    server: str = "localhost"
    use_windows_auth: bool = True
    username: str = ""
    password: str = field(default="", repr=False)
    database: Optional[str] = None
    dialect: str = DEFAULT_DIALECT
    model: str = DEFAULT_MODEL
    driver: str = "ODBC Driver 17 for SQL Server"

    def to_sql_config(self) -> SqlServerConfig:
        """The admin/Windows-auth connection config the rest of the package takes.

        Deliberately without `database`: the app connects at server level, lists
        what is there, and only then scopes to one via select_database.
        """
        return SqlServerConfig(
            server=self.server,
            use_windows_auth=self.use_windows_auth,
            username=self.username or None,
            password=self.password or None,
            driver=self.driver,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable form. Note the missing password — that is the point."""
        return {
            "server": self.server,
            "use_windows_auth": self.use_windows_auth,
            "username": self.username,
            "database": self.database,
            "dialect": self.dialect,
            "model": self.model,
            "driver": self.driver,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Build from parsed JSON, ignoring junk rather than raising.

        A config file is edited by hand and survives version changes, so an
        unknown key or a dialect that no longer exists must not stop the app
        from starting.
        """
        known = {f for f in cls.__dataclass_fields__ if f != "password"}
        clean = {k: v for k, v in data.items() if k in known and v is not None}

        dialect = clean.get("dialect")
        if dialect not in DIALECTS:
            clean["dialect"] = DEFAULT_DIALECT

        return cls(**clean)


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Read the saved config, or return defaults if there isn't one (or it's broken).

    Never raises: a corrupt config file is a reason to start fresh, not a reason
    the app cannot open.
    """
    target = path or config_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return AppConfig.from_dict(json.load(handle))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return AppConfig()


def save_config(config: AppConfig, path: Optional[Path] = None) -> Path:
    """Write the config, creating the directory if needed. Returns the path."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)
    return target


def with_database(config: AppConfig, database: Optional[str]) -> AppConfig:
    """A copy pointed at a different database."""
    return replace(config, database=database)
