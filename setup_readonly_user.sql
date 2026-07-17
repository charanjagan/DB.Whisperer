/*
    setup_readonly_user.sql
    -----------------------
    Creates a SQL login + database user that can do nothing but SELECT.

    This is the real security boundary for DB.Whisperer. validate_select_only()
    in sql_executor.py is a helpful early rejection, but it runs on a string the
    LLM produced; if it is ever wrong, this login is what stops the damage.

    The login is added to db_datareader and nothing else. db_datareader grants
    SELECT on every table in the database and grants no INSERT, UPDATE, DELETE,
    EXECUTE, or DDL. Catalog metadata (INFORMATION_SCHEMA, sys.*) stays visible
    for objects the role can read, so schema introspection still works through
    this account.

    Run as sysadmin (or securityadmin + db_owner on the target database).
    Safe to re-run: every step is guarded by an existence check, and an existing
    login's password is left alone.

    As of Phase 3 you do not have to run this by hand. ensure_readonly_access()
    in nl2sql/db_setup.py does the same thing through the app's admin connection
    for whichever database the user picks, so a new database provisions itself on
    first selection. This script remains the readable reference for what that
    function does, and is still the way to provision a database before the app
    ever connects.
*/

SET NOCOUNT ON;

------------------------------------------------------------------------
-- Script variables. Edit these before running.
------------------------------------------------------------------------
DECLARE @LoginName sysname       = N'nl2sql_reader';
DECLARE @Password  nvarchar(128) = N'Wh1sperer_ReadOnly!2026';
DECLARE @Database  sysname       = N'AdventureWorks';
------------------------------------------------------------------------

DECLARE @sql        nvarchar(max);
DECLARE @inner      nvarchar(max);
DECLARE @execInDb   nvarchar(max);

-- A SQL login cannot authenticate on a Windows-auth-only server. The CREATE
-- would succeed and every later connect would fail with error 18456 state 58,
-- so fail loudly here instead.
IF CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) = 1
BEGIN
    RAISERROR(N'Server is in Windows Authentication mode. Enable Mixed Mode (SQL Server Properties > Security > SQL Server and Windows Authentication mode), restart the service, then re-run.', 16, 1);
    RETURN;
END

IF DB_ID(@Database) IS NULL
BEGIN
    RAISERROR(N'Database "%s" does not exist on this server.', 16, 1, @Database);
    RETURN;
END

------------------------------------------------------------------------
-- 1. Server-level login.
------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = @LoginName)
BEGIN
    -- Doubling the quotes keeps a password containing ' from ending the literal.
    SET @sql =
        N'CREATE LOGIN ' + QUOTENAME(@LoginName) +
        N' WITH PASSWORD = N''' + REPLACE(@Password, N'''', N'''''') + N''',' +
        N' DEFAULT_DATABASE = ' + QUOTENAME(@Database) + N',' +
        N' CHECK_EXPIRATION = OFF, CHECK_POLICY = ON;';

    -- Three-part name runs the batch in master's context regardless of the
    -- database the script was opened against.
    EXEC master.sys.sp_executesql @sql;
    PRINT 'Created login: ' + @LoginName;
END
ELSE
    PRINT 'Login already exists, password left unchanged: ' + @LoginName;

------------------------------------------------------------------------
-- 2. Database user, mapped to that login, in db_datareader only.
------------------------------------------------------------------------
SET @inner = N'
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = @ln AND type IN (''S'', ''U''))
BEGIN
    DECLARE @c nvarchar(max) = N''CREATE USER '' + QUOTENAME(@ln) + N'' FOR LOGIN '' + QUOTENAME(@ln) + N'';'';
    EXEC sys.sp_executesql @c;
    PRINT ''Created user: '' + @ln;
END
ELSE
    PRINT ''User already exists: '' + @ln;

DECLARE @r nvarchar(max) = N''ALTER ROLE db_datareader ADD MEMBER '' + QUOTENAME(@ln) + N'';'';
EXEC sys.sp_executesql @r;
PRINT ''Added to db_datareader: '' + @ln;
';

SET @execInDb = QUOTENAME(@Database) + N'.sys.sp_executesql';
EXEC @execInDb @inner, N'@ln sysname', @ln = @LoginName;

------------------------------------------------------------------------
-- 3. Show what the account ended up with.
------------------------------------------------------------------------
SET @inner = N'
SELECT
    DB_NAME()            AS [database],
    dp.name              AS [user],
    r.name               AS [role]
FROM sys.database_principals AS dp
LEFT JOIN sys.database_role_members AS drm ON drm.member_principal_id = dp.principal_id
LEFT JOIN sys.database_principals   AS r   ON r.principal_id = drm.role_principal_id
WHERE dp.name = @ln;
';
EXEC @execInDb @inner, N'@ln sysname', @ln = @LoginName;

PRINT '';
PRINT 'Done. Expected roles above: db_datareader (and nothing else).';
PRINT 'If db_owner or db_datawriter appears, this account is NOT read-only.';
GO
