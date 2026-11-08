#!/usr/bin/env python3
"""tclgen.py — VMD/TCL 脚本生成

相对 v2.0 的关键变化：**不再使用 nsystem 循环 + 索引文件名**，而是逐分子展开、
直接写绝对路径。这样数据无需拷贝或重命名，也就不需要 staging 目录。

所有路径一律用 `{...}` 包裹，避免用户名/目录名含空格时解析失败。

本模块不依赖 PyQt5，可独立单测。
"""

from __future__ import annotations

import os

AU = 627.509  # 1 a.u. = 627.509 kcal/mol

_ISO_RHO = 0.001

#: 等值面可选材质。三者都是 VMD 内置材质，无需用户额外安装。
#:   Transparent — 半透明（教程 ESPiso.vmd 的用法），最通用
#:   GlassBubble — 玻璃泡（教程 ESPiso2.vmd），更通透，适合露出内部骨架
#:   Opaque      — 不透明，传统实心表面
ISO_MATERIALS = ("Transparent", "GlassBubble", "Opaque")
DEFAULT_ISO_MATERIAL = "Transparent"

#: 默认不透明度取 VMD 内置 Transparent 的出厂值 0.30，与教程 `ESPiso.vmd`
#: 完全一致（实测同参数渲染结果与教程脚本逐像素相同）。
DEFAULT_ISO_OPACITY = 0.30

#: 各材质推荐的不透明度，供 GUI 在切换材质时联动。
MATERIAL_DEFAULT_OPACITY = {
    "Transparent": 0.30,   # 教程 ESPiso.vmd：不写 opacity，即 VMD 出厂 0.30
    "GlassBubble": 0.26,   # 教程 ESPiso2.vmd 显式值
    "Opaque": 1.00,
}

#: 教程 ESPiso.vmd / ESPiso2.vmd 开头都打开了 4 盏灯。只留默认的 light 0/1
#: 时，等值面只有一个方向的高光，看起来是灰白发雾的"磨砂"感；凑齐 4 盏灯
#: 才有教程里那种多点镜面高光 + 湿润蜡膜的观感。这是"像不像教程"的第一因素。
_ISO_LIGHTS = ("light 2 on", "light 3 on")

HEAD_NORMAL = """# ESPViewer generated VMD script (do not edit by hand)
color scale method BWR
color Display Background white
axes location Off
display depthcue off
display rendermode Normal
"""


def material_tcl(material=DEFAULT_ISO_MATERIAL, opacity=DEFAULT_ISO_OPACITY):
    """返回设置等值面材质的 Tcl 命令行列表。

    ISO 脚本开头和 GUI 的实时预览共用这段，保证"预览里看到的"和
    "出图渲染的"是同一套材质参数。

    **只改 opacity（GlassBubble 另加 diffuse），不再覆盖 ambient /
    diffuse / specular / shininess**：v2.1.3 曾经把它们改成
    ambient 0.15 / diffuse 0.75 / specular 0.20，结果把 VMD 内置材质
    本身带的高光压平了，表面变成灰白发雾的磨砂质感——这正是"GUI 里的
    ISO 没有教程好看"的直接原因。保留出厂值 + 开 4 盏灯后，用
    water 实测与教程 `ESPiso.vmd` 渲染结果逐像素一致（MAD = 0）。

    outline / outlinewidth 仍然显式置 0：它们是 GLSL 特性，Tachyon 不支持，
    EdgyGlass 那套 outline 正是早期无头渲染崩溃的根因。
    """
    if material not in ISO_MATERIALS:
        material = DEFAULT_ISO_MATERIAL
    op = min(max(float(opacity), 0.05), 1.0)
    if material == "Opaque":
        # Opaque 出厂即不透，opacity 对它无意义，写进去反而误导
        return []
    lines = []
    if material == "GlassBubble":
        # 教程 ESPiso2.vmd：diffuse 0.7 才够"泡"，出厂值偏暗
        lines.append("material change diffuse GlassBubble 0.70")
    lines += [
        f"material change opacity {material} {op:.2f}",
        f"material change outline {material} 0.00",
        f"material change outlinewidth {material} 0.00",
    ]
    return lines


def iso_head(material=DEFAULT_ISO_MATERIAL, opacity=DEFAULT_ISO_OPACITY,
             rendermode="GLSL"):
    """等值面脚本的公共头。

    材质用 VMD 内置的 Transparent / GlassBubble，**不用 EdgyGlass**：
    EdgyGlass 依赖 outline + GLSL transmode，在无头 Tachyon 渲染时
    会直接崩溃（实测 TGA 不生成、进程退出码异常），这正是旧版
    "渲染失败" 的根因。

    `display rendermode` 只影响交互窗口的观感；无头渲染脚本里
    `tclgen.render_tcl()` 会再把它压回 Normal（VMD 文本模式下
    GLSL 是非法的，会打印 "Illegal rendering mode: GLSL"）。
    灯光与材质在 Normal 下同样生效，所以预览与出图观感一致。
    """
    lines = [
        "# ESPViewer generated VMD script (do not edit by hand)",
        "# Style follows MEP tutorial ESPiso.vmd: stock material + 4 lights",
        "color scale method BWR",
        "color Display Background white",
        "axes location Off",
        "display depthcue off",
        f"display rendermode {rendermode}",
    ]
    lines += list(_ISO_LIGHTS)
    lines += material_tcl(material, opacity)
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════
#  路径与片段
# ══════════════════════════════════════════════════════════

def tcl_path(path):
    """Tcl 路径字面量：绝对路径 + 正斜杠 + 花括号包裹。"""
    p = os.path.abspath(path).replace("\\", "/")
    return "{" + p + "}"


def colorbar_tcl(color_low, color_high, unit="kcal/mol"):
    """色彩刻度轴 Tcl 片段。"""
    return f"""
# -- ESP Color Scale Bar --
after 1000 {{
  if {{[catch {{
    package require colorscalebar
    catch {{::ColorScaleBar::delete_color_scale_bar}}
    ::ColorScaleBar::color_scale_bar \\
      1.5 0.08 0 1 \\
      {color_low} \\
      {color_high} \\
      10 16 0 0.82 -0.75 1 top 0 1 \\
      "ESP ({unit})"
  }} err]}} {{
    puts "ESPViewer ColorScaleBar ERROR:"
    puts $err
  }}
}}
"""


def render_tcl(script_path, output_path, width=0, height=0):
    """无头渲染用的外层脚本内容。

    注意三点（均为实测结论）：
    1. `render TachyonInternal` 之后**不能再跟任何参数**。VMD 会把多余参数
       当成"渲染后要执行的 shell 命令"，`rawaam` 会被真的当命令执行，
       导致 VMD 退出码非 0（Windows 上是 127），图片却已经生成。
    2. `render` 的输出尺寸取决于当前显示窗口，无头模式下默认 512x512，
       必须显式 `display resize`，并在 resize 之后重新 resetview 才能取景正确。
    3. 无头模式下 **GLSL 渲染模式非法**（VMD 会打印 "Illegal rendering mode:
       GLSL"，并在某些材质上直接崩溃），source 之后必须压回 Normal。
       材质的透明度在 Normal 模式下照常生效，不影响半透明观感。
    """
    lines = [f"source {tcl_path(script_path)}",
             "display rendermode Normal"]
    if width and height:
        lines.append(f"display resize {int(width)} {int(height)}")
        lines.append("display resetview")
    lines.append(f"render TachyonInternal {tcl_path(output_path)}")
    lines.append("quit")
    return "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════
#  分模式脚本体
# ══════════════════════════════════════════════════════════

def _require(system, kinds, idx):
    for k in kinds:
        if not system.get(k):
            raise ValueError(f"第 {idx} 个分子缺少 {k} 文件路径")
        if not os.path.isfile(system[k]):
            raise ValueError(f"第 {idx} 个分子的 {k} 文件不存在: {system[k]}")


def build_pt(systems, color_low, color_high, pt_size):
    lines = [HEAD_NORMAL]
    for i, s in enumerate(systems, 1):
        _require(s, ("mol", "vtx"), i)
        lines.append(f"\n# --- molecule {i}: {os.path.basename(s['mol'])} ---")
        lines.append(f"set mid [mol new {tcl_path(s['mol'])}]")
        lines.append("mol modstyle 0 $mid CPK 1.000000 0.300000 22.000000 22.000000")
        # vtx.pdb 是几万个间距很小的表面顶点，VMD 默认会做距离成键
        # （上万条键，报 "Exceeded maximum number of bonds"），并在无头渲染时
        # 直接段错误。点云不需要键，必须关掉 autobonds。
        lines.append(f"set vid [mol new {tcl_path(s['vtx'])} autobonds off]")
        lines.append("mol modcolor 0 $vid Beta")
        lines.append(f"mol modstyle 0 $vid Points {pt_size}")
        lines.append(f"mol scaleminmax $vid 0 {color_low} {color_high}")
    lines.append("\ndisplay resetview\n")
    return "\n".join(lines)


def _iso_block(s, i, alow, ahigh, material=DEFAULT_ISO_MATERIAL):
    return [
        f"\n# --- molecule {i}: {os.path.basename(s['density'])} ---",
        f"set id [mol new {tcl_path(s['density'])}]",
        f"mol addfile {tcl_path(s['esp'])}",
        "mol modstyle 0 $id CPK 1.000000 0.300000 22.000000 22.000000",
        "mol addrep $id",
        f"mol modstyle 1 $id Isosurface {_ISO_RHO:.6f} 0 0 0 1 1",
        f"mol modmaterial 1 $id {material}",
        "mol modcolor 1 $id Volume 1",
        f"mol scaleminmax $id 1 {alow} {ahigh}",
    ]


#: 极值点配色：极大 = 红，极小 = 蓝（与 BWR 色标的高/低端一致）。
#: 两套写法各有各的限制（实测）：
#:   `graphics ... color`    —— 认颜色名（`red`/`blue`），也认 ColorID 数字
#:   `mol modcolor ... Color`—— **不认颜色名**，会报
#:                              "Incorrect atom color method command 'Color red'"
#: 所以球用 ColorID（red=1、blue=0），文字用颜色名。
EXTREMA_COLOR = {"max": "red", "min": "blue"}
EXTREMA_COLORID = {"max": 1, "min": 0}


def _ext_block(s, i):
    return [
        f"\n# --- extrema {i}: {os.path.basename(s['extrema'])} ---",
        f"set id [mol new {tcl_path(s['extrema'])}]",
        "mol modstyle 0 $id VDW 0.07 20",
        "mol modselect 0 $id name C",
        f"mol modcolor 0 $id ColorID {EXTREMA_COLORID['max']}",
        "mol addrep $id",
        "mol modstyle 1 $id VDW 0.07 20",
        "mol modselect 1 $id name O",
        f"mol modcolor 1 $id ColorID {EXTREMA_COLORID['min']}",
        # 数值标注要挂在这个分子上（而不是单独 new 一个空分子）：
        # 拖动旋转时文字与极值球共享同一个分子坐标系，才不会各转各的。
        f"set extmol_{i} $id",
    ]


# ── 极值点数值标注 ────────────────────────────────────────

#: 文字高度（Å）。VMD 的 graphics text 以世界坐标计尺寸，会随缩放变化；
#: 1.5 Å 在 1200×900 ~ 2000×1500 的常见取景下清晰，又不至于比原子还大、
#: 把分子和别的标注挤开。
DEFAULT_LABEL_SIZE = 1.5
DEFAULT_LABEL_THICKNESS = 2.0
#: 标注相对极值点小球沿"重心 → 该点"方向外移的距离（Å）。
#: 小球本身半径只有 ~0.1 Å，外移 0.55 Å 就够把字放到球外侧；
#: 再远就会看着像两件互不相干的东西（实测 1.2 + 半串宽 ≈ 2.7 Å 太散）。
LABEL_OFFSET = 0.55
#: 朝默认观察方向再挪一点，避免被同深度的半透明表面压暗（单位 Å，很小）
LABEL_Z_NUDGE = 1.0
#: 估算文字宽度用的字符宽系数（宽度 ≈ 系数 × 字号 × 字符数）。
#: 实测 VMD 的 graphics text 大约 0.4~0.45 个字号一个字符。
_LABEL_CHAR_W = 0.45
#: 文字高度相对字号的系数（VMD 的字高约等于 size）
_LABEL_H_FACTOR = 0.9

_LABEL_COLOR = dict(EXTREMA_COLOR)   # 文字与极值球同色：红=极大、蓝=极小

#: 默认每侧（极大 / 极小）标注几个
DEFAULT_LABEL_COUNT = 4


def extrema_label_tcl(points, molid="top", size=DEFAULT_LABEL_SIZE,
                      thickness=DEFAULT_LABEL_THICKNESS,
                      offset=LABEL_OFFSET):
    """生成极值点数值标注的 Tcl 片段。

    用 3D `graphics text`（而不是 `label add Atoms`）：后者只在 OpenGL 窗口
    里以 2D 叠加显示，**Tachyon 出图时根本不会出现**；`graphics text` 是真正
    的 3D 文字对象，预览和渲染都有，并且跟着它所属的分子一起转动。

    `molid` 必须是**极值球所在的那个分子**（调用方传 `$extmol_<i>`）。
    以前写法是 `set lab [mol new]` 另开一个空分子再挂上去：空分子没有原子，
    在 VMD 里拖动旋转时它的坐标系不跟真实分子走，结果球转了、字没转
    （实测）。挂到极值分子上，两者共享同一个分子坐标系，怎么转都同步。

    数值直接取自 surfanalysis.pdb 的 B-factor（即 Multiwfn 找极值时的采样值），
    不做任何"按值反查原子"的匹配——两者本来就会有零点几到一两 kcal/mol 的
    差异，硬匹配只会张冠李戴。

    位置：从极值点沿"重心 → 该点"方向外移 `offset`，紧贴小球外侧。
    不再整体抬到某个 z 平面——那个平面只在默认视角下"在前面"，一转就跑到
    分子背后去，字反而会被挡住，而且看起来离球很远。
    """
    if not points:
        return []
    cx = sum(p["x"] for p in points) / len(points)
    cy = sum(p["y"] for p in points) / len(points)
    cz = sum(p["z"] for p in points) / len(points)
    lines = ["\n# --- extrema value labels ---",
             "# 极值点数值：来自 surfanalysis.pdb 的 B-factor 列",
             f"# 挂在极值球所在分子上（molid = {molid}），随分子一起旋转",
             f"# 每个标注沿\"重心 → 该点\"外移 {offset:.2f} Å，紧贴小球"]
    last_color = None
    placed = []          # 已占用的文字包围盒 (x0, x1, y0, y1)，用于避让
    for p in points:
        text = f"{p['value']:.1f}"
        dx, dy, dz = p["x"] - cx, p["y"] - cy, p["z"] - cz
        norm = (dx * dx + dy * dy + dz * dz) ** 0.5
        if norm > 1e-6:
            k = offset / norm
            tx, ty, tz = p["x"] + dx * k, p["y"] + dy * k, p["z"] + dz * k
        else:
            tx, ty, tz = p["x"], p["y"], p["z"]
        width = _LABEL_CHAR_W * size * len(text)
        # VMD 的 text 从锚点向屏幕右方排；左半边的点如果也从锚点往右写，
        # 整串会压回分子里、被原子和半透明表面挡掉后半截（实测 -36.8 只剩 -36.）。
        # 所以左半边把锚点左移一整串宽度：数字落在点的外侧，看着是"往外标"。
        if dx < 0:
            tx -= width
        # 同一分子上常有几个极值点投影到很近的位置（如 -12.7 与 -22.5），
        # 数字会叠在一起、后画的把先画的盖掉。这里按投影包围盒做简单避让：
        # 上下各让 1 个字号，最多让两次，仍冲突就保持原位（不把标注推得太远）。
        ty = _avoid_overlap(tx, ty, width, size, placed)
        placed.append((tx, tx + width, ty, ty + _LABEL_H_FACTOR * size))
        tz += LABEL_Z_NUDGE
        color = _LABEL_COLOR.get(p["kind"], "red")
        if color != last_color:
            # `graphics ... color` 只认颜色名或 ColorID 的**数字下标**，
            # 写 `color {ColorID 21}` 会报 "unknown color" 且文字整段不生成（实测）。
            lines.append(f"graphics {molid} color {color}")
            last_color = color
        lines.append(
            f'graphics {molid} text {{{tx:.3f} {ty:.3f} {tz:.3f}}} "{text}" '
            f"size {size:.2f} thickness {thickness:.2f}")
    return lines


def _avoid_overlap(tx, ty, width, size, placed, margin=0.12):
    """给文字在投影平面上找一个不与已放置文字重叠的 y。

    文字从锚点向右、向上展开，所以包围盒是 [tx, tx+width] × [ty, ty+h]。
    VMD 的 text 是朝屏幕的贴片，这里只用 xy 投影估算——旋转后会有偏差，
    但避让只在"本来就会叠在一起"时触发，误差可以接受。
    """
    h = _LABEL_H_FACTOR * size
    step = h + margin
    for shift in (0.0, step, -step, 2 * step, -2 * step):
        y = ty + shift
        x0, x1 = tx - margin, tx + width + margin
        y0, y1 = y - margin, y + h + margin
        if not any(x0 < b[1] and x1 > b[0] and y0 < b[3] and y1 > b[2]
                   for b in placed):
            return y
    return ty


def build_iso(systems, color_low, color_high,
              material=DEFAULT_ISO_MATERIAL, opacity=DEFAULT_ISO_OPACITY,
              rendermode="GLSL"):
    alow, ahigh = color_low / AU, color_high / AU
    lines = [iso_head(material, opacity, rendermode)]
    for i, s in enumerate(systems, 1):
        _require(s, ("density", "esp"), i)
        lines.extend(_iso_block(s, i, alow, ahigh, material))
    lines.append("\ndisplay resetview\n")
    return "\n".join(lines)


def build_ext(systems, extrema_labels=None):
    lines = [HEAD_NORMAL]
    for i, s in enumerate(systems, 1):
        _require(s, ("extrema",), i)
        lines.extend(_ext_block(s, i))
    if extrema_labels:
        for i, pts in enumerate(extrema_labels, 1):
            lines.extend(extrema_label_tcl(pts, molid=f"$extmol_{i}"))
    lines.append("\ndisplay resetview\n")
    return "\n".join(lines)


def build_all(systems, color_low, color_high,
              material=DEFAULT_ISO_MATERIAL, opacity=DEFAULT_ISO_OPACITY,
              rendermode="GLSL", extrema_labels=None):
    """ISO 全部铺开后再铺 EXT，使 mol id 映射简单可预测。

    标注放在最后统一生成，这样 `molid_map()` 里 ISO/EXT 的 id 规律不受影响，
    GUI 的实时材质切换仍然找得到正确的分子对象。
    """
    alow, ahigh = color_low / AU, color_high / AU
    lines = [iso_head(material, opacity, rendermode)]
    for i, s in enumerate(systems, 1):
        _require(s, ("density", "esp", "extrema"), i)
        lines.extend(_iso_block(s, i, alow, ahigh, material))
    for i, s in enumerate(systems, 1):
        lines.extend(_ext_block(s, i))
    if extrema_labels:
        for i, pts in enumerate(extrema_labels, 1):
            lines.extend(extrema_label_tcl(pts, molid=f"$extmol_{i}"))
    lines.append("\ndisplay resetview\n")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
#  对外入口
# ══════════════════════════════════════════════════════════

BUILDERS = {
    "pt": build_pt,
    "iso": build_iso,
    "ext": build_ext,
    "all": build_all,
}


def generate_vmd_script(mode, script_dir, systems, color_low, color_high,
                        pt_size=2.0, show_colorbar=False,
                        colorbar_unit="kcal/mol",
                        material=DEFAULT_ISO_MATERIAL,
                        opacity=DEFAULT_ISO_OPACITY,
                        rendermode="GLSL",
                        extrema_labels=None):
    """生成脚本文件，返回绝对路径。

    `extrema_labels`：与 `systems` 等长的列表，每项是该分子要标注的极值点
    （`cache.parse_surfanalysis_pdb` + `cache.pick_extrema` 的结果）。只对
    EXT / ALL 生效；为空则不标注。
    """
    if mode not in BUILDERS:
        raise ValueError(f"未知模式: {mode}")
    if not systems:
        raise ValueError("没有可加载的分子")
    if material not in ISO_MATERIALS:
        material = DEFAULT_ISO_MATERIAL
    if mode == "pt":
        extrema_labels = None

    if mode == "pt":
        body = build_pt(systems, color_low, color_high, pt_size)
    elif mode == "ext":
        body = build_ext(systems, extrema_labels)
    elif mode == "iso":
        body = build_iso(systems, color_low, color_high,
                         material, opacity, rendermode)
    else:
        body = build_all(systems, color_low, color_high,
                         material, opacity, rendermode, extrema_labels)

    if show_colorbar:
        # 刻度轴标签统一按 kcal/mol 标注：iso/all 的 scaleminmax 用 a.u.，
        # 但端点值本身是由 kcal/mol 换算而来，标注 kcal/mol 才与物理量一致。
        body += colorbar_tcl(color_low, color_high, "kcal/mol")

    os.makedirs(script_dir, exist_ok=True)
    path = os.path.join(script_dir, f"esp_auto_{mode}.vmd")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def molid_map(mode, nsystems):
    """预测 VMD 加载后各分子对象的 id。

    pt  : 每个体系 2 个 mol（mol, vtx），交错加载 → 2i / 2i+1
    iso : 每体系 1 个 → 0..n-1
    ext : 每体系 1 个 → 0..n-1
    all : 先全部 ISO 再全部 EXT → ISO 为 0..n-1，EXT 为 n..2n-1
    """
    n = max(0, nsystems)
    if mode == "pt":
        return {"mol": [2 * i for i in range(n)],
                "vtx": [2 * i + 1 for i in range(n)]}
    if mode == "iso":
        return {"iso": list(range(n))}
    if mode == "ext":
        return {"ext": list(range(n))}
    if mode == "all":
        return {"iso": list(range(n)), "ext": [n + i for i in range(n)]}
    return {}
