# -*- mode: python ; coding: utf-8 -*-
#
# このファイルは tools/build.py が自動生成する。直接編集しても次のビルドで消える。
#
# upx は必ず False のままにすること。
# True にすると Windows Defender に Trojan:Win32/Wacatac.C!ml として
# 誤検知され、ダウンロードした瞬間に消される（2026-08-03 に実際に踏んだ）。
# version-file（会社名・製品名・著作権）を入れておくのも誤検知対策。
#
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
    [],
    exclude_binaries=True,
    name='ArkBreedingTimer-dir',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='C:\\Users\\master\\Desktop\\作業場\\ark-breeding-timer\\build_version_info.txt',
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ArkBreedingTimer-dir',
)
