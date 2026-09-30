# -*- mode: python ; coding: utf-8 -*-
import re
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
root = spec_dir.parent

datas = [
    (str(root / "VERSION"), "."),
    (str(root / "assets"), "assets"),
]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "keyring.backends.Windows",
        "keyring.backends.null",
        "PySide6.QtSvg",
        "pyqtgraph",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "scipy", "llvmlite", "numba", "matplotlib", "pandas", "tkinter", "IPython", "pytest",
    ],
    noarchive=False,
)

# Qt6Core 依赖的是 Windows 自带的 icuuc.dll（无版本号导出）。PyInstaller 会顺着 PATH 把别的软件
# （如 poppler）带版本号的 ICU 打进来，盖住系统版本，导致 "DLL load failed while importing QtCore"。
_SYSTEM_DLLS = re.compile(r"^icu\w*\.dll$", re.IGNORECASE)
a.binaries = [b for b in a.binaries if not _SYSTEM_DLLS.match(Path(b[0]).name)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RdpOptimizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(root / "assets" / "icon.ico") if (root / "assets" / "icon.ico").exists() else None,
    manifest=str(root / "app.manifest"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="RdpOptimizer",
)
