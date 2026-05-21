# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['simple_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('crimson_rs', 'crimson_rs'), ('crimson_data.db.gz', '.'), ('parc_parser.dll', '.')],
    hiddenimports=[
        'lz4', 'lz4.block',
        'crimson_rs', 'crimson_rs.enums', 'crimson_rs.create_pack', 'crimson_rs.pack_mod',
        'crimson_rs.validate_game_dir',
        'paz_patcher', 'paz_parse', 'pabgb_field_parsers', 'data_db',
        'item_creator', 'iteminfo_parser', 'iteminfo_reader',
        'equipslotinfo_parser', 'shared_state', 'overlay_coordinator',
        'models',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CrimsonGameModsSimple',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='app_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
