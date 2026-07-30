<div align="center">

```
██████╗ ██████╗    ██╗    ██╗██╗  ██╗██╗███████╗██████╗ ███████╗██████╗ ███████╗██████╗ 
██╔══██╗██╔══██╗   ██║    ██║██║  ██║██║██╔════╝██╔══██╗██╔════╝██╔══██╗██╔════╝██╔══██╗
██║  ██║██████╔╝   ██║ █╗ ██║███████║██║███████╗██████╔╝█████╗  ██████╔╝█████╗  ██████╔╝
██║  ██║██╔══██╗   ██║███╗██║██╔══██║██║╚════██║██╔═══╝ ██╔══╝  ██╔══██╗██╔══╝  ██╔══██╗
██████╔╝██████╔╝██╗╚███╔███╔╝██║  ██║██║███████║██║     ███████╗██║  ██║███████╗██║  ██║
╚═════╝ ╚═════╝ ╚═╝ ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝╚══════╝╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝

```

</div>

<div align="center">

```
╭─ charan@mr.zeus:~/DB.Whisperer ────────────────────────────╮
│                                                            │
│  $ ./dbwhisperer --info                                    │
│                                                            │
│  ► A native desktop app that turns English into SQL.       │
│  ► Runs fully offline. Your data never leaves your machine.│
│  ► Built with Claude Code, one phase at a time.            │
│                                                            │
│  $ cat status.txt                                          │
│                                                            │
│  ► Core pipeline:      [ ██████████ ] done                 │
│  ► Safety layer:       [ ██████████ ] done                 │
│  ► Visualization:      [ ██████████ ] done                 │
│  ► Native UI:          [ ██████████ ] done                 │
│  ► Offline local LLM:  [ ██████████ ] done                 │
│  ► Packaging:          [ ██████████ ] done                 │
│                                                            │
│  "It's not a hallucinated column, it's a GROUP BY away."   │
│  — me, mid schema-filtering debug session                  │
│                                                            │
╰────────────────────────────────────────────────────────────╯
```

</div>

---

## 🚧 Project Status: Shipped

```
> Full pipeline built, tested against a live SQL Server, and packaged
> into a standalone desktop app. Portfolio-ready.
```

---

## 🔧 What It Does

```
✅ Ask questions about your SQL Server data in plain English
✅ Auto-generates and runs safe, read-only SQL queries
✅ Auto-picks the right chart — line, bar, table, or single value
✅ Plain-English summary alongside every result
✅ Query Generator mode — get raw SQL back, no execution, any dialect
✅ Pick T-SQL, PostgreSQL, or MySQL syntax on the fly
✅ Runs on a local LLM — no API key, no cloud call, no cost
✅ Works fully offline after first launch
✅ Connect to any database on your SQL Server, switch anytime
```

---

## 🧠 How It Works

```
┌──────────────┐     ┌────────────────────────────────────────────────────┐
│  PySide6 UI  │ ──▶ │  schema introspection (filter 74 tables → ~4-12)  │
│ (native app) │     │           │                                        │
└──────────────┘     │           ▼                                        │ 
                     │   local LLM (qwen2.5-coder, GGUF or Ollama)        │
                     │           │                                        │
                     │           ▼                                        │
                     │   generate SQL ── dialect: T-SQL / Postgres / MySQL│
                     └───────────┬─────────────────────┬──────────────────┘
                                 │                     │
                        Full Assistant           Query Generator
                                 │                     │
                                 ▼                     ▼
                   validator (21 unsafe keywords)   shown as text,
                                 │                  never executed
                                 ▼
                   execute on read-only db_datareader login ◀────┐
                                 │                                │
                          (SQL error) ─────── retry, up to 2× ────┘
                                 │
                                 ▼
                   chart + plain-English summary ──▶ back to UI
                                 │
                                 ▼
                          ┌─────────────┐
                          │  SQL Server │◀── separate admin/Windows-auth
                          │ (your data) │    connection lists databases
                          └─────────────┘    and grants the read-only login
```

Both modes share one LLM call end to end — the backend (bundled GGUF vs.
dev-time Ollama) is a single swappable seam behind `llm_client.complete()`,
not duplicated per mode. They diverge right after SQL generation: Full
Assistant validates, executes, charts, and summarises; Query Generator
stops at the generated SQL text, since the app holds no connection to run
PostgreSQL or MySQL against in the first place.

---

## 🛠️ Built With

```
Python · PySide6 · llama-cpp-python · qwen2.5-coder-7b (GGUF)
pyodbc · pandas · matplotlib · SQL Server 2025 · Claude Code
```

---

## ⚙️ Key Decisions & Tradeoffs

```
► Local LLM over cloud API    — free, private, offline. Costs speed:
                                 CPU-only inference runs ~2x slower
                                 than a cloud/Ollama equivalent. No
                                 GPU offload is configured on purpose —
                                 it's the tradeoff that keeps the app
                                 running on any machine, not just one
                                 with a capable GPU.

► qwen2.5-coder over sqlcoder — sqlcoder is Postgres-trained and kept
                                 emitting ILIKE / to_char() against
                                 T-SQL, and answered "which tables are
                                 relevant" with a SELECT instead of a
                                 list. qwen2.5-coder got the dialect
                                 and the instruction-following right.

► Read-only SQL login         — the actual security boundary. A SQL
                                 login scoped to db_datareader and
                                 nothing else runs every generated
                                 query, so a write that slips past the
                                 validator is still refused by SQL
                                 Server itself. The validator (21
                                 blocked keywords: DML/DDL/DCL, EXEC,
                                 OPENROWSET/OPENQUERY, WAITFOR) is
                                 defense-in-depth, not a substitute —
                                 it's a regex pass over a string the
                                 LLM wrote, and any such pass can be
                                 fooled.

► Schema filtering            — AdventureWorks' 74 tables would blow
                                 past what a 7B model can reason over
                                 cleanly. A cheap preliminary LLM call
                                 picks the relevant tables (backstopped
                                 by a lexical name match and a foreign-
                                 key bridge step for joins the question
                                 never names), cutting context to the
                                 ~4 tables a typical question actually
                                 needs — roughly 19x — before the real
                                 generation call.
```

---

## ⚠️ Known Limitations

```
► CPU-only inference is noticeably slower than a cloud LLM call —
  one question (table selection + SQL generation + summary are all
  separate model calls) takes on the order of a minute or two.
► Assumes a SQL Server instance is already installed and running.
  Local/single-machine SQL Server is the tested setup; not exercised
  against a remote or high-availability topology.
► First-time setup (creating the read-only login) needs an account
  with admin rights on that SQL Server — automatic on a personal
  machine, may need a DBA on a locked-down corporate instance.
► The default read-only login password is a fixed value in source
  (nl2sql/db_setup.py, setup_readonly_user.sql), overridable via
  NL2SQL_READONLY_PASSWORD. It only ever grants db_datareader, but
  rotate it via the env var before pointing this at anything real.
► Query Generator's PostgreSQL/MySQL output is generate-and-copy, not
  validated — the app holds no connection to run either against, so
  those dialect rules are prompt-level guidance, not a guarantee.
► Windows-first: built and tested against SQL Server's Windows ODBC
  drivers and a Windows (PyInstaller) packaging pipeline. Linux/macOS
  have not been exercised.
```

---

## 📦 Setup

```
1. Install the SQL Server ODBC Driver (17 or 18)
2. Unzip the packaged app — the local model ships bundled inside
3. Run the app, point it at your SQL Server, pick a database
4. Ask it something
```

See `SETUP.md` for the full walkthrough.

**Running from source instead of the packaged build:**
```
pip install -r requirements.txt

# dev mode — needs `ollama serve` with qwen2.5-coder:7b pulled
python main.py

# offline mode — needs models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
# (see nl2sql/llm_backend.py for the exact filename/source)
LLM_BACKEND=local python main.py
```

---

## 🎬 Demo

```
[ demo gif goes here — launch → ask a question → chart + summary
  appear → switch to Query Generator → flip dialect → copy SQL ]
```

---

<div align="center">

```
repo status: shipped. polish in progress.
last updated: July 2026
```

</div>
