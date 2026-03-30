# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['mod_version_checker_v2.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
    ],
    hiddenimports=[
        'requests',
        'packaging',
        'concurrent.futures',
        'urllib3',
        'chardet',
        'certifi',
        'idna',
        'dataclasses',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MinecraftModCheckerV2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MinecraftModCheckerV2',
)
