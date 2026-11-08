#!/usr/bin/env python3
"""
ESP Surface Visualization GUI v2.0 (PyQt5 Edition)
Multiwfn (fchk -> surface data) + VMD (Preview + Tachyon Rendering)

Based on: sobereva.com/443 (Multiwfn+VMD ESP surface tutorial)

Features:
  - Select .fch/.fchk files (single or batch)
  - Mode: PT (vertex-colored), ISO (isosurface-colored), EXT (extrema), ALL (overlay)
  - Color scale range adjustment
  - VMD interactive preview or headless Tachyon render
  - Output path selection
  - VMD socket control (render current view, pick extrema)
  - ESP area distribution analysis with histograms

Usage:
  Run directly -> GUI pops up
  python esp_surface_gui.py
"""

import os
import sys
import re
import glob
import queue
import subprocess
import threading
import shutil
import time
import socket
import configparser
import math

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QDialog,
    QGroupBox, QGridLayout, QMessageBox, QComboBox,
    QFrame, QScrollArea, QListWidget,
    QProgressBar, QDialogButtonBox,
    QTabWidget, QSlider, QTableWidget, QTableWidgetItem, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QRectF
from PyQt5.QtGui import (QFont, QTextCursor, QPainter, QColor, QKeySequence,
                         QIcon, QLinearGradient, QRadialGradient, QPen, QBrush)

# ── 本项目本地模块（与主程序同目录）────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cache                                            # noqa: E402
import tclgen                                           # noqa: E402
import theme                                            # noqa: E402
from cache import (AU, CANONICAL_NAME, MODE_REQUIRES,    # noqa: E402
                   BundleResolver, JobWorkspace, parse_esp_range_text)

# ── Optional dependencies ──────────────────────────────────
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import numpy as np
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

APP_VERSION = "2.3.6"

#: 窗口标题。版本号 / 作者只在顶栏徽标里显示一次，标题栏不再重复。
WINDOW_TITLE = "ESPViewer"

#: 初始窗口的期望宽度。布局自然宽度约 850（控件挤得下但不好看），
#: 给到 1240 才算"打开就能看清"；屏幕更窄时才退让（见 _fit_to_screen）。
#: 再宽下去模式卡片右侧会空出一大片，反而不协调。
DEFAULT_WIDTH = 1240

EV_TO_KCAL = 23.0605   # 1 eV = 23.0605 kcal/mol

# ── Default Paths ────────────────────────────────────────
DEFAULT_MULTIWFN = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
DEFAULT_VMD = r"C:\Program Files (x86)\University of Illinois\VMD\vmd.exe"
DEFAULT_TACHYON = r"C:\Program Files (x86)\University of Illinois\VMD\tachyon_WIN32.exe"

APP_DIR = os.path.dirname(
    os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__)
)

# ── 程序图标 ─────────────────────────────────────────────
ICON_NAME = "ESPViewer.ico"


def _resource_dirs():
    """按优先级返回可能存放资源（图标）的目录。"""
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    dirs.append(APP_DIR)
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in dirs:
        dirs.append(here)
    return dirs


def icon_path():
    """ESPViewer.ico 的绝对路径；找不到返回空串。"""
    for d in _resource_dirs():
        p = os.path.join(d, ICON_NAME)
        if os.path.isfile(p):
            return p
    return ""


def app_icon():
    """程序图标对象；文件缺失时返回空 QIcon（不影响运行）。"""
    p = icon_path()
    return QIcon(p) if p else QIcon()


def _config_path():
    """配置文件路径：优先程序目录；无写权限时退回 %APPDATA%/ESPViewer。"""
    primary = os.path.join(APP_DIR, "esp_surface_gui.ini")
    if os.path.exists(primary):
        return primary
    try:
        probe = os.path.join(APP_DIR, ".esp_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return primary
    except OSError:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "ESPViewer")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return os.path.join(d, "esp_surface_gui.ini")


CONFIG_FILE = _config_path()


# ── 外部工具自动定位 ─────────────────────────────────────
def _tool_search_roots():
    """返回值得扫描的父目录。

    打包成 exe 后配置目录变成 exe 所在目录，默认路径多半不存在；
    这里只扫"盘符根 + 几个常见软件目录"，不递归整盘，避免拖慢启动。
    """
    roots = []
    for drv in "CDEFGH":
        p = f"{drv}:\\"
        if os.path.isdir(p):
            roots.append(p)
    for env in ("ProgramFiles", "ProgramFiles(x86)",
                "LOCALAPPDATA", "ProgramData", "USERPROFILE"):
        p = os.environ.get(env)
        if p and os.path.isdir(p):
            roots.append(p)
            roots.append(os.path.join(p, "Programs"))
            roots.append(os.path.join(p, "Desktop"))
    seen, out = set(), []
    for p in roots:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen and os.path.isdir(p):
            seen.add(k)
            out.append(p)
    return out


#: 扫描预算：命中这些目录名就直接跳过（体积大且不可能放工具）
_SKIP_DIRS = {"windows", "$recycle.bin", "system volume information",
              "node_modules", ".git", "appdata", "winsxs", "driverstore"}


def find_tool(pattern, exe_names, depth=2, max_scan=600):
    """在常见位置找一个可执行文件，找到返回绝对路径，否则返回空串。

    pattern 是目录名通配（如 "multiwfn*"），exe_names 是候选文件名。
    先查 PATH，再按 roots → 匹配子目录（必要时再下一层）逐级找；
    max_scan 是 scandir 次数上限，防止在奇怪的文件系统上卡住。
    """
    import fnmatch
    for name in exe_names:
        p = shutil.which(name)
        if p:
            return os.path.abspath(p)

    tried = set()
    budget = [max_scan]

    def hit(exe_dir):
        for name in exe_names:
            for sub in ("", "bin", "win64", "win32"):
                p = os.path.join(exe_dir, sub, name) if sub else os.path.join(exe_dir, name)
                if os.path.isfile(p):
                    return os.path.abspath(p)
        return ""

    def look(parent, level):
        if level > depth or budget[0] <= 0:
            return ""
        try:
            entries = list(os.scandir(parent))
        except OSError:
            return ""
        budget[0] -= 1
        dirs = []
        for e in entries:
            try:
                if not e.is_dir():
                    continue
            except OSError:
                continue
            low = e.name.lower()
            if low in _SKIP_DIRS or e.name.startswith("."):
                continue
            if fnmatch.fnmatch(low, pattern):
                got = hit(e.path)
                if got:
                    return got
            dirs.append(e.path)
        for d in dirs:
            if os.path.normcase(d) in tried:
                continue
            tried.add(os.path.normcase(d))
            got = look(d, level + 1)
            if got:
                return got
        return ""

    for root in _tool_search_roots():
        got = hit(root)
        if got:
            return got
        got = look(root, 1)
        if got:
            return got
    return ""


def autodetect_tools(values):
    """默认路径不存在时，尝试自动定位 Multiwfn / VMD / Tachyon。

    只在"文件确实不存在"时改写，用户手填的合法路径不会被覆盖。
    返回被自动修正的键列表（供界面提示）。
    """
    fixed = []
    if not os.path.isfile(values.get("multiwfn") or ""):
        p = find_tool("multiwfn*", ("Multiwfn.exe", "Multiwfn"))
        if p:
            values["multiwfn"] = p
            fixed.append("multiwfn")
    if not os.path.isfile(values.get("vmd") or ""):
        p = find_tool("vmd*", ("vmd.exe", "vmd_windows.exe"))
        if p:
            values["vmd"] = p
            fixed.append("vmd")
    if not os.path.isfile(values.get("tachyon") or ""):
        exe_names = ("tachyon_WIN32.exe", "tachyon.exe", "tachyon_WIN64.exe")
        vdir = os.path.dirname(values.get("vmd") or "")
        p = ""
        if vdir and os.path.isdir(vdir):
            for n in exe_names:
                if os.path.isfile(os.path.join(vdir, n)):
                    p = os.path.join(vdir, n)
                    break
        if not p:
            p = find_tool("vmd*", exe_names, depth=1)
        if p:
            values["tachyon"] = p
            fixed.append("tachyon")
    return fixed


#: vmd_dir 语义已降级：它只是 VMD 的启动工作目录，留空表示用临时脚本目录。
DEFAULTS = {
    "multiwfn": DEFAULT_MULTIWFN,
    "vmd": DEFAULT_VMD,
    "vmd_dir": "",
    "tachyon": DEFAULT_TACHYON,
    "cache_root": "",
    "verify": "auto",
    "save_computed": "true",
}

_PATH_KEYS = ("multiwfn", "vmd", "vmd_dir", "tachyon")
_CACHE_KEYS = ("cache_root", "verify", "save_computed")


def load_config():
    """读路径与缓存配置。"""
    cfg = configparser.ConfigParser()
    values = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.read(CONFIG_FILE, encoding="utf-8")
        except (configparser.Error, OSError):
            return values
        if "paths" in cfg:
            for k in _PATH_KEYS:
                if cfg["paths"].get(k):
                    values[k] = cfg["paths"][k]
        if "cache" in cfg:
            for k in _CACHE_KEYS:
                v = cfg["cache"].get(k)
                if v is not None and v != "":
                    values[k] = v
    if not values.get("vmd_dir"):
        values["vmd_dir"] = ""
    values["_autodetected"] = autodetect_tools(values)
    return values


def save_config(values):
    """写路径与缓存配置。"""
    cfg = configparser.ConfigParser()
    cfg["paths"] = {k: values.get(k, "") or "" for k in _PATH_KEYS}
    cfg["cache"] = {k: str(values.get(k, "")) for k in _CACHE_KEYS}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


# ── Multiwfn Command Templates ───────────────────────────
CMD_ESPPT = """
12
3
0.15
0
5
mol.pdb
6
"""

#: 5→1→3→2：电子密度（高质量网格）导出 density.cub
#: 5→12→2→2：ESP（中等质量网格）导出 totesp.cub
#: 第二段原为 "12 1 2"（低质量，13 万点），与 ESP_auto.sh 的 "12 2 2"
#: （中等质量，53 万点）不一致——同一 fchk 在 Linux/Windows 会得到不同的
#: totesp.cub，进而影响等值面着色。实测改为 2 后两端 cube 的 sha1 完全相同。
CMD_ESPISO = """
5
1
3
2
0
5
12
2
2
"""

CMD_ESPEXT = """
12
3
0.15
0
5
mol.pdb
6
2
"""

CMD_ESP_AREA_DIST = """
12
0
9
all
"""

CMD_ESP_QUERY_RANGE = """
12
0
-1
-1
q
"""

# ── Progress Parsing ──────────────────────────────────────
_PROGRESS_PATTERNS = [
    (re.compile(r'(\d+(?:\.\d+)?)\s*%', re.IGNORECASE), 'pct'),
    (re.compile(r'(\d+)\s*/\s*(\d+)', re.IGNORECASE), 'frac'),
    (re.compile(r'(\d+)\s+of\s+(\d+)', re.IGNORECASE), 'frac'),
]


def _parse_progress(line):
    """Try to extract progress info from a Multiwfn output line.
    Returns (value: float 0.0-1.0 or None, msg: str).
    """
    for pat, kind in _PROGRESS_PATTERNS:
        m = pat.search(line)
        if m:
            if kind == 'pct':
                return min(float(m.group(1)) / 100.0, 1.0), line.strip()
            elif kind == 'frac':
                num, den = int(m.group(1)), int(m.group(2))
                if den > 0:
                    return min(num / den, 1.0), line.strip()
    return None, line.strip()


# ── ESP Range Auto-Detection ─────────────────────────────────
# 文本解析已收敛到 cache.parse_esp_range_text，这里只保留入口别名。
_parse_esp_range_from_stdout = parse_esp_range_text


def _pdb_beta_extremes(pdb_path):
    """取 PDB 中 B-factor 列（Multiwfn 用来存 ESP 值）的极值。"""
    lo = hi = None
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                try:
                    b = float(line[60:66])
                except (ValueError, IndexError):
                    continue
                lo = b if lo is None else min(lo, b)
                hi = b if hi is None else max(hi, b)
    except OSError:
        return None
    if lo is None or hi is None:
        return None
    return lo, hi


def _read_text(path, limit=4_000_000):
    """读文本产物；失败返回空串（调用方按"没读到"处理）。"""
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def detect_esp_range_fast(bundle):
    """从已有产物快速读出全局 ESP 范围，**不调用 Multiwfn**。

    返回 ``(low, high, source)``，单位统一为 kcal/mol；读不到返回 None。

    两级来源：
      1. atomsurface.txt / medinfo.txt 的汇总行（"Minimal value: … kcal/mol"）
      2. surfanalysis.pdb 的 B-factor 极值（Multiwfn 可能写成 eV，自动换算）
    """
    if bundle is None:
        return None
    for kind in ("atomsurface", "stdout"):
        p = bundle.path(kind)
        if not p:
            continue
        r = cache.parse_esp_range_text(_read_text(p))
        if r:
            return r[0], r[1], os.path.basename(p)
    ext_p = bundle.path("extrema")
    if ext_p:
        vals = _pdb_beta_extremes(ext_p)
        if vals:
            lo, hi = vals
            if cache.detect_esp_unit(ext_p) == "eV":
                lo, hi = lo * EV_TO_KCAL, hi * EV_TO_KCAL
            return lo, hi, os.path.basename(ext_p) + " (B-factor)"
    return None


def auto_esp_range(bundles):
    """多文件时取所有体系的并集范围。

    返回 ``(low, high, sources)``（kcal/mol），全都没有产物时返回 None。
    单文件就直接是该文件的范围；多文件取 min/max，保证每个体系的极值都落在
    分区区间内，不会出现"某个分子的极小值被裁掉"。
    """
    lo = hi = None
    srcs = []
    for b in bundles or ():
        r = detect_esp_range_fast(b)
        if not r:
            continue
        lo = r[0] if lo is None else min(lo, r[0])
        hi = r[1] if hi is None else max(hi, r[1])
        if r[2] not in srcs:
            srcs.append(r[2])
    if lo is None:
        return None
    src = " + ".join(srcs[:3]) + (" 等" if len(srcs) > 3 else "")
    return lo, hi, src


#: 单次 Multiwfn 调用允许的"无任何文字输出"时长。超时判定卡死并强杀。
#: 实测大体系（8 MB fchk）的 ESP 网格阶段可以十几分钟**完全不打印任何东西**
#: （连 \r 都没有），所以这里给到 1 小时：它只用来兜住真正的死锁，
#: 正常运行不该撞上；用户想提前结束随时可以点 [■ 停止]。
MW_IDLE_TIMEOUT = 3600

#: 无输出超过这个秒数就在日志里提一句"仍在计算"，避免用户以为程序死了。
MW_QUIET_HINT = 20


def kill_proc_tree(proc, log_cb=None):
    """强制结束进程及其子进程（Windows 无原生 kill-tree，走 taskkill /T）。"""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:
        pass
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.kill()
    except Exception as e:
        if log_cb:
            log_cb(f"  结束进程失败: {e}")
        try:
            proc.kill()
        except Exception:
            pass


def _pump_output(proc, progress_cb=None, log_cb=None, proc_box=None,
                 idle_timeout=MW_IDLE_TIMEOUT):
    """边跑边读 Multiwfn 输出，返回 (lines, aborted, timed_out)。

    两个坑必须一起解决，否则长计算时界面像死机：
      1) **Multiwfn 的进度条用 `\\r` 刷同一行**（"Progress: [##--] 42.0 %"），
         按行读（`for line in stdout`）永远等不到 `\\n`，进度、日志、abort 标志
         全都拿不到。这里按 `\\r` 和 `\\n` 双分隔切分。
      2) 阻塞读期间要能响应"停止"，所以读线程只管往队列塞行，主循环带
         0.5 s 超时轮询 abort 与空闲计时。
    """
    q = queue.Queue()

    def reader():
        buf = ""
        try:
            fd = proc.stdout.fileno()
            while True:
                chunk = os.read(fd, 4096)          # 有多少读多少，不等换行
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
                parts = re.split(r"[\r\n]", buf)
                buf = parts.pop()
                for ln in parts:
                    q.put(ln)
        except Exception:
            pass
        finally:
            if buf.strip():
                q.put(buf)
            q.put(None)

    threading.Thread(target=reader, daemon=True).start()

    lines, last, aborted, timed_out = [], time.time(), False, False
    started = time.time()
    next_hint = started + MW_QUIET_HINT
    while True:
        if proc_box is not None and proc_box.get("abort"):
            kill_proc_tree(proc, log_cb)
            aborted = True
            break
        try:
            line = q.get(timeout=0.5)
        except queue.Empty:
            line = ""                              # 空转，仍要走下面的计时检查
        if line is None:
            break
        # 只有"有内容的行"才算活动：进度条结尾的裸 \r 会被切成空串，
        # 若把空串也算成新输出，静默计时会被无限重置，用户永远等不到提示。
        # 注意不能简单 continue——空串会持续塞满队列，超时分支就再也不会触发。
        if line.strip():
            last = time.time()
            next_hint = last + MW_QUIET_HINT
            lines.append(line)
            if progress_cb:
                try:
                    progress_cb(line)
                except Exception:
                    pass
            if log_cb:
                _log_important(line, log_cb)
            continue
        now = time.time()
        idle = now - last
        if idle > idle_timeout:
            kill_proc_tree(proc, log_cb)
            if log_cb:
                log_cb(f"⚠ Multiwfn 已 {int(idle)} s 无任何输出，判定卡死，已终止")
            timed_out = True
            break
        # 长计算期间每 60 s 报一次"已运行多久"，让用户知道不是死机
        if log_cb and now >= next_hint:
            log_cb(f"  …仍在计算（已运行 {int(now - started)} s）"
                   "，可随时点 [■ 停止] 中断")
            next_hint = now + 60
    return lines, aborted, timed_out


_LOG_KEEP = re.compile(
    r"(error|warn|elapsed|calculation of|has been saved|cube file|"
    r"not enough memory|fail)", re.I)

#: Multiwfn 交互菜单的回显行，形如 "5 Multiply all grid data"、" -1 Show isosurface"。
#: 日志和状态栏都要丢掉，否则真正的进度会被几千行菜单淹没。
_MW_MENU_RE = re.compile(r"^\s*-?\d+\s+\S")


def _log_important(line, log_cb):
    """只把 Multiwfn 输出里的关键行抄进日志，避免几千行刷屏。"""
    s = line.strip()
    if len(s) < 5:
        return
    if _MW_MENU_RE.match(s):
        return
    if _LOG_KEEP.search(s):
        log_cb(f"    {s[:140]}")


def run_multiwfn(multiwfn_exe, fch_path, cmd_string, work_dir, extra_args="",
                 progress_cb=None, log_cb=None, proc_box=None,
                 idle_timeout=MW_IDLE_TIMEOUT):
    """Run Multiwfn with command string via file redirection.
    Returns (success: bool, stdout: str)

    `proc_box` 是一个 dict（由 worker 持有）：运行中的 Popen 存在
    `proc_box["proc"]`，worker 调 abort() 时置 `proc_box["abort"]=True` 并强杀，
    这样"停止"能立刻生效，而不是等这一步算完。
    """
    fch_name = os.path.basename(fch_path)

    cmd_file = os.path.join(work_dir, "_mw_cmd.txt")
    if not cmd_string.startswith("\n"):
        cmd_string = "\n" + cmd_string
    with open(cmd_file, "w", encoding="ascii") as f:
        f.write(cmd_string)

    argv = [multiwfn_exe, fch_name] + (extra_args.split() if extra_args else [])
    print(f"  Multiwfn: {' '.join(argv)} < _mw_cmd.txt")

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    stdin_f = open(cmd_file, "rb")
    # 先给默认值：_pump_output 中途抛异常时 finally 里仍要能安全写回状态
    lines, aborted, timed_out = [], False, False
    try:
        try:
            proc = subprocess.Popen(
                argv, cwd=work_dir, stdin=stdin_f,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0, creationflags=creationflags,
            )
        except Exception as e:
            print(f"    Popen failed: {e}")
            return False, ""
        if proc_box is not None:
            proc_box["proc"] = proc

        lines, aborted, timed_out = _pump_output(
            proc, progress_cb, log_cb, proc_box, idle_timeout)

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            kill_proc_tree(proc, log_cb)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            print("    TIMEOUT waiting for Multiwfn exit")
    finally:
        stdin_f.close()
        if proc_box is not None:
            proc_box["proc"] = None
            proc_box["aborted"] = aborted
            proc_box["timed_out"] = timed_out
            try:
                # 记下退出码：进程被外部杀掉/崩溃时，日志能给出可判断的线索，
                # 而不是只有一句"计算失败"
                proc_box["returncode"] = proc.returncode
            except Exception:
                proc_box["returncode"] = None

    full_stdout = "\n".join(lines)

    if aborted:
        print("    ABORTED by user")
        return False, full_stdout
    if timed_out:
        return False, full_stdout

    if proc.returncode not in (0, 24):
        print(f"    WARN: exit code {proc.returncode}")
        for line in full_stdout.strip().split("\n")[-15:]:
            print(f"      | {line}")
        return False, full_stdout

    if "Error" in full_stdout or "ERROR" in full_stdout:
        print("    WARN: 'Error' in stdout")
        for line in full_stdout.strip().split("\n")[-10:]:
            print(f"      | {line}")

    return True, full_stdout


# ── VMD 脚本生成 ─────────────────────────────────────────
# 已迁移到 tclgen.py：逐分子绝对路径展开，不再使用索引文件名与 nsystem 循环。

# ── ESP Area Distribution Analysis ─────────────────────────

def run_multiwfn_area_dist(multiwfn_exe, fch_path, work_dir,
                            range_low=-25.0, range_high=22.0,
                            n_bins=15, unit_code=3, progress_cb=None,
                            log_cb=None, proc_box=None):
    """Run Multiwfn area distribution analysis for a single .fch file."""
    cmd = CMD_ESP_AREA_DIST + f"{range_low},{range_high}\n{n_bins}\n{unit_code}\nn\n"
    ok, stdout = run_multiwfn(
        multiwfn_exe, fch_path, cmd, work_dir, progress_cb=progress_cb,
        log_cb=log_cb, proc_box=proc_box,
    )
    data = _parse_area_output(stdout)
    if not data:
        tail = stdout.strip().split("\n")[-30:]
        dbg = ["  [AreaDist] No data parsed. Last 30 lines of Multiwfn stdout:"]
        for i, line in enumerate(tail):
            dbg.append(f"    {i:3d}: {line}")
        dbg_str = "\n".join(dbg)
        print(dbg_str)
        if log_cb:
            log_cb(dbg_str)
    return ok, data, stdout


def _area_matches(data, range_low, range_high, n_bins):
    """判断缓存的分区表是否与本次请求一致（分区数 + 起止范围）。"""
    if not data or len(data) != n_bins or n_bins < 2:
        return False
    step = (data[-1][0] - data[0][0]) / (n_bins - 1)
    if step <= 0:
        return False
    lo_got = data[0][0] - step / 2.0
    hi_got = data[-1][0] + step / 2.0
    tol_lo = max(0.05, abs(range_low) * 1e-3)
    tol_hi = max(0.05, abs(range_high) * 1e-3)
    return abs(lo_got - range_low) <= tol_lo and abs(hi_got - range_high) <= tol_hi


def _parse_area_output(stdout):
    """Parse Multiwfn area distribution output from stdout."""
    data = []
    lines = stdout.split("\n")
    ncols = 3
    header_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if 'Begin' in stripped and 'End' in stripped and 'Center' in stripped:
            ncols = 5
            header_idx = i
            break
        if 'Center' in stripped and 'Area' in stripped and 'Begin' not in stripped:
            ncols = 3
            header_idx = i
            break

    if header_idx < 0:
        return data

    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            if data:
                break
            continue
        if stripped.startswith('Sum') or stripped.startswith('---') or \
           stripped.startswith('===') or 'Area unit' in stripped:
            continue
        nums = re.findall(r'[-+]?\d+\.?\d*', stripped)
        if ncols == 5:
            if len(nums) >= 5:
                try:
                    center = float(nums[2])
                    area = float(nums[3])
                    pct = float(nums[4])
                    data.append((center, area, pct))
                except ValueError:
                    continue
        else:
            if len(nums) >= 3:
                try:
                    c = float(nums[0])
                    a = float(nums[1])
                    p = float(nums[2])
                    data.append((c, a, p))
                except ValueError:
                    continue
    return data


def plot_esp_area_histogram(area_data, output_path,
                             title="ESP Area Distribution",
                             xlabel="ESP (kcal/mol)"):
    """Generate ESP area distribution histogram as PNG."""
    if not _HAS_MPL:
        print("  matplotlib not available, cannot generate chart")
        return None
    if not area_data:
        print("  No area data to plot")
        return None

    centers = [d[0] for d in area_data]
    areas = [d[1] for d in area_data]

    if len(centers) > 1:
        bin_width = centers[1] - centers[0]
    else:
        bin_width = 2.0

    data_min, data_max = min(centers), max(centers)
    pad = max(0.5, (data_max - data_min) * 0.05)
    norm = mcolors.TwoSlopeNorm(vmin=data_min - pad, vcenter=0, vmax=data_max + pad)
    cmap_bwr = plt.get_cmap('bwr')
    colors = [cmap_bwr(norm(c)) for c in centers]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(
        centers, areas, width=bin_width * 0.92, align='center',
        color=colors, edgecolor='#333333', linewidth=0.8,
    )
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel('Surface Area (Å²)', fontsize=12)
    ax.set_title(title, fontsize=13, fontweight='bold')
    ax.set_xticks(centers)
    ax.set_xticklabels([f'{c:.1f}' for c in centers], rotation=45, ha='right', fontsize=8)

    max_area = max(areas) if max(areas) > 0 else 1
    for bar, val in zip(bars, areas):
        if val > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2.,
                bar.get_height() + max_area * 0.02,
                f'{val:.1f}', ha='center', va='bottom',
                fontsize=7, rotation=90, color='#333333',
            )

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_xlim(centers[0] - bin_width, centers[-1] + bin_width)
    ax.set_ylim(0, max_area * 1.18)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return output_path


def save_area_data_file(area_data, output_path):
    """Export ESP area distribution data as tab-separated text file."""
    if not area_data:
        print("  No area data to export")
        return None
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("Center(kcal/mol)\tArea(Ang^2)\tPercentage(%)\n")
            for center, area, pct in area_data:
                f.write(f"{center:.4f}\t{area:.4f}\t{pct:.4f}\n")
        return output_path
    except OSError as e:
        print(f"  Failed to write data file: {e}")
        return None


# ── VMD Socket / Launch / Render ───────────────────────────

def find_free_port():
    """Find an available TCP port on localhost."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def socket_tcl_snippet(port, callback_port=0):
    """Generate Tcl code for a socket server inside VMD."""
    pick_code = ""
    if callback_port > 0:
        pick_code = (
            "\n# === Pick callback: send clicked atom info to Python GUI ===\n"
            "trace add variable ::vmd_pick_event write _esp_pick_cb\n"
            "proc _esp_pick_cb {args} {\n"
            "    global vmd_pick_atom vmd_pick_mol\n"
            "    set mol $vmd_pick_mol\n"
            "    set atom_idx $vmd_pick_atom\n"
            "    set sel [atomselect $mol \"index $atom_idx\"]\n"
            "    set aname [$sel get name]\n"
            "    set abeta [$sel get beta]\n"
            "    set axyz  [$sel get {x y z}]\n"
            "    $sel delete\n"
            "    if {[catch {\n"
            f"        set s [socket 127.0.0.1 {callback_port}]\n"
            "        fconfigure $s -buffering line -translation binary\n"
            "        puts $s \"PICK:$atom_idx:$aname:$abeta:$axyz\"\n"
            "        flush $s\n"
            "        close $s\n"
            "    } err]} {\n"
            "        # Python callback server not running, ignore\n"
            "    }\n"
            "}\n"
            f'puts "ESP_VMD_CALLBACK:{callback_port}"\n'
        )

    return f"""
# === Socket server: accept commands from Python GUI ===
set _esp_server_sock [socket -server _esp_accept -myaddr 127.0.0.1 {port}]
proc _esp_accept {{chan addr port}} {{
    fconfigure $chan -buffering line -translation binary
    fileevent $chan readable [list _esp_handle $chan]
}}
proc _esp_handle {{chan}} {{
    if [eof $chan] {{ close $chan; return }}
    gets $chan cmd
    if {{$cmd eq ""}} return
    if [catch {{uplevel #0 $cmd}} err] {{
        puts $chan "ERROR: $err"
    }} else {{
        puts $chan "OK"
    }}
    flush $chan
}}
puts "ESP_VMD_SERVER:{port}"
{pick_code}"""


def send_vmd_cmd(port, cmd, timeout=5):
    """Send a Tcl command to VMD via socket and return the response."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", port))
        sock.sendall((cmd + "\n").encode("utf-8"))
        time.sleep(0.3)
        resp = b""
        sock.settimeout(3)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if b"\n" in resp:
                    break
        except socket.timeout:
            pass
        return resp.decode("utf-8", errors="replace").strip()
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        if sock:
            sock.close()


def default_bundle_folder(source_fchk):
    """单个分子的产物目录：`<输入目录>/<输入主名>/`。

    与 `cache.default_bundle_dir()` 同一约定——中间产物（mol.pdb、density.cub、
    surfanalysis.pdb…）本来就落在这里，渲染图、面积图、计算临时区也一并放进来，
    做到"一个分子一个文件夹"。
    """
    d = os.path.dirname(os.path.abspath(source_fchk))
    stem = os.path.splitext(os.path.basename(source_fchk))[0]
    return os.path.join(d, stem)


def default_render_path(source_fchk, ext=".png"):
    """渲染图默认落位：`<输入目录>/<输入主名>/<输入主名>_esp<ext>`。

    旧版把图平铺在输入目录里，且「输出路径」框一旦有值就无条件复用：先对
    A 点过「渲染输出」（自动填了 `A_esp.tga`），再换 B 点「渲染当前视角」，
    仍然写 A 的路径，B 的图就把 A 的覆盖掉了。改成按输入文件推导后，
    不同分子的图天然隔离。
    """
    if not source_fchk:
        return ""
    stem = os.path.splitext(os.path.basename(source_fchk))[0]
    return os.path.join(default_bundle_folder(source_fchk), f"{stem}_esp{ext}")


def render_current_view_tachyon(port, vmd_dir, tachyon_exe, output_path,
                                resolution=(2000, 1500), log_cb=None):
    """让 VMD 导出场景文件，再用外部 Tachyon 渲染成图。

    必须全部用**绝对路径**：VMD 进程的工作目录是它自己的启动目录（用户在
    「VMD 目录」里填的位置），而本函数在 bundle 的 `_espcalc/scripts` 里工作。
    旧实现发送的是 `render Tachyon vmdscene.dat` 这样的相对路径，文件会写到
    VMD 的 cwd，这边永远等不到，于是报 "Tachyon 渲染失败" —— 这是最常见的
    失败原因，不是 Tachyon 本身的问题。

    外部 Tachyon 失败时，回退到 VMD 内置的 `render TachyonInternal`，
    保证无论如何都能出图。
    """
    def log(msg):
        if log_cb:
            log_cb(f"  {msg}")

    work = vmd_dir
    if not work or not os.path.isdir(work):
        work = os.path.dirname(os.path.abspath(output_path or "."))
    dat_path = os.path.join(work, "vmdscene.dat")
    bmp_path = os.path.join(work, "_esp_render.bmp")
    dat_tcl = tclgen.tcl_path(dat_path)
    bmp_tcl = tclgen.tcl_path(bmp_path)

    for fp in (dat_path, bmp_path):
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as e:
                log(f"清理旧文件失败: {e}")

    resp = send_vmd_cmd(port, f"render Tachyon {dat_tcl}")
    if resp and "ERROR" in resp:
        log(f"VMD 导出场景失败: {resp}")

    for _ in range(60):
        if os.path.exists(dat_path) and os.path.getsize(dat_path) > 0:
            break
        time.sleep(0.5)
    else:
        log(f"等待场景文件超时: {dat_path}")

    ok = os.path.exists(dat_path) and os.path.getsize(dat_path) > 0
    if ok and os.path.isfile(tachyon_exe):
        args = [
            tachyon_exe, dat_path,
            "-format", "BMP", "-o", bmp_path,
            "-res", str(resolution[0]), str(resolution[1]),
            "-numthreads", "4", "-aasamples", "24",
            "-fullshade",
        ]
        try:
            proc = subprocess.run(args, capture_output=True, text=True,
                                  cwd=work, timeout=900,
                                  errors="replace")
            if proc.returncode != 0:
                tail = (proc.stdout or "").strip().splitlines()[-6:]
                log(f"Tachyon 退出码 {proc.returncode}: " + " | ".join(tail))
        except (subprocess.TimeoutExpired, OSError) as e:
            log(f"Tachyon 运行失败: {e}")
        ok = os.path.exists(bmp_path) and os.path.getsize(bmp_path) > 0

    if not ok:
        # 回退：VMD 内置 TachyonInternal（不需要外部 exe）
        log("改用 VMD 内置渲染器 (TachyonInternal)...")
        out = output_path or os.path.join(work, "esp_render.tga")
        tga = os.path.splitext(out)[0] + ".tga"
        if os.path.exists(tga):
            try:
                os.remove(tga)
            except OSError:
                pass
        w, h = resolution
        send_vmd_cmd(port, f"display resize {int(w)} {int(h)}")
        send_vmd_cmd(port, f"render TachyonInternal {tclgen.tcl_path(tga)}")
        for _ in range(120):
            if os.path.exists(tga) and os.path.getsize(tga) > 0:
                break
            time.sleep(0.5)
        if os.path.exists(tga) and os.path.getsize(tga) > 0:
            return tga
        log("内置渲染器同样未产出图片")
        return None

    out = output_path or os.path.join(work, "esp_render.png")
    try:
        from PIL import Image
        Image.open(bmp_path).save(out)
    except ImportError:
        if not out.lower().endswith(".bmp"):
            out = os.path.splitext(out)[0] + ".bmp"
        shutil.copy2(bmp_path, out)
    return out


# ═══════════════════════════════════════════════════════════════════
#  StatusButton — capsule-status button with breathing animation
# ═══════════════════════════════════════════════════════════════════

class StatusButton(QPushButton):
    """Capsule status button, breathing pulse animation when running."""

    def __init__(self, text="Ready", parent=None):
        super().__init__(text, parent)
        self._state_text = text
        self._state_color = QColor("#1565C0")
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._running = False
        self._breath_color = QColor("#1565C0")
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(self._state_color.name())

    def _apply_style(self, bg):
        # 文字用压色（亮底深字 / 暗底亮字），切主题后重建即可
        on = theme.active_palette()["ON_ACC"]
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {on}; font-weight: bold; font-size: 11pt;"
            f"  padding: 8px 34px; border-radius: 20px; border: none;"
            f"}}"
        )

    def _tick(self):
        self._offset = (self._offset + 0.02) % 2.0
        self.update()

    def set_status(self, text, bg):
        self._state_text = text
        self._state_color = QColor(bg)
        self.stop()
        self.setText(text)
        self._apply_style(bg)

    def start(self, text="计算中"):
        if not self._running:
            self._running = True
            self._state_text = text
            self.setText(text)
            self._timer.start(16)

    def stop(self):
        if self._running:
            self._running = False
            self._timer.stop()
            self._apply_style(self._state_color.name())

    def paintEvent(self, event):
        if self._running:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()
            alpha = int(100 + 100 * (0.5 + 0.5 * math.sin(self._offset * math.pi)))
            c = QColor(self._breath_color)
            c.setAlpha(alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(0, 0, w, h, 20, 20)
            p.setPen(QColor("white"))
            f = p.font(); f.setBold(True); f.setPointSizeF(11)
            p.setFont(f)
            p.drawText(0, 0, w, h, Qt.AlignCenter, self._state_text)
            p.end()
        else:
            super().paintEvent(event)


# ═══════════════════════════════════════════════════════════════════
#  Workers
# ═══════════════════════════════════════════════════════════════════

class MultiwfnWorker(QThread):
    """Background thread for running Multiwfn + VMD jobs."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)  # result dict
    busy_signal = pyqtSignal(bool)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self._abort_flag = False
        # 运行中的 Multiwfn 进程句柄 + 中止标志，供 abort() 立刻强杀
        self._proc_box = {}

    def abort(self):
        """中止任务：置标志并**直接结束**正在跑的 Multiwfn。

        旧实现只置一个布尔，而这个标志只在分子/步骤之间被检查，
        所以正在跑的这一步（大体系 ESP 动辄十几分钟）根本停不下来，
        界面还一直卡在 busy 状态。
        """
        self._abort_flag = True
        self._proc_box["abort"] = True
        kill_proc_tree(self._proc_box.get("proc"))

    def run(self):
        try:
            self._do_run()
        except Exception as e:
            import traceback
            if self._abort_flag:
                self.log_signal.emit(f"[ABORT] 已中止（{e}）")
                self.busy_signal.emit(False)
                self.finished_signal.emit(
                    {'ok': False, 'action': 'error', 'error': 'aborted'})
                return
            tb = traceback.format_exc()
            self.log_signal.emit(f"[FATAL] 内部错误: {e}")
            self.log_signal.emit(tb)
            self.busy_signal.emit(False)
            self.finished_signal.emit({'ok': False, 'action': 'error', 'error': str(e)})

    # ══ 主流程 ══

    def _collect_extrema_labels(self, mode, systems, enabled, per_side):
        """为 EXT / ALL 收集每个分子要标注的极值点。

        返回与 systems 等长的列表；未启用或模式不匹配时返回 None。

        数值来源是 `surfanalysis.pdb` 的 B-factor（Multiwfn 找极值时采样点处的
        值），**不是** atomsurface.txt 的逐原子值。两者会差零点几到一两
        kcal/mol（采样位置不同，前者还要求是局域极值），但排序趋势一致；
        所以这里只按坐标取点、按 |值| 取前 N 个，完全不做"按值反查原子"。
        """
        if mode not in ("ext", "all") or not enabled:
            return None
        out, total = [], 0
        for s in systems:
            pts = cache.parse_surfanalysis_pdb(s.get("extrema"))
            picked = cache.pick_extrema(pts, per_side)
            out.append(picked)
            total += len(picked)
        if total:
            self.log_signal.emit(
                "极值点标注：每个分子最多 %d 个极大 + %d 个极小，共 %d 个"
                % (per_side, per_side, total))
            self.log_signal.emit(
                "  提示：标注值取自 surfanalysis.pdb 的 B-factor，与 atomsurface.txt "
                "的逐原子值可差 0.5~2 kcal/mol，属正常（采样点不同），排序趋势一致。")
        else:
            self.log_signal.emit("⚠ 未从 surfanalysis.pdb 解析到极值点，跳过数值标注")
        return out

    def _do_run(self):
        p = self.params
        action = p['action']
        mode = p['mode']
        bundles = p['bundles']
        multiwfn_exe = p['multiwfn_exe']
        vmd_exe = p['vmd_exe']
        vmd_cwd = p.get('vmd_cwd') or ''
        resolution = p.get('resolution') or (2000, 1500)
        color_low = p['color_low']
        color_high = p['color_high']
        pt_size = p['pt_size']
        show_colorbar = p['show_colorbar']
        iso_material = p.get('iso_material') or tclgen.DEFAULT_ISO_MATERIAL
        iso_opacity = float(p.get('iso_opacity') or tclgen.DEFAULT_ISO_OPACITY)
        label_extrema = bool(p.get('label_extrema'))
        label_count = int(p.get('label_count') or tclgen.DEFAULT_LABEL_COUNT)
        output_path = p.get('output_path')
        ws = p['workspace']
        save_computed = p.get('save_computed', True)
        callback_port = p.get('callback_port', 0)

        self.busy_signal.emit(True)
        self.progress_signal.emit(0)
        self.status_signal.emit("准备...")

        required = MODE_REQUIRES.get(mode, frozenset())
        n = len(bundles)
        if n == 0:
            raise RuntimeError("没有输入文件")

        # 临时区锚定到首个分子的同名文件夹：<数据目录>/<主名>/_espcalc/
        # （脚本、ASCII 暂存、计算中间态都收在该分子自己的目录里，
        #  不再散落在数据目录下与 fchk 平级）
        anchor_dir = default_bundle_folder(bundles[0].source_fchk)
        ws.anchor(anchor_dir)
        self.log_signal.emit(f"临时区: {ws.root}")

        # ── 1) 预检：决定每个分子要算哪几步 ──
        plan = []
        total_steps = 0
        for b in bundles:
            need = {}
            # 注意：ALL 模式的 VMD 脚本只加载 ISO + EXT，不加载 mol/vtx，
            # 因此不计算 PT 步骤（旧版在 ALL 下白算一次 PT）。
            if mode == "pt":
                need["pt"] = not b.has_all(MODE_REQUIRES["pt"])
            if mode in ("iso", "all"):
                need["iso"] = not b.has_all(MODE_REQUIRES["iso"])
            if mode in ("ext", "all"):
                need["ext"] = not b.has_all(MODE_REQUIRES["ext"])
            plan.append(need)
            total_steps += sum(1 for v in need.values() if v)

        self.log_signal.emit(
            f"模式 {mode.upper()}｜{n} 个分子｜需计算 {total_steps} 步，"
            f"其余直接复用")
        for i, b in enumerate(bundles, 1):
            self.log_signal.emit(
                f"  [{i}] {os.path.basename(b.source_fchk)}"
                f"  ← {b.layout or '无缓存'}（{b.summary(mode)}）")
            for kind, a in sorted(b.artifacts.items()):
                if a.note:
                    self.log_signal.emit(f"      · {kind}: {a.note}")
            if b.conflict_note:
                self.log_signal.emit(f"      ! {b.conflict_note}")

        if total_steps and not os.path.isfile(multiwfn_exe):
            raise RuntimeError(f"需要计算但未找到 Multiwfn：{multiwfn_exe}")

        # 版本只在"本次要算东西"时探测一次：算出的产物会和旧产物混在一个
        # bundle 里，版本不同时提醒一句。复用为主时不去多起一个进程。
        mw_version = cache.probe_multiwfn_version(multiwfn_exe) if total_steps else ""
        if mw_version:
            self.log_signal.emit(f"Multiwfn 版本：{mw_version}")
        for b in bundles:
            diff, old = cache.version_differs(b.manifest, mw_version)
            if diff:
                self.log_signal.emit(
                    f"  ⚠ {os.path.basename(b.source_fchk)}: bundle 由 "
                    f"Multiwfn {old} 生成，当前为 {mw_version}。"
                    "已有产物照旧复用；如需全链数值一致，删掉该目录的 "
                    "bundle.json 再算一次即可。")

        # ── 2) 逐分子装配 ──
        systems = []
        completed = 0
        for idx, b in enumerate(bundles):
            if self._abort_flag:
                self.log_signal.emit("[ABORT] 用户终止")
                self.busy_signal.emit(False)
                self.finished_signal.emit(
                    {'ok': False, 'action': action, 'error': 'aborted'})
                return

            sysno = idx + 1
            self.log_signal.emit("\n" + "=" * 50)
            self.log_signal.emit(
                f"分子 {sysno}/{n}: {os.path.basename(b.source_fchk)}")

            have = {k: a.path for k, a in b.artifacts.items() if a.path}
            need = plan[idx]
            stdout_parts = []

            for step in ("pt", "iso", "ext"):
                if step not in need:
                    continue
                req = MODE_REQUIRES[step]
                if not need[step]:
                    self.log_signal.emit(
                        "  [复用] %s: %s" % (step.upper(), " / ".join(sorted(req))))
                    continue
                want = {k for k in req if not have.get(k)}
                # 措辞强调"正在算"：旧文案「[计算] ISO（缺 density / esp）」
                # 被理解成"缺文件所以停下"，其实这一行就是自动补算的开始。
                self.log_signal.emit(
                    "  [计算] %s：缺少 %s，正在调用 Multiwfn 补算…"
                    % (step.upper(), " / ".join(sorted(want))))
                self.status_signal.emit(
                    f"[{sysno}/{n}] 正在计算 {step.upper()} "
                    f"（缺 {' / '.join(sorted(want))}），可点 [■ 停止] 中断")
                cb = self._progress_cb(completed, max(total_steps, 1),
                                      f"{sysno}/{n}")
                t0 = time.time()
                got, out = self._compute_step(
                    step, want, multiwfn_exe, b, sysno, ws, save_computed, cb)
                have.update(got)
                if out:
                    stdout_parts.append(out)
                completed += 1
                self.log_signal.emit(
                    "  [完成] %s 用时 %.0f s" % (step.upper(), time.time() - t0))
                self.progress_signal.emit(
                    int(completed / max(total_steps, 1) * 90))

            missing = [k for k in required if not have.get(k)]
            if missing:
                raise RuntimeError(
                    f"{os.path.basename(b.source_fchk)} 缺少必要产物: "
                    + ", ".join(sorted(missing)))

            if save_computed:
                if stdout_parts:
                    self._write_text_artifacts(b, "\n".join(stdout_parts))
                # 纯复用时不传版本，write_manifest 会保留旧记录，不会把
                # 老产物的来源"洗"成当前版本。
                self._update_manifest(b, have, mw_version)

            systems.append({k: have[k] for k in required})
            for k in sorted(required):
                self.log_signal.emit(f"    {k}: {have[k]}")

        # ── 3) 非 ASCII 路径降级 ──
        if any(not cache.is_ascii_path(v)
               for s in systems for v in s.values()):
            self.log_signal.emit(
                "⚠ 检测到非 ASCII 路径，启用兼容拷贝模式（VMD 使用 Tcl 8.5）")
            systems = [ws.ascii_stage(s) for s in systems]

        # ── 4) 生成脚本 ──
        self.log_signal.emit("\n" + "=" * 50)
        self.log_signal.emit("生成 VMD 脚本...")
        self.status_signal.emit("生成 VMD 脚本...")
        self.progress_signal.emit(95)

        extrema_labels = self._collect_extrema_labels(
            mode, systems, label_extrema, label_count)

        script = tclgen.generate_vmd_script(
            mode, ws.script_dir, systems, color_low, color_high,
            pt_size=pt_size, show_colorbar=show_colorbar,
            material=iso_material, opacity=iso_opacity,
            # 交互预览用 GLSL（材质特效完整）；无头渲染必须用 Normal，
            # 否则 VMD 在文本模式下会报 "Illegal rendering mode: GLSL"。
            rendermode=("GLSL" if action == "preview" else "Normal"),
            extrema_labels=extrema_labels)
        self.log_signal.emit(f"VMD 脚本: {script}")

        extrema_unit = "kcal/mol"
        for s in systems:
            if s.get("extrema"):
                extrema_unit = cache.detect_esp_unit(s["extrema"])
                break

        if action == "preview":
            vmd_port = find_free_port()
            with open(script, "a", encoding="utf-8") as f:
                f.write(socket_tcl_snippet(vmd_port, callback_port))

            cwd = vmd_cwd if (vmd_cwd and os.path.isdir(vmd_cwd)) else ws.script_dir
            self.log_signal.emit(f"启动 VMD 预览 (交互模式, 端口 {vmd_port})...")
            self.status_signal.emit("启动 VMD...")
            self.progress_signal.emit(100)

            cmd = '"{0}" -e "{1}"'.format(vmd_exe, script)
            vmd_proc = subprocess.Popen(cmd, shell=True, cwd=cwd)
            self.log_signal.emit("VMD 已启动，请在 VMD 窗口中调整视角")
            self.log_signal.emit("调整好后点击 [渲染当前视角] 按钮出图")

            self.finished_signal.emit({
                'ok': True, 'action': 'preview',
                'vmd_port': vmd_port, 'vmd_proc': vmd_proc,
                'vmd_dir': ws.script_dir, 'mode': mode,
                'extrema_unit': extrema_unit,
                'computed_steps': total_steps,
            })
            return

        if not output_path:
            output_path = default_render_path(bundles[0].source_fchk, ".tga")
        # VMD 直接把图写到目标路径，目录不存在会静默失败
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)),
                        exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"无法创建输出目录 {output_path}: {e}")
        self.log_signal.emit(f"无头渲染 -> {output_path} ...")
        self.status_signal.emit(f"渲染中: {os.path.basename(output_path)}")
        self.progress_signal.emit(98)

        render_tcl = ws.script_path("_esp_render.tcl")
        res_w, res_h = resolution
        with open(render_tcl, "w", encoding="utf-8") as f:
            f.write(tclgen.render_tcl(script, output_path, res_w, res_h))

        # 先记下渲染前的状态：VMD 在 Windows 上即使渲染成功、日志显示
        # "Rendering complete"，进程退出码也可能是 127（实测 VMD 1.9.4a53），
        # 因此不能只看 returncode，必须以产物是否真的写出为准。
        before = None
        if os.path.isfile(output_path):
            try:
                before = (os.path.getsize(output_path),
                          os.path.getmtime(output_path))
            except OSError:
                before = None

        render_cmd = '"{0}" -dispdev text -e "{1}"'.format(vmd_exe, render_tcl)
        render_result = subprocess.run(render_cmd, shell=True,
                                      cwd=ws.script_dir,
                                      capture_output=True, text=True,
                                      timeout=300)

        produced = False
        if os.path.isfile(output_path):
            try:
                after = (os.path.getsize(output_path),
                         os.path.getmtime(output_path))
                produced = after[0] > 0 and after != before
            except OSError:
                produced = False

        if produced:
            if render_result.returncode != 0:
                self.log_signal.emit(
                    f"  注: VMD 退出码 {render_result.returncode}，"
                    f"但图片已生成（VMD 在 Windows 无头渲染后会返回非 0）")
            self.log_signal.emit(
                f"✓ 渲染完成: {output_path}  ({res_w}x{res_h})")
            self.status_signal.emit(
                f"✓ 渲染完成: {os.path.basename(output_path)}")
            self.progress_signal.emit(100)
            result = {'ok': True, 'action': 'render',
                      'output_path': output_path,
                      'extrema_unit': extrema_unit,
                      'computed_steps': total_steps}
        else:
            self.log_signal.emit("✗ 渲染失败（未生成图片）")
            self.status_signal.emit("✗ 渲染失败")
            tail = ((render_result.stderr or "") + (render_result.stdout or ""))
            for line in tail.strip().split("\n")[-15:]:
                if line.strip():
                    self.log_signal.emit(f"  | {line.strip()}")
            result = {'ok': False, 'action': 'render'}
        self.finished_signal.emit(result)

    # ── 单步计算 ──

    _STEP_CMD = {"pt": CMD_ESPPT, "iso": CMD_ESPISO, "ext": CMD_ESPEXT}
    _STEP_PRODUCES = {
        "pt": ("mol", "vtx"),
        "iso": ("density", "esp"),
        "ext": ("mol", "vtx", "extrema"),
    }

    def _compute_step(self, step, want, multiwfn_exe, bundle, sysno, ws,
                      save_computed, progress_cb):
        """跑一次 Multiwfn，返回 (kind->最终路径, stdout)。

        中间态落在该分子同名文件夹下的 `<主名>/_espcalc/sysN/`；
        产物按需归位到 bundle.out_dir，只覆盖本次判定为缺失/失效的规范名文件。
        """
        base = bundle.out_dir or os.path.dirname(
            os.path.abspath(bundle.source_fchk))
        calc = ws.calc_subdir(f"{sysno}_{step}", base)
        # 用 ASCII 名调用 Multiwfn：避免中文路径在 cmd.exe 重定向下失效
        fch_local = os.path.join(calc, f"sys{sysno}.fch")
        try:
            shutil.copy2(bundle.source_fchk, fch_local)
        except OSError as e:
            raise RuntimeError(f"复制 fchk 失败: {e}")

        extra_args = "-ESPrhoiso 0.001" if step == "iso" else ""
        ok, stdout = run_multiwfn(multiwfn_exe, fch_local,
                                  self._STEP_CMD[step], calc,
                                  extra_args=extra_args,
                                  progress_cb=progress_cb,
                                  log_cb=self.log_signal.emit,
                                  proc_box=self._proc_box)
        if self._proc_box.get("aborted"):
            raise RuntimeError(f"{step.upper()} 已被用户中止")
        if not ok:
            rc = self._proc_box.get("returncode")
            hint = ""
            if self._proc_box.get("timed_out"):
                hint = "（长时间无任何输出，已按卡死终止）"
            elif rc not in (None, 0, 24):
                hint = f"（Multiwfn 退出码 {rc}）"
            raise RuntimeError(f"{step.upper()} 计算失败{hint}，详见运行日志")

        out_dir = bundle.out_dir if save_computed else ""
        must = [k for k in self._STEP_PRODUCES[step] if k in want]
        kinds = list(must)
        if save_computed:
            # 顺带产出的其它规范产物（EXT 也会写 mol.pdb / vtx.pdb）：
            # 目标目录里还没有就一并收下，后续 PT 模式即可直接复用。
            for k in self._STEP_PRODUCES[step]:
                if k in kinds:
                    continue
                dst = os.path.join(out_dir, CANONICAL_NAME[k])
                if (os.path.isfile(os.path.join(calc, CANONICAL_NAME[k]))
                        and not os.path.isfile(dst)):
                    kinds.append(k)

        got = cache.promote_files(calc, out_dir, kinds, overwrite=True)
        if save_computed:
            self.log_signal.emit(
                f"    → 产物已保存到 {out_dir}"
                "（与输入文件同名的文件夹，下次直接复用）")
        else:
            self.log_signal.emit(
                f"    → 未勾选「计算后保存中间文件」，产物仅留在临时区 {calc}")
        missing = [k for k in must if k not in got]
        if missing:
            raise RuntimeError(
                f"{step.upper()} 未产出: {', '.join(sorted(missing))}")

        bonus = [k for k in kinds if k not in must]
        if bonus:
            self.log_signal.emit("    （顺带收下: %s）" % ", ".join(sorted(bonus)))

        leftover = [k for k in self._STEP_PRODUCES[step] if k not in kinds
                    and os.path.isfile(os.path.join(calc,
                                                    CANONICAL_NAME[k]))]
        if leftover:
            self.log_signal.emit(
                "    （附带产出未回写: %s）" % ", ".join(sorted(leftover)))
        return got, stdout

    #: 状态栏只显示"有事发生"的行，关键词不命中就不刷新
    _STATUS_KEEP = re.compile(
        r"(export|calculat|load|wait|progress|done|saved|analyz|generat|"
        r"surface|grid|basin|optimiz|read|finish|error|warn|%|step)", re.I)

    def _progress_cb(self, completed, total, tag):
        def cb(line):
            if not line or not line.strip():
                return
            stripped = line.strip()
            if len(stripped) < 3:
                return
            for sp in ("========", "--------", "Multiwfn", "http://",
                       "Version", "Cite", "forrtl", "Image  ",
                       "KERNEL32", "ntdll"):
                if sp in stripped:
                    return
            # Multiwfn 的交互菜单会整屏回显（"5 Multiply all grid data"…），
            # 逐行刷到状态栏会把真正的进度淹没，直接丢掉。
            if _MW_MENU_RE.match(stripped):
                return
            pct_val, msg = _parse_progress(line)
            if len(msg) > 78:
                msg = msg[:75] + "..."
            base = completed / total
            if pct_val is not None:
                self.status_signal.emit(f"[{tag}] {msg}")
                self.progress_signal.emit(min(99, int((base + pct_val / total) * 90)))
                return
            if self._STATUS_KEEP.search(stripped):
                self.status_signal.emit(f"[{tag}] {msg}")
        return cb

    def _write_text_artifacts(self, bundle, stdout):
        """把 Multiwfn stdout 落为 medinfo.txt / atomsurface.txt。"""
        if not stdout:
            return
        d = bundle.out_dir
        try:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, CANONICAL_NAME["stdout"]), "w",
                      encoding="utf-8") as f:
                f.write(stdout)
            seg = cache.extract_atomsurface(stdout)
            if seg:
                with open(os.path.join(d, CANONICAL_NAME["atomsurface"]), "w",
                          encoding="utf-8") as f:
                    f.write(seg)
        except OSError:
            pass

    def _update_manifest(self, bundle, have, multiwfn_version=""):
        extrema_unit = None
        if have.get("extrema"):
            extrema_unit = cache.detect_esp_unit(have["extrema"])
        cache.write_manifest(
            bundle.out_dir, bundle.source_fchk,
            {k: v for k, v in have.items() if v},
            multiwfn_version=multiwfn_version,
            extrema_unit=extrema_unit, app_version=APP_VERSION)


class AreaAnalysisWorker(QThread):
    """Background thread for ESP area distribution analysis."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    busy_signal = pyqtSignal(bool)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self._abort_flag = False
        self._proc_box = {}

    def abort(self):
        self._abort_flag = True
        self._proc_box["abort"] = True
        kill_proc_tree(self._proc_box.get("proc"))

    def run(self):
        params = self.params
        input_files = params['input_files']
        multiwfn_exe = params['multiwfn_exe']
        work_dir = params['work_dir']
        range_low = params['range_low']
        range_high = params['range_high']
        n_bins = params['n_bins']
        bundles = params.get('bundles') or []

        self.busy_signal.emit(True)
        self.status_signal.emit("正在计算 ESP 分面面积分布...")
        self.log_signal.emit("")
        self.log_signal.emit("━━━ ESP 分区面积分布分析 ━━━")
        self.log_signal.emit(f"范围: {range_low} ~ {range_high} kcal/mol, 分区数: {n_bins}")

        all_data = []
        n_total = len(input_files)
        for idx, fch_path in enumerate(input_files):
            if self._abort_flag:
                self.log_signal.emit("[ABORT] 用户终止")
                break

            sys_num = idx + 1
            fch_name = os.path.basename(fch_path)
            self.log_signal.emit(f"\n分析文件 {sys_num}/{n_total}: {fch_name}")

            # 该分子的临时区也放进它自己的文件夹：<主名>/_espcalc/area_sysN
            # 目录不可写时退回共享临时区，不让整批分析中断
            base_dir = default_bundle_folder(fch_path) if fch_path else work_dir
            tmp_dir = os.path.join(base_dir, cache.CALC_DIR_NAME,
                                   f"area_sys{sys_num}")
            try:
                os.makedirs(tmp_dir, exist_ok=True)
            except OSError as e:
                self.log_signal.emit(f"  ⚠ 无法创建临时区 {tmp_dir}: {e}，改用共享临时区")
                tmp_dir = os.path.join(work_dir, f"area_sys{sys_num}")
                os.makedirs(tmp_dir, exist_ok=True)

            # ── 先尝试复用已缓存的 Multiwfn stdout（仅当范围与分区数一致）──
            data = None
            b = bundles[idx] if idx < len(bundles) else None
            if b and b.path("stdout"):
                try:
                    with open(b.path("stdout"), "r", encoding="utf-8",
                              errors="replace") as f:
                        cached = _parse_area_output(f.read())
                except OSError:
                    cached = []
                if cached and _area_matches(cached, range_low, range_high, n_bins):
                    data = cached
                    self.log_signal.emit("  复用已缓存的 stdout（范围与分区数一致）")
                elif cached:
                    self.log_signal.emit(
                        "  缓存 stdout 的分区参数与本次不同，需重算")

            ok = True
            if data is None:
                fch_tmp = os.path.join(tmp_dir, f"sys{sys_num}.fch")
                try:
                    shutil.copy2(fch_path, fch_tmp)
                except OSError as e:
                    self.log_signal.emit(f"  复制 fchk 失败: {e}")
                    continue

                def area_cb(line):
                    stripped = line.strip()
                    # 与主流程一致：菜单回显不刷状态栏，否则真正的进度会被淹没
                    if len(stripped) > 3 and not _MW_MENU_RE.match(stripped):
                        if len(stripped) > 70:
                            stripped = stripped[:67] + "..."
                        self.status_signal.emit(
                            f"[面积分析 {sys_num}/{n_total}] {stripped}")
                    pct, _ = _parse_progress(line)
                    if pct is not None:
                        self.progress_signal.emit(int(((idx + pct) / n_total) * 100))

                ok, data, area_stdout = run_multiwfn_area_dist(
                    multiwfn_exe, fch_tmp, tmp_dir,
                    range_low=range_low, range_high=range_high,
                    n_bins=n_bins, unit_code=3,
                    progress_cb=area_cb, log_cb=self.log_signal.emit,
                    proc_box=self._proc_box,
                )
                if self._proc_box.get("aborted"):
                    self.log_signal.emit("[ABORT] 面积分析已中止")
                    self.busy_signal.emit(False)
                    self.finished_signal.emit(False)
                    return
                self._persist_stdout(b, tmp_dir, area_stdout)

            if data:
                # 存完整路径：出图时要按文件定位各自同名文件夹
                all_data.append((fch_path, data))
                n_found = len(data)
                total_area = sum(d[1] for d in data)
                self.log_signal.emit(f"  已获取 {n_found} 个分区数据, 总表面积 = {total_area:.2f} Å²")
            else:
                if not ok:
                    self.log_signal.emit("  Multiwfn 返回异常且未解析到面积分布数据")
                else:
                    self.log_signal.emit("  Multiwfn 正常完成但未解析到面积分布数据")

        if not all_data:
            self.log_signal.emit("\n✗ 未获取到有效面积分布数据")
            self.busy_signal.emit(False)
            self.status_signal.emit("✗ 分析失败")
            self.finished_signal.emit(False)
            return

        # 每个分子的图与数据都写进它自己的同名文件夹（与渲染图、中间产物同处）
        for fch_path, data in all_data:
            out_dir = default_bundle_folder(fch_path)
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                self.log_signal.emit(f"✗ 无法创建目录 {out_dir}: {e}")
                continue
            base = os.path.splitext(os.path.basename(fch_path))[0]
            chart_path = os.path.join(out_dir, f"{base}_esp_area.png")
            self.log_signal.emit(f"\n生成柱形图: {chart_path}")
            # 标题不带文件名：出图即用，避免标题里混入 "-xxx.fchk"
            result_path = plot_esp_area_histogram(
                data, chart_path,
                title="ESP Area Distribution",
                xlabel="ESP (kcal/mol)",
            )
            if result_path:
                self.log_signal.emit(f"✓ 图表已保存: {result_path}")
                try:
                    os.startfile(result_path)
                except Exception:
                    pass
            else:
                self.log_signal.emit("✗ 图表生成失败")

            data_path = os.path.join(out_dir, f"{base}_esp_area_data.txt")
            saved = save_area_data_file(data, data_path)
            if saved:
                self.log_signal.emit(f"✓ 数据文件已保存: {saved}")

        self.progress_signal.emit(100)
        self.status_signal.emit("✓ ESP 分区面积图完成")
        self.busy_signal.emit(False)
        self.finished_signal.emit(True)

    def _persist_stdout(self, bundle, tmp_dir, stdout):
        """把面积分析的 stdout 并回 medinfo.txt，供下次离线重解析。"""
        if bundle is None or not bundle.out_dir or not stdout:
            return
        try:
            os.makedirs(bundle.out_dir, exist_ok=True)
            path = os.path.join(bundle.out_dir, CANONICAL_NAME["stdout"])
            old = ""
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8",
                              errors="replace") as f:
                        old = f.read()
                except OSError:
                    old = ""
            with open(path, "w", encoding="utf-8") as f:
                if old:
                    f.write(old.rstrip("\n") + "\n\n")
                f.write(stdout)
            self.log_signal.emit("  已缓存 stdout → medinfo.txt")
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════
#  UI Text Dictionary
#
#  v2.3.6 起只保留中文界面，字典从 {"zh": ..., "en": ...} 收敛成纯字符串。
#  文案集中在这里，改措辞不必翻部件代码。
# ═══════════════════════════════════════════════════════════════════

TR = {
    "tab_analysis": "分析与绘图",
    "tab_path": "路径设置",
    "input_files": "输入文件 (.fch / .fchk)",
    "path_settings": "路径设置",
    "mode_settings": "分析模式与设置",
    "run_log": "运行日志",
    "add_file": "添加文件",
    "add_dir": "添加目录",
    "clear_list": "清空列表",
    "browse": "浏览",
    "save_cfg": "保存路径配置",
    "detect_range": "检测 ESP 范围",
    "mode": "模式:",
    "color_low": "色彩下限:",
    "color_high": "色彩上限:",
    "hint_unit": "(PT模式单位kcal/mol, ISO模式单位a.u.)",
    "pt_size": "点大小(PT):",
    "resolution": "渲染分辨率:",
    "output": "输出路径:",
    "opacity": "透明度:",
    "colorbar": "显示色彩刻度轴 (Color Scale Bar)",
    "label_extrema": "标注极值点数值",
    "label_count": "每侧数量:",
    "pt_short": "PT 顶点着色",
    "iso_short": "ISO 等值面",
    "ext_short": "EXT 极值点",
    "all_short": "ALL 全部叠加",
    "pt_mode": "PT (顶点着色)",
    "iso_mode": "ISO (等值面着色)",
    "ext_mode": "EXT (极值点)",
    "all_mode": "ALL (全部叠加)",
    "btn_preview": "▶ VMD 预览",
    "btn_render_view": "渲染当前视角",
    "btn_pick": "查询极值点",
    "btn_render": "▼ 渲染输出",
    "btn_area": "ESP 分区面积图",
    "btn_stop": "■ 停止",
    "output_ph": "留空 = 存到 <输入主名>/<输入主名>_esp.png",
    "cache_dir": "缓存目录:",
    "verify": "校验策略:",
    "save_computed": "计算后保存中间文件（下次直接复用）",
    "precheck": "预检中间文件",
}

# ═══════════════════════════════════════════════════════════════════
#  Slider / Toggle selectors
#
#  数字选择框（QSpinBox）换成滑块 [─────●─────] 值；
#  布尔选项换成胶囊滑动开关。对外保留原控件的常用方法名
#  （value / setValue / isChecked / setChecked / stateChanged ...），
#  调用方无需关心底层换了控件。
# ═══════════════════════════════════════════════════════════════════

class IntSlider(QWidget):
    """整数滑块。API 与 QSpinBox 的常用子集一致（range / value / setValue）。"""

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None, label_width=32, slider_width=120):
        super().__init__(parent)
        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(1, 10)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(1)
        self._slider.setMinimumWidth(slider_width)
        self._slider.setCursor(Qt.PointingHandCursor)

        self._value_label = QLabel("1", self)
        self._value_label.setObjectName("SliderValue")
        self._value_label.setMinimumWidth(label_width)
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._value_label, 0)

        self._slider.valueChanged.connect(self._on_value_changed)

    def setRange(self, lo, hi):
        self._slider.setRange(int(lo), int(hi))
        self._refresh_label(self._slider.value())

    def setMinimum(self, v):
        self._slider.setMinimum(int(v))

    def setMaximum(self, v):
        self._slider.setMaximum(int(v))

    def minimum(self):
        return self._slider.minimum()

    def maximum(self):
        return self._slider.maximum()

    def setValue(self, v):
        self._slider.setValue(int(v))

    def value(self):
        return self._slider.value()

    def setToolTip(self, text):
        super().setToolTip(text)
        self._slider.setToolTip(text)
        self._value_label.setToolTip(text)

    def _refresh_label(self, v):
        self._value_label.setText(str(v))

    def _on_value_changed(self, v):
        self._refresh_label(v)
        self.valueChanged.emit(v)


class ToggleSwitch(QWidget):
    """开关式复选框（左开关 + 右文字），API 与 QCheckBox 常用子集一致。

    stateChanged 兼容 QCheckBox 的取值：0 = 未选，2 = 已选。
    """

    stateChanged = pyqtSignal(int)
    toggled = pyqtSignal(bool)

    TRACK_W = 42
    TRACK_H = 22
    GAP = 8

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text
        self._checked = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        # 布局在高度不够时会压到 11 px，圆角胶囊会被削平，这里兜住最小高度
        self.setMinimumHeight(self.TRACK_H + 4)

    # ── QCheckBox 兼容 API ──
    def text(self):
        return self._text

    def setText(self, t):
        self._text = t or ""
        self.updateGeometry()
        self.update()

    def isChecked(self):
        return self._checked

    def setChecked(self, on):
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        self.update()
        self.stateChanged.emit(2 if on else 0)
        self.toggled.emit(on)

    def click(self):
        if self.isEnabled():
            self.setChecked(not self._checked)

    def sizeHint(self):
        fm = self.fontMetrics()
        w = self.TRACK_W + self.GAP + (fm.horizontalAdvance(self._text)
                                      if self._text else 0) + 2
        h = max(self.TRACK_H, fm.height()) + 4
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()

    # ── 交互 ──
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.pos()):
            self.click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)

    # ── 绘制 ──
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        enabled = self.isEnabled()
        pal = theme.active_palette()

        track_rect = QRectF(0, (self.height() - self.TRACK_H) / 2.0,
                            self.TRACK_W, self.TRACK_H)
        radius = self.TRACK_H / 2.0

        if self._checked:
            # 开启：青色渐变轨道 + 外发光
            if enabled:
                glow = QColor(pal["ACC"])
                glow.setAlpha(46)
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(track_rect.adjusted(-2, -2, 2, 2),
                                  radius + 2, radius + 2)
                grad = QLinearGradient(track_rect.topLeft(),
                                       track_rect.bottomRight())
                grad.setColorAt(0.0, QColor(pal["ACC_HI"]))
                grad.setColorAt(1.0, QColor(pal["ACC_DK"]))
                p.setBrush(grad)
            else:
                p.setBrush(QColor(pal["LINE_HI"]))
        else:
            p.setBrush(QColor(pal["TRACK_OFF"]) if enabled
                       else QColor(pal["CARD2"]))

        p.setPen(QPen(QColor(pal["ACC_DK"] if self._checked and enabled
                             else pal["LINE"]), 1))
        p.drawRoundedRect(track_rect, radius, radius)
        p.setPen(Qt.NoPen)

        # 滑块头
        d = self.TRACK_H - 6
        x = (self.TRACK_W - d - 3) if self._checked else 3
        if self._checked and enabled:
            knob = QColor("#FFFFFF")
        elif enabled:
            knob = QColor(pal["KNOB_OFF"])
        else:
            knob = QColor(pal["TXT_DIM"])
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, (self.height() - d) / 2.0, d, d))

        if self._text:
            if not enabled:
                color = pal["TXT_DIM"]
            elif self._checked:
                color = pal["ACC_HI"]
            else:
                color = pal["TXT_MID"]
            p.setPen(QColor(color))
            text_rect = QRectF(self.TRACK_W + self.GAP, 0,
                               self.width() - self.TRACK_W - self.GAP,
                               self.height())
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self._text)
        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Header — 顶部品牌条（渐变底 + 发丝线 + 版本徽标）
# ═══════════════════════════════════════════════════════════════════

class HeaderBar(QWidget):
    """自绘顶栏：左侧图标 + 标题/副标题，右侧版本徽标与工具按钮。

    QSS 画不出渐变叠加与发光发丝线，所以这里用 paintEvent 手绘，
    颜色全部取自 theme.active_palette()，切主题后 update() 即生效。
    """

    HEIGHT = 68

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 16, 8)
        lay.setSpacing(12)

        # 图标（缺失时用一块发光的占位色块）
        self.logo = QLabel()
        self.logo.setFixedSize(38, 38)
        icon = app_icon()
        if not icon.isNull():
            self.logo.setPixmap(icon.pixmap(36, 36))
        else:
            self.logo.setObjectName("LogoPlaceholder")
        lay.addWidget(self.logo, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("BrandTitle")
        f = self.title_lbl.font()
        f.setPointSizeF(15.5)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        self.title_lbl.setFont(f)

        self.sub_lbl = QLabel(subtitle)
        self.sub_lbl.setObjectName("BrandSub")
        fs = self.sub_lbl.font()
        fs.setPointSizeF(7.5)
        fs.setLetterSpacing(QFont.AbsoluteSpacing, 1.1)
        self.sub_lbl.setFont(fs)

        text_col.addWidget(self.title_lbl)
        text_col.addWidget(self.sub_lbl)
        lay.addLayout(text_col)
        lay.addStretch()

        # 作者标注（介于 stretch 与版本徽标之间，弱化显示）
        self.author_lbl = QLabel("By Dongxu Yi Rebuild")
        self.author_lbl.setObjectName("AuthorTag")
        self.author_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.author_lbl, 0, Qt.AlignVCenter)

        self.version_lbl = QLabel(f"v{APP_VERSION}")
        self.version_lbl.setObjectName("VersionChip")
        self.version_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.version_lbl, 0, Qt.AlignVCenter)

    def add_tool(self, widget):
        """把额外按钮追加到右侧工具区。"""
        self.layout().addWidget(widget, 0, Qt.AlignVCenter)
        return widget

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.active_palette()
        r = self.rect()

        grad = QLinearGradient(0, 0, r.width(), r.height())
        grad.setColorAt(0.0, QColor(pal["CARD"]))
        grad.setColorAt(0.5, QColor(pal["CARD2"]))
        grad.setColorAt(1.0, QColor(pal["CARD"]))
        p.fillRect(r, QBrush(grad))

        # 左上角一点青色辉光
        glow = QColor(pal["ACC"])
        glow.setAlpha(26)
        rg = QRadialGradient(0, 0, 260)
        rg.setColorAt(0.0, glow)
        glow2 = QColor(pal["ACC"])
        glow2.setAlpha(0)
        rg.setColorAt(1.0, glow2)
        p.fillRect(QRectF(0, 0, 260, r.height()), QBrush(rg))

        # 底部发丝线：两端淡、中间亮
        line = QLinearGradient(0, 0, r.width(), 0)
        c0 = QColor(pal["LINE"]); c0.setAlpha(0)
        c1 = QColor(pal["LINE_HI"])
        c2 = QColor(pal["ACC"]); c2.setAlpha(150)
        c3 = QColor(pal["LINE"]); c3.setAlpha(0)
        line.setColorAt(0.0, c0)
        line.setColorAt(0.35, c1)
        line.setColorAt(0.62, c2)
        line.setColorAt(1.0, c3)
        p.setPen(QPen(QBrush(line), 1))
        p.drawLine(0, r.height() - 1, r.width(), r.height() - 1)
        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Main Window
# ═══════════════════════════════════════════════════════════════════

class ESPSurfaceGUI(QMainWindow):
    pick_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.input_files = []
        self.bundles = []                       # 最近一次预检的 Bundle 列表
        self.ws = JobWorkspace()                # 脚本与计算临时区（延迟锚定到数据目录）
        self.vmd_process = None
        self.vmd_port = None
        self.vmd_render_dir = None
        self.callback_port = None
        self.callback_server = None
        self.callback_thread = None
        self.esp_unit = "kcal/mol"
        # 输出路径是否由用户手动指定（手动输入 / 浏览选择）。
        # 只有 True 时才沿用框里的字面路径；否则按当前输入文件动态推导，
        # 避免上一个分子的路径被静默复用、把新图写到旧位置。
        self._output_user_set = False

        self._worker = None
        self._vmd_persist_sock = None
        self.pick_signal.connect(self._handle_pick)

        self._init_ui()
        self._apply_texts()
        self._apply_theme()
        self._sync_surface_controls()
        self._log("ESP Surface Visualization GUI (PyQt5) 已启动")
        self._log("临时区: <输入主名>/_espcalc/（可手动删除）")
        # 打包成 exe 后配置目录换了地方，默认路径往往不存在：
        # 首次启动自动定位到的工具路径要说一声，并写回配置，下次不再扫描。
        auto = [k for k in (self.config.get("_autodetected") or []) if k]
        if auto:
            label = {"multiwfn": "Multiwfn", "vmd": "VMD", "tachyon": "Tachyon"}
            self._log("自动定位到工具路径：" + "、".join(label.get(k, k) for k in auto)
                      + "（可在 [路径设置] 页修改后保存）")
            try:
                save_config(self.config)
            except OSError as e:
                self._log(f"（自动定位结果未能写入配置: {e}）")

        # 标题栏只留程序名：版本号与作者已在顶栏各显示一次，别重复
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(app_icon())
        self._fit_to_screen()

    def _fit_to_screen(self):
        """按屏幕可用区域决定初始窗口尺寸（原来写死 950×1100）。

        写死 950 宽小于布局的自然宽度（≈1420）：模式单选按钮会被压到
        120 px，四个模式名叠在一起；写死 1100 高又比不少笔记本的可用高度还大，
        标题栏会被挤到屏幕外。现在：
          - 最小尺寸 = 布局自己要求的最小尺寸（并夹到屏幕内）；
          - 初始尺寸 = 内容真正需要的高度（见 `_content_hint`），屏幕放不下才缩；
          - 宽度给一个舒适的默认值，避免一打开就贴着控件最小宽度；
          - 居中摆放。
        """
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            ax, ay, aw, ah = g.x(), g.y(), g.width(), g.height()
        else:
            ax, ay, aw, ah = 0, 0, 1920, 1080
        # 60 / 80 是标题栏 + 任务栏的安全余量
        max_w, max_h = max(900, aw - 60), max(640, ah - 80)
        need_w, need_h = self._content_hint()
        min_hint = self.minimumSizeHint()
        min_w = min(max(min_hint.width(), 1000), max_w)
        min_h = min(max(min_hint.height(), 640), max_h)
        self.setMinimumSize(min_w, min_h)

        w = min(max(need_w, DEFAULT_WIDTH), max_w)
        h = min(max(need_h, min_h), max_h)
        self.resize(w, h)
        self.move(ax + (aw - w) // 2, ay + (ah - h) // 2)

    def _content_hint(self):
        """打开窗口要把两个 Tab 页完整放下，需要多大。

        `QScrollArea::sizeHint()` 被 Qt 截断成「36 个字符宽 × 24 行高」，
        窗口的 sizeHint 因此远小于真实内容（实测 714 vs 1153），照它开窗
        必然一进来就挂着滚动条。这里把被截断的那部分差值补回去。
        """
        base = self.sizeHint()
        dw = dh = 0
        for i in range(self.left_tabs.count()):
            sa = self.left_tabs.widget(i)
            page = sa.widget() if isinstance(sa, QScrollArea) else None
            if page is None:
                continue
            need, got = page.sizeHint(), sa.sizeHint()
            dw = max(dw, need.width() - got.width())
            dh = max(dh, need.height() - got.height())
        # +12 留给可能出现的滚动条与描边，避免刚好差 1~2 px 就冒出滑块
        return base.width() + dw + 12, base.height() + dh + 12

    def closeEvent(self, event):
        self._close_persist_sock()
        self._stop_callback_server()
        if self.vmd_process:
            try:
                self.vmd_process.terminate()
                self.vmd_process.wait(timeout=5)
            except Exception:
                pass
        self._cleanup_work_dir()
        super().closeEvent(event)

    def _cleanup_work_dir(self):
        """只清理程序自建的临时目录；同名文件夹里的 _espcalc/ 保留。"""
        try:
            self.ws.cleanup()
            if self.ws.temporary:
                self._log("已清理系统临时工作区")
            elif self.ws.root:
                self._log(f"计算临时文件保留在: {self.ws.root}（可手动删除）")
        except Exception as e:
            self._log(f"清理临时工作区失败: {e}")

    def _work_root(self):
        """计算临时目录根。锚定到首个输入文件同名文件夹下的 `_espcalc/`。"""
        if not self.ws.root:
            if self.input_files:
                self.ws.anchor(default_bundle_folder(self.input_files[0]))
            else:
                self.ws.ensure_temp()
        return self.ws.root

    # ══ UI Construction ══

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 顶栏（品牌 + 版本 + 作者）──
        self.header = HeaderBar(
            "ESPViewer",
            "ELECTROSTATIC POTENTIAL SURFACE  ·  MULTIWFN + VMD")

        root.addWidget(self.header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)

        # ── Main Panel (Tabbed) ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.left_tabs = QTabWidget()

        # Tab 1: Analysis & Run
        tab_analysis = QWidget()
        tab_analysis_layout = QVBoxLayout(tab_analysis)
        tab_analysis_layout.setContentsMargins(4, 4, 4, 4)
        tab_analysis_layout.setSpacing(6)
        self._build_input_files(tab_analysis_layout)
        self._build_mode_settings(tab_analysis_layout)
        self._build_control_bar(tab_analysis_layout)
        self._build_progress(tab_analysis_layout)
        self._build_log(tab_analysis_layout)
        self.left_tabs.addTab(self._scroll_page(tab_analysis), "分析与绘图")

        # Tab 2: Path Settings
        tab_path = QWidget()
        tab_path_layout = QVBoxLayout(tab_path)
        tab_path_layout.setContentsMargins(4, 4, 4, 4)
        tab_path_layout.setSpacing(6)
        self._build_path_settings(tab_path_layout)
        tab_path_layout.addStretch()
        self.left_tabs.addTab(self._scroll_page(tab_path), "路径设置")

        left_layout.addWidget(self.left_tabs)
        body_layout.addWidget(left, stretch=1)
        root.addWidget(body, stretch=1)

    @staticmethod
    def _scroll_page(page):
        """把 Tab 页套进滚动区：高度不够时滚动，而不是把行压扁。

        QGridLayout 拿到的可用高度小于自身的 minimumSizeHint 时不会滚动，
        而是按比例压缩行高——控件本身仍保持最小高度，于是模式开关直接压到
        下一行的文字上。套一层 QScrollArea（widgetResizable）后内层页保留自己的
        最小高度，窗口再矮也只多出一条滚动条；空间够时滚动条不出现，观感不变。
        """
        scroll = QScrollArea()
        scroll.setObjectName("TabScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    def _build_path_settings(self, parent_layout):
        self._path_settings_gb = QGroupBox("路径设置")
        gb = self._path_settings_gb
        gl = QGridLayout()
        gl.setVerticalSpacing(4)
        gl.setHorizontalSpacing(6)

        # Multiwfn
        gl.addWidget(QLabel("Multiwfn:"), 0, 0)
        self.mwfn_edit = QLineEdit(self.config["multiwfn"])
        self.mwfn_edit.setPlaceholderText("Multiwfn.exe 路径")
        gl.addWidget(self.mwfn_edit, 0, 1)
        btn_mwfn = QPushButton("浏览")
        btn_mwfn.setCursor(Qt.PointingHandCursor)
        btn_mwfn.clicked.connect(lambda: self._browse_exe(self.mwfn_edit, "Multiwfn.exe"))
        gl.addWidget(btn_mwfn, 0, 2)

        # VMD
        gl.addWidget(QLabel("VMD exe:"), 1, 0)
        self.vmd_edit = QLineEdit(self.config["vmd"])
        self.vmd_edit.setPlaceholderText("vmd.exe 路径")
        gl.addWidget(self.vmd_edit, 1, 1)
        btn_vmd = QPushButton("浏览")
        btn_vmd.setCursor(Qt.PointingHandCursor)
        btn_vmd.clicked.connect(lambda: self._browse_exe(self.vmd_edit, "vmd.exe"))
        gl.addWidget(btn_vmd, 1, 2)

        # VMD Dir
        gl.addWidget(QLabel("VMD 目录:"), 2, 0)
        self.vmdir_edit = QLineEdit(self.config.get("vmd_dir", ""))
        self.vmdir_edit.setPlaceholderText("VMD 工作目录")
        gl.addWidget(self.vmdir_edit, 2, 1)
        btn_vmdir = QPushButton("浏览")
        btn_vmdir.setCursor(Qt.PointingHandCursor)
        btn_vmdir.clicked.connect(lambda: self._browse_dir(self.vmdir_edit, "选择 VMD 工作目录"))
        gl.addWidget(btn_vmdir, 2, 2)

        # Tachyon
        gl.addWidget(QLabel("Tachyon:"), 3, 0)
        self.tachyon_edit = QLineEdit(self.config.get("tachyon", DEFAULT_TACHYON))
        self.tachyon_edit.setPlaceholderText("tachyon_WIN32.exe 路径")
        gl.addWidget(self.tachyon_edit, 3, 1)
        btn_tachyon = QPushButton("浏览")
        btn_tachyon.setCursor(Qt.PointingHandCursor)
        btn_tachyon.clicked.connect(lambda: self._browse_exe(self.tachyon_edit, "tachyon_WIN32.exe"))
        gl.addWidget(btn_tachyon, 3, 2)

        # 中间文件缓存根目录（可选）
        self._lbl_cache = QLabel("缓存目录:")
        gl.addWidget(self._lbl_cache, 4, 0)
        self.cache_root_edit = QLineEdit(self.config.get("cache_root", ""))
        self.cache_root_edit.setPlaceholderText(
            "可选：服务器结果集中存放的根目录（留空则只搜索 fchk 同级/子目录）")
        gl.addWidget(self.cache_root_edit, 4, 1)
        btn_cache = QPushButton("浏览")
        btn_cache.setCursor(Qt.PointingHandCursor)
        btn_cache.clicked.connect(
            lambda: self._browse_dir(self.cache_root_edit, "选择缓存根目录"))
        gl.addWidget(btn_cache, 4, 2)

        # 校验策略
        self._lbl_verify = QLabel("校验策略:")
        gl.addWidget(self._lbl_verify, 5, 0)
        self.verify_combo = QComboBox()
        self.verify_combo.addItem("自动（有 manifest 严格，无则告警）", "auto")
        self.verify_combo.addItem("严格（仅信任有 manifest 的产物）", "strict")
        self.verify_combo.addItem("信任现有文件（不校验）", "off")
        self.verify_combo.setToolTip(
            "自动：有 manifest 就严格校验，没有仍然采用（标⚠）\n"
            "严格：只信任有 manifest 且校验通过的产物\n"
            "不校验：有同名文件就用（信任模式）")
        idx = self.verify_combo.findData(self.config.get("verify", "auto"))
        self.verify_combo.setCurrentIndex(max(0, idx))
        gl.addWidget(self.verify_combo, 5, 1, 1, 2)

        # 计算后保存中间文件
        self.save_computed_cb = ToggleSwitch("计算后保存中间文件（下次直接复用）")
        self.save_computed_cb.setToolTip(
            "勾选后，Multiwfn 算出的中间文件留在数据目录，下次直接复用")
        self.save_computed_cb.setChecked(
            str(self.config.get("save_computed", "true")).lower()
            not in ("0", "false", "no", "off"))
        gl.addWidget(self.save_computed_cb, 6, 1, 1, 2)

        # 预检按钮
        self.btn_precheck = QPushButton("预检中间文件")
        self.btn_precheck.setCursor(Qt.PointingHandCursor)
        self.btn_precheck.setObjectName("PrimaryBtn")
        self.btn_precheck.clicked.connect(self._action_precheck)
        gl.addWidget(self.btn_precheck, 4, 3)

        # Save config
        self._btn_save_cfg = QPushButton("保存路径配置")
        self._btn_save_cfg.setCursor(Qt.PointingHandCursor)
        self._btn_save_cfg.setObjectName("PrimaryBtn")
        self._btn_save_cfg.setMinimumHeight(34)
        self._btn_save_cfg.clicked.connect(self._save_paths)
        # 原来跨 7 行铺成一整条竖按钮，视觉上像根柱子；改成右上角一个常规按钮
        gl.addWidget(self._btn_save_cfg, 0, 4, 1, 1, Qt.AlignTop)

        gl.setColumnStretch(1, 1)
        # Right-align labels
        for i in range(gl.count()):
            w = gl.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gb.setLayout(gl)
        parent_layout.addWidget(gb)

    def _build_input_files(self, parent_layout):
        self._input_files_gb = QGroupBox("输入文件 (.fch / .fchk)")
        gb = self._input_files_gb
        vl = QVBoxLayout()

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("添加文件")
        self._btn_add.setCursor(Qt.PointingHandCursor)
        self._btn_add.setObjectName("PrimaryBtn")
        self._btn_add.clicked.connect(self._add_files)
        btn_row.addWidget(self._btn_add)

        self._btn_adddir = QPushButton("添加目录")
        self._btn_adddir.setCursor(Qt.PointingHandCursor)
        self._btn_adddir.setObjectName("PrimaryBtn")
        self._btn_adddir.clicked.connect(self._add_dir)
        btn_row.addWidget(self._btn_adddir)

        self._btn_clear_files = QPushButton("清空列表")
        self._btn_clear_files.setCursor(Qt.PointingHandCursor)
        self._btn_clear_files.setObjectName("DangerBtn")
        self._btn_clear_files.clicked.connect(self._clear_files)
        btn_row.addWidget(self._btn_clear_files)

        self.lbl_filecount = QLabel("(0 个文件)")
        btn_row.addWidget(self.lbl_filecount)

        btn_row.addStretch()

        vl.addLayout(btn_row)

        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")
        self.file_list.setMaximumHeight(100)
        vl.addWidget(self.file_list)
        gb.setLayout(vl)
        parent_layout.addWidget(gb)

    def _build_mode_settings(self, parent_layout):
        self._mode_settings_gb = QGroupBox("分析模式与设置")
        gb = self._mode_settings_gb
        gl = QGridLayout()
        gl.setVerticalSpacing(4)
        gl.setHorizontalSpacing(6)

        # 模式：四个滑动开关（互斥，打开一个其余自动关闭）
        self._lbl_mode = QLabel("模式:")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(self._lbl_mode)
        self.mode_switches = {}
        self._mode_guard = False
        for key, txt, tip in (
            ("pt", "PT 顶点着色", "PT：每个表面顶点按 ESP 着色（点云）"),
            ("iso", "ISO 等值面", "ISO：半透明等值面着色"),
            ("ext", "EXT 极值点", "EXT：只画表面极大/极小值球"),
            ("all", "ALL 全部叠加", "ALL：PT + ISO + EXT 叠加显示"),
        ):
            sw = ToggleSwitch(txt)
            sw.setToolTip(tip + "\n（四个开关互斥，打开一个其余自动关闭）")
            sw.toggled.connect(lambda on, k=key: self._on_mode_toggled(k, on))
            self.mode_switches[key] = sw
            mode_row.addWidget(sw)
        mode_row.addStretch()
        gl.addLayout(mode_row, 0, 0, 1, 8)

        # Color scale
        self._lbl_clow = QLabel("色彩下限:")
        gl.addWidget(self._lbl_clow, 1, 0)
        self.clow_edit = QLineEdit("-50")
        self.clow_edit.setMaximumWidth(80)
        gl.addWidget(self.clow_edit, 1, 1)

        self._lbl_chigh = QLabel("色彩上限:")
        gl.addWidget(self._lbl_chigh, 1, 2)
        self.chigh_edit = QLineEdit("50")
        self.chigh_edit.setMaximumWidth(80)
        gl.addWidget(self.chigh_edit, 1, 3)

        # 说明文字单独一行并允许换行：挤在色彩上下限右边时，
        # 窗口一窄它就被压成半截（“(PT模式单位kcal/mol, ISO模式单位a.u.)” 只露出前半）。
        # 但它独占一整行后已经不可能被挤窄，所以**不开 wordWrap**：带换行的 QLabel 会让
        # 整条布局 hasHeightForWidth() 变成 True，QScrollArea 于是按“这个宽度下的自然高度”
        # 给页面定最小高度（919px），窗口明明够高也会常年挂着一条滚动条。
        self._hint_lbl = QLabel("(PT模式单位kcal/mol, ISO模式单位a.u.)")
        self._hint_lbl.setObjectName("HintLabel")
        gl.addWidget(self._hint_lbl, 8, 0, 1, 8)

        self.clow_edit.editingFinished.connect(self._on_color_range_changed)
        self.chigh_edit.editingFinished.connect(self._on_color_range_changed)

        self._btn_detect_range = QPushButton("检测 ESP 范围")
        self._btn_detect_range.setCursor(Qt.PointingHandCursor)
        self._btn_detect_range.setObjectName("GhostBtn")
        self._btn_detect_range.setMaximumWidth(150)
        self._btn_detect_range.clicked.connect(self._action_detect_range)
        gl.addWidget(self._btn_detect_range, 1, 4, 1, 2, Qt.AlignLeft)

        # Point size
        self._lbl_ptsize = QLabel("点大小(PT):")
        gl.addWidget(self._lbl_ptsize, 2, 0)
        self.ptsize_edit = QLineEdit("2.0")
        self.ptsize_edit.setMaximumWidth(80)
        gl.addWidget(self.ptsize_edit, 2, 1)

        # Resolution
        self._lbl_res = QLabel("渲染分辨率:")
        gl.addWidget(self._lbl_res, 2, 2)
        self.res_combo = QComboBox()
        # QSS 里的 min-width 会盖掉 setMinimumWidth（80 + padding ≈ 102 px），
        # 结果 "2000x1500" 被截成 "2000x1"：这里改用 objectName 单独放宽。
        self.res_combo.setObjectName("ResCombo")
        self.res_combo.addItems(["2000x1500", "1200x900", "3000x2250", "4000x3000"])
        self.res_combo.setCurrentText("2000x1500")
        self.res_combo.setMinimumWidth(150)
        self.res_combo.setToolTip(
            "渲染分辨率：越高越清晰，也越慢（默认 2000x1500）")
        gl.addWidget(self.res_combo, 2, 3)

        # Output
        self._lbl_output = QLabel("输出路径:")
        gl.addWidget(self._lbl_output, 3, 0)
        self.output_edit = QLineEdit("")
        self.output_edit.setPlaceholderText(
            "留空则自动存到 <输入主名>/<输入主名>_esp.png")
        self.output_edit.setToolTip(
            "留空（推荐）：每个分子的图存到与输入文件同名的文件夹里，\n"
            "不同分子互不覆盖；手动填写则严格按填写的路径保存。\n"
            "清空此框即可恢复为自动。")
        # 只有键盘输入才算"用户指定"；程序 setText 自动填充不置位。
        self.output_edit.textEdited.connect(self._on_output_edited)
        gl.addWidget(self.output_edit, 3, 1, 1, 3)
        btn_output = QPushButton("浏览")
        btn_output.setCursor(Qt.PointingHandCursor)
        btn_output.clicked.connect(self._browse_output)
        gl.addWidget(btn_output, 3, 4)

        # Opacity slider
        self._lbl_opacity = QLabel("表面透明度:")
        gl.addWidget(self._lbl_opacity, 4, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(int(tclgen.DEFAULT_ISO_OPACITY * 100))
        self.opacity_slider.setToolTip(
            "等值面（ISO/ALL）的透明度：越小越通透，能看清内部分子骨架。\n"
            "只影响 ISO / ALL 模式；PT 点云不受影响。")
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        gl.addWidget(self.opacity_slider, 4, 1, 1, 3)
        self.opacity_value_label = QLabel(f"{tclgen.DEFAULT_ISO_OPACITY:.2f}")
        self.opacity_value_label.setMinimumWidth(40)
        # 左对齐：紧贴滑块末端，否则右对齐会被推到列尾，中间空一大截
        self.opacity_value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        gl.addWidget(self.opacity_value_label, 4, 4)

        # Surface material
        self._lbl_material = QLabel("表面材质:")
        gl.addWidget(self._lbl_material, 5, 0)
        self.material_combo = QComboBox()
        self.material_combo.addItem("半透明 (Transparent)", "Transparent")
        self.material_combo.addItem("玻璃泡 (GlassBubble)", "GlassBubble")
        self.material_combo.addItem("不透明 (Opaque)", "Opaque")
        self.material_combo.setCurrentIndex(0)
        self.material_combo.setMinimumWidth(210)
        self.material_combo.setToolTip(
            "半透明 (Transparent) = 教程 MEP 画图效果（推荐）\n"
            "玻璃泡 (GlassBubble) = 更通透，突出内部骨架\n"
            "Opaque = 传统不透明表面")
        # 记录"当前材质对应的推荐透明度"，用来判断用户有没有手动改过滑块
        self._last_material_default = tclgen.MATERIAL_DEFAULT_OPACITY[
            tclgen.DEFAULT_ISO_MATERIAL]
        self.material_combo.currentIndexChanged.connect(
            self._on_material_changed)
        gl.addWidget(self.material_combo, 5, 1, 1, 3)

        # Colorbar toggle（滑动开关）
        self.colorbar_cb = ToggleSwitch("显示色彩刻度轴 (Color Scale Bar)")
        self.colorbar_cb.setChecked(False)
        self.colorbar_cb.setToolTip("在图上叠加 ESP 色彩刻度轴（右上角）")
        self.colorbar_cb.stateChanged.connect(self._on_colorbar_toggle)
        gl.addWidget(self.colorbar_cb, 6, 1, 1, 3)

        # Extrema value labels (EXT / ALL)（滑动开关）
        self.extrema_label_cb = ToggleSwitch("标注极值点数值")
        self.extrema_label_cb.setChecked(False)
        self.extrema_label_cb.setToolTip(
            "在等值面外侧标出表面极大/极小值（kcal/mol），颜色与极值球一致：\n"
            "黄 = 极大，蓝 = 极小。\n"
            "数值取自 surfanalysis.pdb，与 atomsurface.txt 的逐原子值会差\n"
            "零点几到一两 kcal/mol，属正常（采样点不同），排序趋势一致。\n"
            "只对 EXT / ALL 生效。")
        gl.addWidget(self.extrema_label_cb, 7, 1)

        self._lbl_count = QLabel("每侧数量:")
        gl.addWidget(self._lbl_count, 7, 2)

        self.extrema_count_spin = IntSlider(label_width=28)
        self.extrema_count_spin.setRange(1, 30)
        self.extrema_count_spin.setValue(tclgen.DEFAULT_LABEL_COUNT)
        self.extrema_count_spin.setMinimumWidth(160)
        self.extrema_count_spin.setToolTip(
            "每侧（极大 / 极小）标注几个，按 |值| 取最大的")
        gl.addWidget(self.extrema_count_spin, 7, 3, 1, 2)
        self.extrema_label_cb.stateChanged.connect(self._sync_surface_controls)

        gl.setColumnStretch(1, 1)
        gl.setColumnStretch(3, 1)
        for i in range(gl.count()):
            w = gl.itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gb.setLayout(gl)
        parent_layout.addWidget(gb)

        # 初始模式 = PT。放在所有控件建好之后再点，否则开关回调会
        # 提前去读还没创建的 clow_edit / chigh_edit。
        self._mode_guard = True
        self.mode_switches["pt"].setChecked(True)
        self._mode_guard = False

    def _build_control_bar(self, parent_layout):
        ctrl = QHBoxLayout()

        self.btn_preview = QPushButton("▶ VMD 预览")
        self.btn_preview.setCursor(Qt.PointingHandCursor)
        self.btn_preview.setObjectName("PrimaryBtn")
        self.btn_preview.clicked.connect(self._action_preview)
        ctrl.addWidget(self.btn_preview)

        self.btn_render_view = QPushButton("渲染当前视角")
        self.btn_render_view.setCursor(Qt.PointingHandCursor)
        self.btn_render_view.setObjectName("GhostBtn")
        self.btn_render_view.setEnabled(False)
        self.btn_render_view.clicked.connect(self._action_render_view)
        ctrl.addWidget(self.btn_render_view)

        self.btn_pick = QPushButton("查询极值点")
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        self.btn_pick.setObjectName("GhostBtn")
        self.btn_pick.setEnabled(False)
        self.btn_pick.clicked.connect(self._action_pick)
        ctrl.addWidget(self.btn_pick)

        self.btn_render_out = QPushButton("▼ 渲染输出")
        self.btn_render_out.setCursor(Qt.PointingHandCursor)
        self.btn_render_out.setObjectName("PrimaryBtn")
        self.btn_render_out.clicked.connect(self._action_render)
        ctrl.addWidget(self.btn_render_out)
        self.btn_render_out.hide()

        self.btn_area_chart = QPushButton("ESP 分区面积图")
        self.btn_area_chart.setCursor(Qt.PointingHandCursor)
        self.btn_area_chart.setObjectName("GhostBtn")
        self.btn_area_chart.clicked.connect(self._action_area_chart)
        ctrl.addWidget(self.btn_area_chart)

        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setObjectName("DangerBtn")
        self.btn_stop.clicked.connect(self._action_stop)
        ctrl.addWidget(self.btn_stop)

        ctrl.addStretch()
        parent_layout.addLayout(ctrl)

    def _build_progress(self, parent_layout):
        prog_fr = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        prog_fr.addWidget(self.progress_bar)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("StatusLabel")
        prog_fr.addWidget(self.lbl_status)
        parent_layout.addLayout(prog_fr)

    def _build_log(self, parent_layout):
        self._log_gb = QGroupBox("运行日志")
        gb = self._log_gb
        vl = QVBoxLayout()
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setObjectName("LogView")
        vl.addWidget(self.log_edit)
        gb.setLayout(vl)
        parent_layout.addWidget(gb, stretch=1)

    # ══ UI Callbacks ══

    def _log(self, msg):
        self.log_edit.append(msg)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _set_progress(self, value):
        self.progress_bar.setValue(max(0, min(100, value)))

    def _set_status(self, msg):
        self.lbl_status.setText(msg)

    def _set_busy(self, busy=True):
        state = "normal" if not busy else "disabled"
        for btn in (self.btn_preview, self.btn_render_out, self.btn_area_chart):
            btn.setEnabled(not busy)
        if busy:
            self.btn_render_view.setEnabled(False)
            self.btn_pick.setEnabled(False)
        if not busy:
            self._sync_surface_controls()
        else:
            for w in (getattr(self, "opacity_slider", None),
                      getattr(self, "material_combo", None),
                      getattr(self, "opacity_value_label", None),
                      getattr(self, "extrema_label_cb", None),
                      getattr(self, "extrema_count_spin", None)):
                if w is not None:
                    w.setEnabled(False)

    # ══ 文案 ══

    def _tr(self, key, **fmt):
        s = TR.get(key, key)
        return s.format(**fmt) if fmt else s

    # ══ 主题 ══

    def _apply_theme(self):
        """应用配色：全局 QSS + QPalette + 自绘控件重绘。

        只有一套浅色色板（v2.3.6 去掉深色主题），启动时调一次即可；
        保留成方法是因为自绘控件（开关 / 顶栏）不吃 QSS，需要显式 update()。
        """
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.qss())

        for w in self.findChildren(QWidget):
            w.update()
        self.update()

    def _apply_texts(self):
        self.left_tabs.setTabText(0, self._tr("tab_analysis"))
        self.left_tabs.setTabText(1, self._tr("tab_path"))
        self._input_files_gb.setTitle(self._tr("input_files"))
        self._path_settings_gb.setTitle(self._tr("path_settings"))
        self._mode_settings_gb.setTitle(self._tr("mode_settings"))
        self._log_gb.setTitle(self._tr("run_log"))
        self._btn_add.setText(self._tr("add_file"))
        self._btn_adddir.setText(self._tr("add_dir"))
        self._btn_clear_files.setText(self._tr("clear_list"))
        self._btn_save_cfg.setText(self._tr("save_cfg"))
        self._btn_detect_range.setText(self._tr("detect_range"))
        self._lbl_mode.setText(self._tr("mode"))
        self._lbl_clow.setText(self._tr("color_low"))
        self._lbl_chigh.setText(self._tr("color_high"))
        self._hint_lbl.setText(self._tr("hint_unit"))
        self._lbl_ptsize.setText(self._tr("pt_size"))
        self._lbl_res.setText(self._tr("resolution"))
        self._lbl_output.setText(self._tr("output"))
        self._lbl_opacity.setText(self._tr("opacity"))
        self.colorbar_cb.setText(self._tr("colorbar"))
        self.extrema_label_cb.setText(self._tr("label_extrema"))
        self._lbl_count.setText(self._tr("label_count"))
        for key in ("pt", "iso", "ext", "all"):
            sw = getattr(self, "mode_switches", {}).get(key)
            if sw is not None:
                sw.setText(self._tr(f"{key}_short"))
        self.btn_preview.setText(self._tr("btn_preview"))
        self.btn_render_view.setText(self._tr("btn_render_view"))
        self.btn_pick.setText(self._tr("btn_pick"))
        self.btn_render_out.setText(self._tr("btn_render"))
        self.btn_area_chart.setText(self._tr("btn_area"))
        self.btn_stop.setText(self._tr("btn_stop"))
        self.output_edit.setPlaceholderText(self._tr("output_ph"))
        self._lbl_cache.setText(self._tr("cache_dir"))
        self._lbl_verify.setText(self._tr("verify"))
        self.save_computed_cb.setText(self._tr("save_computed"))
        self.btn_precheck.setText(self._tr("precheck"))

    def _browse_exe(self, edit, name):
        p, _ = QFileDialog.getOpenFileName(self, f"选择 {name}", "", "EXE (*.exe);;All (*)")
        if p:
            edit.setText(p)

    def _browse_dir(self, edit, title):
        d = QFileDialog.getExistingDirectory(self, title)
        if d:
            edit.setText(d)

    def _browse_output(self):
        p, _ = QFileDialog.getSaveFileName(self, "保存渲染输出", "", "TGA (*.tga);;PNG (*.png);;BMP (*.bmp)")
        if p:
            self._output_user_set = True
            self.output_edit.setText(p)

    def _on_output_edited(self, _text=""):
        """用户手动敲了路径 → 后续渲染尊重这个字面值。"""
        self._output_user_set = True

    def _default_output_path(self, ext=".png"):
        """默认输出路径；无输入文件时退回临时脚本目录。"""
        if self.input_files:
            return default_render_path(self.input_files[0], ext)
        return os.path.join(self.vmd_render_dir or self._work_root() or ".",
                            "esp_render" + ext)

    def _resolve_output_path(self, ext):
        """决定本次写哪个文件：手动指定优先，否则按输入文件推导。

        返回 (path, explicit)。explicit=True 表示这是用户写死的路径。
        """
        if self._output_user_set:
            t = self.output_edit.text().strip()
            if t:
                return t, True
        return self._default_output_path(ext), False

    def _sync_output_default(self):
        """输入文件变化后刷新输出框里的自动路径（不动用户手动填的值）。"""
        if self._output_user_set:
            return
        if self.input_files:
            self.output_edit.setText(self._default_output_path(".png"))
        else:
            self.output_edit.clear()

    def _save_paths(self):
        self.config.update({
            "multiwfn": self.mwfn_edit.text().strip(),
            "vmd": self.vmd_edit.text().strip(),
            "vmd_dir": self.vmdir_edit.text().strip(),
            "tachyon": self.tachyon_edit.text().strip(),
            "cache_root": self.cache_root_edit.text().strip(),
            "verify": self.verify_combo.currentData(),
            "save_computed": "true" if self.save_computed_cb.isChecked() else "false",
        })
        try:
            save_config(self.config)
            self._log(f"路径与缓存配置已保存: {CONFIG_FILE}")
        except OSError as e:
            self._log(f"✗ 配置保存失败: {e}")

    # ── 中间文件预检 ──

    def _resolver(self):
        return BundleResolver(
            cache_root=self.cache_root_edit.text().strip() or None,
            verify=self.verify_combo.currentData() or "auto")

    def _collect_bundles(self):
        """只读扫描，不做任何计算。"""
        resolver = self._resolver()
        self.bundles = resolver.locate_all(list(self.input_files))
        return self.bundles

    def _multiwfn_exe(self):
        """当前配置里的 Multiwfn 路径（控件还没建好时返回空串）。"""
        try:
            return self.mwfn_edit.text().strip()
        except AttributeError:
            return ""

    def _action_precheck(self):
        if not self.input_files:
            QMessageBox.information(self, "提示", "请先添加输入文件")
            return

        mode = self._get_mode()
        bundles = self._collect_bundles()

        dlg = QDialog(self)
        dlg.setWindowTitle("中间文件预检（只读）")
        dlg.setWindowIcon(app_icon())
        dlg.setMinimumSize(820, 380)
        outer = QVBoxLayout()
        outer.addWidget(QLabel(
            f"当前模式：<b>{mode.upper()}</b>　"
            f"✔ 命中且校验通过　⚠ 命中但未验证　✘ 缺失，将调用 Multiwfn"))

        grid = QTableWidget(len(bundles), 6)
        grid.setHorizontalHeaderLabels(
            ["文件", "PT (mol+vtx)", "ISO (density+esp)", "EXT (extrema)",
             "布局", "校验"])
        grid.verticalHeader().setVisible(False)
        grid.setEditTriggers(QTableWidget.NoEditTriggers)
        grid.setSelectionBehavior(QTableWidget.SelectRows)
        grid.setAlternatingRowColors(True)

        def cell(b, kinds):
            arts = [b.get(k) for k in kinds]
            if all(a is not None for a in arts):
                return "✔" if all(a.verified for a in arts) else "⚠"
            return "✘"

        def verify_text(b):
            tot = len(b.artifacts)
            if tot == 0:
                return "—"
            ver = sum(1 for a in b.artifacts.values() if a.verified)
            if ver == tot:
                return f"严格通过 ({tot})"
            if ver == 0:
                return f"未验证 ({tot})"
            return f"{ver}/{tot} 通过"

        need_steps = 0
        for r, b in enumerate(bundles):
            name_item = QTableWidgetItem(os.path.basename(b.source_fchk))
            if b.conflict_note:
                name_item.setToolTip(b.conflict_note)
            grid.setItem(r, 0, name_item)

            row = [("PT", ("mol", "vtx")), ("ISO", ("density", "esp")),
                   ("EXT", ("extrema",))]
            for c, (_label, kinds) in enumerate(row, start=1):
                txt = cell(b, kinds)
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                miss = [k for k in kinds if not b.get(k)]
                item.setToolTip("缺失: " + ", ".join(miss) if miss else "已命中")
                grid.setItem(r, c, item)

            layout = b.layout or "—"
            if b.conflict_note:
                layout += "（冲突）"
            grid.setItem(r, 4, QTableWidgetItem(layout))

            vit = QTableWidgetItem(verify_text(b))
            vit.setToolTip("\n".join(sorted(
                f"{k}: {a.note or '已校验'}" for k, a in b.artifacts.items()))
                or "无产物")
            grid.setItem(r, 5, vit)

            if mode == "pt" and cell(b, ("mol", "vtx")) == "✘":
                need_steps += 1
            if mode in ("iso", "all") and cell(b, ("density", "esp")) == "✘":
                need_steps += 1
            if mode in ("ext", "all") and cell(b, ("extrema",)) == "✘":
                need_steps += 1

        grid.resizeColumnsToContents()
        grid.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(grid)

        req = MODE_REQUIRES.get(mode, frozenset())
        fully = sum(1 for b in bundles if b.has_all(req))
        outer.addWidget(QLabel(
            f"共 {len(bundles)} 个文件：完全命中 {fully} 个；"
            f"当前模式预计需计算 <b>{need_steps}</b> 步。"))

        # 版本一致性提示：只提示，不影响可用性（产物校验只看 fchk 与网格质量）
        cur_ver = cache.probe_multiwfn_version(self._multiwfn_exe())
        diffs = []
        for b in bundles:
            diff, old = cache.version_differs(b.manifest, cur_ver)
            if diff:
                diffs.append(f"{os.path.basename(b.source_fchk)}（{old} → {cur_ver}）")
        if cur_ver:
            if diffs:
                lbl = QLabel(
                    "⚠ Multiwfn 版本与原产物不同：" + "；".join(diffs) +
                    "<br>已有产物<b>照旧可用</b>，不需要删 bundle.json；"
                    "若要让整条链路都用新版本重算，删掉对应目录的 "
                    "bundle.json 即可。")
                lbl.setWordWrap(True)
                outer.addWidget(lbl)
            else:
                outer.addWidget(QLabel(f"Multiwfn 版本：{cur_ver}"))

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        outer.addWidget(btns)
        dlg.setLayout(outer)
        dlg.exec_()

        for b in bundles:
            self._log(f"[预检] {os.path.basename(b.source_fchk)} → "
                      f"{b.layout or '无缓存'} | {b.summary(mode)}")
        self._set_status(
            f"预检完成：{len(bundles)} 个文件，{fully} 个完全命中")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择 .fch / .fchk 文件", "",
            "FCH/FCHK (*.fch *.fchk);;All (*)"
        )
        for f in files:
            if f not in self.input_files:
                self.input_files.append(f)
                self.file_list.addItem(f)
        self.lbl_filecount.setText(f"({len(self.input_files)} 个文件)")
        self._sync_output_default()

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择包含 .fch 文件的目录")
        if not d:
            return
        for ext in ("*.fch", "*.fchk"):
            for f in glob.glob(os.path.join(d, ext)):
                if f not in self.input_files:
                    self.input_files.append(f)
                    self.file_list.addItem(f)
        self.lbl_filecount.setText(f"({len(self.input_files)} 个文件)")
        self._sync_output_default()

    def _clear_files(self):
        self.input_files.clear()
        self.file_list.clear()
        self.lbl_filecount.setText("(0 个文件)")
        # 重新锚定临时区：`anchor()` 只认第一次，不复位的话清空后换分子，
        # 脚本还会落在上一个分子的 `<旧主名>/_espcalc/` 里。
        try:
            self.ws.cleanup()
        except Exception:
            pass
        self.ws = JobWorkspace()
        self._sync_output_default()

    # 每个模式切换时顺带把色彩范围调成该模式常用的量级
    MODE_COLOR_RANGE = {
        "pt": ("-50", "50"),
        "iso": ("-22", "22"),
        "ext": ("-50", "50"),
        "all": ("-22", "22"),
    }

    def _get_mode(self):
        try:
            for key, sw in self.mode_switches.items():
                if sw.isChecked():
                    return key
        except AttributeError:
            pass
        return "pt"

    def set_mode(self, mode):
        """按名称设置模式（pt/iso/ext/all）；互斥由开关回调保证。"""
        key = str(mode).lower()
        if key.isdigit():
            key = ("pt", "iso", "ext", "all")[int(key) % 4]
        sw = getattr(self, "mode_switches", {}).get(key)
        if sw is not None:
            sw.setChecked(True)

    def _on_mode_toggled(self, mode, on):
        """四个模式开关互斥：打开一个就关掉其余；不许全部关掉。"""
        if self._mode_guard:
            return
        self._mode_guard = True
        try:
            if not on:
                # 直接点当前模式时不让它关掉，否则会出现"没有模式"
                self.mode_switches[mode].setChecked(True)
                return
            for key, sw in self.mode_switches.items():
                if key != mode:
                    sw.setChecked(False)
        finally:
            self._mode_guard = False
        self._on_mode_change()

    def _on_mode_change(self):
        lo, hi = self.MODE_COLOR_RANGE.get(self._get_mode(), ("-50", "50"))
        self.clow_edit.setText(lo)
        self.chigh_edit.setText(hi)
        self._sync_surface_controls()

    def _sync_surface_controls(self):
        """透明度与材质只对 ISO / ALL；极值点标注只对 EXT / ALL。"""
        iso = self._get_mode() in ("iso", "all")
        ext = self._get_mode() in ("ext", "all")
        for w in (getattr(self, "opacity_slider", None),
                  getattr(self, "material_combo", None),
                  getattr(self, "opacity_value_label", None)):
            if w is not None:
                w.setEnabled(iso)
        if iso and self._iso_material() == "Opaque":
            self.opacity_slider.setEnabled(False)
            self.opacity_value_label.setEnabled(False)
        for w in (getattr(self, "extrema_label_cb", None),
                  getattr(self, "extrema_count_spin", None)):
            if w is not None:
                w.setEnabled(ext)
        if ext and not self._label_extrema_enabled():
            self.extrema_count_spin.setEnabled(False)

    def _validate_inputs(self, need_multiwfn=True):
        if not self.input_files:
            QMessageBox.critical(self, "错误", "请先添加输入文件")
            return False
        vmd_exe = self.vmd_edit.text()
        if not os.path.isfile(vmd_exe):
            QMessageBox.critical(self, "错误", f"VMD 不存在:\n{vmd_exe}")
            return False
        if need_multiwfn:
            multiwfn_exe = self.mwfn_edit.text()
            if not os.path.isfile(multiwfn_exe):
                QMessageBox.critical(self, "错误", f"Multiwfn 不存在:\n{multiwfn_exe}")
                return False
        try:
            float(self.clow_edit.text())
            float(self.chigh_edit.text())
            float(self.ptsize_edit.text())
        except ValueError:
            QMessageBox.critical(self, "错误", "色彩范围或点大小不是有效数字")
            return False
        return True

    def _get_params(self, action):
        mode = self._get_mode()
        save_computed = self.save_computed_cb.isChecked()
        try:
            rw, rh = self.res_combo.currentText().split("x")
            resolution = (int(rw), int(rh))
        except Exception:
            resolution = (2000, 1500)
        return {
            'action': action,
            'mode': mode,
            'input_files': list(self.input_files),
            'bundles': self._collect_bundles(),
            'multiwfn_exe': self.mwfn_edit.text(),
            'vmd_exe': self.vmd_edit.text(),
            'vmd_cwd': self.vmdir_edit.text().strip(),
            'color_low': float(self.clow_edit.text()),
            'color_high': float(self.chigh_edit.text()),
            'pt_size': float(self.ptsize_edit.text()),
            'iso_material': self._iso_material(),
            'iso_opacity': self._iso_opacity(),
            'show_colorbar': self.colorbar_cb.isChecked(),
            'label_extrema': self._label_extrema_enabled(),
            'label_count': self._label_extrema_count(),
            'output_path': self.output_edit.text() or None,
            'resolution': resolution,
            'workspace': self.ws,
            'save_computed': save_computed,
            'callback_port': self.callback_port or 0,
        }

    # ══ Actions ══

    def _need_multiwfn(self, mode, bundles):
        req = MODE_REQUIRES.get(mode, frozenset())
        return any(not b.has_all(req) for b in bundles)

    def _action_preview(self):
        mode = self._get_mode()
        bundles = self._collect_bundles()
        if not self._validate_inputs(
                need_multiwfn=self._need_multiwfn(mode, bundles)):
            return
        self._log("")
        self._log("━━━ VMD 预览 ━━━")
        if not self._need_multiwfn(mode, bundles):
            self._log("✓ 中间文件全部命中，本次不调用 Multiwfn")
        self._start_callback_server()
        self._run_job("preview")

    def _action_render(self):
        mode = self._get_mode()
        bundles = self._collect_bundles()
        if not self._validate_inputs(
                need_multiwfn=self._need_multiwfn(mode, bundles)):
            return
        # 未手动指定时，把"这次会写到哪"显示出来（按当前输入文件推导），
        # 换分子后再点会重新推导，不会沿用上一个分子的路径。
        if not self._output_user_set:
            self.output_edit.setText(self._default_output_path(".tga"))
        self._log("")
        self._log("━━━ 渲染输出 ━━━")
        self._run_job("render")

    def _action_render_view(self):
        if not self.vmd_port:
            QMessageBox.warning(self, "提示", "请先点击 [VMD 预览] 启动 VMD")
            return
        tachyon_exe = self.tachyon_edit.text().strip()
        if not os.path.isfile(tachyon_exe):
            QMessageBox.critical(self, "错误", f"Tachyon 不存在:\n{tachyon_exe}")
            return

        try:
            w_s, h_s = self.res_combo.currentText().split("x")
            resolution = (int(w_s), int(h_s))
        except (ValueError, AttributeError):
            resolution = (2000, 1500)

        output_path, explicit = self._resolve_output_path(".png")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)),
                        exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "错误", f"无法创建输出目录:\n{e}")
            return
        if explicit:
            self._log(f"输出路径（手动指定）: {output_path}")
        else:
            self.output_edit.setText(output_path)
            self._log(f"输出路径（自动）: {output_path}")
        if len(self.input_files) > 1:
            self._log(f"  注意：当前场景含 {len(self.input_files)} 个分子，"
                      "这张图是整体画面；单分子出图请只添加对应文件。")

        self.btn_render_view.setEnabled(False)

        class RenderViewWorker(QThread):
            log_signal = pyqtSignal(str)
            finished_signal = pyqtSignal(bool, str)

            def __init__(self, vmd_port, vmd_dir, tachyon_exe, output_path, resolution):
                super().__init__()
                self.vmd_port = vmd_port
                self.vmd_dir = vmd_dir
                self.tachyon_exe = tachyon_exe
                self.output_path = output_path
                self.resolution = resolution

            def run(self):
                try:
                    self.log_signal.emit(
                        f"\n正在渲染当前视角 ({self.resolution[0]}x{self.resolution[1]})..."
                    )
                    t0 = time.time()
                    result = render_current_view_tachyon(
                        self.vmd_port, self.vmd_dir,
                        self.tachyon_exe, self.output_path,
                        resolution=self.resolution,
                        log_cb=self.log_signal.emit,
                    )
                    dt = time.time() - t0
                    if result:
                        self.log_signal.emit(f"✓ 渲染完成 ({dt:.1f}s): {result}")
                        self.finished_signal.emit(True, result)
                    else:
                        self.log_signal.emit(f"✗ 渲染失败 ({dt:.1f}s)")
                        self.finished_signal.emit(False, "Tachyon 渲染失败，请检查日志")
                except Exception as e:
                    self.log_signal.emit(f"✗ 渲染错误: {e}")
                    self.finished_signal.emit(False, str(e))

        self._render_view_worker = RenderViewWorker(
            self.vmd_port, self.vmd_render_dir,
            tachyon_exe, output_path, resolution
        )
        self._render_view_worker.log_signal.connect(self._log)

        def on_render_view_done(ok, msg):
            self.btn_render_view.setEnabled(True)
            if ok:
                try:
                    os.startfile(msg)
                except Exception:
                    pass
            else:
                QMessageBox.critical(self, "渲染失败", msg)
        self._render_view_worker.finished_signal.connect(on_render_view_done)
        self._render_view_worker.start()

    def _action_pick(self):
        if not self.vmd_port:
            QMessageBox.warning(self, "提示", "请先点击 [VMD 预览] 启动 VMD")
            return
        resp = send_vmd_cmd(self.vmd_port, "mouse mode 4", timeout=3)
        if "ERROR" in resp:
            self._log(f"⚠ VMD 进入选取模式失败: {resp}")
            self._set_pick_mode_ui(False)
        else:
            self._log("")
            self._log("━━━ 查询极值点 ━━━")
            self._log("VMD 已进入选取模式，请点击极值点球查询 ESP 值")
            self._log("（C = 极大值点, O = 极小值点）")
            self._log("提示：请点击 surfanalysis.pdb 中的极值点球，不是分子骨架原子")
            self._set_status("选取模式：点击 VMD 中的极值点球（C/O 原子）")
            self._set_pick_mode_ui(True)

    def _set_pick_mode_ui(self, active):
        if active:
            self.btn_pick.setText("● 选取中...")
        else:
            self.btn_pick.setText("🔍 查询极值点")

    def _action_detect_range(self):
        """查询 ESP 范围：优先复用已有文本产物，最后才调用 Multiwfn。

        三级降级：
          1. atomsurface.txt / medinfo.txt 中的汇总行（秒出）
          2. surfanalysis.pdb 的 B-factor 极值（快）
          3. Multiwfn module 12→0（等于整张表面重算，最慢）
        """
        if not self.input_files:
            QMessageBox.critical(self, "错误", "请先添加输入文件")
            return

        fch_path = self.input_files[0]
        bundle = self._collect_bundles()[0]

        self._log("━━━ 查询 ESP 范围 ━━━")
        self._log(f"文件: {os.path.basename(fch_path)}")
        self._set_status("正在查询 ESP 范围...")

        result, source = None, ""

        # ── 1) 文本产物 + 2) surfanalysis.pdb 的 B-factor（都不调用 Multiwfn）──
        fast = detect_esp_range_fast(bundle)
        if fast:
            result = (fast[0], fast[1], "kcal/mol")
            source = fast[2]

        # ── 3) 回落到 Multiwfn 重算 ──
        if not result:
            multiwfn_exe = self.mwfn_edit.text()
            if not os.path.isfile(multiwfn_exe):
                self._log("✗ 无可用文本产物，且未找到 Multiwfn，无法计算范围")
                self._set_status("查询失败")
                return
            self._log("  未找到可复用的中间数据，正在调用 Multiwfn 重算（较慢）...")
            tmp_dir = os.path.join(self._work_root(), "_range_query")
            os.makedirs(tmp_dir, exist_ok=True)
            fch_tmp = os.path.join(tmp_dir, "tmp.fch")
            try:
                shutil.copy2(fch_path, fch_tmp)
            except OSError as e:
                self._log(f"文件复制失败: {e}")
                return
            ok, stdout = run_multiwfn(multiwfn_exe, fch_tmp,
                                      CMD_ESP_QUERY_RANGE, tmp_dir)
            if not ok:
                self._log("✗ Multiwfn 运行失败")
                self._set_status("查询失败")
                return
            result = parse_esp_range_text(stdout)
            if result:
                source = "Multiwfn 实时计算"
            if bundle.out_dir:
                try:
                    os.makedirs(bundle.out_dir, exist_ok=True)
                    with open(os.path.join(bundle.out_dir,
                                           CANONICAL_NAME["stdout"]),
                              "w", encoding="utf-8") as f:
                        f.write(stdout)
                except OSError:
                    pass

        if not result:
            self._log("✗ 无法解析 ESP 范围")
            self._set_status("解析失败")
            return

        # cache.parse_esp_range_text 返回的数值**已经是 kcal/mol**，
        # 这里不要再乘 AU（旧代码在 a.u. 分支乘了一次，结果大 627 倍）。
        low_val, high_val, _unit = result
        self._log(f"  数据来源: {source}")
        self.clow_edit.setText(f"{low_val:.2f}")
        self.chigh_edit.setText(f"{high_val:.2f}")
        self._log(f"ESP 范围: {low_val:.2f} ~ {high_val:.2f} kcal/mol")

        self._set_status("ESP 范围已填充 (kcal/mol)")
        self._on_color_range_changed()

    def _on_color_range_changed(self):
        """用户修改色彩上下限后，实时推送 mol scaleminmax 到已运行的 VMD。
        Text fields are always in kcal/mol; for ISO/ALL mode, convert to a.u. for VMD.
        """
        if not self.vmd_port:
            return
        try:
            low = float(self.clow_edit.text())
            high = float(self.chigh_edit.text())
        except ValueError:
            return
        mode = self._get_mode()
        nsystems = max(1, len(self.input_files))
        ids = tclgen.molid_map(mode, nsystems)
        self._log(f"色彩范围实时更新: {low} ~ {high}")
        if mode in ("iso", "all"):
            vmd_low = low / AU
            vmd_high = high / AU
            # ALL 模式下 ISO 与 EXT 是两组 mol，EXT 的 rep 1 不是等值面，
            # 因此只对 ISO 组（rep 1）下发。
            for mid in ids.get("iso", []):
                self._send_vmd_cmd_fast(
                    f"mol scaleminmax {mid} 1 {vmd_low} {vmd_high}")
        elif mode == "pt":
            for mid in ids.get("vtx", []):
                self._send_vmd_cmd_fast(
                    f"mol scaleminmax {mid} 0 {low} {high}")
        # Rebuild colorbar if visible
        if self.colorbar_cb.isChecked():
            tcl = (
                "catch {package require colorscalebar}; "
                "catch {::ColorScaleBar::delete_color_scale_bar}; "
                f'::ColorScaleBar::color_scale_bar 1.5 0.08 0 1 {low} {high} 10 16 0 0.82 -0.75 1 top 0 1 "ESP (kcal/mol)"'
            )
            self._send_vmd_cmd_fast(tcl)

    def _iso_molids(self):
        """当前模式下等值面对应的 VMD mol id 列表（预览里改材质用）。"""
        mode = self._get_mode()
        if mode not in ("iso", "all"):
            return []
        n = max(1, len(self.input_files))
        return tclgen.molid_map(mode, n).get("iso", []) or list(range(n))

    def _iso_material(self):
        """当前选择的等值面材质。"""
        try:
            return self.material_combo.currentData() or tclgen.DEFAULT_ISO_MATERIAL
        except AttributeError:
            return tclgen.DEFAULT_ISO_MATERIAL

    def _iso_opacity(self):
        try:
            return self.opacity_slider.value() / 100.0
        except AttributeError:
            return tclgen.DEFAULT_ISO_OPACITY

    def _label_extrema_enabled(self):
        try:
            return bool(self.extrema_label_cb.isChecked())
        except AttributeError:
            return False

    def _label_extrema_count(self):
        try:
            return max(1, int(self.extrema_count_spin.value()))
        except AttributeError:
            return tclgen.DEFAULT_LABEL_COUNT

    def _on_material_changed(self, _index=None):
        """切换材质：必要时联动透明度，并立即推到正在运行的 VMD。"""
        mat = self._iso_material()
        op = self._iso_opacity()
        new_default = tclgen.MATERIAL_DEFAULT_OPACITY.get(
            mat, tclgen.DEFAULT_ISO_OPACITY)
        # 用户没手动改过滑块（还停在上一材质的推荐值）→ 跟着材质走；
        # 手动改过就尊重用户的选择，不要突然跳值。
        if abs(op - self._last_material_default) < 1e-6 and \
                abs(op - new_default) > 1e-6:
            op = new_default
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(int(round(op * 100)))
            self.opacity_slider.blockSignals(False)
            self.opacity_value_label.setText(f"{op:.2f}")
        self._last_material_default = new_default
        # 不透明材质下透明度是无意义的，禁用滑块避免误导
        self.opacity_slider.setEnabled(mat != "Opaque")

        if self.vmd_port:
            for mid in self._iso_molids():
                self._send_vmd_cmd_fast(f"mol modmaterial 1 {mid} {mat}")
            for cmd in tclgen.material_tcl(mat, op):
                self._send_vmd_cmd_fast(cmd)
        self._log(f"表面材质: {mat}（透明度 {op:.2f}）")

    def _on_opacity_slider_changed(self, val):
        op = val / 100.0
        self.opacity_value_label.setText(f"{op:.2f}")
        mat = self._iso_material()
        if self.vmd_port and mat != "Opaque":
            self._send_vmd_cmd_fast(f"material change opacity {mat} {op:.2f}")

    def _send_vmd_cmd_fast(self, cmd):
        """通过持久化 TCP socket 向 VMD 发送一条 Tcl 命令。"""
        if not self.vmd_port:
            return
        try:
            if self._vmd_persist_sock is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(("127.0.0.1", self.vmd_port))
                self._vmd_persist_sock = sock
            self._vmd_persist_sock.sendall((cmd + "\n").encode("utf-8"))
            resp = b""
            try:
                self._vmd_persist_sock.settimeout(0.5)
                while True:
                    chunk = self._vmd_persist_sock.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in resp:
                        break
            except socket.timeout:
                pass
            self._vmd_persist_sock.settimeout(5)
        except Exception:
            self._close_persist_sock()

    def _close_persist_sock(self):
        """关闭 VMD 持久化 socket 连接。"""
        if self._vmd_persist_sock:
            try:
                self._vmd_persist_sock.close()
            except Exception:
                pass
            self._vmd_persist_sock = None

    def _on_colorbar_toggle(self, state):
        """Dynamically show/hide the VMD color scale bar."""
        if not self.vmd_port:
            return
        if state:
            try:
                lo = float(self.clow_edit.text())
                hi = float(self.chigh_edit.text())
            except ValueError:
                lo, hi = -22, 22
            tcl = (
                "catch {package require colorscalebar}; "
                "catch {::ColorScaleBar::delete_color_scale_bar}; "
                f'::ColorScaleBar::color_scale_bar 1.5 0.08 0 1 {lo} {hi} 10 16 0 0.82 -0.75 1 top 0 1 "ESP (kcal/mol)"'
            )
            self._send_vmd_cmd_fast(tcl)
            self._log(f"色彩刻度轴已显示 ({lo} ~ {hi} kcal/mol)")
        else:
            self._send_vmd_cmd_fast("catch {::ColorScaleBar::delete_color_scale_bar}")
            self._log("色彩刻度轴已隐藏")

    def _action_stop(self):
        """停止当前任务：真的结束 Multiwfn 进程，不只是等它算完。

        旧版 `abort()` 只置一个布尔，而这个标志只在"分子之间/步骤之间"被检查，
        所以正在跑的那一步（大体系 ESP 动辄十几分钟）根本停不下来，
        界面还一直停在 busy、其它按钮全是灰的——用户看到的就是"点了停止没反应"。
        """
        running = self._worker is not None and self._worker.isRunning()
        if running:
            self._log("正在停止：已中断当前 Multiwfn 计算，不必等这一步算完…")
            self._set_status("正在停止…")
            self._worker.abort()
        self._close_persist_sock()
        os.system("taskkill /F /IM vmd.exe 2>nul")
        if running:
            # 兜底：万一线程卡在不可中断的系统调用里，8 s 后也要把界面放开，
            # 不能让用户面对一排永远灰着的按钮。
            QTimer.singleShot(8000, self._ensure_idle_after_stop)
        else:
            self._set_busy(False)
            self._log("当前没有运行中的任务，已清理 VMD 预览")
        self._sync_surface_controls()

    def _ensure_idle_after_stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._log("⚠ 后台线程仍未退出（可能卡在系统调用），界面已解锁；"
                      "如再启动任务失败，请重启程序")
        self._set_busy(False)
        self._set_status("已停止")

    def _action_area_chart(self):
        if not self.input_files:
            QMessageBox.critical(self, "错误", "请先添加输入文件")
            return
        multiwfn_exe = self.mwfn_edit.text()
        bundles = self._collect_bundles()
        if not all(b.path("stdout") for b in bundles) \
                and not os.path.isfile(multiwfn_exe):
            QMessageBox.critical(self, "错误", f"Multiwfn 不存在:\n{multiwfn_exe}")
            return
        if not _HAS_MPL:
            QMessageBox.critical(
                self, "缺少依赖",
                "需要 matplotlib 和 numpy 来绘制柱形图。\n请运行: pip install matplotlib numpy"
            )
            return

        # 先自动检测一次范围（只读已有产物，不调用 Multiwfn）
        auto = auto_esp_range(bundles)

        # Area distribution parameter dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("ESP 分区设置")
        dlg.setWindowIcon(app_icon())
        dlg.setMinimumWidth(560)

        layout = QVBoxLayout()
        form = QGridLayout()

        form.addWidget(QLabel("ESP 范围下限:"), 0, 0)
        rlo_edit = QLineEdit(f"{auto[0]:.2f}" if auto else "-25")
        rlo_edit.setMinimumWidth(110)
        form.addWidget(rlo_edit, 0, 1)
        form.addWidget(QLabel("kcal/mol"), 0, 2)

        form.addWidget(QLabel("ESP 范围上限:"), 1, 0)
        rhi_edit = QLineEdit(f"{auto[1]:.2f}" if auto else "22")
        rhi_edit.setMinimumWidth(110)
        form.addWidget(rhi_edit, 1, 1)
        form.addWidget(QLabel("kcal/mol"), 1, 2)

        form.addWidget(QLabel("分区数量:"), 2, 0)
        bins_slider = IntSlider(label_width=28)
        bins_slider.setRange(2, 50)
        bins_slider.setValue(15)
        bins_slider.setMinimumWidth(160)
        bins_slider.setToolTip("2~50 之间，滑块拖动即可；数值实时显示在右侧")
        form.addWidget(bins_slider, 2, 1, 1, 2)
        layout.addLayout(form)

        info = QLabel()
        info.setWordWrap(True)
        info.setMinimumWidth(520)
        info.setObjectName("HintLabel")
        info.setWordWrap(True)

        def apply_detected():
            """重新检测并填回上下限；检测不到就保留用户当前输入。"""
            rng = auto_esp_range(self._collect_bundles())
            if rng:
                rlo_edit.setText(f"{rng[0]:.2f}")
                rhi_edit.setText(f"{rng[1]:.2f}")
                info.setText(f"已自动填入检测到的 ESP 范围 {rng[0]:.2f} ~ "
                             f"{rng[1]:.2f} kcal/mol（来源: {rng[2]}）。可手动修改。")
            else:
                info.setText("未找到可复用的 ESP 产物（atomsurface.txt / "
                             "medinfo.txt / surfanalysis.pdb），请手动填写范围。")

        if auto:
            info.setText(f"已自动填入检测到的 ESP 范围 {auto[0]:.2f} ~ "
                         f"{auto[1]:.2f} kcal/mol（来源: {auto[2]}）。可手动修改。")
        else:
            info.setText("未找到可复用的 ESP 产物，当前为默认范围，可直接手动修改。")
        layout.addWidget(info)

        bottom = QHBoxLayout()
        btn_auto = QPushButton("重新检测")
        btn_auto.setCursor(Qt.PointingHandCursor)
        btn_auto.clicked.connect(apply_detected)
        bottom.addWidget(btn_auto)
        bottom.addStretch()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        bottom.addWidget(btns)
        layout.addLayout(bottom)
        dlg.setLayout(layout)

        if not dlg.exec_():
            return

        try:
            range_low = float(rlo_edit.text())
            range_high = float(rhi_edit.text())
            n_bins = int(bins_slider.value())
        except ValueError:
            QMessageBox.critical(self, "错误", "请输入有效的数值")
            return
        if n_bins < 2 or n_bins > 50:
            QMessageBox.critical(self, "错误", "分区数量应在 2~50 之间")
            return
        if range_high <= range_low:
            QMessageBox.critical(self, "错误", "ESP 范围上限必须大于下限")
            return

        self._log("")
        self._log("━━━ ESP 分区面积分布分析 ━━━")
        self._set_busy(True)
        self._set_status("正在计算 ESP 分面面积分布...")

        params = {
            'input_files': list(self.input_files),
            'bundles': bundles,
            'multiwfn_exe': multiwfn_exe,
            'work_dir': self._work_root(),
            'range_low': range_low,
            'range_high': range_high,
            'n_bins': n_bins,
        }
        self._worker = AreaAnalysisWorker(params)
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._set_progress)
        self._worker.status_signal.connect(self._set_status)
        self._worker.busy_signal.connect(self._set_busy)
        self._worker.start()

    def _run_job(self, action):
        params = self._get_params(action)
        self._worker = MultiwfnWorker(params)
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._set_progress)
        self._worker.status_signal.connect(self._set_status)
        self._worker.busy_signal.connect(self._set_busy)
        self._worker.finished_signal.connect(self._on_job_finished)
        self._worker.start()

    def _on_job_finished(self, result):
        self._set_busy(False)
        if result.get('extrema_unit'):
            self.esp_unit = result['extrema_unit']
        if not result.get('ok'):
            err = str(result.get('error') or '')
            if err == 'aborted':
                # 用户主动停止：不弹窗，只给个明确的状态，并把按钮解锁
                self._set_status("已停止（未完成的产物不会写入）")
                self._log("已停止：当前步骤中途中断，未归位的产物留在 _espcalc/ 里")
                return
            # 真正的失败要弹窗：此前只写日志，用户点完按钮以为程序"没反应"
            if err and result.get('action') == 'error':
                QMessageBox.critical(self, "任务失败", err)
            return
        action = result.get('action')
        if action == 'preview':
            self.vmd_port = result.get('vmd_port')
            self.vmd_process = result.get('vmd_proc')
            self.vmd_render_dir = result.get('vmd_dir')
            self.btn_render_view.setEnabled(True)
            if result.get('mode') in ('iso', 'all'):
                self._log(
                    f"ISO/ALL 模式：表面材质 {self._iso_material()}"
                    f"（透明度 {self._iso_opacity():.2f}），"
                    "可拖动 [透明度] 滑块或切换 [表面材质] 实时调整")
            if result.get('mode') in ('ext', 'all'):
                self.btn_pick.setEnabled(True)
                self._log("EXT/ALL 模式：点击 [🔍 查询极值点] 可查看极值点 ESP 数值")
        elif action == 'render':
            output_path = result.get('output_path', '')
            QMessageBox.information(self, "完成", f"渲染完成:\n{output_path}")
            self.btn_render_view.setEnabled(False)
            self.btn_pick.setEnabled(False)

    # ══ VMD Pick Callback Server ══

    def _start_callback_server(self):
        self._stop_callback_server()
        self.callback_port = find_free_port()

        def server_loop():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.callback_port))
            srv.listen(1)
            srv.settimeout(1.0)
            self.callback_server = srv
            while self.callback_server is srv:
                try:
                    conn, addr = srv.accept()
                    conn.settimeout(3.0)
                    data = b""
                    try:
                        while True:
                            chunk = conn.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                            if b"\n" in data:
                                break
                    except socket.timeout:
                        pass
                    conn.close()
                    if data:
                        msg = data.decode("utf-8", errors="replace").strip()
                        if msg.startswith("PICK:"):
                            self.pick_signal.emit(msg)
                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception:
                    break

        t = threading.Thread(target=server_loop, daemon=True)
        t.start()
        self.callback_thread = t

    def _stop_callback_server(self):
        srv = self.callback_server
        self.callback_server = None
        if srv:
            try:
                srv.close()
            except Exception:
                pass
        self.callback_port = None

    def _handle_pick(self, msg):
        try:
            parts = msg.split(":", 4)
            atom_idx = parts[1]
            atom_name = parts[2]
            beta_str = parts[3]
            xyz_str = parts[4].strip("{} ")

            try:
                beta_val = float(beta_str)
            except ValueError:
                beta_val = None

            xyz_parts = xyz_str.split()
            if len(xyz_parts) >= 3:
                x, y, z = float(xyz_parts[0]), float(xyz_parts[1]), float(xyz_parts[2])
            else:
                x = y = z = None

            if atom_name == "C":
                ext_type = "极大"
            elif atom_name == "O":
                ext_type = "极小"
            else:
                ext_type = f"原子({atom_name})"

            pdb_line = int(atom_idx) + 1
            unit = self.esp_unit

            if beta_val is not None:
                esp_str = f"{beta_val:+.2f} {unit}"
                self._log("-" * 50)
                self._log(f"  #{pdb_line:<4}  {ext_type:>6}值点   ESP = {esp_str}")
                if x is not None:
                    self._log(f"        坐标: ({x:8.3f}, {y:8.3f}, {z:8.3f})")
                self._log("-" * 50)
                self._set_status(f"ESP = {esp_str} ({ext_type}值点, index {atom_idx})")
            else:
                self._log(f"  📌 极值点 #{pdb_line} (index {atom_idx}): {ext_type}值点")
                if x is not None:
                    self._log(f"     坐标: ({x:.3f}, {y:.3f}, {z:.3f})")

        except (IndexError, ValueError) as e:
            self._log(f"  ⚠ 解析 VMD pick 数据失败: {msg} ({e})")


# ── 样式 ────────────────────────────────────────────────
# 配色与 QSS 全部搬到了 theme.py：这里只保留两个常量方便外部脚本沿用旧名字。
# 界面里不再出现写死的十六进制色值，控件用 objectName 标记角色
# （PrimaryBtn / GhostBtn / DangerBtn ...）由 QSS 统一上色。

def build_qss():
    """构建 QSS（全局样式表）。"""
    return theme.qss()


def build_palette():
    """构建 QPalette（原生图元配色）。"""
    return theme.palette()


# ── Main ────────────────────────────────────────────────

def main():
    # Windows 任务栏图标：先声明 AppUserModelID，否则任务栏显示 python 图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ESPViewer.SurfaceVisualization")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)     # 所有窗口 / 对话框 / 消息框默认继承此图标

    # QSS + QPalette 一起设，否则 Fusion 的原生图元（下拉箭头等）会花。
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.qss())

    window = ESPSurfaceGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()