# -*- coding: utf-8 -*-
"""设置对话框。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from config import APP_VERSION, AppConfig, DEFAULT_ACCENT
from floating import make_icon

INTERVAL_PRESETS = [
    ("30 秒", 30),
    ("1 分钟", 60),
    ("2 分钟", 120),
    ("5 分钟", 300),
    ("10 分钟", 600),
    ("30 分钟", 1800),
    ("1 小时", 3600),
]

DEVICE_TYPE_OPTIONS = [
    ("自动识别", "auto"),
    ("鼠标", "mouse"),
    ("键盘", "keyboard"),
    ("耳机", "headphones"),
    ("音箱", "speaker"),
    ("手表", "watch"),
    ("手写笔", "pen"),
    ("蓝牙设备", "chip"),
]


class SettingsDialog(QDialog):
    # 任意外观相关设置被调整时发出，用于悬浮窗实时预览（尚未保存）
    preview_changed = Signal()

    def __init__(self, cfg: AppConfig, theme_icon_color: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._cfg = cfg
        self._icon_color = theme_icon_color
        self.setWindowIcon(make_icon("settings", theme_icon_color, 16))
        self._build()
        self._load_values()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        # -------- 常规 --------
        root.addWidget(self._caption("常规"))
        form1 = QFormLayout()
        form1.setSpacing(9)
        form1.setLabelAlignment(Qt.AlignRight)

        self.interval_combo = QComboBox()
        for text, secs in INTERVAL_PRESETS:
            self.interval_combo.addItem(text, secs)
        self.interval_combo.currentIndexChanged.connect(
            lambda _i: self.preview_changed.emit())
        form1.addRow("自动刷新间隔", self.interval_combo)

        self.chk_start = QCheckBox("登录 Windows 时自动启动本程序")
        self.chk_minimized = QCheckBox("启动时先最小化到系统托盘")
        self.chk_uncached = QCheckBox("强制实时读取电量（更慢，可能唤醒休眠设备）")
        form1.addRow("", self.chk_start)
        form1.addRow("", self.chk_minimized)
        form1.addRow("", self.chk_uncached)
        root.addLayout(form1)

        root.addWidget(self._separator())

        # -------- 外观 --------
        root.addWidget(self._caption("外观"))
        form2 = QFormLayout()
        form2.setSpacing(9)
        form2.setLabelAlignment(Qt.AlignRight)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("跟随系统", "auto")
        self.theme_combo.currentIndexChanged.connect(
            lambda _i: self.preview_changed.emit())
        form2.addRow("主题", self.theme_combo)

        color_row = QWidget()
        ch = QHBoxLayout(color_row)
        ch.setContentsMargins(0, 0, 0, 0)
        self.btn_color = QPushButton()
        self.btn_color.setFixedSize(54, 24)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.clicked.connect(self._pick_color)
        self.btn_reset_color = QPushButton("恢复默认")
        self.btn_reset_color.setCursor(Qt.PointingHandCursor)
        self.btn_reset_color.clicked.connect(
            lambda: self._set_accent(DEFAULT_ACCENT))
        ch.addWidget(self.btn_color)
        ch.addWidget(self.btn_reset_color)
        ch.addStretch(1)
        form2.addRow("主题强调色", color_row)

        opacity_row = QWidget()
        oh = QHBoxLayout(opacity_row)
        oh.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setFixedWidth(170)
        self.opacity_slider.setCursor(Qt.PointingHandCursor)
        self.opacity_label = QLabel()
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%"))
        self.opacity_slider.valueChanged.connect(
            lambda _v: self.preview_changed.emit())
        oh.addWidget(self.opacity_slider)
        oh.addWidget(self.opacity_label)
        oh.addStretch(1)
        form2.addRow("悬浮窗不透明度", opacity_row)

        self.chk_compact = QCheckBox("使用紧凑模式（只显示电量圆环）")
        form2.addRow("", self.chk_compact)
        self.chk_minimal = QCheckBox("精简模式（仅圆环，双击刷新）")
        form2.addRow("", self.chk_minimal)
        self.chk_on_top = QCheckBox("悬浮窗始终显示在最顶层")
        form2.addRow("", self.chk_on_top)
        for _chk in (self.chk_compact, self.chk_minimal, self.chk_on_top):
            _chk.toggled.connect(lambda _checked: self.preview_changed.emit())
        root.addLayout(form2)

        root.addWidget(self._separator())

        # -------- 显示 --------
        root.addWidget(self._caption("设备显示"))
        self.chk_connected = QCheckBox("只显示当前已连接的设备")
        self.chk_local = QCheckBox("同时显示本机电脑电池")
        self.chk_connected.toggled.connect(
            lambda _checked: self.preview_changed.emit())
        self.chk_local.toggled.connect(
            lambda _checked: self.preview_changed.emit())
        root.addWidget(self.chk_connected)
        root.addWidget(self.chk_local)

        list_label = QLabel("设备可见性（取消勾选则隐藏该设备）：")
        root.addWidget(list_label)
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(110)
        root.addWidget(self.device_list)

        root.addWidget(self._separator())

        # -------- 关于 / 作者信息 --------
        root.addWidget(self._caption("关于"))
        form3 = QFormLayout()
        form3.setSpacing(9)
        form3.setLabelAlignment(Qt.AlignRight)
        form3.addRow("版本", QLabel(APP_VERSION))
        form3.addRow("作者", QLabel("王雪豪"))
        mail_label = QLabel(
            '<a href="mailto:findaxh@outlook.com">'
            'findaxh@outlook.com</a>'
            '<span style="color:#8A92A2;">（点击发送邮件）</span>')
        mail_label.setOpenExternalLinks(True)
        form3.addRow("邮箱", mail_label)
        root.addLayout(form3)

        # -------- 按钮 --------
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font()
        f.setBold(True)
        f.setPointSizeF(10)
        lbl.setFont(f)
        return lbl

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        cfg = self._cfg
        idx = self.interval_combo.findData(cfg.refresh_interval)
        if idx < 0:
            self.interval_combo.addItem(f"{cfg.refresh_interval} 秒（自定义）",
                                        cfg.refresh_interval)
            idx = self.interval_combo.count() - 1
        self.interval_combo.setCurrentIndex(idx)

        self.chk_start.setChecked(cfg.autostart)
        self.chk_minimized.setChecked(cfg.start_minimized)
        self.chk_uncached.setChecked(cfg.uncached_read)
        self.chk_compact.setChecked(cfg.compact)
        self.chk_minimal.setChecked(cfg.minimal)
        self.chk_on_top.setChecked(cfg.always_on_top)
        self.chk_connected.setChecked(cfg.only_connected)
        self.chk_local.setChecked(cfg.show_local)

        ti = self.theme_combo.findData(cfg.theme)
        self.theme_combo.setCurrentIndex(ti if ti >= 0 else 0)

        self.opacity_slider.setValue(int(cfg.opacity * 100))
        self._set_accent(cfg.accent)

        self.device_list.clear()
        self._device_rows = []  # (key, checkbox, combo)
        if cfg.known_devices:
            items = sorted(cfg.known_devices.items(),
                           key=lambda kv: kv[1].lower())
            for key, name in items:
                item = QListWidgetItem()
                w = QWidget()
                row = QHBoxLayout(w)
                row.setContentsMargins(6, 3, 6, 3)
                row.setSpacing(8)
                chk = QCheckBox(name)
                chk.setChecked(key not in cfg.hidden_devices)
                combo = QComboBox()
                combo.setFixedWidth(112)
                for text, val in DEVICE_TYPE_OPTIONS:
                    combo.addItem(text, val)
                saved = cfg.device_types.get(key, "auto")
                idx = combo.findData(saved)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                row.addWidget(chk)
                row.addStretch(1)
                row.addWidget(combo)
                item.setSizeHint(w.sizeHint())
                self.device_list.addItem(item)
                self.device_list.setItemWidget(item, w)
                chk.toggled.connect(
                    lambda _checked: self.preview_changed.emit())
                combo.currentIndexChanged.connect(
                    lambda _i: self.preview_changed.emit())
                self._device_rows.append((key, chk, combo))
        else:
            item = QListWidgetItem("（首次刷新后会在这里列出已发现的设备）")
            item.setFlags(Qt.NoItemFlags)
            self.device_list.addItem(item)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._cfg.accent), self, "选择主题色")
        if color.isValid():
            self._set_accent(color.name())

    def _set_accent(self, hex_color: str) -> None:
        self.btn_color.setStyleSheet(
            f"background: {hex_color}; border: 1px solid #999; border-radius: 4px;")
        self.btn_color.setText(hex_color.upper())
        # 让按钮上的色值在深浅色背景上都可读
        c = QColor(hex_color)
        text_color = "#1D2129" if c.lightness() > 150 else "#FFFFFF"
        self.btn_color.setStyleSheet(
            f"background: {hex_color}; color: {text_color}; "
            f"border: 1px solid rgba(0,0,0,0.25); border-radius: 4px;")
        self.preview_changed.emit()

    # ------------------------------------------------------------------ #
    def apply_to_config(self) -> AppConfig:
        cfg = self._cfg
        cfg.refresh_interval = int(self.interval_combo.currentData())
        cfg.autostart = self.chk_start.isChecked()
        cfg.start_minimized = self.chk_minimized.isChecked()
        cfg.uncached_read = self.chk_uncached.isChecked()
        cfg.compact = self.chk_compact.isChecked()
        cfg.minimal = self.chk_minimal.isChecked()
        cfg.always_on_top = self.chk_on_top.isChecked()
        cfg.only_connected = self.chk_connected.isChecked()
        cfg.show_local = self.chk_local.isChecked()
        cfg.theme = self.theme_combo.currentData()
        cfg.opacity = self.opacity_slider.value() / 100.0
        raw = self.btn_color.text()
        if QColor(raw).isValid():
            cfg.accent = raw

        hidden = []
        types = {}
        for key, chk, combo in self._device_rows:
            if not chk.isChecked():
                hidden.append(key)
            val = combo.currentData()
            if val and val != "auto":
                types[key] = val
        cfg.hidden_devices = hidden
        cfg.device_types = types
        return cfg
