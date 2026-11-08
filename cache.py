#!/usr/bin/env python3
"""cache.py — ESPViewer 中间文件（bundle）解析、校验与临时工作区

设计要点（详见 docs/BUNDLE_CACHE_DESIGN.md）：

  1. 规范产物名 = Multiwfn 原生输出名（mol.pdb / vtx.pdb / density.cub /
     totesp.cub / surfanalysis.pdb），保证 Linux 与 Windows 产出一致。
  2. 数据零拷贝：Bundle 只保存绝对路径，VMD TCL 直接引用，不做数据 staging。
  3. 数据层只读：本模块不删除、不移动用户的任何文件；唯一允许的写入是
     "补充缺失产物"（见 write_manifest / promote）。
  4. 校验粒度是 artifact 而非 bundle：单个产物失效只重算该产物。

本模块不依赖 PyQt5 / numpy，可独立单测。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from datetime import datetime

AU = 627.509  # 1 a.u. = 627.509 kcal/mol

MANIFEST_NAME = "bundle.json"

#: 计算临时区目录名（位于数据目录下，VMD 脚本与 Multiwfn 中间态都放这里）
CALC_DIR_NAME = "_espcalc"
SCHEMA_VERSION = 1

# ── 产物定义 ──────────────────────────────────────────────

ARTIFACT_KINDS = ("mol", "vtx", "density", "esp",
                  "extrema", "atomsurface", "stdout")

#: 规范文件名（Multiwfn 原生输出名）
CANONICAL_NAME = {
    "mol":         "mol.pdb",
    "vtx":         "vtx.pdb",
    "density":     "density.cub",
    "esp":         "totesp.cub",
    "extrema":     "surfanalysis.pdb",
    "atomsurface": "atomsurface.txt",
    "stdout":      "medinfo.txt",
}

#: 历史别名（仅用于读取 v2.0 之前的产物，程序自身不再生成）
ARTIFACT_ALIASES = {
    "mol":         ("mol1.pdb",),
    "vtx":         ("vtx1.pdb",),
    "density":     ("density1.cub",),
    "esp":         ("ESP1.cub", "esp.cub", "totesp1.cub"),
    "extrema":     (),
    "atomsurface": (),
    "stdout":      ("multiwfn.log",),
}

#: 每种分析模式所需的最小产物集合
MODE_REQUIRES = {
    "pt":  frozenset({"mol", "vtx"}),
    "iso": frozenset({"density", "esp"}),
    "ext": frozenset({"extrema"}),
    "all": frozenset({"density", "esp", "extrema"}),
}

#: 宽松兜底匹配（大小写不敏感；仅在某目录内使用）
_LOOSE = {
    "mol":         re.compile(r"^mol0*1?\.pdb$", re.I),
    "vtx":         re.compile(r"^vtx0*1?\.pdb$", re.I),
    "density":     re.compile(r"^density0*1?\.cub$", re.I),
    "esp":         re.compile(r"^(?:totesp|esp)0*1?\.cub$", re.I),
    "extrema":     re.compile(r"^surfanalysis0*1?\.pdb$", re.I),
    "atomsurface": re.compile(r"^atomsurface.*\.txt$", re.I),
    "stdout":      re.compile(r"^(?:medinfo|multiwfn).*\.(?:txt|log)$", re.I),
}

#: 网格质量。cub 的格点密度不同则不可互换，不一致必须重算。
EXPECTED_GRID_QUALITY = 3

#: ESP cube 的网格质量（Multiwfn 里 5→12→<质量>→2 那一步）。
#: 2 = Medium，与 Script/ESP_auto.sh 的 "12 2 2" 对齐；
#: 改这一项会让 totesp.cub 的格点从 53 万变成 13 万，表面着色随之改变。
EXPECTED_ESP_GRID_QUALITY = 2


# ══════════════════════════════════════════════════════════
#  基础工具
# ══════════════════════════════════════════════════════════

_SHA_CACHE = {}


def sha1_file(path, limit=None):
    """计算文件 sha1。limit 给定时只取前 limit 字节。失败返回 None。

    以 (绝对路径, 大小, mtime) 为键做记忆化，避免在 GUI 线程上反复哈希大 cub。
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns, limit)
    hit = _SHA_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            if limit:
                h.update(f.read(limit))
            else:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        digest = h.hexdigest()
    except OSError:
        return None
    _SHA_CACHE[key] = digest
    return digest


def is_ascii_path(path):
    try:
        str(path).encode("ascii")
        return True
    except (UnicodeEncodeError, AttributeError):
        return False


# ── Multiwfn 版本探测 ─────────────────────────────────────
#
# 版本只用于**提示与记录**，不参与失效判定：换掉 Multiwfn 可执行文件后，
# 已有 bundle 仍然可以直接复用（校验只看源 fchk 与网格质量）。如果改了版本
# 又想确保数值完全一致，再手动删 bundle.json 重算即可。

#: Multiwfn banner 有两种写法：
#:   " Multiwfn -- A Multifunctional Wavefunction Analyzer"
#:   " Version 2026.11.3 (release date is the same as version name)"
#: 以及带文件启动时的 "Multiwfn 3.8(dev), ..."
_RE_MWFN_VER = re.compile(
    r"(?:Multiwfn|Version)\s+(?:version\s+)?([0-9]{4}\.[0-9]+(?:\.[0-9]+)?"
    r"|[0-9]+\.[0-9]+(?:\([0-9A-Za-z._]+\))?)", re.I)

_VER_CACHE: dict = {}


def parse_multiwfn_version(text):
    """从 Multiwfn 输出里取版本号；取不到返回 ""。"""
    if not text:
        return ""
    for line in text.splitlines()[:40]:
        m = _RE_MWFN_VER.search(line)
        if m:
            return m.group(1)
    m = _RE_MWFN_VER.search(text[:4000])
    return m.group(1) if m else ""


def probe_multiwfn_version(exe, timeout=10):
    """取 Multiwfn 版本号，不进入交互。

    做法是传一个不存在的参数（`-h`）：Multiwfn 会报 "Unable to find the input
    file" 并立刻退出（实测 0.1~0.2 s），但 banner 里的版本号照常打印。
    别用"无参数启动 + q"——它会在等待文件路径里卡住（实测 20 s 超时）。

    结果按 (绝对路径, 大小, mtime) 缓存：换掉 exe 自然重新探测。
    任何异常都返回 ""，调用方按"未知"处理，绝不影响主流程。
    """
    if not exe:
        return ""
    try:
        st = os.stat(exe)
    except OSError:
        return ""
    key = (os.path.abspath(exe), st.st_size, st.st_mtime_ns)
    if key in _VER_CACHE:
        return _VER_CACHE[key]

    out = ""
    try:
        p = subprocess.run(
            [exe, "-h"], input="q\n", text=True,
            encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=os.path.dirname(os.path.abspath(exe)), timeout=timeout)
        out = p.stdout or ""
    except Exception:          # 超时 / 权限 / 被测试桩替换 ……
        out = ""
    ver = parse_multiwfn_version(out)
    _VER_CACHE[key] = ver
    return ver


def version_differs(manifest, current):
    """manifest 记录的版本与当前版本是否"确实不同"。任一为空都不算不同。"""
    old = ((manifest or {}).get("generator") or {}).get("multiwfn") or ""
    if not old or not current:
        return False, old
    return (old.strip() != current.strip()), old


def ascii_temp_root():
    """返回一个尽量为纯 ASCII 且可写的临时根目录（用于 VMD 编码兼容降级）。"""
    candidates = []
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(os.path.join(public, "ESPViewer", "tmp"))
    drive = os.environ.get("SystemDrive", "C:")
    candidates.append(os.path.join(drive + os.sep, "Temp", "ESPViewer"))
    candidates.append(os.path.join(tempfile.gettempdir(), "ESPViewer"))
    for c in candidates:
        if not is_ascii_path(c):
            continue
        try:
            os.makedirs(c, exist_ok=True)
            probe = os.path.join(c, ".w")
            with open(probe, "w") as f:
                f.write("1")
            os.remove(probe)
            return c
        except OSError:
            continue
    return tempfile.mkdtemp(prefix="espv_")


def default_bundle_dir(fchk_path):
    """计算产物默认落位：<fchk目录>/<fchk主名>/ （与 ESP_auto.sh 布局一致）。"""
    d = os.path.dirname(os.path.abspath(fchk_path))
    stem = os.path.splitext(os.path.basename(fchk_path))[0]
    return os.path.join(d, stem)


# ── ESP 单位与范围解析 ────────────────────────────────────

_RE_MINMAX_KCAL = re.compile(
    r"Minimal value:\s*(-?\d+(?:\.\d+)?)\s*kcal/mol\s+"
    r"Maximal value:\s*(-?\d+(?:\.\d+)?)\s*kcal/mol",
    re.I)
_RE_GLOBAL_MIN = re.compile(r"Global surface minimum:\s*(-?[\d.eE+]+)\s*a\.u\.", re.I)
_RE_GLOBAL_MAX = re.compile(r"Global surface maximum:\s*(-?[\d.eE+]+)\s*a\.u\.", re.I)


def detect_esp_unit(pdb_path):
    """读 surfanalysis.pdb 头部判断 ESP 单位，返回 'eV' 或 'kcal/mol'。"""
    try:
        with open(pdb_path, "r", encoding="utf-8", errors="replace") as f:
            for _ in range(100):
                line = f.readline()
                if not line:
                    break
                if line.startswith(("ATOM", "HETATM")):
                    break
                low = line.lower()
                if "kcal/mol" in low or "kcal per mol" in low:
                    return "kcal/mol"
                if "ev" in low and ("esp" in low or "potential" in low):
                    return "eV"
    except OSError:
        pass
    return "kcal/mol"


def parse_esp_range_text(text):
    """从文本（stdout / atomsurface.txt）解析全局 ESP 范围。

    优先读 kcal/mol 汇总行；只有 a.u. 的 Global min/max 时换算成 kcal/mol。
    **返回值统一是 kcal/mol**（unit 恒为 'kcal/mol'），这样调用方不需要
    再乘一次 AU —— 以前 a.u. 分支里已经乘过，调用方又乘一次，结果大了 627 倍。

    返回 (low, high, unit) 或 None。
    """
    if not text:
        return None
    m = _RE_MINMAX_KCAL.search(text)
    if m:
        return (float(m.group(1)), float(m.group(2)), "kcal/mol")
    lo, hi = _RE_GLOBAL_MIN.search(text), _RE_GLOBAL_MAX.search(text)
    if lo and hi:
        return (float(lo.group(1)) * AU, float(hi.group(1)) * AU, "kcal/mol")
    return None


def read_esp_range(paths):
    """从文本产物中读全局 ESP 范围，返回 (low, high, unit) 或 None。"""
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        r = parse_esp_range_text(text)
        if r:
            return r
    return None


def extract_atomsurface(stdout_text):
    """从 Multiwfn stdout 中截出 atomsurface 段（与 ESP_auto.sh 的 sed 等价）。"""
    if not stdout_text:
        return None
    start_tok = "Note: Minimal and maximal value below are in kcal/mol"
    end_tok = "If outputting the surface facets to locsurf.pdb"
    i = stdout_text.find(start_tok)
    if i < 0:
        return None
    j = stdout_text.find(end_tok, i)
    if j < 0:
        j = len(stdout_text)
    return stdout_text[i:j]


# ── 极值点（surface analysis）解析 ────────────────────────

#: surfanalysis.pdb 用"原子名"当类型标记：C = 表面极大，O = 表面极小
EXTREMA_KIND = {"C": "max", "O": "min"}

#: eV → kcal/mol 换算（1 eV = 23.0605 kcal/mol）
EV_TO_KCAL = 23.0605


def _pdb_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_surfanalysis_pdb(path, to_kcal=True):
    """解析 surfanalysis.pdb，返回表面极值点列表。

    文件格式（Multiwfn 12-3 分析）：头部两行 REMARK 说明「Carbon 行 = 表面
    极大值、Oxygen 行 = 表面极小值」，每个 HETATM 的 B-factor 列就是该点的
    ESP 值。列坐标固定，但负值会与 occupancy 粘连（`1.00-36.79`），所以
    B-factor 用 "去掉前导 occupancy 再取数" 的方式读，避免按列切片读错。

    返回 [{"x","y","z","value","kind","unit"}]，kind ∈ {"max","min"}；
    文件不存在或无记录时返回 []。

    **关于数值偏差**：这里的 value 是 Multiwfn 在 vdW 面上"找极值"时采样点
    处的值，和 atomsurface.txt 里逐原子的值会差零点几到一两 kcal/mol（两者
    采样位置不同，且前者要求是局域极值）。这是 Multiwfn 的正常行为，排序
    趋势一致。标注只用这里的值，**不做"按值反查原子"**这种脆弱匹配。
    """
    points = []
    if not path or not os.path.isfile(path):
        return points
    unit = detect_esp_unit(path)
    scale = EV_TO_KCAL if (to_kcal and unit == "eV") else 1.0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith(("HETATM", "ATOM")):
                    continue
                x = _pdb_float(line[30:38])
                y = _pdb_float(line[38:46])
                z = _pdb_float(line[46:54])
                if x is None or y is None or z is None:
                    continue
                kind = EXTREMA_KIND.get(line[12:16].strip().upper()[:1])
                if kind is None:
                    kind = EXTREMA_KIND.get(line[17:20].strip().upper()[:1])
                if kind is None:
                    continue
                rest = line[54:].strip()
                if rest.startswith("1.00"):
                    rest = rest[4:].strip()
                val = _pdb_float(rest.split()[0] if rest.split() else "")
                if val is None:
                    continue
                points.append({"x": x, "y": y, "z": z,
                               "value": val * scale, "kind": kind,
                               "unit": "kcal/mol"})
    except OSError:
        return []
    return points


def pick_extrema(points, per_side=4):
    """按 |value| 取每侧最显著的若干极值点（标注用，避免图上糊成一片）。"""
    if not points:
        return []
    if per_side is None or per_side <= 0:
        return list(points)
    out = []
    for kind in ("max", "min"):
        side = [p for p in points if p["kind"] == kind]
        side.sort(key=lambda p: abs(p["value"]), reverse=True)
        out.extend(side[:per_side])
    return out


# ══════════════════════════════════════════════════════════
#  数据结构
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Artifact:
    kind: str
    path: str
    origin: str = "bundle"   # "bundle" | "computed"
    verified: bool = False
    note: str = ""


@dataclass
class Bundle:
    source_fchk: str
    root: str | None = None          # 命中的 bundle 目录（无产物时为 None）
    layout: str | None = None        # sibling / subdir / cache_root / None
    manifest: dict | None = None
    artifacts: dict = field(default_factory=dict)
    out_dir: str = ""                # 计算产物落位目录
    conflict_note: str = ""          # 目录被同主名文件争用时的说明

    # ── 查询 ──
    def get(self, kind):
        return self.artifacts.get(kind)

    def path(self, kind):
        a = self.artifacts.get(kind)
        return a.path if a else None

    def missing(self, required):
        return {k for k in required if k not in self.artifacts}

    def has_all(self, required):
        return not self.missing(required)

    @property
    def needs_ascii_fallback(self):
        for a in self.artifacts.values():
            if not is_ascii_path(a.path):
                return True
        return False

    def summary(self, mode):
        """给 UI 的单行摘要，例如：PT OK / ISO OK? / EXT --"""
        req = MODE_REQUIRES.get(mode, frozenset())
        if not self.artifacts:
            return "--"
        parts = []
        for label, kinds in (("PT", ("mol", "vtx")),
                             ("ISO", ("density", "esp")),
                             ("EXT", ("extrema",))):
            if not set(kinds) & req:
                continue
            arts = [self.artifacts.get(k) for k in kinds]
            if all(a is not None for a in arts):
                parts.append(label + (" OK" if all(a.verified for a in arts) else " OK?"))
            else:
                parts.append(label + " --")
        return " / ".join(parts) if parts else "--"


# ══════════════════════════════════════════════════════════
#  解析器
# ══════════════════════════════════════════════════════════

class BundleResolver:
    """把 fchk 路径映射为 Bundle。只读，无副作用。"""

    def __init__(self, cache_root=None, verify="auto"):
        self.cache_root = cache_root.strip() if cache_root else None
        self.verify = verify or "auto"      # auto / strict / off

    # ── 公开接口 ──
    def locate(self, fchk_path):
        fchk_path = os.path.abspath(fchk_path)
        stem = os.path.splitext(os.path.basename(fchk_path))[0]
        out_dir = default_bundle_dir(fchk_path)

        for layout, d in self._candidate_dirs(fchk_path, stem):
            arts = self._scan(d)
            if not arts:
                continue
            man = self._read_manifest(d)
            b = Bundle(source_fchk=fchk_path, root=d, layout=layout,
                       manifest=man, artifacts=arts, out_dir=d)
            return self._verify(b)

        return Bundle(source_fchk=fchk_path, out_dir=out_dir)

    def locate_all(self, fchk_paths):
        bundles = []
        used_roots = {}
        for p in fchk_paths:
            b = self.locate(p)
            low = os.path.normcase(b.root) if b.root else None
            if low:
                if low in used_roots:
                    b = Bundle(
                        source_fchk=b.source_fchk,
                        out_dir=default_bundle_dir(p),
                        conflict_note=("同名目录已被 %s 占用，不共享缓存"
                                       % os.path.basename(used_roots[low])))
                else:
                    used_roots[low] = p
            bundles.append(b)
        return bundles

    # ── 目录探测 ──
    def _candidate_dirs(self, fchk_path, stem):
        """候选目录，按优先级排列。

        只看**与 fchk 同名**（不含扩展名，大小写不敏感）的子目录，不做递归搜索。
        唯一例外：子目录里有 `bundle.json`，且其中 `source.name` 正好等于当前
        fchk 文件名（用户改过文件夹名时兜底）—— 是否真的匹配仍由 `_verify`
        用源文件大小/sha1 最终确认。
        """
        fchk_dir = os.path.dirname(fchk_path)
        fchk_name = os.path.basename(fchk_path)
        cands = [("sibling", fchk_dir)]
        seen = {os.path.normcase(fchk_dir)}

        for label, root, by_name in (
                ("subdir", fchk_dir, stem),
                ("cache_root", self.cache_root, stem)):
            if not root or not os.path.isdir(root):
                continue
            exact = os.path.join(root, by_name)
            if os.path.isdir(exact):
                key = os.path.normcase(exact)
                if key not in seen:
                    seen.add(key)
                    cands.append((label, exact))
                continue
            matched = None
            for name in sorted(os.listdir(root)):
                if name.lower() == by_name.lower():
                    d = os.path.join(root, name)
                    if os.path.isdir(d):
                        matched = d
                        break
            if matched is None:
                # 名字对不上：只在一层子目录里找 bundle.json 记录的源文件名
                matched = self._match_by_manifest(root, fchk_name)
            if matched:
                key = os.path.normcase(matched)
                if key not in seen:
                    seen.add(key)
                    cands.append((label, matched))
        return cands

    def _match_by_manifest(self, root, fchk_name):
        """在 root 的一层子目录里找 `bundle.json` 记录 source.name == fchk_name 的目录。"""
        want = (fchk_name or "").lower()
        if not want:
            return None
        try:
            names = sorted(os.listdir(root))
        except OSError:
            return None
        for name in names:
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            man = self._read_manifest(d)
            src = (man or {}).get("source") or {}
            if str(src.get("name", "")).lower() == want:
                return d
        return None

    # ── 目录扫描 ──
    def _scan(self, d):
        try:
            names = os.listdir(d)
        except OSError:
            return {}
        by_lower = {}
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                by_lower.setdefault(n.lower(), n)
        found = {}
        for kind in ARTIFACT_KINDS:
            resolved = None
            # 1) 规范名
            c = CANONICAL_NAME[kind]
            if c.lower() in by_lower:
                resolved = by_lower[c.lower()]
            # 2) 历史别名
            if resolved is None:
                for a in ARTIFACT_ALIASES.get(kind, ()):
                    if a.lower() in by_lower:
                        resolved = by_lower[a.lower()]
                        break
            # 3) 宽松正则
            if resolved is None:
                pat = _LOOSE[kind]
                for low, real in by_lower.items():
                    if pat.match(real):
                        resolved = real
                        break
            if resolved is None:
                continue
            p = os.path.join(d, resolved)
            try:
                if os.path.getsize(p) <= 0:
                    continue
            except OSError:
                continue
            note = "" if resolved.lower() == CANONICAL_NAME[kind].lower() \
                else f"别名文件 {resolved}"
            found[kind] = Artifact(kind=kind, path=p, verified=False, note=note)
        return found

    def _read_manifest(self, d):
        p = os.path.join(d, MANIFEST_NAME)
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                man = json.load(f)
            if not isinstance(man, dict):
                return None
            return man
        except (OSError, ValueError):
            return None

    # ── 校验 ──
    def _verify(self, b):
        if not b.artifacts:
            return b

        if self.verify == "off":
            b.artifacts = {
                k: replace(a, verified=False, note=(a.note or "信任模式").strip())
                for k, a in b.artifacts.items()}
            return b

        man = b.manifest
        if man is None:
            if self.verify == "strict":
                b.artifacts = {}
                return b
            b.artifacts = {
                k: replace(a, verified=False,
                           note=(a.note + " 未验证(无manifest)").strip())
                for k, a in b.artifacts.items()}
            return b

        # 源文件指纹：大小与头部 sha1 不一致即全部失效；
        # mtime 不参与判定（拷贝/同步会改变 mtime）。
        src = man.get("source") or {}
        try:
            size = os.path.getsize(b.source_fchk)
        except OSError:
            size = None
        head = sha1_file(b.source_fchk, limit=65536) if size is not None else None
        src_ok = True
        reason = ""
        if src.get("size") is not None and size is not None \
                and src["size"] != size:
            src_ok = False
            reason = "源 fchk 大小变化"
        elif src.get("sha1_head64k") and head and src["sha1_head64k"] != head:
            src_ok = False
            reason = "源 fchk 内容变化"
        if not src_ok:
            b.artifacts = {}
            return b

        # 网格质量不一致则密度/ESP 格点不可用
        params = man.get("params") or {}
        bad_kinds = set()
        gq = params.get("grid_quality")
        if gq is not None and gq != EXPECTED_GRID_QUALITY:
            bad_kinds.update({"density", "esp"})
        # ESP cube 的网格质量是独立参数（Multiwfn 里 5→12→<质量>→2），
        # 与电子密度不是同一个选项。历史上 GUI 用低质量、脚本用中等质量，
        # 同一 fchk 会得到不同格点的 totesp.cub，却没被校验拦下。
        gq_esp = params.get("esp_grid_quality")
        if gq_esp is not None and gq_esp != EXPECTED_ESP_GRID_QUALITY:
            bad_kinds.add("esp")

        # 逐产物 sha1 / 大小校验
        man_arts = man.get("artifacts") or {}
        out = {}
        for kind, a in b.artifacts.items():
            if kind in bad_kinds:
                continue
            info = man_arts.get(kind) or {}
            verdict = True
            note = a.note
            want_sha = info.get("sha1")
            want_bytes = info.get("bytes")
            if want_bytes is not None:
                try:
                    if os.path.getsize(a.path) != want_bytes:
                        verdict = False
                        note = (note + " 大小不符").strip()
                except OSError:
                    verdict = False
            if verdict and want_sha:
                got = sha1_file(a.path)
                if got and got != want_sha:
                    verdict = False
                    note = (note + " 内容已变").strip()
            if verdict:
                out[kind] = replace(a, verified=True,
                                    note=(note + " 校验通过").strip())
        b.artifacts = out
        return b


# ══════════════════════════════════════════════════════════
#  manifest 写入
# ══════════════════════════════════════════════════════════

_SHA_CAP = 64 * 1024 * 1024   # 超过 64MB 只记大小，不算 sha1


def write_manifest(out_dir, fchk_path, artifact_paths,
                   multiwfn_version="", grid_quality=EXPECTED_GRID_QUALITY,
                   extrema_unit=None, app_version="2.1.0"):
    """把当前目录下已知产物写入 bundle.json。失败静默（不影响主流程）。"""
    if not out_dir:
        return None
    try:
        os.makedirs(out_dir, exist_ok=True)
        man_path = os.path.join(out_dir, MANIFEST_NAME)
        old = {}
        if os.path.isfile(man_path):
            try:
                with open(man_path, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except (OSError, ValueError):
                old = {}

        entries = dict(old.get("artifacts") or {})
        for kind, p in artifact_paths.items():
            if not p or not os.path.isfile(p):
                continue
            try:
                nbytes = os.path.getsize(p)
            except OSError:
                continue
            rec = {"file": os.path.basename(p), "bytes": nbytes}
            if nbytes <= _SHA_CAP:
                h = sha1_file(p)
                if h:
                    rec["sha1"] = h
            entries[kind] = rec

        try:
            size = os.path.getsize(fchk_path)
        except OSError:
            size = None
        # 版本号：本次没算（纯复用）时保留旧记录，否则会把老产物的来源洗掉。
        old_mw = ((old.get("generator") or {}).get("multiwfn") or "")
        man = {
            "schema": SCHEMA_VERSION,
            "generator": {"app": "ESPViewer", "app_version": app_version,
                          "multiwfn": multiwfn_version or old_mw},
            "source": {"name": os.path.basename(fchk_path),
                       "size": size,
                       "sha1_head64k": sha1_file(fchk_path, limit=65536)},
            "params": {"grid_quality": grid_quality,
                       "esp_grid_quality": EXPECTED_ESP_GRID_QUALITY,
                       "iso_rho": 0.001,
                       "cub_unit": "a.u.",
                       "extrema_unit": extrema_unit or "kcal/mol"},
            "artifacts": entries,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
        return man_path
    except OSError:
        return None


def promote_files(src_dir, out_dir, kinds, overwrite=False):
    """把 src_dir 中的产物归位到 out_dir（仅规范名，仅指定 kind）。

    返回 {kind: 最终路径}。out_dir 不可写时保留 src 路径。
    """
    result = {}
    writable = True
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            writable = False
    else:
        writable = False

    for kind in kinds:
        name = CANONICAL_NAME.get(kind)
        if not name:
            continue
        src = os.path.join(src_dir, name)
        if not os.path.isfile(src) or os.path.getsize(src) <= 0:
            continue
        if not writable:
            result[kind] = src
            continue
        dst = os.path.join(out_dir, name)
        if os.path.exists(dst) and not overwrite:
            result[kind] = src
            continue
        try:
            if os.path.exists(dst):
                os.replace(src, dst)
            else:
                shutil.move(src, dst)
            result[kind] = dst
        except OSError:
            # 跨盘/占用失败时回退到复制
            try:
                shutil.copy2(src, dst)
                result[kind] = dst
            except OSError:
                result[kind] = src
    return result


# ══════════════════════════════════════════════════════════
#  临时工作区
# ══════════════════════════════════════════════════════════

class JobWorkspace:
    """一次会话的临时资源：脚本与计算中间态，不放数据副本。

    默认落在数据目录下的 `_espcalc/`（与源数据同处，便于复查；由用户手动删除）。
    数据目录不可写时自动回退系统临时目录，此时才在退出时自动清理。
    """

    def __init__(self, root=None):
        self.root = root
        self.temporary = root is None       # True 表示位于系统临时目录、可自动删除
        self._ascii_root = None
        self._ascii_seq = 0
        if root:
            os.makedirs(root, exist_ok=True)

    # ── 目录定位 ──

    def anchor(self, data_dir):
        """把工作区固定到 `<data_dir>/_espcalc`；不可写则回退临时目录。

        重复调用只认第一次的结果，避免多分子场景来回切换目录。
        """
        if self.root:
            return self.root
        target = os.path.join(data_dir, CALC_DIR_NAME)
        try:
            os.makedirs(target, exist_ok=True)
            probe = os.path.join(target, ".write_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("")
            os.remove(probe)
            self.root = target
            self.temporary = False
        except OSError:
            self.ensure_temp()
        return self.root

    def ensure_temp(self):
        """强制使用系统临时目录（无输入文件或数据目录只读时的兜底）。"""
        if not self.root:
            self.root = tempfile.mkdtemp(prefix="esp_gui_")
            self.temporary = True
        os.makedirs(self.script_dir, exist_ok=True)
        return self.root

    @property
    def script_dir(self):
        return os.path.join(self.root or self.ensure_temp(), "scripts")

    @property
    def calc_dir(self):
        return os.path.join(self.root or self.ensure_temp(), "calc")

    def script_path(self, name):
        d = self.script_dir
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def calc_subdir(self, idx, base_dir=None):
        """计算子目录。给了 base_dir 就落在 `<base_dir>/_espcalc/sys<idx>`。"""
        if base_dir:
            d = os.path.join(base_dir, CALC_DIR_NAME, f"sys{idx}")
        else:
            d = os.path.join(self.calc_dir, f"sys{idx}")
        os.makedirs(d, exist_ok=True)
        return d

    def ascii_stage(self, files):
        """把文件拷到 ASCII 安全目录，返回新路径映射。用于 VMD 编码降级。"""
        if self._ascii_root is None:
            self._ascii_root = ascii_temp_root()
        self._ascii_seq += 1
        d = os.path.join(self._ascii_root, f"stage{self._ascii_seq}")
        os.makedirs(d, exist_ok=True)
        out = {}
        for kind, p in files.items():
            if not p:
                continue
            dst = os.path.join(d, CANONICAL_NAME.get(kind, os.path.basename(p)))
            try:
                shutil.copy2(p, dst)
                out[kind] = dst
            except OSError:
                out[kind] = p
        return out

    def cleanup(self):
        """只清理自己创建的临时目录与 ASCII 暂存区。

        落在数据目录的 `_espcalc/` 属于用户可见的复查材料，不自动删除。
        """
        if self.temporary and self.root:
            shutil.rmtree(self.root, ignore_errors=True)
        if self._ascii_root:
            shutil.rmtree(self._ascii_root, ignore_errors=True)
