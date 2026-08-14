========================================
 DB.Whisperer  -  Setup Guide
========================================

Ask your SQL Server database questions in plain English.
It writes the SQL, runs it, draws a chart, and explains the answer.

Everything runs on your own computer. Nothing is sent to the internet.


----------------------------------------
 WHAT'S IN THIS FOLDER
----------------------------------------

  DB.Whisperer-1.0.0-setup.exe     <-- double-click this one to install
  DB.Whisperer-1.0.0-setup-1.bin   <-- leave this alone, setup needs it
  README.txt                       <-- this file

IMPORTANT: Keep both files together in the same folder.
The setup file is small (2 MB) and the .bin file is large (4.4 GB).
Setup will not work if you move or delete the .bin file.


----------------------------------------
 BEFORE YOU START
----------------------------------------

You need:

  1. Windows 10 or 11, 64-bit
  2. About 5 GB of free disk space
  3. Administrator rights on your PC (to install)
  4. SQL Server already installed and running
  5. The SQL Server ODBC driver (see Step 1 below)

You do NOT need:

  - Python
  - Ollama
  - An internet connection (after installing)
  - An API key, an account, or a subscription

The AI model is already inside the installer. That's why it's 4.4 GB.


----------------------------------------
 STEP 1  -  Install the ODBC driver
----------------------------------------

This is what lets the app talk to SQL Server. Without it, the app opens
but cannot connect to anything.

  a) Go to:
     https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server

  b) Download "ODBC Driver 18 for SQL Server" (64-bit)

  c) Run it, click Next through the wizard, done.

Takes about a minute. No restart needed.

(Already have Driver 17 or 18? Skip this step.)


----------------------------------------
 STEP 2  -  Install DB.Whisperer
----------------------------------------

  a) Unzip this folder somewhere first, if you haven't.
     Do NOT run setup from inside the zip preview window.

  b) Double-click:  DB.Whisperer-1.0.0-setup.exe

  c) Windows will ask "Do you want to allow this app to make changes?"
     Click Yes.

  d) Click through the wizard: Next, accept the licence, Next, Install.

  e) Optional: tick "Create a desktop shortcut" if you want one.

Installing takes 2-4 minutes because of the 4.4 GB model file.
Be patient at the "Extracting files" step. It is not frozen.


----------------------------------------
 STEP 3  -  First launch
----------------------------------------

  a) Open DB.Whisperer from the Start Menu (or the desktop shortcut).

  b) It will say "Loading model..." for 10-30 seconds.
     This happens every time you open the app. It's normal.

  c) Click the Settings button (top right).

  d) Fill in:
       Server:          localhost
                        (or your server name, e.g. MYPC\SQLEXPRESS)
       Authentication:  Windows Authentication
                        (or SQL login + password if that's how you connect)

  e) Click Connect.

  f) Pick your database from the dropdown list.

  g) Click OK.

NOTE: The first time you pick a database, the app creates a read-only
login for itself. Your Windows account needs permission to do that on
that SQL Server. On your own PC this just works. On a company server
you may need your DBA to do it.


----------------------------------------
 STEP 4  -  Ask a question
----------------------------------------

Type a question in plain English and click Run. For example:

    How many customers are there?
    What are the top 10 products by sales?
    Show me monthly revenue for last year

You'll get a chart, a one-line summary, and the SQL it wrote
(click "Generated SQL" to see it).

Answers take about 1-2 minutes. The AI runs on your CPU, not
in the cloud, so it's slower but completely private.

Tick "Explain query" before clicking Run if you also want it to
explain why it wrote the query that way. This makes it slower.


----------------------------------------
 THE TWO MODES
----------------------------------------

Full Assistant    Writes SQL, runs it, and shows you the answer
                  with a chart. This is the main mode.

Query Generator   Only writes the SQL and shows it to you.
                  Never runs anything. You can pick SQL Server,
                  PostgreSQL, or MySQL syntax.


----------------------------------------
 IS MY DATA SAFE?
----------------------------------------

Yes.

  - The AI runs on your computer. Your data never leaves it.
  - The app can only READ your database. It creates a read-only
    login for itself and uses that for every query, so it cannot
    delete, change, or add anything even if it wanted to.
  - Your password is never saved to disk.


----------------------------------------
 IF SOMETHING GOES WRONG
----------------------------------------

"Setup files are corrupted / missing"
   The .bin file isn't next to the setup .exe. Unzip everything
   again into one folder and try again.

"Could not connect" / driver error
   The ODBC driver isn't installed. Do Step 1.

"Login failed for user..."
   Wrong server name or wrong authentication type. Check Step 3d.

App opens but Run does nothing
   Still loading the model. Wait for "Loading model..." to disappear.

Answers are slow
   Normal. It's a 7-billion-parameter AI model running on your CPU.
   1-2 minutes per question is expected.


----------------------------------------
 UNINSTALLING
----------------------------------------

Windows Settings > Apps > DB.Whisperer > Uninstall

Or use the "Uninstall DB.Whisperer" shortcut in the Start Menu folder.
