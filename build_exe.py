#!/usr/bin/env python3
"""一键打包 ESPViewer：产出单个 dist/ESPViewer.exe。

用法：
    python build_exe.py              # 干净重编（约 3 min）
    python build_exe.py --no-clean   # 增量重编（快，改了代码也能触发）

v2.3.6 起界面只有中文，不再生成 _CN / _EN 变体，也不再读取 --lang 参数。

产物：
    dist/ESPViewer.exe   单文件绿色版（同目录放 esp_surface_gui.ini 可带配置）
"""

import hashlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "ESPViewer.spec")
DIST = os.path.join(HERE, "dist")
EXE = "ESPViewer.exe"


def sha256_head(path, n=12):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def human(nbytes):
    return f"{nbytes / (1024 * 1024):.0f} MB"


def main(argv):
    clean = "--no-clean" not in argv

    if not os.path.isfile(SPEC):
        sys.exit(f"找不到 {SPEC}")

    cmd = [sys.executable, "-m", "PyInstaller", SPEC, "--noconfirm"]
    if clean:
        cmd.append("--clean")
    print(f"打包：{' '.join(cmd)}")
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=HERE)
    if rc != 0:
        sys.exit(f"PyInstaller 失败，退出码 {rc}")

    exe = os.path.join(DIST, EXE)
    if not os.path.isfile(exe):
        sys.exit(f"未找到产物 {exe}")
    print(f"完成，用时 {time.time() - t0:.0f} s")
    print()
    print(f"{'文件':<18}{'大小':<10}sha256")
    print(f"{EXE:<18}{human(os.path.getsize(exe)):<10}{sha256_head(exe)}")
    print()
    print("分发时把 ESPViewer.exe 单独拷出去即可；需要固定工具路径就在同目录放 esp_surface_gui.ini。")


if __name__ == "__main__":
    main(sys.argv[1:])
