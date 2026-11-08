# ESPViewer v2.3.6

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20791148.svg)](https://doi.org/10.5281/zenodo.20791148)

基于 Multiwfn + VMD 的静电势（ESP）表面可视化工具，PyQt5 GUI 界面。
By Dongxu Yi Rebuild.

📺 **视频演示**：[B站 BV1zSVW6PEwe](https://www.bilibili.com/video/BV1zSVW6PEwe/)

> **v2.3.6 更新**：**界面收敛为"浅色 + 中文"单一形态**——删掉深色主题与右上角的 `◐`
> 切换按钮（`theme.py` 只剩一套色板，不再有 `set_active()` / QPalette 换肤流程）；
> 删掉英文界面与 `EN` 按钮（`TR` 从 `{"zh":…, "en":…}` 收敛成纯字符串，语言检测、
> `--lang`、`ESPVIEWER_LANG`、`_CN`/`_EN` 变体 exe 全部移除，`build_exe.py` 只产出一份
> `dist/ESPViewer.exe`）。同时修掉**版本号与作者各显示两次**的问题：窗口标题回归
> `ESPViewer`，版本徽标 `v2.3.6` 与 `By Dongxu Yi Rebuild` 只在顶栏各出现一次，
> 启动日志也不再重复。顺手修了渲染分辨率下拉框被 QSS `min-width` 压窄、
> `2000x1500` 显示成 `2000x1` 的老问题

> **v2.3.5 更新**：**一个构建出三个 exe**——`ESPViewer.exe`（默认中文）、
> `ESPViewer_CN.exe`、`ESPViewer_EN.exe`。启动语言由 `detect_initial_lang()` 判定，
> 优先级 `--lang` > `ESPVIEWER_LANG` > **exe 文件名后缀** > 中文，因此三份二进制
> 完全相同、只靠名字区分，省掉两次重复打包。新增一键脚本 `build_exe.py`
> （`python build_exe.py` 即重编并生成三份）——*该方案在 v2.3.6 已取消*

> **v2.3.4 更新**：**窗口标题栏与顶栏写上版本号和作者标注**——窗口标题改为
> `ESPViewer v2.3.4 — By Dongxu Yi Rebuild`（版本号由 `APP_VERSION` 注入，
> 此前 `win_title` 写死 v2.0，中英文切换后标题栏一直显示旧版本）；顶栏在版本徽标旁
> 新增弱化的 `By Dongxu Yi Rebuild` 标签，运行日志首行同样带出处
> ——*v2.3.6 已收敛为"顶栏各显示一次"，标题栏与日志不再重复*

> **v2.3.3 更新**：**打包成单个 exe**（`pyinstaller ESPViewer.spec` → `dist/ESPViewer.exe`，
> 约 79 MB，无控制台窗口，双击即用，不需要装 Python）。同时解决打包后必然踩到的
> "工具路径默认值不存在"：exe 首次运行会在 **PATH、各盘符根目录、常见软件目录**里
> 自动找 `Multiwfn.exe` / `vmd.exe` / `tachyon_WIN32.exe`，找到后写进 exe 同目录的
> `esp_surface_gui.ini` 并在日志里说明；找不到就到【路径设置】手动选一次即可

> **v2.3.2 更新**：修掉"**看着像卡死、点停止也没反应**"的两个老问题——
> ① Multiwfn 的进度条用 `\r` 刷同一行，旧的逐行读法永远等不到换行，于是进度、
> 日志、停止标志全都拿不到，界面像死机；现在按 `\r`/`\n` 双分隔实时取值，
> 状态栏能看到 `Progress: [####----] 42 %`，每 60 s 还会提示"仍在计算（已运行 N s）"。
> ② 「■ 停止」过去只置一个布尔，而这个标志只在**步骤之间**检查，正在跑的那一步
> （大体系 ESP 动辄十几分钟）根本停不下来、按钮一直灰着；现在直接 `taskkill /T` 结束
> 进程树，实测 **1 s 内**松开界面，并提示"已停止"。
> 另外把 `[计算] ISO（缺 density / esp）` 改成 `[计算] ISO：缺少 density / esp，正在调用
> Multiwfn 补算…`——旧文案容易被读成"缺文件所以停下了"，其实那一行就是自动补算的开始；
> 每步结束再报一次 `[完成] ISO 用时 N s`
> **v2.3.1 更新**：渲染图默认存到**与输入文件同名的文件夹**（`<fchk主名>/<fchk主名>_esp.png`），
> 与计算结果放在一起；「输出路径」框**不再复用上一次的字面路径**——此前先对 A 点「渲染输出」
> （自动填入 `A_esp.tga`）、再换 B 点「渲染当前视角」时，B 的图会把 A 的覆盖掉。
> 现在留空即按**当前**输入文件推导、换文件自动跟随；手动填写或浏览选择才严格照填，清空即回到自动。
> **所有产物统一收进同名文件夹**：渲染图、ESP 分区面积图（`_esp_area.png` / `_esp_area_data.txt`）、
> 中间产物、计算临时区 `_espcalc/` 全在 `<fchk主名>/` 内，数据目录里只剩 fchk 本身；
> 每个分子计算完成后日志会明确打印产物落位，关掉「计算后保存中间文件」时也会给出提示
> **v2.3.0 更新**：界面**整体重做为卡片式现代风**（**默认浅色**，深色科技风可切换）——顶部品牌栏（渐变底 + 青色发丝线 +
> 版本徽标）、卡片化分组、青色主按钮/描边次按钮/红色危险按钮三种角色；配色与 QSS
> 全部收进 `theme.py`，界面代码里**不再有写死的色值**；右上角 `◐` 可一键在
> **浅色 / 深色**之间切换（写入配置，下次启动保持）。原生图元（下拉箭头、表格表头）
> 通过 QPalette 同步换色，不会出现深底黑三角；两个 Tab 页的内容套了滚动区，
> 窗口比内容矮时**出滚动条而不是把行压扁**（此前模式开关会叠到下一行文字上）；
> 初始窗口按**内容真实高度**开（`_content_hint()` 修正了 `QScrollArea::sizeHint()`
> 被 Qt 截断成 36 字符 × 24 行的问题），默认 1240 宽、屏幕放得下就一屏显示完
> **v2.2.1 更新**：模式改为**四个独立的滑动开关**（PT / ISO / EXT / ALL 各一个，互斥：
> 打开一个其余自动关闭，点当前项不会被关掉）；渲染分辨率、表面材质、校验策略**恢复为下拉框**
> （枚举选项用下拉更直观），数字类的每侧数量、分区数量仍是滑块
> **v2.2.0 更新**：模式里的单选按钮全部退场，改由滑动开关承担；
> 「显示色彩刻度轴」「标注极值点数值」「计算后保存中间文件」三个方框改成**胶囊滑动开关**
> （左开关 + 右文字，点击整行都能切，蓝色为开）
> **v2.1.9 更新**：界面里的**选择框全部换成滑块**——渲染分辨率、表面材质、校验策略、
> 极值点每侧数量（以及面积图弹窗的分区数量）都改成拖动式滑块，数值/选项实时显示在右侧，
> 看不清的选项可悬停查看完整文字；ESP 分区面积图的标题**不再带 `-文件名`**；
> 主窗口与所有弹窗、任务栏统一使用 `ESPViewer.ico`
> **v2.1.8 更新**：ESP 分区面积图弹窗会**自动检测并填入** ESP 上下限（读已有产物，
> 不额外调用 Multiwfn，仍可手动改）；修掉范围计算的 a.u.→kcal/mol **二次换算**
> （极端情况下会大 627 倍）；默认窗口尺寸改为按屏幕自适应，模式单选/提示文字不再挤在一起
> **v2.1.7 更新**：极值点数值**紧贴小球**（外移 0.55 Å，原来约 2.7 Å），并挂到
> **极值球所在的那个分子**上——拖动旋转时数字和小球、骨架一起转；左半边的数字改为
> 往**外侧**排（不再压回分子里截断），挨太近的数字自动上下错开
> **v2.1.6 更新**：极值点改为**红=极大、蓝=极小**（球与数字同色）；
> `ESP_auto.sh` 支持"只有 chk / 只有 fchk / 两者都有"三种输入，并改为**增量计算**
> （已有产物校验通过就跳过，不再整目录重建）；`bundle.json` 记录 Multiwfn 版本，
> **换掉 Multiwfn 后旧 bundle 仍可直接用**，只在预检里提示差异
> **v2.1.5 更新**：EXT/ALL 可把**极值点数值标在图上**（教程里要手工往 PPT 里加的那种），
> 每侧个数可调；数值直接取 `surfanalysis.pdb`，不做"按值反查原子"的脆弱匹配
> **v2.1.4 更新**：ISO 默认效果对齐 MEP 教程——不再覆盖 `Transparent` 的出厂高光参数、
> 补齐 4 盏灯、透明度默认 0.30。实测与教程 `ESPiso.vmd` 渲染结果**逐像素一致**（MAD = 0）
> **v2.1.3 更新**：等值面改用半透明材质（效果同 MEP 教程），透明度/材质可调；
> 修掉 `EdgyGlass` 在无头 Tachyon 下崩溃、「渲染当前视角」因相对路径一直失败
> **v2.1.2 更新**：计算临时文件改到数据目录下的 `_espcalc/`（不再占用系统临时目录），
> EXT 顺带产出的 `mol.pdb`/`vtx.pdb` 自动收下（后面跑 PT 免算）
> **v2.1.1 更新**：实机联调（Linux 服务器 + Windows 本地）修掉 4 个确定性缺陷——
> ESP 网格质量两端不一致、PT 点云渲染崩溃、渲染命令误执行 shell、渲染成功判定失效
> **v2.1 更新**：中间文件复用（服务器算完直接读，缺失才调用 Multiwfn）、数据零拷贝、多分子 EXT 修复
> **v2.0 更新**：修复渲染出图 bug + 新增色彩刻度轴

## 功能

- **中间文件复用**：`mol.pdb / vtx.pdb / density.cub / totesp.cub / surfanalysis.pdb` 已存在时直接读取，只补算缺失的那一步
- **顺带收产物** 🆕：EXT 步骤会顺带产出 `mol.pdb`/`vtx.pdb`，程序自动收下，之后跑 PT 零计算
- **零拷贝** 🆕：VMD 脚本用绝对路径引用原文件，不复制、不重命名、不删除任何数据
- **预检表格** 🆕：不启动任何计算，先看清每个分子哪一步命中、哪一步要算
- **四种分析模式**：PT（顶点着色）、ISO（等值面）、EXT（极值点）、ALL（叠加显示）
- **VMD 交互式预览**：实时 3D 分子表面渲染，可旋转/缩放/平移
- **半透明等值面（对齐 MEP 教程）** 🆕：ISO/ALL 默认即教程观感——`Transparent` 保留出厂高光参数 + 4 盏灯，表面是"有光泽的半透明薄膜"而不是灰白发雾；可切换 `GlassBubble`（玻璃泡）/`Opaque`，透明度 0.05–1.00 实时可调，切换材质时透明度按教材推荐值自动跟随
- **色彩刻度轴**：VMD 内置 Color Scale Bar，清晰标注 ESP (kcal/mol) 数值，实时联动色彩范围
- **Tachyon 高质量渲染**：双路径渲染（无头 TachyonInternal + 外部 Tachyon 交互渲染），外部 Tachyon 失败时自动回退内置渲染器
- **多档分辨率**：四档可选 1200×900 ~ 4000×3000
- **极值点数值标注** 🆕：EXT/ALL 勾一下就把表面极大/极小值标在图上（**红=极大、蓝=极小**，与极值球同色），每侧个数可调；数值来自 `surfanalysis.pdb`，不会与 `atomsurface.txt` 的逐原子值硬匹配
- **极值点交互查询**：VMD 中点击极值点球查询 ESP 值（自动识别 eV / kcal/mol）
- **ESP 分区面积图**：分面面积分布柱状图 + 数据导出（Origin/Excel 可用）
- **中文界面**：单语言（v2.3.6 起不再提供英文界面）

## ISO 等值面效果（v2.1.4）

ISO 模式点下去就是 MEP 教程的观感：等值面沿用 VMD 内置 `Transparent` 材质
**自带的镜面高光**（v2.1.3 曾把 ambient/diffuse/specular/shininess 全部改写，
反而把高光压平了），再配教程同样的 4 盏灯和 0.30 透明度，表面呈现"有光泽的
半透明薄膜"，内部球棍骨架清晰可见。

| 旧版 v2.1.3（高光被压平、发雾） | 新版（对齐教程 `ESPiso.vmd`） |
|---|---|
| ![](docs/samples/ESPViewer_ISO_before_v2.1.3_flat.png) | ![](docs/samples/ESPViewer_ISO_after_v2.1.5_tutorial.png) |

同一份 `density.cub` / `totesp.cub`（D-π-A 示例，ESP 色标 ±45 kcal/mol，1400×1000）。
玻璃泡材质（`GlassBubble`，0.26）：

![](docs/samples/ESPViewer_ISO_GlassBubble_0.26.png)

> 验证方式：用同一组 cube 分别跑教程原版 `ESPiso.vmd` 与本程序生成的脚本，
> 两张渲染图逐像素比较 **MAD = 0.000**。

## 极值点数值标注（v2.1.5）

EXT / ALL 模式勾选「标注极值点数值」即可，右侧数字框控制**每侧标注几个**
（默认 4 个，按 |值| 取最显著的；下面两张样图取了 3 个，免得挤在一起）：

![](docs/samples/ESPViewer_EXT_extrema_labels.png)

- **红色 = 表面极大值，蓝色 = 表面极小值**，与极值球同色（与 BWR 色标的高低端一致）
- 数值取自 `surfanalysis.pdb` 的 B-factor 列，单位 kcal/mol
- 用 3D `graphics text` 绘制：交互预览和 Tachyon 出图**都有**；
  老式的 `label add Atoms` 只在 OpenGL 窗口里叠一层，出图时根本不出现
- 文字紧贴小球：从极值点沿"重心 → 该点"方向只外移 **0.55 Å**，字号 **1.5 Å**，
  不再整体抬到某个 z 平面（那会把字放到离球 2~3 Å 外，看着像两件不相干的东西）。
- 文字**挂在极值球所在的分子上**（`graphics $extmol_<i> ...`），不是另开空分子。
  空分子没有原子，拖动旋转时它的坐标系不跟真实分子走，会出现"球转了、字没转"；
  挂在同一个分子上，两者共享同一套变换，任何角度都同步。
- 左半边的极值点，锚点会再左移一整串宽度（VMD 的 text 从锚点向右排）。
  否则 `-36.8` 会横着压回分子里，后半截被原子挡住、只剩 `-36.`。
- 两个极值点投影得很近时（如 `-12.7` 与 `-22.5`），按包围盒上下错开一个字高，
  避免后画的把先画的盖掉。
- 已知小瑕疵：数字与它压着的原子**同色**时（蓝色 `-12.7` 正好落在蓝色 N 上），
  负号会糊在球里、读成正数。把「每侧标注个数」调小、或把视角转一点即可避开；
  EXT 模式没有原子，不会出现这种情况。

![](docs/samples/ESPViewer_ALL_extrema_labels.png)

### 关于"极值点数值和 atomsurface.txt 略有出入"

这是 Multiwfn 的正常现象，不是 bug：`surfanalysis.pdb` 记的是**在 vdW 面上搜索到的
局域极值点处的值**（采样点位置由搜索步长决定），`atomsurface.txt` 记的是**每个原子
表面上的统计值**。两者采样位置不同，因此常常差零点几到一两 kcal/mol，但**排序和
趋势一致**（极大仍是极大、极小仍是极小）。

所以程序的处理方式是：**只用 `surfanalysis.pdb` 自己的坐标 + 自己的值**，
绝不拿数值去 `atomsurface.txt` 里"按值反查是哪个原子"——那种匹配在数值有微小偏差时
就会张冠李戴。你若要判断某个极值点属于哪个原子，用坐标看更快（工具 → 极值点查询）。

## 依赖

### 必需（外部程序）

| 工具 | 用途 |
|------|------|
| [Multiwfn](http://sobereva.com/multiwfn/) | 从 .fchk 计算 ESP 表面数据 |
| [VMD](https://www.ks.uiuc.edu/Research/vmd/) | 3D 分子可视化 + Tachyon 渲染 |
| Tachyon（VMD 自带） | 光线追踪渲染器 |

### 可选（Python 包）

```
matplotlib  numpy  pillow  PyQt5
```

- `matplotlib + numpy`：ESP 分区面积图功能需要
- `Pillow`：BMP → PNG 图片转换
- `PyQt5`：GUI 框架

## 文件说明

| 文件 | 说明 |
|------|------|
| `esp_surface_gui.py` | **v2.3 主程序**（PyQt5 重构，全功能） |
| `theme.py` | **配色与 QSS 单一来源**：浅色色板、控件角色样式、QPalette |
| `cache.py` | 中间文件解析、指纹校验、临时工作区（可独立单测） |
| `tclgen.py` | VMD/TCL 脚本生成（逐分子绝对路径） |
| `tests/` | 单元测试与端到端流程测试 |
| `docs/BUNDLE_CACHE_DESIGN.md` | 中间文件复用方案设计文档 |
| `ESPViewer.spec` | PyInstaller 打包配置 |
| `ESPViewer.py` | v1.x 基础版（单面板布局） |
| `ESPViewer_cn.py` | v1.x 中文增强版 |
| `ESPViewer_en.py` | v1.x 英文增强版 |

## 界面配色

配色与样式表**只在 `theme.py` 里定义**，界面代码中不再出现写死的十六进制色值：

- `PALETTE`：底色、卡片、描边、文字、强调色、按钮渐变等全部 token，**只有一套浅色**
  （v2.3.6 删掉了深色主题与切换入口）
- 控件用 `objectName` 标记角色，QSS 按角色上色：
  `PrimaryBtn`（青色实心，主操作）、`GhostBtn`（描边，次要操作）、
  `DangerBtn`（红色描边，清空/停止）
- 自绘控件（顶部品牌栏、胶囊开关）读 `theme.active_palette()`
- 原生图元（下拉箭头、表格表头、勾选标记）由 `QApplication.setPalette()` 同步取色，
  不会出现看不清的黑色小三角

要微调观感，改 `PALETTE` 里的 token 即可；想换成别的色系，把整套 token 换掉，
其余代码不用动（注意 QSS 里 `QComboBox` 的 `min-width` 会盖掉 `setMinimumWidth`，
个别下拉框需要单独放宽时用 objectName 加规则）。

## 中间文件复用

选好 `.fchk` 后，程序会先在三个位置找已有的 Multiwfn 产物，命中就跳过计算：

| 优先级 | 位置 | 说明 |
|---|---|---|
| 1 | 与 `.fchk` 同目录 | 本地直接算过的场景 |
| 2 | `<fchk目录>/<fchk主名>/` | **`ESP_auto.sh` 的输出布局** |
| 3 | 路径设置页指定的「缓存目录」下 `<fchk主名>/` | 服务器结果集中存放 |

产物文件名统一为 Multiwfn 原生名，Linux 与 Windows 完全一致：

```
mol.pdb  vtx.pdb  density.cub  totesp.cub  surfanalysis.pdb  medinfo.txt
```

典型用法：在服务器跑完 `Script/ESP_auto.sh`，把 `fchk/` 整个目录拷回本地，
在程序里选中 `fchk/*.fchk`，点「预检中间文件」确认全部命中，然后直接预览 / 出图 —— 全程不调用 Multiwfn。

### 目录命名规则（重要）

第 2、3 项的子目录名**必须与 fchk 主名一致**（不含 `.fchk`/`.fch` 扩展名，
大小写不敏感），程序**不会**递归搜索，也不会把任意子目录当成缓存。
唯一例外：子目录里有 `bundle.json`，且其中 `source.name` 正好是当前 fchk 文件名
（文件夹被改过名时兜底；最终仍要过指纹校验）。

```
fchk/
├── benzene.fchk        ← 输入
├── benzene/            ← 只会认这个（同名）
│   ├── density.cub
│   ├── totesp.cub
│   ├── mol.pdb
│   ├── vtx.pdb
│   ├── surfanalysis.pdb
│   ├── atomsurface.txt
│   └── medinfo.txt
└── other/              ← 名字对不上，忽略
```

`ESP_auto.sh` 的产物天然就是这个布局（`fchk/<分子名>/`），整个 `fchk/` 拷回来即可。
如果产物和 fchk 直接放在同一层（第 1 项），也能识别；只是多分子时容易互相覆盖，不推荐。

**校验策略**（路径设置页）：

| 策略 | 行为 |
|---|---|
| 自动（默认） | 有 `bundle.json` 时做严格指纹校验；没有则照常使用，但日志标记「未验证」 |
| 严格 | 只信任有 `bundle.json` 且指纹匹配的产物，否则重算 |
| 信任现有文件 | 存在即用，不校验 |

`bundle.json` 记录源 fchk 的大小与头部 sha1、网格质量、极值点单位、各产物的字节数与 sha1。
`ESP_auto.sh` 会自动生成它；本地计算产生的产物也由程序自动写出。

> 注意：**「计算后保存中间文件」默认开启**，本地算过一次的产物会写回 `<fchk主名>/`，下次直接复用。
> 程序不会删除或移动你的任何已有文件。

## 下载

📦 **打包好的 exe 请到 Release 页面下载**：[V1.0 Release](https://cnb.cool/chem311/ESPViewer/-/releases/tag/V1.0)（v2.0 打包版即将发布）

- `ESPViewer.exe` — 单文件绿色版（中文界面）

无需安装 Python，下载即用。

## 使用方法

### v2.1 从源码运行

```bash
pip install PyQt5 matplotlib numpy pillow
python esp_surface_gui.py
```

### 运行测试

```bash
python tests/test_cache.py                          # 纯逻辑，无需 GUI
python tests/test_gui_flow.py                       # 端到端，需要 PyQt5
```

`test_gui_flow.py` 会把 Multiwfn 与 VMD 调用打桩，验证「缓存齐全时零次计算」
「只缺一项时只补算一步」「数据目录只增不减」等关键行为，不需要真实安装 Multiwfn / VMD。

### v1.x 从源码运行

```bash
python ESPViewer_cn.py    # 中文版
python ESPViewer_en.py    # 英文版
```

### 打包为 exe

```bash
pip install pyinstaller pyqt5 matplotlib numpy
python build_exe.py                   # 一键：干净重编
# 或手动：
pyinstaller ESPViewer.spec --clean
```

产物：`dist/ESPViewer.exe`，**单文件**、约 79 MB、无控制台窗口，双击即用
（v2.3.6 起只出一个 exe，不再有 `_CN` / `_EN` 变体）。

- 配置写在 **exe 同目录**的 `esp_surface_gui.ini`；目录不可写时回退到
  `%APPDATA%\ESPViewer\`。换台机器只要拷 exe 即可，配置会重新生成
- 首次启动若默认的 Multiwfn / VMD / Tachyon 路径不存在，程序会自动去
  **PATH、各盘符根目录、`Program Files`、`%LOCALAPPDATA%` 等常见位置**找
  （按目录名 `multiwfn*` / `vmd*` 匹配，只在两层内查找并设扫描上限，
  实测 0.02 s），找到后写回配置并在日志里写明；找不到就在【路径设置】手动选
- 打包用的是 `ESPViewer.spec`：自动带上 `ESPViewer.ico`（`datas`），
  并把本地模块 `cache` / `tclgen` / `theme` 列入 `hiddenimports`
- 单文件模式每次启动要把内容解到临时目录，首次打开约 3–5 s，属正常现象；
  需要秒开可把 spec 里的 `EXE(...)` 拆成 `COLLECT(...)` 走目录模式

## 输入文件

支持 Gaussian 格式化检查点文件：`.fch` / `.fchk`

## 输出文件

所有产物默认都放在**与输入文件同名的文件夹**里（`<fchk主名>/`），一个分子一处，批量处理互不覆盖：

- **渲染图片**：`<fchk主名>/<fchk主名>_esp.png`（Tachyon 渲染结果）。
  「输出路径」留空即按此规则自动推导、**换输入文件会跟着变**；手动填写/浏览选择则严格照填
- **中间文件**（开启「计算后保存中间文件」时）：`<fchk主名>/` 下的 `mol.pdb`、`vtx.pdb`、`density.cub`、`totesp.cub`、`surfanalysis.pdb`、`medinfo.txt`、`bundle.json`，以及临时区 `_espcalc/`（脚本与中间态，可手动删除）
- **面积分布图**：`<fchk主名>/<fchk主名>_esp_area.png`（柱状图）
- **面积数据**：`<fchk主名>/<fchk主名>_esp_area_data.txt`（Tab 分隔，Origin/Excel 可用）

计算临时区也在同名文件夹内（`<fchk主名>/_espcalc/`：VMD 脚本、ASCII 暂存、`sysN/` 中间态），
数据目录里除 fchk 本身外不会再散落任何程序产生的文件。清空文件列表后临时区会重新锚定，
换分子不会复用上一个分子的目录。

## 路径配置

首次运行后需设置以下路径（点击浏览按钮或手动输入）：

| 项 | 说明 |
|---|---|
| Multiwfn.exe | 仅在需要计算时使用；中间文件全部命中时可以留空 |
| VMD 可执行文件 | vmd.exe |
| VMD 目录 | **可选**。VMD 的启动工作目录，留空则使用临时脚本目录（推荐留空） |
| Tachyon | tachyon_WIN32.exe |
| 缓存目录 | **可选**。服务器结果的集中存放根目录 |
| 校验策略 | 自动 / 严格 / 信任现有文件 |
| 计算后保存中间文件 | 默认开启 |

配置保存到 `esp_surface_gui.ini`；若程序目录不可写（例如安装在 `Program Files`），
自动改为保存到 `%APPDATA%\ESPViewer\esp_surface_gui.ini`。

> v2.1 起「VMD 目录」不再是数据中转目录。程序不再向其中写入或删除 ESP 中间文件，
> 中间文件只在**计算时**写入对应的 `<fchk主名>/` 目录。

## 计算临时文件

需要调用 Multiwfn 时，中间态写在**该分子自己的目录**下，不占用系统临时目录：

```
<fchk 所在目录>/<fchk 主名>/
├── mol.pdb  vtx.pdb  density.cub  totesp.cub  surfanalysis.pdb   ← 产物（复用依据）
├── bundle.json                                                   ← 指纹清单
└── _espcalc/                                                     ← 临时区
    ├── scripts/           VMD 脚本（每次运行重新生成）
    └── sys1_iso/  sys1_ext/   各自的 fch 副本与未回写的附带产物
```

`_espcalc/` **不会随程序退出自动删除**，方便复查渲染现场，看完手动删掉即可。
只有数据目录不可写时，才回退系统临时目录并在退出时自动清理。

## 服务器脚本 `ESP_auto.sh`（v1.3）

输入自动判定，不用再手动删 / 移文件：

| 目录内容 | 行为 |
|---|---|
| 只有 `*.chk` | 全部 `formchk` 转成 fchk 再算 |
| 只有 `*.fchk` | 跳过转换，直接算 |
| 两者都有 | 把所有 `.chk` 转成 fchk（同名 fchk 会被覆盖）再算 —— 以 chk 为权威来源 |

**增量计算**：不再把 `fchk/` 改名重建。每个分子按 `bundle.json` 校验（源 fchk 大小与
头部 sha1、`grid_quality` / `esp_grid_quality`、各产物字节数与 sha1），通过就跳过，
只算新增或失效的分子。没有 `python3` 时退化为"7 个文件齐全即复用"，不做指纹校验。

**Multiwfn 版本**：`bundle.json` 的 `generator.multiwfn` 记录版本（取自 `medinfo.txt`
的 banner）。它**不参与失效判定** —— 换掉 Multiwfn 可执行文件后旧产物照旧可用，
程序只在「预检中间文件」里提示版本差异；要让整条链都用新版本重算，删掉对应目录的
`bundle.json` 即可。

## 跨平台一致性

Linux（`Script/ESP_auto.sh`）与 Windows（本程序）必须用**同一套 Multiwfn 命令序列**，
否则同一份 fchk 会得到格点不同的 `totesp.cub`，表面着色随之改变。关键参数有两处：

| 参数 | 取值 | 含义 |
|---|---|---|
| `grid_quality` | 3 | 电子密度网格（`5→1→3→2`），决定 `density.cub` |
| `esp_grid_quality` | 2 | ESP 网格（`5→12→2→2`），决定 `totesp.cub` |

> v2.1.1 之前 GUI 的 ESP 网格用的是 `1`（低质量，约 13 万点），脚本用 `2`（中等，约 53 万点）。
> 已统一为 `2`，实测两端生成的 `totesp.cub`/`density.cub` 的 sha1 完全一致。
> `bundle.json` 里会记录 `esp_grid_quality`，不一致时该产物会被判为失效并重算。

## 已知限制

- **遇到整片单色时先重算 cub**：实测用当前版本生成的配套 `density.cub` + `totesp.cub`，
  ISO/ALL 的红蓝分区是正常的。如果出图整片红或整片蓝，多半是沿用了旧版本留下的 cub
  （v2.1.0 及更早版本的 ESP 网格质量与密度不一致）。处置：删掉该分子目录下的
  `density.cub`、`totesp.cub` 与 `_espcalc/`，再跑一次即可。
- **VMD 的退出码不可信**：Windows 版 VMD 1.9.4a53 在完成渲染后返回 127，
  退出 `quit` 时还可能以 `0xC0000374`（3221226356，堆损坏）结束，但图片已经写完整。
  程序以「输出文件是否真的被写出」判定成功，不看 returncode；日志里那行只是提示。

## 致谢

本软件的核心计算引擎来自 **卢天老师** 开发的 **Multiwfn** 多功能波函数分析程序，特此致以最诚挚的感谢！

> Tian Lu, Feiwu Chen, *Multiwfn: A Multifunctional Wavefunction Analyzer*, J. Comput. Chem., **2012**, 33, 580–592. DOI: [10.1002/jcc.22885](https://doi.org/10.1002/jcc.22885)
>
> Tian Lu, *A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn*, J. Chem. Phys., **2024**, 161, 082503. DOI: [10.1063/5.0216272](https://doi.org/10.1063/5.0216272) (JCP Editors' Choice 2024)

Multiwfn 目前已被超过 4 万篇论文引用，用户遍布全球 90 余国。

## 📖 引用 / Cite

若您的研究使用了本软件，请按以下格式引用：

> houcheng-gxnu. (2026). *ESPViewer* (Version 2.0.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20791148

```bibtex
@software{espviewer_2026,
  author       = {Hou, Cheng},
  title        = {ESPViewer},
  year         = 2026,
  publisher    = {Zenodo},
  version      = {2.0.0},
  doi          = {10.5281/zenodo.20791148},
  url          = {https://doi.org/10.5281/zenodo.20791148}
}
```

## 许可证

MIT License
