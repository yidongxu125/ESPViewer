# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
#
# 用法：pyinstaller ESPViewer.spec
# 说明：路径改为相对本文件，便于在不同机器上直接打包。
#       图标用同目录下的 ESPViewer.ico（程序窗口/对话框/任务栏都用它）；
#       缺失时自动跳过，不影响打包。

import os

_here = os.path.abspath(os.path.dirname(SPEC)) if "SPEC" in globals() else os.getcwd()
_icon = os.path.join(_here, "ESPViewer.ico")
_datas = [(_icon, ".")] if os.path.isfile(_icon) else []

a = Analysis(
    [os.path.join(_here, "esp_surface_gui.py")],
    pathex=[_here],
    binaries=[],
    datas=_datas,          # 把 ico 一起打进去，运行时可被 app_icon() 找到
    # cache.py / tclgen.py / theme.py 是本地模块，通常能被自动发现；
    # 显式声明，避免被误裁剪（theme.py 里是全部配色与 QSS）。
    hiddenimports=["cache", "tclgen", "theme"],
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
    name='ESPViewer',
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
    icon=[_icon] if os.path.isfile(_icon) else None,
)
