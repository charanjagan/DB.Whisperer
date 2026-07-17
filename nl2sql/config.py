"""Connection configuration for SQL Server."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SqlServerConfig:
    """Holds everything needed to build a pyodbc connection string.

    `database` is intentionally optional: the app connects at server level
    first, lists the available databases, and only then scopes to one.
    """

    server: str
    use_windows_auth: bool = True
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    driver: str = "ODBC Driver 17 for SQL Server"
    trust_server_certificate: bool = True

    def to_connection_string(self, include_database: bool = True) -> str:
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
        ]

        if include_database:
            if not self.database:
                raise ValueError(
                    "include_database=True but config.database is not set. "
                    "Pick a database first (see list_databases)."
                )
            parts.append(f"DATABASE={self.database}")

        if self.use_windows_auth:
            parts.append("Trusted_Connection=yes")
        else:
            if not self.username:
                raise ValueError("SQL auth selected but username is not set.")
            parts.append(f"UID={self.username}")
            parts.append(f"PWD={self.password or ''}")

        # Driver 18 defaults to Encrypt=yes and will reject a self-signed
        # local cert without this.
        if self.trust_server_certificate:
            parts.append("TrustServerCertificate=yes")

        return ";".join(parts) + ";"

    def __repr__(self) -> str:  # keep the password out of logs and tracebacks
        auth = "windows" if self.use_windows_auth else f"sql/{self.username}"
        return (
            f"SqlServerConfig(server={self.server!r}, auth={auth}, "
            f"database={self.database!r}, driver={self.driver!r})"
        )
