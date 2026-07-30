# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Phase 6 packaged build.

    pyinstaller db_whisperer.spec

Produces a single onedir folder (dist/DB.Whisperer/) containing the exe, all
Python deps, and the bundled GGUF model as a sibling asset -- this is the
folder that gets zipped and shared, not a single exe.

Two things here are not optional and are easy to lose on a rebuild:

1. `collect_dynamic_libs("llama_cpp")` -- llama_cpp's inference engine
   (llama.dll, ggml*.dll, mtmd.dll under llama_cpp/lib/) is loaded at runtime
   via ctypes.CDLL, not imported as a normal Python C-extension. PyInstaller's
   dependency walker only follows binaries reachable from an `import`-style
   extension module, so these DLLs are invisible to it and silently missing
   from the build unless declared explicitly here.

2. `collect_data_files("matplotlib")` -- mpl-data (matplotlibrc, the default
   font, stylelib) is package data, not code, and this matplotlib version
   ships no bundled PyInstaller hook to pull it in automatically. Without it
   the packaged app fails on the first chart render, not at startup, which
   makes it an easy gotcha to miss during a quick smoke test.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

project_root = Path(SPECPATH)

datas = []
binaries = []
hiddenimports = []

datas += collect_data_files("matplotlib")
binaries += collect_dynamic_libs("llama_cpp")
hiddenimports += collect_submodules("llama_cpp")

# The bundled model weight is a data file, not code -- collected as a
# top-level `models/` folder so it lands as a sibling of the exe (see
# contents_directory="." on COLLECT below), not nested inside a
# `nl2sql/models/` path or an internal-only directory.
model_file = project_root / "models" / "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
if not model_file.exists():
    raise SystemExit(
        f"Model file not found at {model_file}. See README.md's 'Local model' "
        f"section for how to obtain it before building."
    )
datas += [(str(model_file), "models")]

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DB.Whisperer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Pre-6.0 flat layout: exe, DLLs, and models/ all sit directly in
    # dist/DB.Whisperer/ instead of nested under a dist/DB.Whisperer/_internal/
    # subfolder. Requested explicitly so the model file reads as "a separate
    # asset alongside the exe", not buried in an internal-only directory a
    # friend receiving this folder would not think to look in. Belongs on
    # EXE, not COLLECT -- passing it to COLLECT is a silent no-op that leaves
    # the default _internal/ layout in place.
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DB.Whisperer",
)
