# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('data', 'data'), ('assets', 'assets')]
binaries = []
hiddenimports = ['firebase_admin', 'firebase_admin.credentials', 'firebase_admin.db', 'firebase_admin.auth', 'firebase_admin.exceptions', 'google.auth', 'google.auth.transport.requests', 'google.oauth2.service_account', 'google.oauth2.credentials', 'grpc', 'requests', 'PIL', 'PIL.Image', 'reportlab', 'openpyxl', 'pandas', 'PyQt5.sip', 'PyQt5.QtPrintSupport', 'PyQt5.QtSvg', 'email.mime.text', 'email.mime.multipart', 'bcrypt']
tmp_ret = collect_all('firebase_admin')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.auth')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.oauth2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='MABS_Invoice',
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
    codesign_identity=None,
    entitlements_file=None,
)
