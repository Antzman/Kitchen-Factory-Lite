# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_dir = Path(SPECPATH)
hiddenimports = collect_submodules("reportlab")

a = Analysis(
    [str(project_dir / "launch.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "templates"), "templates"),
        (str(project_dir / "static"), "static"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KitchenFactory",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
