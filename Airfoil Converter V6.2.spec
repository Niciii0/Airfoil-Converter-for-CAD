# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

root = Path.cwd()
python_root = Path(r'C:\Users\nicol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python')

a = Analysis(
    ['Airfoil Converter V6.2.py'],
    pathex=[str(root)],
    binaries=[
        ('xfoil.exe', '.'),
        (str(python_root / 'DLLs' / '_tkinter.pyd'), '.'),
        (str(python_root / 'DLLs' / 'tcl86t.dll'), '.'),
        (str(python_root / 'DLLs' / 'tk86t.dll'), '.'),
    ],
    datas=[
        ('Airfoil_DATA', 'Airfoil_DATA'),
        ('NACA 4 digit', 'NACA 4 digit'),
        (str(python_root / 'tcl' / 'tcl8.6'), 'tcl/tcl8.6'),
        (str(python_root / 'tcl' / 'tk8.6'), 'tcl/tk8.6'),
        (str(python_root / 'Lib' / 'tkinter'), 'tkinter'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.simpledialog',
        'tkinter.font',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_tk_runtime.py'],
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
    name='Airfoil Converter V6.2',
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
    name='Airfoil Converter V6.2',
)
