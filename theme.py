# -*- coding: utf-8 -*-
"""ESPViewer 配色：单一浅色主题。

设计要点
--------
* 只在这里定义颜色，界面代码不再写死十六进制色值；
* 控件用 objectName 标记"角色"（PrimaryBtn / GhostBtn / DangerBtn ...），
  QSS 按角色统一上色，按钮改配色不用再逐处改代码；
* 自绘控件（ToggleSwitch / StatusButton / HeaderBar）通过 active_palette()
  取色板。

v2.3.6 起去掉了深色主题：只有一套浅色色板，没有切换入口。

用法：:

    import theme
    app.setStyleSheet(theme.qss())      # 全局样式
    app.setPalette(theme.palette())     # 原生图元（下拉箭头、勾选）也跟着变
"""

from string import Template

# ── 色板 ────────────────────────────────────────────────
# 命名沿用"角色"而不是色相，改色时映射关系不变。
PALETTE = {
    "WIN":      "#E9EFF8",
    "PANEL":    "#FFFFFF",
    "CARD":     "#FFFFFF",
    "CARD2":    "#F5F8FD",
    "FIELD":    "#FFFFFF",
    "LINE":     "#CBD5E1",
    "LINE_HI":  "#94A3B8",
    "TXT":      "#1E293B",
    "TXT_MID":  "#475569",
    "TXT_DIM":  "#64748B",
    "ACC":      "#0EA5E9",
    "ACC_HI":   "#38BDF8",
    "ACC_DK":   "#0369A1",
    "OK":       "#10B981",
    "WARN":     "#F59E0B",
    "ERR":      "#DC2626",
    "VIO":      "#8B5CF6",
    "ACC_A08":  "rgba(14, 165, 233, 0.07)",
    "ACC_A16":  "rgba(14, 165, 233, 0.14)",
    "ACC_A30":  "rgba(14, 165, 233, 0.26)",
    "ERR_A10":  "rgba(239, 68, 68, 0.08)",
    "ERR_A40":  "rgba(239, 68, 68, 0.35)",
    "ON_ACC":   "#FFFFFF",
    "ACC_TEXT": "#0B6E8F",   # 浅色底上够深的青，白底对比 ≈ 5.4
    "BTN_G1":   "#0A79B4",
    "BTN_G2":   "#0369A1",
    "BTN_TXT":  "#FFFFFF",
    "SHADOW":   "rgba(15, 23, 42, 0.12)",
    "LOG_TXT":  "#1E293B",
    "LOG_SEL":  "rgba(14, 165, 233, 0.18)",
    "HANDLE_BG": "#FFFFFF",
    "TRACK_OFF": "#D7E1EE",
    "KNOB_OFF":  "#8FA3B8",
}


def active_palette():
    """当前色板（自绘控件用）。只有一套，返回值恒定。"""
    return PALETTE


# ── QSS 模板 ────────────────────────────────────────────
# 用 $TOKEN 占位；QSS 里没有 $ 字符，Template 替换是安全的。
_QSS = Template("""
/* ══ 基础 ══ */
QMainWindow, QDialog, QMessageBox {
    background: $WIN;
}

QWidget {
    font-family: "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI",
                 "Microsoft YaHei", sans-serif;
    font-size: 9pt;
    color: $TXT;
}

QToolTip {
    background: $CARD;
    color: $TXT;
    border: 1px solid $LINE_HI;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 8.5pt;
}

/* ══ 卡片（GroupBox）══ */
QGroupBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 $CARD, stop:1 $CARD2);
    border: 1px solid $LINE;
    border-top: 1px solid $ACC_A30;
    border-radius: 10px;
    margin-top: 16px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 9pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0px 8px 0px 8px;
    margin-top: 2px;
    color: $ACC_TEXT;
    background: $CARD;
    border-radius: 4px;
    font-size: 9pt;
    font-weight: 700;
}

/* ══ 文字 ══ */
QLabel {
    color: $TXT_MID;
    background: transparent;
    padding: 0px;
}

QLabel#BrandTitle {
    color: $TXT;
    font-size: 16pt;
    font-weight: 700;
}

QLabel#BrandSub {
    color: $TXT_DIM;
    font-size: 7.5pt;
}

QLabel#VersionChip {
    color: $ACC_TEXT;
    background: $ACC_A08;
    border: 1px solid $ACC_A30;
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 8pt;
    font-weight: 700;
}

QLabel#AuthorTag {
    color: $TXT_MID;
    background: transparent;
    border: 1px solid $LINE;
    border-radius: 9px;
    padding: 2px 9px;
    font-size: 8pt;
}

QLabel#HintLabel {
    color: $TXT_DIM;
    font-size: 7.8pt;
    padding: 2px 2px 0px 2px;
}

QLabel#StatusLabel {
    color: $TXT_DIM;
    font-size: 8.5pt;
    font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
}

QLabel#SliderValue {
    color: $ACC_TEXT;
    font-size: 9pt;
    font-weight: 700;
    font-family: "Cascadia Mono", "Consolas", monospace;
}

QLabel#SliderValue:disabled {
    color: $TXT_DIM;
}

QLabel#FileCountLabel {
    color: $TXT_DIM;
    font-size: 8.5pt;
    font-family: "Cascadia Mono", "Consolas", monospace;
}

/* ══ 输入 ══ */
QLineEdit {
    background: $FIELD;
    border: 1px solid $LINE;
    border-radius: 7px;
    padding: 6px 10px;
    color: $TXT;
    selection-background-color: $ACC_A30;
    selection-color: $TXT;
}

QLineEdit:hover {
    border: 1px solid $LINE_HI;
}

QLineEdit:focus {
    border: 1px solid $ACC;
    background: $CARD2;
}

QLineEdit:disabled {
    background: $CARD2;
    color: $TXT_DIM;
    border: 1px solid $LINE;
}

QLineEdit[readOnly="true"] {
    color: $TXT_MID;
}

/* ══ 下拉 ══ */
QComboBox {
    background: $FIELD;
    border: 1px solid $LINE;
    border-radius: 7px;
    padding: 6px 10px;
    color: $TXT;
    min-width: 80px;
}

QComboBox:hover {
    border: 1px solid $LINE_HI;
}

/* 渲染分辨率：默认 min-width 会盖掉 setMinimumWidth，把 "2000x1500" 截断 */
QComboBox#ResCombo {
    min-width: 128px;
}

QComboBox:focus, QComboBox:on {
    border: 1px solid $ACC;
    background: $CARD2;
}

QComboBox:disabled {
    background: $CARD2;
    color: $TXT_DIM;
    border: 1px solid $LINE;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
    background: transparent;
}

QComboBox::down-arrow {
    width: 0px;
    height: 0px;
}

QComboBox QAbstractItemView {
    background: $CARD;
    border: 1px solid $LINE_HI;
    border-radius: 8px;
    padding: 4px;
    color: $TXT;
    outline: none;
    selection-background-color: $ACC_A16;
    selection-color: $ACC_TEXT;
}

QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 8px;
    border-radius: 5px;
}

QComboBox QAbstractItemView::item:hover {
    background: $ACC_A08;
    color: $ACC_TEXT;
}

/* ══ 按钮 ══ */
QPushButton {
    background: $CARD2;
    border: 1px solid $LINE;
    border-radius: 7px;
    padding: 7px 14px;
    color: $TXT_MID;
    font-weight: 600;
    font-size: 9pt;
}

QPushButton:hover {
    background: $ACC_A08;
    border: 1px solid $ACC_A30;
    color: $ACC_TEXT;
}

QPushButton:pressed {
    background: $ACC_A16;
    border: 1px solid $ACC;
    color: $ACC_TEXT;
}

QPushButton:disabled {
    background: $CARD2;
    border: 1px solid $LINE;
    color: $TXT_DIM;
}

/* 主按钮：青色渐变 + 深色字，视觉焦点 */
QPushButton#PrimaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 $BTN_G1, stop:1 $BTN_G2);
    border: 1px solid $BTN_G2;
    border-radius: 8px;
    padding: 8px 18px;
    color: $BTN_TXT;
    font-weight: 700;
    font-size: 9.5pt;
}

QPushButton#PrimaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 $ACC_HI, stop:1 $ACC);
    border: 1px solid $ACC_HI;
    color: $BTN_TXT;
}

QPushButton#PrimaryBtn:pressed {
    background: $ACC_DK;
    border: 1px solid $ACC_DK;
    color: #FFFFFF;
}

QPushButton#PrimaryBtn:disabled {
    background: $CARD2;
    border: 1px solid $LINE;
    color: $TXT_DIM;
}

/* 次按钮：描边 + 少量填充 */
QPushButton#GhostBtn {
    background: transparent;
    border: 1px solid $LINE;
    border-radius: 7px;
    padding: 7px 14px;
    color: $TXT_MID;
    font-weight: 600;
}

QPushButton#GhostBtn:hover {
    background: $ACC_A08;
    border: 1px solid $ACC_A30;
    color: $ACC_TEXT;
}

QPushButton#GhostBtn:pressed {
    background: $ACC_A16;
    border: 1px solid $ACC;
}

QPushButton#GhostBtn:disabled {
    background: transparent;
    border: 1px solid $LINE;
    color: $TXT_DIM;
}

/* 危险操作 */
QPushButton#DangerBtn {
    background: transparent;
    border: 1px solid $ERR_A40;
    border-radius: 7px;
    padding: 7px 14px;
    color: $ERR;
    font-weight: 600;
}

QPushButton#DangerBtn:hover {
    background: $ERR_A10;
    border: 1px solid $ERR;
    color: $ERR;
}

QPushButton#DangerBtn:pressed {
    background: rgba(248, 113, 113, 0.22);
}

/* ══ 文本区 / 列表 ══ */
QTextEdit#LogView {
    background: $FIELD;
    border: 1px solid $LINE;
    border-radius: 8px;
    padding: 8px 10px;
    color: $LOG_TXT;
    font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
    font-size: 8.5pt;
    selection-background-color: $LOG_SEL;
    selection-color: $TXT;
}

QTextEdit#LogView:focus {
    border: 1px solid $LINE_HI;
}

QListWidget#FileList {
    background: $FIELD;
    border: 1px solid $LINE;
    border-radius: 8px;
    padding: 4px;
    color: $TXT_MID;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 8.5pt;
    outline: none;
}

QListWidget#FileList::item {
    padding: 4px 6px;
    border-radius: 5px;
}

QListWidget#FileList::item:selected {
    background: $ACC_A16;
    color: $ACC_TEXT;
}

QListWidget#FileList::item:hover {
    background: $ACC_A08;
}

QTableWidget {
    background: $FIELD;
    alternate-background-color: $CARD2;
    border: 1px solid $LINE;
    border-radius: 8px;
    gridline-color: $LINE;
    color: $TXT;
    selection-background-color: $ACC_A16;
    selection-color: $ACC_TEXT;
}

QHeaderView::section {
    background: $CARD2;
    color: $TXT_MID;
    border: none;
    border-right: 1px solid $LINE;
    border-bottom: 1px solid $LINE;
    padding: 6px 8px;
    font-weight: 700;
}

QTableCornerButton::section {
    background: $CARD2;
    border: none;
}

/* ══ 滚动条 ══ */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: $LINE_HI;
    border-radius: 3px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background: $ACC_DK;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: $LINE_HI;
    border-radius: 3px;
    min-width: 28px;
}

QScrollBar::handle:horizontal:hover {
    background: $ACC_DK;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
    background: none;
    border: none;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}

/* ══ 滑块 ══ */
QSlider::groove:horizontal {
    height: 6px;
    background: $TRACK_OFF;
    border: 1px solid $LINE_HI;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $ACC_DK, stop:1 $ACC);
    border-radius: 3px;
}

/* 手柄右侧这一段必须显式画出来：只设 sub-page 时 add-page 会退化成透明，
   整条轨道看起来只剩左半截（截图时才发现）。 */
QSlider::add-page:horizontal {
    background: $TRACK_OFF;
    border-radius: 3px;
}

QSlider::add-page:horizontal:disabled {
    background: $CARD2;
}

QSlider::handle:horizontal {
    background: $HANDLE_BG;
    border: 2px solid $ACC;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background: $ACC_HI;
    border: 2px solid $ACC_HI;
}

QSlider::handle:horizontal:pressed {
    background: $ACC;
    border: 2px solid $ACC_HI;
}

QSlider::groove:horizontal:disabled {
    background: $CARD2;
    border: 1px solid $LINE;
}

QSlider::sub-page:horizontal:disabled {
    background: $LINE;
}

QSlider::handle:horizontal:disabled {
    background: $CARD2;
    border: 2px solid $LINE_HI;
}

/* ══ 进度条 ══ */
QProgressBar {
    background: $CARD2;
    border: 1px solid $LINE;
    border-radius: 7px;
    height: 14px;
    text-align: center;
    color: $TXT_MID;
    font-size: 8pt;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 $ACC_DK, stop:0.55 $ACC, stop:1 $ACC_HI);
    border-radius: 6px;
}

/* ══ 标签页 ══ */
QTabWidget::pane {
    background: $PANEL;
    border: 1px solid $LINE;
    border-radius: 10px;
    top: -1px;
    padding: 10px;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 20px;
    margin-right: 6px;
    margin-bottom: 4px;
    min-width: 84px;
    color: $TXT_DIM;
    font-weight: 600;
    font-size: 9pt;
}

QTabBar::tab:hover:!selected {
    background: $ACC_A08;
    color: $TXT_MID;
}

QTabBar::tab:selected {
    background: $ACC_A16;
    border: 1px solid $ACC_A30;
    color: $ACC_TEXT;
    font-weight: 700;
}

QTabBar::tab:disabled {
    color: $TXT_DIM;
}

/* ══ 其他 ══ */
QFrame#Separator {
    background: $LINE;
    max-height: 1px;
}

QFrame#Card {
    background: $CARD;
    border: 1px solid $LINE;
    border-radius: 10px;
}

QMenu {
    background: $CARD;
    border: 1px solid $LINE_HI;
    border-radius: 8px;
    padding: 4px;
    color: $TXT;
}

QMenu::item {
    padding: 6px 18px;
    border-radius: 5px;
}

QMenu::item:selected {
    background: $ACC_A16;
    color: $ACC_TEXT;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* Tab 页的滚动容器：别让 viewport 画出自己的底色，透出 QTabWidget::pane 的 $PANEL */
QScrollArea#TabScroll,
QScrollArea#TabScroll > QWidget > QWidget {
    background: transparent;
    border: none;
}

QScrollArea#TabScroll:focus {
    outline: none;
}

QCheckBox, QRadioButton {
    color: $TXT_MID;
    spacing: 6px;
    padding: 3px 4px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid $LINE_HI;
    background: $FIELD;
    border-radius: 4px;
}

QRadioButton::indicator {
    border-radius: 8px;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $ACC;
    border: 1px solid $ACC_HI;
}
""")


def qss():
    """返回完整样式表。"""
    return _QSS.substitute(**PALETTE)


def palette():
    """返回可直接喂给 QApplication.setPalette 的 QPalette。

    让 Fusion 风格的原生图元（下拉箭头、勾选标记、表格表头）也跟着取色，
    否则可能出现看不清的黑色小三角。
    """
    from PyQt5.QtGui import QPalette, QColor
    p = PALETTE
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p["WIN"]))
    pal.setColor(QPalette.WindowText, QColor(p["TXT"]))
    pal.setColor(QPalette.Base, QColor(p["FIELD"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["CARD2"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["CARD"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["TXT"]))
    pal.setColor(QPalette.Text, QColor(p["TXT"]))
    pal.setColor(QPalette.Button, QColor(p["CARD2"]))
    pal.setColor(QPalette.ButtonText, QColor(p["TXT"]))
    pal.setColor(QPalette.BrightText, QColor(p["ERR"]))
    pal.setColor(QPalette.Link, QColor(p["ACC"]))
    pal.setColor(QPalette.Highlight, QColor(p["ACC"]))
    pal.setColor(QPalette.HighlightedText, QColor(p["ON_ACC"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p["TXT_DIM"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p["TXT_DIM"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["TXT_DIM"]))
    return pal
