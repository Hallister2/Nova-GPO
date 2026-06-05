# -*- mode: python ; coding: utf-8 -*-
import ssl
import os
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('app')

# Bundle the assets folder (icons, logo, nav images) and the SSL CA bundle
# so HTTPS downloads work correctly in the frozen EXE.
datas = [
    ('assets', 'assets'),
]

# Include the system CA certificate bundle if certifi is installed
try:
    import certifi
    datas.append((certifi.where(), 'certifi'))
except ImportError:
    pass

# On Windows, truststore lets urllib validate HTTPS with the OS trust store,
# including enterprise roots managed outside Python's CA bundle.
try:
    hiddenimports += collect_submodules('truststore')
except Exception:
    pass

# Fall back to Python's built-in ssl CA bundle
_ssl_cafile = ssl.get_default_verify_paths().cafile
if _ssl_cafile and os.path.exists(_ssl_cafile):
    datas.append((_ssl_cafile, 'ssl_certs'))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
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
    name='Nova GPO',
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
    icon=['assets\\Nova GPO - Icon.ico'],
)
