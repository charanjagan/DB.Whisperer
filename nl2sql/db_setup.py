"""Read-only login plumbing.

Phase 1 ran every generated query through the admin/Windows-auth connection.
That account can DROP TABLE, so `validate_select_only` was the only thing
standing between a hallucinated statement and the data. Phase 2 splits the two
connections:

  * queries        -> the db_datareader-only SQL login created by
                      setup_readonly_user.sql. This is the security boundary.
  * introspection  -> may keep using the fuller account, since reading
                      INFORMATION_SCHEMA on an unfamiliar server sometimes needs
                      more than db_datareader has.

In practice db_datareader can see the catalog for everything it can SELECT, so
the read-only login is usually enough for both. `readonly_config` therefore
derives from an existing admin config rather than replacing it.

Phase 3 adds `ensure_readonly_access`, which does what setup_readonly_user.sql
does but for whichever database the user just picked, through the admin
connection the app already holds. The .sql script is still the reference and is
useful to read; it is no longer something a user has to open SSMS and run.
"""

import os
from typing import List, NamedTuple, Optional, Tuple

import pyodbc

from .config import SqlServerConfig

# Must match the @LoginName / @Password variables in setup_readonly_user.sql.
DEFAULT_READONLY_LOGIN = "nl2sql_reader"
DEFAULT_READONLY_PASSWORD = "Wh1sperer_ReadOnly!2026"

# Env vars win, so a real deployment never has to keep the password in source.
READONLY_LOGIN_ENV = "NL2SQL_READONLY_LOGIN"
READONLY_PASSWORD_ENV = "NL2SQL_READONLY_PASSWORD"

_ROLE_PROBE = """
SELECT
    CAST(IS_ROLEMEMBER('db_datareader') AS int) AS is_datareader,
    CAST(IS_ROLEMEMBER('db_datawriter') AS int) AS is_datawriter,
    CAST(IS_ROLEMEMBER('db_owner')      AS int) AS is_owner,
    CAST(IS_SRVROLEMEMBER('sysadmin')   AS int) AS is_sysadmin,
    CAST(HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL') AS int) AS has_control,
    SUSER_NAME() AS login_name;
"""


# Mirrors setup_readonly_user.sql, with @Database supplied per call instead of
# edited by hand. Every step is guarded by an existence check, so re-running it
# on an already-provisioned database changes nothing and reports granted = 0.
#
# The database name cannot be a parameter (it is an identifier, not a value), so
# it arrives as a parameter *here* and is only ever concatenated after passing
# through QUOTENAME on the server. That keeps a name like `IBM HR Dataset` — or
# one containing a `]` — from breaking out of the identifier.
_ENSURE_ACCESS_SQL = """
SET NOCOUNT ON;

DECLARE @db sysname = ?, @ln sysname = ?, @pw nvarchar(128) = ?;

-- A SQL login cannot authenticate on a Windows-auth-only server: the CREATE
-- would succeed and every later connect would fail with 18456 state 58.
IF CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) = 1
BEGIN
    RAISERROR(N'Server is in Windows Authentication mode. Enable Mixed Mode (SQL Server Properties > Security > SQL Server and Windows Authentication mode), restart the service, then retry.', 16, 1);
    RETURN;
END

IF DB_ID(@db) IS NULL
BEGIN
    RAISERROR(N'Database "%s" does not exist on this server.', 16, 1, @db);
    RETURN;
END

DECLARE @created_login bit = 0;
DECLARE @granted bit = 0;
DECLARE @sql nvarchar(max);

------------------------------------------------------------------------
-- 1. Server-level login. Password of an existing login is left alone.
------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @ln)
BEGIN
    -- Doubling the quotes keeps a password containing ' from ending the literal.
    SET @sql =
        N'CREATE LOGIN ' + QUOTENAME(@ln) +
        N' WITH PASSWORD = N''' + REPLACE(@pw, N'''', N'''''') + N''',' +
        N' CHECK_EXPIRATION = OFF, CHECK_POLICY = ON;';
    EXEC master.sys.sp_executesql @sql;
    SET @created_login = 1;
END

------------------------------------------------------------------------
-- 2. Is it already db_datareader on this database? Then there is nothing
--    to do -- this is the path every switch back to a known database takes.
------------------------------------------------------------------------
DECLARE @execInDb nvarchar(max) = QUOTENAME(@db) + N'.sys.sp_executesql';
DECLARE @isMember int;

-- NULL when the login has no user in this database at all.
SET @sql = N'SET @out = CAST(IS_ROLEMEMBER(''db_datareader'', @ln) AS int);';
EXEC @execInDb @sql, N'@ln sysname, @out int OUTPUT', @ln = @ln, @out = @isMember OUTPUT;

IF @isMember IS NULL OR @isMember = 0
BEGIN
    SET @sql = N'
    IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @ln AND type IN (''S'', ''U''))
    BEGIN
        DECLARE @c nvarchar(max) = N''CREATE USER '' + QUOTENAME(@ln) + N'' FOR LOGIN '' + QUOTENAME(@ln) + N'';'';
        EXEC sys.sp_executesql @c;
    END
    DECLARE @r nvarchar(max) = N''ALTER ROLE db_datareader ADD MEMBER '' + QUOTENAME(@ln) + N'';'';
    EXEC sys.sp_executesql @r;';
    EXEC @execInDb @sql, N'@ln sysname', @ln = @ln;
    SET @granted = 1;
END

SELECT
    CAST(@created_login AS int) AS created_login,
    CAST(@granted AS int)       AS granted;
"""


class ReadOnlyLoginError(RuntimeError):
    """Raised when the read-only login is missing, wrong, or not read-only."""


class AccessGrant(NamedTuple):
    """What `ensure_readonly_access` had to do, if anything.

    `changed` is false on the common path — the database was already provisioned
    — which is what makes it safe to call on every single database switch.
    """

    database: str
    login_name: str
    created_login: bool
    granted_role: bool

    @property
    def changed(self) -> bool:
        return self.created_login or self.granted_role

    def describe(self) -> str:
        if not self.changed:
            return f"'{self.login_name}' already had db_datareader on {self.database}."
        did = []
        if self.created_login:
            did.append("created the login")
        if self.granted_role:
            did.append(f"granted db_datareader on {self.database}")
        return f"'{self.login_name}': " + " and ".join(did) + "."


def resolve_login(username: Optional[str] = None) -> str:
    """Explicit argument, then NL2SQL_READONLY_LOGIN, then the baked-in default.

    Provisioning and connecting must agree on the name, so both go through here:
    otherwise setting the env var would grant db_datareader to one login and
    connect as another.
    """
    return username or os.environ.get(READONLY_LOGIN_ENV) or DEFAULT_READONLY_LOGIN


def resolve_password(password: Optional[str] = None) -> str:
    """Explicit argument, then NL2SQL_READONLY_PASSWORD, then the default."""
    return (
        password
        or os.environ.get(READONLY_PASSWORD_ENV)
        or DEFAULT_READONLY_PASSWORD
    )


def readonly_config(
    base: SqlServerConfig,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
) -> SqlServerConfig:
    """Copy `base`'s server/driver settings but swap in SQL auth as the reader.

    `base` is normally the admin/Windows-auth config the app already connected
    with. Credentials fall back to the NL2SQL_READONLY_* env vars, then to the
    defaults baked into setup_readonly_user.sql.
    """
    resolved_db = database or base.database
    if not resolved_db:
        raise ValueError(
            "A read-only connection must be scoped to a database, but neither "
            "`database` nor base.database is set."
        )

    return SqlServerConfig(
        server=base.server,
        use_windows_auth=False,
        username=resolve_login(username),
        password=resolve_password(password),
        database=resolved_db,
        driver=base.driver,
        trust_server_certificate=base.trust_server_certificate,
    )


def connect_readonly(
    base: SqlServerConfig,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    timeout: int = 5,
) -> pyodbc.Connection:
    """Connect as the read-only login. Raises ReadOnlyLoginError with a hint."""
    config = readonly_config(base, username, password, database)
    try:
        return pyodbc.connect(
            config.to_connection_string(include_database=True), timeout=timeout
        )
    except pyodbc.Error as exc:
        message = str(exc)
        if "18456" in message:
            raise ReadOnlyLoginError(
                f"Login failed for '{config.username}'. Run setup_readonly_user.sql "
                f"first, and check the password matches "
                f"({READONLY_PASSWORD_ENV} overrides the default). If the state is "
                f"58, the server is in Windows-auth-only mode and needs Mixed Mode."
            ) from exc
        raise ReadOnlyLoginError(
            f"Could not connect as '{config.username}': {exc}"
        ) from exc


def verify_readonly(conn: pyodbc.Connection) -> Tuple[bool, str]:
    """Confirm this connection really is read-only. Returns (ok, message).

    Checks role membership rather than attempting a write, because a write that
    *succeeds* against a misconfigured account is exactly the outcome worth
    avoiding.
    """
    cursor = conn.cursor()
    cursor.execute(_ROLE_PROBE)
    row = cursor.fetchone()

    problems: List[str] = []
    if row.is_sysadmin:
        problems.append("member of sysadmin")
    if row.is_owner:
        problems.append("member of db_owner")
    if row.is_datawriter:
        problems.append("member of db_datawriter")
    if row.has_control:
        problems.append("has CONTROL on the database")
    if not row.is_datareader and not problems:
        problems.append("not a member of db_datareader, so it cannot read anything")

    if problems:
        return False, f"'{row.login_name}' is NOT read-only: " + "; ".join(problems)
    return True, f"'{row.login_name}' is db_datareader only. Writes will be refused."


def ensure_readonly_access(
    admin_conn: pyodbc.Connection,
    database_name: str,
    login_name: Optional[str] = None,
    password: Optional[str] = None,
) -> AccessGrant:
    """Make sure the read-only login can SELECT on `database_name`. Idempotent.

    Runs setup_readonly_user.sql's logic through `admin_conn` — which must be the
    admin/Windows-auth connection, since creating a login and altering a role are
    exactly the things the read-only login cannot do — scoped to whichever
    database was just picked instead of one edited into the script by hand.

    Doing nothing is the normal outcome: if the login is already db_datareader
    there, this is a single round-trip and returns changed = False. That is what
    lets the database picker call it unconditionally on every switch.

    Only db_datareader is ever granted, so a database provisioned this way is
    exactly as read-only as one provisioned by the script. Raises
    ReadOnlyLoginError if the server refuses (Windows-auth-only server, missing
    database, or an admin connection without the rights to grant).
    """
    login = resolve_login(login_name)

    cursor = admin_conn.cursor()
    try:
        cursor.execute(
            _ENSURE_ACCESS_SQL, database_name, login, resolve_password(password)
        )
        row = cursor.fetchone()
    except pyodbc.Error as exc:
        # RAISERROR from the guards above lands here, as does a permission
        # failure when admin_conn turns out not to be an admin after all.
        detail = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
        raise ReadOnlyLoginError(
            f"Could not provision read-only access to '{database_name}' for "
            f"'{login}': {detail}"
        ) from exc

    if row is None:
        # A guard fired RETURN without raising, which should not happen; treat
        # it as a failure rather than reporting success we did not verify.
        raise ReadOnlyLoginError(
            f"Provisioning '{database_name}' for '{login}' returned no status."
        )

    admin_conn.commit()
    return AccessGrant(
        database=database_name,
        login_name=login,
        created_login=bool(row.created_login),
        granted_role=bool(row.granted),
    )


def select_database(
    admin_conn: pyodbc.Connection,
    base: SqlServerConfig,
    database_name: str,
    login_name: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 5,
) -> Tuple[pyodbc.Connection, AccessGrant]:
    """Switch to `database_name`: provision access if needed, then connect as reader.

    This is the entry point the database picker should call with whatever
    `list_databases(admin_conn)` returned. It keeps the two connections in their
    proper roles: the admin connection grants, and the connection handed back —
    the one every generated query will run on — is the db_datareader login and
    can do nothing else.

    The caller owns the returned connection and should close the previous one.
    """
    grant = ensure_readonly_access(admin_conn, database_name, login_name, password)
    conn = connect_readonly(
        base, username=login_name, password=password, database=database_name, timeout=timeout
    )
    return conn, grant
