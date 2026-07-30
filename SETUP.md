# Setup

This folder is a self-contained build of DB.Whisperer -- Python, the UI
toolkit, and the offline LLM (including its ~4.4GB model file) are all
already inside it. Two things are *not* bundled, because they're system-level
and not something an app folder should install for you:

## 1. SQL Server ODBC Driver

Install "ODBC Driver 17 for SQL Server" or "ODBC Driver 18 for SQL Server"
(either works -- the app's default config uses 17, but 18 can be typed into
the driver field in Settings):

https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

One-time install, a few clicks, no reboot required on most systems.

## 2. A running SQL Server instance

DB.Whisperer connects to a SQL Server that already exists -- it does not
install, configure, or provision one. Before launching:

- SQL Server (Express, Developer, or full edition) is installed and running,
  reachable from this machine (`localhost` if it's local).
- You know the server name and how you're authenticating (Windows auth, or a
  SQL login) -- both are entered in the app's Settings dialog on first run.

If you don't have a SQL Server instance yet, SQL Server Express is free:
https://www.microsoft.com/en-us/sql-server/sql-server-downloads

## Running it

Double-click `DB.Whisperer.exe` in this folder. First launch shows "Loading
model..." for several seconds while the bundled GGUF loads into memory --
this is normal and only happens once per app start, not once per question.

No internet connection is required at any point after installing the ODBC
driver -- the LLM runs fully offline, in-process.
