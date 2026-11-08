# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import ssl
import sys
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from desktop import VERSION
version_tuple = tuple(int(part) for part in VERSION.split('.')) + (0,)
data = []
# Some Python distributions carry an additional TLS trust-policy data file.
# Preserve that file when present instead of changing their SSL behavior.
tls_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if tls_policy.is_file():
    data.append((str(tls_policy), "."))
for folder in ("app/assets", "app/static", "desktop/assets", "reference/ke-startup"):
    for path in (root / folder).rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and "sources" not in path.parts:
            data.append((str(path), str(path.parent.relative_to(root))))
for name in ("printer_catalog.json", "bambu_catalog.json", "midi_library.json", "popular_midi_sources.json"):
    data.append((str(root / "app" / name), "app"))
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    data.append((str(root / name), "."))

a = Analysis([str(root / "desktop/launcher.py")],
    pathex=[str(root), str(root / "app"), str(root / "tools")],
    binaries=[], datas=data, hiddenimports=["webview.platforms.edgechromium", "webview.platforms.winforms"],
    hookspath=[], runtime_hooks=[], excludes=["tkinter", "matplotlib", "numpy", "pandas", "PyQt5", "PyQt6", "PySide6", "pytest", "flask", "waitress"],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
version = VSVersionInfo(ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
    kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName','QUINRY'), StringStruct('FileDescription','3DMidi - MIDI to printer music'),
        StringStruct('FileVersion',VERSION), StringStruct('ProductName','3DMidi'), StringStruct('ProductVersion',VERSION),
        StringStruct('OriginalFilename','3DMidi.exe'), StringStruct('LegalCopyright','Copyright (C) 2026 QUINRY. GNU GPLv3.')])]),
        VarFileInfo([VarStruct('Translation',[1033,1200])])])
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="3DMidi", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(root / "desktop/assets/3dmidi.ico"), version=version)
