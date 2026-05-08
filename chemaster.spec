# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ChemMaster.

Build:  pyinstaller scripts/packaging/chemaster.spec --noconfirm
Output: dist/chemaster (single executable on macOS / Linux; .exe on Windows)

Note: psi4 is intentionally excluded — it ships as a conda-only scientific stack
(BLAS / LAPACK / Fortran binaries) and cannot be bundled into a PyInstaller
single-file exe. Users install psi4 separately via conda; chemaster discovers
it at runtime via PATH.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = []
# kb/skills (Markdown), kb/formulas (.py auto), agent/system_prompt.md, ...
datas += collect_data_files(
    "chemaster",
    includes=["**/*.md", "**/*.yaml", "**/*.yml", "**/*.json", "**/*.txt"],
)

hidden = []
# Make sure all chemaster sub-packages are walked even if not statically imported
hidden += collect_submodules("chemaster")
hidden += [
    "anthropic",
    "mcp",
    "click",
    "rich",
    "pydantic",
    "pint",
    "yaml",
]

# Heavy scientific deps that chemaster-the-glue does not strictly need at
# import-time. They're imported lazily inside specific MCP servers (calc_psi4
# imports psi4; viz imports matplotlib). Excluding them keeps the binary slim.
excludes = [
    "psi4",        # conda-only, must remain external
    "rdkit",       # conda-only stack
    "matplotlib",  # only used in viz; users can install if needed
    "scipy",
    "pandas",
    "ase",         # used in io_ase server (optional)
    "cclib",
]

a = Analysis(
    ["scripts/packaging/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="chemaster",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
