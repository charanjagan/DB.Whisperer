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
╭─ charan@mr.zeus:~/DB.Whisperer ───────────────────────────╮
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
┌──────────────┐       ┌────────────────────────────────────────┐      ┌──────────────┐
│  PySide6 UI  │ ───▶  │          Orchestration Layer          │ ───▶ │  SQL Server  │
│ (native app) │       │                                        │      │  (your data) │
└──────────────┘       │  schema introspection → prompt builder │      └──────────────┘
                       │  → local LLM (qwen2.5-coder, GGUF)     │
                       │  → SQL validator (read-only guard)     │
                       │  → chart + summary generator           │
                       └────────────────────────────────────────┘
                            │                             │
                     Full Assistant                Query Generator
                (executes + visualizes)       (SQL text only, never runs)
```

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
                                 than a cloud/Ollama equivalent.

► qwen2.5-coder over sqlcoder — sqlcoder is Postgres-trained and kept
                                 emitting ILIKE / to_char() against
                                 T-SQL. qwen2.5-coder got the dialect
                                 right from the first try.

► Read-only SQL login         — the actual security boundary. The SQL
                                 validator is defense-in-depth, not a
                                 substitute for real DB permissions.

► Schema filtering            — AdventureWorks' 74 tables would blow
                                 past what a 7B model can reason over
                                 cleanly. Filtering to relevant tables
                                 cut context by ~19x before generation.
```

---

## ⚠️ Known Limitations

```
► CPU-only inference is noticeably slower than a cloud LLM call
► Assumes a SQL Server instance is already installed and running
► First-time setup (creating the read-only login) needs an account
  with admin rights on that SQL Server — automatic on a personal
  machine, may need a DBA on a locked-down corporate instance
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
