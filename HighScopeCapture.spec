# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the High Scope Capture desktop app.

Build:
    python tools/make_ico.py        # rebuild icon (only when design changes)
    pyinstaller --noconfirm --clean HighScopeCapture.spec

Output:
    dist/HighScopeCapture/  ← folder mode (faster startup, easier to update)
    dist/HighScopeCapture/HighScopeCapture.exe
"""

from pathlib import Path

ROOT = Path(SPECPATH)

# ---- Data files bundled next to the .exe ----
# Anything Qt / our code reads at runtime that isn't a Python module.
datas = [
    # Default settings — operator can edit via the in-app Settings dialog.
    (str(ROOT / "config" / "settings.example.yaml"), "config"),
]
# Include the live settings.yaml only if it exists (won't on a clean check-out).
if (ROOT / "config" / "settings.yaml").exists():
    datas.append((str(ROOT / "config" / "settings.yaml"), "config"))

# ---- Hidden imports ----
# Modules PyInstaller's static analysis can miss (Qt plugin auto-loaders,
# zeep dynamic imports, watchdog backends).
hiddenimports = [
    "watchdog.observers.read_directory_changes",
    "watchdog.observers.polling",
    "PyQt6.sip",
    "zeep.transports",
    "PIL.Image",
]

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Strip heavy stdlib / matplotlib bits that aren't used to keep size sane.
    excludes=[
        "tkinter", "test", "pydoc",
        # Matplotlib was used only by the deleted trend dialog — drop it
        # entirely to shrink the build.
        "matplotlib",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HighScopeCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # ← no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "build_assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HighScopeCapture",
)
