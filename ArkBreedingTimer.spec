# -*- mode: python ; coding: utf-8 -*-
#
# upx は必ず False のままにすること。
# True にすると Windows Defender に Trojan:Win32/Wacatac.C!ml として
# 誤検知され、ダウンロードした瞬間に消される（2026-08-03 に実際に踏んだ）。
# UPX を外すと同じコードでも検出されなくなる。サイズはほとんど変わらない。


a = Analysis(
    ['ark_breeding_timer.py'],
    pathex=[],
    binaries=[],
    datas=[('data\\species.json', 'data')],
    hiddenimports=['sounds', 'theme'],
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
    a.binaries,
    a.datas,
    [],
    name='ArkBreedingTimer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # ← 上のコメント参照。True にしないこと
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
