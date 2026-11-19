# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

# Dependency discovery must not pick up foreign Qt/ICU DLLs from tools added
# to PATH (for example Poppler). Qt hooks add their own package directories.
windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
os.environ['PATH'] = os.pathsep.join([
    str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
    str(windows / 'System32'), str(windows),
])


a = Analysis(
    ['src/mnemo/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/mnemo/resources', 'mnemo/resources')],
    hiddenimports=[],
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
    name='Mnemo',
    icon='src/mnemo/resources/mnemo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Mnemo',
)
