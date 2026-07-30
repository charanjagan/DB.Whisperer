# DB.Whisperer

Natural-language to SQL assistant. Phases 1-4 built the pipeline (schema
introspection → SQL generation → safe execution → charting → summarisation)
and the PySide6 UI against a local Ollama server. Phase 5 makes the packaged
app run fully offline by swapping the LLM backend for a bundled GGUF model
loaded in-process via `llama-cpp-python` — see `nl2sql/llm_backend.py`.

## LLM backend

Set by the `LLM_BACKEND` env var, or the constant in `nl2sql/app_config.py`:

- `ollama` (default, dev) — talks to a locally running `ollama serve`. Fast
  to iterate with: swap models via `ollama pull`, no multi-GB file to manage.
- `local` (packaged build) — loads `models/*.gguf` in-process. No server, no
  network call, no separate Ollama install on the user's machine.

Both implementations share one interface (`generate(prompt, temperature=0) ->
str`) in `nl2sql/llm_backend.py`, and every call site (`generate_sql`,
`generate_sql_with_retry`, `repair_sql`, `get_relevant_tables`,
`generate_summary`) goes through it via `llm_client.complete()` — the backend
choice is the only thing that changes, not the calling code.

```
LLM_BACKEND=local python main.py
```

## Local model

`LocalGGUFBackend` expects this exact file at `models/qwen2.5-coder-7b-instruct-q4_k_m.gguf`:

- **Model:** Qwen2.5-Coder-7B-Instruct — the model Phases 2-4 actually
  validated against SQL Server, Postgres, and MySQL dialects (sqlcoder, tried
  in Phase 1, wrote Postgres-only SQL and ignored plain-English instructions;
  see the comment on `DEFAULT_MODEL` in `nl2sql/llm_client.py`).
- **Quantization:** Q4_K_M — the same quantization level Ollama's
  `qwen2.5-coder:7b` tag pulls by default, so local-backend output should
  match what Phase 2-4 testing already validated. ~4.7GB, a reasonable
  size/quality tradeoff for bundling.
- **Source:** Hugging Face, `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`, file
  `qwen2.5-coder-7b-instruct-q4_k_m.gguf`.
  https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF
- **To install:** download that file and place it at
  `models/qwen2.5-coder-7b-instruct-q4_k_m.gguf`. Verify the checksum
  published on the Hugging Face file page before shipping it in a build.

`models/*.gguf` is gitignored — the weight file is a build input, not source,
and does not belong in version control.

## Confirming offline inference

`LocalGGUFBackend.generate()` (`nl2sql/llm_backend.py`) calls `llama_cpp.Llama`
directly in-process — there is no HTTP client, no socket, nothing in that path
that could reach the network. This differs from `OllamaBackend`, which is
`urllib` talking to `localhost:11434`.

To confirm this in practice rather than by reading the code: with
`LLM_BACKEND=local`, disconnect the machine from the network (or drop the
process into a firewall profile with no outbound access) after the model has
loaded, then ask a question in Full Assistant or Query Generator mode. SQL
generation and summarisation both complete normally — the only network-using
part of the app at that point is the SQL Server connection itself, which is
local infrastructure, not the LLM call.

## Model loading indicator

`llama_cpp.Llama(...)` loading a ~4.7GB GGUF takes several seconds. Rather
than let that block the first question a user asks (or the window appear
frozen during construction), `MainWindow` triggers a preload on startup when
`LLM_BACKEND=local`, via `ui.workers.ModelLoadWorker`, showing "Loading
model…" and disabling Run until it completes. `LLM_BACKEND=ollama` skips this
— Ollama manages its own model loading server-side.

## Packaging (Phase 6)

```
pyinstaller db_whisperer.spec --noconfirm
```

Produces `dist/DB.Whisperer/` — a onedir build (not `--onefile`: a ~5GB
single exe would have to unpack itself into a temp dir on every launch,
which is pointless for a file this size). `DB.Whisperer.exe`, all Python
deps, and `models/*.gguf` sit as flat siblings in that one folder — that
folder is the whole shareable artifact, zip it and hand it over as-is.

Default `LLM_BACKEND` is `local` (see `nl2sql/app_config.py`) so the
packaged build never expects an Ollama install; override with the env var
for a dev build.

**Total size: ~4.6GB, of which 4.4GB is the bundled GGUF.** Everything else
(Python runtime, PySide6, llama-cpp-python, pyodbc, pandas, matplotlib) adds
up to a few hundred MB.

### Gotchas hit building this

- **`contents_directory` goes on `EXE(...)`, not `COLLECT(...)`.** Passing it
  to `COLLECT` is a silent no-op — the build still succeeds, it just quietly
  keeps PyInstaller 6.x's default `_internal/` subfolder instead of the flat
  layout. Cost us a full rebuild (including a ~4.4GB re-copy of the model)
  to catch, since nothing errors or warns.

- **llama-cpp-python's DLLs are invisible to PyInstaller's dependency
  walker.** `llama.dll` / `ggml*.dll` / `mtmd.dll` (under `llama_cpp/lib/`)
  are loaded at runtime via `ctypes.CDLL`, not imported as a normal Python
  C-extension — so PyInstaller's static analysis never sees them referenced
  and leaves them out unless declared explicitly. Fixed with
  `collect_dynamic_libs("llama_cpp")` in the spec's `binaries`.

- **matplotlib's data files (mpl-data: fonts, `matplotlibrc`, stylelib) are
  not auto-collected** by this matplotlib version — there's no bundled
  PyInstaller hook for it. Missing this fails silently at build time and
  breaks on the *first chart render* at runtime, not at startup, which makes
  it easy to miss in a quick smoke test. Fixed with
  `collect_data_files("matplotlib")`.

- **`vcomp140.dll` (MSVC OpenMP runtime) missing on the build machine**
  blocked `llama_cpp` from loading at all — a system-level gap (not a
  PyInstaller issue, but it blocks the build's own dependencies from even
  importing), fixed by installing the VC++ Redistributable
  (`winget install Microsoft.VCRedist.2015+.x64`). If a rebuild fails with
  `Could not find module '...\llama_cpp\lib\llama.dll' (or one of its
  dependencies)`, check this first — the DLL that's actually missing is a
  dependency of `llama.dll`, not `llama.dll` itself, so the error message is
  misleading.

- **PySide6 plugin paths (`platforms/`, `imageformats/`, etc.) needed no
  manual handling** — PyInstaller's built-in `hook-PySide6.*` hooks and the
  `pyi_rth_pyside6` runtime hook cover this automatically. matplotlib's Qt
  backend (`backend_qtagg`) also got pulled in automatically by
  `hook-matplotlib.backends.py`'s auto-discovery even though this app only
  ever imports the plain `backend_agg` — harmless, just extra size, not
  worth fighting.

- **`pyodbc` needed no manual binaries/hiddenimports** —
  `pyinstaller-hooks-contrib` ships `hook-pyodbc.py` and it just worked.

### Verifying a rebuild

Build-time confirmation: `dist/DB.Whisperer/` has no `_internal/` folder and
`models/qwen2.5-coder-7b-instruct-q4_k_m.gguf` sits next to
`DB.Whisperer.exe`.

Functional confirmation was done headlessly rather than by clicking through
the frozen exe's window (driving a real mouse/keyboard is invasive on a
live desktop and this is a good enough substitute — same code, same DLLs,
same model): a throwaway script built the real `MainWindow` in-process,
called `connect_session(window, "AdventureWorks")` and `window.run()`
directly, and pumped the Qt event loop instead of a human clicking — the
same pattern `test_phase4.py` already uses. That confirmed, against the
real local SQL Server and the real bundled GGUF (no Ollama running):
server connect + read-only role grant, schema introspection, SQL
generation, query execution, chart rendering, and summarisation all
completed correctly in ~67s end to end. Separately, launching the actual
frozen `DB.Whisperer.exe` and inspecting its window via UI Automation
confirmed the exe itself opens and the "Loading model…" indicator clears
without a crash.
