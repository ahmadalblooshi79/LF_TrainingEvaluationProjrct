# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller — حزمة سطح المكتب لنظام إدارة التمارين (بدون Python على الجهاز المستهدف)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH).resolve().parent

hiddenimports = collect_submodules("app")
hiddenimports += [
    "passlib.handlers.bcrypt",
    "bcrypt",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.sql.default_comparator",
    "waitress",
    "openpyxl",
    "pypdf",
    "pypdf._reader",
    "lxml",
    "lxml.etree",
    "psutil",
    "dotenv",
    "jinja2.ext",
    "email.mime.multipart",
    "email.mime.text",
    "ctypes",
    "ctypes.wintypes",
]

datas = [
    (str(project_root / "app" / "templates"), "app/templates"),
    (str(project_root / "app" / "static"), "app/static"),
]
datas += collect_data_files("passlib", include_py_files=True)

a = Analysis(
    [str(project_root / "pyinstaller_run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "PIL", "fontTools"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LF_TrainingEvaluation_Server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LF_TrainingEvaluation_Server",
)
