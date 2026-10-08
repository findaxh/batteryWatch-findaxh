# -*- coding: utf-8 -*-
"""桌面悬浮窗：无边框、圆角、半透明、置顶、可拖拽。"""

import ctypes
from typing import Dict, List, Optional

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF,
    QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget, QApplication,
)

from bt_reader import DeviceInfo
from config import MINIMAL_ACCENT


# --------------------------------------------------------------------------- #
# 线性 SVG 图标（stroke 风格，颜色可替换）
# --------------------------------------------------------------------------- #
_ICON_BODIES: Dict[str, str] = {
    "bluetooth": '<polyline points="7,7 17,17 12,22 12,2 17,7 7,17"/>',
    "refresh": ('<polyline points="23,4 23,10 17,10"/>'
                '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'),
    "settings": ('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>'
                 '<line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>'
                 '<line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>'
                 '<line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/>'
                 '<line x1="17" y1="16" x2="23" y2="16"/>'),
    "close": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "chevron_down": '<polyline points="6,9 12,15 18,9"/>',
    "chevron_up": '<polyline points="18,15 12,9 6,15"/>',
    "mouse": ('<rect x="6" y="3" width="12" height="18" rx="6"/>'
              '<line x1="12" y1="7" x2="12" y2="11"/>'),
    "keyboard": ('<rect x="2" y="6" width="20" height="12" rx="2"/>'
                 '<line x1="6" y1="10" x2="6" y2="10"/><line x1="10" y1="10" x2="10" y2="10"/>'
                 '<line x1="14" y1="10" x2="14" y2="10"/><line x1="18" y1="10" x2="18" y2="10"/>'
                 '<line x1="7" y1="14" x2="17" y2="14"/>'),
    "headphones": ('<path d="M3 18v-6a9 9 0 0 1 18 0v6"/>'
                   '<path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3z"/>'
                   '<path d="M3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>'),
    "speaker": ('<polygon points="11,5 6,9 2,9 2,15 6,15 11,19 11,5"/>'
                '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'),
    "watch": ('<circle cx="12" cy="12" r="6"/><polyline points="12,10 12,12 13,13"/>'
              '<path d="M9.5,3h5l1,5H8.5z"/><path d="M8.5,21h5l-1-5h-3z"/>'),
    "pen": ('<path d="M12 20h9"/>'
            '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
    "laptop": ('<rect x="4" y="4" width="16" height="11" rx="2"/>'
               '<line x1="2" y1="20" x2="22" y2="20"/>'),
    "chip": ('<rect x="6" y="6" width="12" height="12" rx="2"/>'
             '<line x1="9" y1="2" x2="9" y2="6"/><line x1="15" y1="2" x2="15" y2="6"/>'
             '<line x1="9" y1="18" x2="9" y2="22"/><line x1="15" y1="18" x2="15" y2="22"/>'
             '<line x1="2" y1="9" x2="6" y2="9"/><line x1="2" y1="15" x2="6" y2="15"/>'
             '<line x1="18" y1="9" x2="22" y2="9"/><line x1="18" y1="15" x2="22" y2="15"/>'),
    "bolt": '<polygon points="13,2 3,14 12,14 11,22 21,10 12,10 13,2"/>',
}

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{color}" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)


def make_icon(name: str, color: str = "#FFFFFF", size: int = 16) -> QIcon:
    body = _ICON_BODIES.get(name, _ICON_BODIES["chip"])
    svg = _SVG_TEMPLATE.format(color=color, body=body).encode("utf-8")
    dpr = max(1.0, QApplication.primaryScreen().devicePixelRatio())
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg)).render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    icon = QIcon(pm)
    return icon


def render_icon_pixmap(name: str, color: str, size: int,
                       stroke_width: float = 1.9) -> QPixmap:
    """把 SVG 图标渲染成指定逻辑尺寸的 QPixmap（适配高 DPI）。"""
    body = _ICON_BODIES.get(name, _ICON_BODIES["chip"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
           f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
           ).encode("utf-8")
    dpr = max(1.0, QApplication.primaryScreen().devicePixelRatio())
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def device_kind(name: str) -> str:
    n = name.lower()
    if "本机" in name:
        return "laptop"
    if any(k in n for k in ("mouse", "鼠标")):
        return "mouse"
    if any(k in n for k in ("keyboard", "键盘", "keychron", "wave")):
        return "keyboard"
    if any(k in n for k in ("ear", "pod", "bud", "headphone", "headset",
                            "耳机", "耳麦", "音箱", "音响", "speaker", "sound",
                            "小爱", "airpods", "wh-", "wf-", "wi-", "mdr-",
                            "qc35", "qc45", "qc ultra", "studio buds")):
        return "headphones" if ("耳机" in name or "耳" in n or "pod" in n
                                or "bud" in n or "head" in n
                                or "wh-" in n or "wf-" in n or "wi-" in n) else "speaker"
    if any(k in n for k in ("watch", "手表", "band", "手环")):
        return "watch"
    if any(k in n for k in (" pen", "pen ", "笔")):
        return "pen"
    return "chip"


KIND_LABEL = {
    "laptop": "电脑", "mouse": "鼠标", "keyboard": "键盘",
    "headphones": "耳机", "speaker": "音箱", "watch": "手表",
    "pen": "手写笔", "chip": "蓝牙设备",
}


def level_color(percent: Optional[int], charging: bool, accent: str) -> QColor:
    if charging:
        return QColor("#5DADE2")
    if percent is None:
        return QColor("#8A92A2")
    if percent <= 20:
        return QColor("#F87171")
    if percent <= 50:
        return QColor("#FBBF24")
    return QColor("#34D399")


# --------------------------------------------------------------------------- #
# 电量圆环
# --------------------------------------------------------------------------- #
class BatteryRing(QWidget):
    def __init__(self, diameter: int = 46, parent=None,
                 icon_on_top: bool = False, tile: bool = False,
                 accent: QColor = None):
        super().__init__(parent)
        self._diameter = diameter
        self._icon_on_top = icon_on_top
        self._tile = tile
        self._accent = accent if accent is not None else QColor("#5B9CFF")
        self._icon_size = int(diameter * 0.4)
        if tile:
            # tile 模式：宽 diameter，高 diameter*1.4（上图标、下数字两行）
            self.setFixedSize(diameter, int(diameter * 1.4))
            self._top_pad = 0
        else:
            # 图标置顶时，控件顶部留出半个图标高度的留白
            top_pad = self._icon_size // 2 if icon_on_top else 0
            self._top_pad = top_pad
            self.setFixedSize(diameter, diameter + top_pad)
        self._value = 0.0
        self._target = 0.0
        self._track = QColor(255, 255, 255, 26)
        self._arc = QColor("#34D399")
        self._text_color = QColor("#E9ECF3")
        self._kind: Optional[str] = None
        self._icon_pm: Optional[QPixmap] = None
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(700)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def setColors(self, track: QColor, arc: QColor, text: QColor,
                  accent: QColor = None) -> None:
        self._track, self._arc, self._text_color = track, arc, text
        if accent is not None:
            self._accent = accent
        if self._kind:
            self._refresh_icon()
        self.update()

    def set_device_kind(self, kind: Optional[str]) -> None:
        """设置设备类型图标（None 则回退显示百分比数字）。"""
        self._kind = kind
        if kind:
            self._refresh_icon()
        else:
            self._icon_pm = None
        self.update()

    def _refresh_icon(self) -> None:
        if self._tile:
            # 精简模式：图标与数字均用强调色，图标尺寸适中
            self._icon_pm = render_icon_pixmap(
                self._kind, self._accent.name(),
                int(self._diameter * 0.62), stroke_width=2.0)
        else:
            color = "#FFFFFF" if self._icon_on_top else self._arc.name()
            self._icon_pm = render_icon_pixmap(self._kind, color,
                                               self._icon_size)

    def getValue(self) -> float:
        return self._value

    def setValue(self, v: float) -> None:
        self._value = max(0.0, min(100.0, float(v)))
        self.update()

    value = Property(float, fget=getValue, fset=setValue)

    def animateTo(self, target: Optional[int]) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(float(target) if target is not None else 0.0)
        self._anim.start()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 高 DPI 下若发生尺寸换算，使用高质量平滑缩放，避免边缘锯齿
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        d = self.width()

        if self._tile:
            self._paint_tile(p, d)
        else:
            self._paint_ring(p, d)
        p.end()

    def _paint_tile(self, p: QPainter, d: float) -> None:
        """精简模式：两行布局——上图标、下电量数字；仅线条与文字用强调色，其余透明。"""
        h = float(self.height())
        # 第一行：设备图标（强调色），位于上半部分居中
        if self._icon_pm is not None:
            # QPixmap.width() 是物理像素，需除以其 DPR 换算回逻辑尺寸，
            # 否则高 DPI 下目标矩形偏大、位图被拉伸放大，边缘发虚有锯齿。
            pm_dpr = self._icon_pm.devicePixelRatio() or 1.0
            iw = self._icon_pm.width() / pm_dpr
            ih = self._icon_pm.height() / pm_dpr
            x = (d - iw) / 2.0
            # 图标中心位于控件高度的 38% 处
            y = h * 0.38 - ih / 2.0
            p.drawPixmap(QRectF(x, y, iw, ih), self._icon_pm,
                         QRectF(self._icon_pm.rect()))

        # 第二行：电量数字（强调色），位于下半部分居中
        font = QFont()
        font.setPointSizeF(d / 4.0)
        font.setBold(True)
        p.setFont(font)
        p.setPen(self._accent)
        text = str(int(round(self._value))) if self._value > 0 else "--"
        # 文字中心位于控件高度的 78% 处
        p.drawText(QRectF(0, h * 0.55, d, h * 0.45),
                   Qt.AlignCenter, text)

    def _paint_ring(self, p: QPainter, d: float) -> None:
        """原有圆环模式。"""
        pen_w = max(3.2, self._diameter / 11.5)
        margin = pen_w / 2 + 1
        rect = QRectF(margin, margin + self._top_pad,
                      d - 2 * margin, d - 2 * margin)

        pen = QPen(self._track)
        pen.setWidthF(pen_w)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)

        if self._value > 0:
            pen.setColor(self._arc)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-self._value * 3.6 * 16))

        show_text = self._icon_on_top or self._icon_pm is None
        if show_text:
            font = QFont()
            font.setPointSizeF(self._diameter / 4.2)
            font.setBold(True)
            p.setFont(font)
            p.setPen(self._text_color)
            text = str(int(round(self._value))) if self._value > 0 else "--"
            cy = self._top_pad + self._diameter / 2.0
            p.drawText(QRectF(0, cy - self._diameter / 2.0,
                              d, self._diameter),
                       Qt.AlignCenter, text)

        if self._icon_pm is not None:
            # 物理像素换算回逻辑尺寸，保证 1:1 像素映射、高 DPI 下清晰不糊
            pm_dpr = self._icon_pm.devicePixelRatio() or 1.0
            iw = self._icon_pm.width() / pm_dpr
            ih = self._icon_pm.height() / pm_dpr
            if self._icon_on_top:
                cx = d / 2.0
                cy = margin + self._top_pad
                x = cx - iw / 2.0
                y = cy - ih / 2.0
            else:
                x = (d - iw) / 2.0
                y = (self.height() - ih) / 2.0
            p.drawPixmap(QRectF(x, y, iw, ih), self._icon_pm,
                         QRectF(self._icon_pm.rect()))


# --------------------------------------------------------------------------- #
# 主题
# --------------------------------------------------------------------------- #
THEMES = {
    "dark": {
        "bg": QColor(24, 26, 33),
        "text": "#E9ECF3",
        "sub": "#979FAF",
        "border": QColor(255, 255, 255, 30),
        "hover": QColor(255, 255, 255, 18),
        "track": QColor(255, 255, 255, 28),
        "btn_hover": QColor(255, 255, 255, 22),
    },
    "light": {
        "bg": QColor(248, 249, 252),
        "text": "#1D2129",
        "sub": "#6B7280",
        "border": QColor(15, 23, 42, 32),
        "hover": QColor(15, 23, 42, 10),
        "track": QColor(15, 23, 42, 22),
        "btn_hover": QColor(15, 23, 42, 16),
    },
}
CARD_RADIUS = 14


def logical_available_geometry(screen) -> QRect:
    """返回屏幕可用区域（逻辑像素）。

    Qt 6.11 在 Windows 上 QScreen 几何返回物理像素，而 QWidget.move()
    使用逻辑像素（二者相差 devicePixelRatio 倍），混用会导致窗口被放到
    屏幕外。这里通过与 Win32 物理虚拟屏宽度比较，判断 Qt 返回的是物理
    还是逻辑几何，并统一换算成逻辑像素。旧版 Qt（几何本就是逻辑）会
    原样返回，100% 缩放时 dpr=1 也无副作用。
    """
    g = screen.availableGeometry()
    try:
        phys_virt = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        qt_virt = QApplication.primaryScreen().virtualGeometry().width()
        if phys_virt and abs(qt_virt - phys_virt) <= 4:
            d = screen.devicePixelRatio() or 1.0
            if d > 1.0001:
                return QRect(round(g.left() / d), round(g.top() / d),
                             round(g.width() / d), round(g.height() / d))
    except Exception:
        pass
    return g


def effective_theme(theme: str) -> str:
    if theme in ("dark", "light"):
        return theme
    # auto：跟随系统
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if light else "dark"
    except OSError:
        w = QApplication.primaryScreen()
        return "light" if QApplication.palette().window().color().lightness() > 128 else "dark"


# --------------------------------------------------------------------------- #
# 悬浮窗
# --------------------------------------------------------------------------- #
class FloatingWidget(QWidget):
    sig_refresh = Signal()
    sig_settings = Signal()
    sig_quit = Signal()
    sig_compact_changed = Signal(bool)
    sig_position_changed = Signal(int, int)

    def __init__(self, accent: str = "#5B9CFF"):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # 分层窗口：圆角外为真实半透明像素，边缘由 DWM 抗锯齿混合。
        # （setMask 是 1-bit 硬裁剪，圆角必然有锯齿台阶。）
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(264)
        self.setMaximumWidth(264)
        self.setMinimumHeight(64)

        self._theme_name = "dark"
        self._accent = accent
        self._compact = False
        self._minimal = False
        self._always_on_top = True
        self._loading = False
        self._opacity = 0.96
        self._device_types: Dict[str, str] = {}
        self._drag_offset: Optional[QPoint] = None
        # 每个设备对应的（正文圆环、紧凑/精简圆环）引用，供原地改色
        self._device_rings: List = []

        self._build_ui()
        self.apply_theme("dark", accent, 0.96)
        self._relayout()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 12, 12)

        self.card = QWidget(self)
        self.card.setObjectName("card")
        root.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ---------- 顶部标题栏 ----------
        self.header_widget = QWidget()
        header = QHBoxLayout(self.header_widget)
        header.setSpacing(6)
        header.setContentsMargins(0, 0, 0, 0)
        self.title_icon = QLabel()
        self.title_icon.setFixedSize(18, 18)
        self.title_text = QLabel("蓝牙电量")
        tf = QFont()
        tf.setPointSizeF(10.5)
        tf.setBold(True)
        self.title_text.setFont(tf)
        header.addWidget(self.title_icon)
        header.addWidget(self.title_text)
        header.addStretch(1)

        self.btn_compact = self._tool_button("chevron_down", 15)
        self.btn_refresh = self._tool_button("refresh", 15)
        self.btn_settings = self._tool_button("settings", 15)
        self.btn_close = self._tool_button("close", 15)
        self.btn_compact.clicked.connect(self.toggle_compact)
        self.btn_refresh.clicked.connect(self.sig_refresh.emit)
        self.btn_settings.clicked.connect(self.sig_settings.emit)
        self.btn_close.clicked.connect(self.hide)
        for b in (self.btn_compact, self.btn_refresh, self.btn_settings, self.btn_close):
            header.addWidget(b)
        layout.addWidget(self.header_widget)

        # ---------- 设备列表 ----------
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 2, 0, 0)
        self.body_layout.setSpacing(4)
        layout.addWidget(self.body)

        # ---------- 紧凑模式：横向圆环 ----------
        self.compact_box = QWidget()
        self.compact_layout = QHBoxLayout(self.compact_box)
        self.compact_layout.setContentsMargins(2, 2, 2, 2)
        self.compact_layout.setSpacing(6)
        self.compact_box.setVisible(False)
        layout.addWidget(self.compact_box)

        # ---------- 空状态 ----------
        self.empty_widget = QWidget()
        ev = QVBoxLayout(self.empty_widget)
        ev.setContentsMargins(0, 6, 0, 6)
        ev.setSpacing(6)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_text = QLabel("暂未发现支持电量显示的蓝牙设备")
        self.empty_text.setAlignment(Qt.AlignCenter)
        ef = QFont()
        ef.setPointSizeF(9)
        self.empty_text.setFont(ef)
        self.empty_hint = QLabel("请确认设备已连接，并支持 BLE 电池服务")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        hf = QFont()
        hf.setPointSizeF(8)
        self.empty_hint.setFont(hf)
        ev.addWidget(self.empty_icon)
        ev.addWidget(self.empty_text)
        ev.addWidget(self.empty_hint)
        self.empty_widget.setVisible(False)
        layout.addWidget(self.empty_widget)

        # ---------- 底部状态栏 ----------
        self.footer_widget = QWidget()
        footer = QHBoxLayout(self.footer_widget)
        footer.setSpacing(6)
        footer.setContentsMargins(0, 0, 0, 0)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(7, 7)
        self.status_text = QLabel("准备就绪")
        sf = QFont()
        sf.setPointSizeF(8)
        self.status_text.setFont(sf)
        footer.addWidget(self.status_dot)
        footer.addWidget(self.status_text)
        footer.addStretch(1)
        layout.addWidget(self.footer_widget)
        self._footer = footer

        self._rows: List[QWidget] = []

    def _tool_button(self, icon_name: str, icon_size: int = 15) -> QToolButton:
        btn = QToolButton(self.card)
        btn.setIconSize(QSize(icon_size, icon_size))
        btn.setFixedSize(27, 27)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("icon_name", icon_name)
        btn.setAutoRaise(True)
        return btn

    # ------------------------------------------------------------------ #
    # 主题与样式
    # ------------------------------------------------------------------ #
    def apply_theme(self, theme_name: str, accent: str, opacity: float) -> None:
        self._theme_name = theme_name if theme_name in THEMES else "dark"
        self._accent = accent
        self._opacity = max(0.0, min(1.0, opacity))
        t = THEMES[self._theme_name]

        self.card.setStyleSheet(
            f"""
            QLabel {{ background: transparent; }}
            QToolButton {{
                border: none; border-radius: 7px; background: transparent;
            }}
            QToolButton:hover {{ background: {t['btn_hover'].name(QColor.HexArgb)}; }}
            #row {{ border-radius: 10px; }}
            #row:hover {{ background: {t['hover'].name(QColor.HexArgb)}; }}
            """
        )
        self.title_text.setStyleSheet(f"color: {t['text']};")
        self.status_text.setStyleSheet(f"color: {t['sub']};")

        for btn in (self.btn_compact, self.btn_refresh, self.btn_settings, self.btn_close):
            name = btn.property("icon_name")
            btn.setIcon(make_icon(name, t["sub"], btn.iconSize().width()))

        self.title_icon.setPixmap(
            make_icon("bluetooth", accent, 18).pixmap(18, 18))
        self.empty_icon.setPixmap(
            make_icon("bluetooth", t["sub"], 30).pixmap(30, 30))
        self.empty_text.setStyleSheet(f"color: {t['sub']};")
        self.empty_hint.setStyleSheet(f"color: {t['sub']};")

        # 不透明度只作用于背景：窗口整体保持不透明，
        # 圆角背景的 alpha 由 self._opacity 控制，圆环/图标/文字始终完全不透明。
        self.setWindowOpacity(1.0)
        self.update()
        self._refresh_status_ui()
        self._recolor_rows()

    # ------------------------------------------------------------------ #
    # 自绘圆角背景（配合 WA_TranslucentBackground，边缘平滑抗锯齿）
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        t = THEMES[self._theme_name]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 边框透明度跟随背景不透明度同步变化：避免 opacity=0 时还能看到轮廓
        border = QColor(t["border"])
        border.setAlphaF(border.alphaF() * self._opacity)
        pen = QPen(border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        bg = QColor(t["bg"])
        bg.setAlphaF(self._opacity)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
                          CARD_RADIUS, CARD_RADIUS)
        p.end()

    def _recolor_rows(self) -> None:
        """主题切换后重建内容最简单稳妥。"""
        if hasattr(self, "_last_devices"):
            self.update_devices(self._last_devices,
                                getattr(self, "_device_types", None))

    # ------------------------------------------------------------------ #
    # 实时预览用的轻量更新（不整窗重建，避免圆环反复重播动画）
    # ------------------------------------------------------------------ #
    def set_accent(self, accent: str) -> None:
        """实时更换强调色：标题图标变色；精简(tile)模式保持固定绿色不变。

        普通圆环/紧凑模式的设备颜色由电量决定，不使用强调色，无需重建。
        """
        self._accent = accent
        self.title_icon.setPixmap(
            make_icon("bluetooth", accent, 18).pixmap(18, 18))
        if self._minimal:
            t = THEMES[self._theme_name]
            for dev, _body_ring, compact_ring in self._device_rings:
                color = level_color(dev.percent, dev.charging, accent)
                compact_ring.setColors(t["track"], color, t["text"],
                                       accent=QColor(MINIMAL_ACCENT))

    def set_opacity(self, opacity: float) -> None:
        """实时调整背景不透明度：仅重绘圆角背景，内容（圆环/文字/图标）不受影响。"""
        self._opacity = max(0.0, min(1.0, opacity))
        self.update()

    # ------------------------------------------------------------------ #
    # 数据展示
    # ------------------------------------------------------------------ #
    def update_devices(self, devices: List[DeviceInfo],
                       device_types: Optional[Dict[str, str]] = None) -> None:
        self._last_devices = list(devices)
        self._device_types = device_types or {}
        t = THEMES[self._theme_name]

        # 清理旧行
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        while self.compact_layout.count():
            item = self.compact_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        self._device_rings.clear()

        has_devices = len(devices) > 0
        if self._minimal:
            # 精简模式：只显圆环，其余全隐
            self.header_widget.setVisible(False)
            self.footer_widget.setVisible(False)
            self.empty_widget.setVisible(False)
            self.body.setVisible(False)
            self.compact_box.setVisible(has_devices)
        else:
            self.empty_widget.setVisible(not has_devices)
            self.body.setVisible(has_devices and not self._compact)
            self.compact_box.setVisible(has_devices and self._compact)

        for dev in devices:
            body_ring = self._make_row(dev)
            compact_wrap, compact_ring = self._make_compact_ring(dev)
            self.compact_layout.addWidget(compact_wrap)
            self._device_rings.append((dev, body_ring, compact_ring))
        if has_devices:
            self.compact_layout.addStretch(1)

        self._relayout()

    def _device_kind_for(self, dev: DeviceInfo) -> str:
        """按配置优先取手动指定的类型，否则按名称自动识别。"""
        if dev.source == "local":
            return "laptop"
        from bt_reader import mac_key
        key = mac_key(dev.address)
        override = self._device_types.get(key) if key else None
        if override and override != "auto":
            return override
        return device_kind(dev.name)

    def _relayout(self) -> None:
        """按布局最小需求设定确定的窗口高度。

        Qt 子布局在 addWidget 后不会立即刷新缓存的 sizeHint/minimumSize，
        需要等下一轮事件循环，因此把固定高度的动作排队到空闲时执行。
        """
        self.layout().invalidate()
        QTimer.singleShot(0, self._apply_fixed_height)

    def _apply_fixed_height(self) -> None:
        lay = self.layout()
        lay.activate()
        if self._minimal:
            self.setFixedSize(lay.minimumSize())
        else:
            self.setFixedHeight(lay.minimumSize().height())

    def _make_row(self, dev: DeviceInfo) -> BatteryRing:
        t = THEMES[self._theme_name]
        row = QWidget()
        row.setObjectName("row")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)

        color = level_color(dev.percent, dev.charging, self._accent)
        kind = self._device_kind_for(dev)
        ring = BatteryRing(44)
        ring.setColors(t["track"], color, t["text"])
        ring.set_device_kind(kind)
        ring.animateTo(dev.percent)
        h.addWidget(ring)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(dev.name)
        nf = QFont()
        nf.setPointSizeF(9.5)
        nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet(f"color: {t['text']};")
        name_lbl.setMinimumWidth(0)
        fm_metrics = name_lbl.fontMetrics()
        name_lbl.setText(fm_metrics.elidedText(dev.name, Qt.ElideRight, 118))

        if dev.source == "local":
            sub = "本机内置电池"
        else:
            sub = KIND_LABEL.get(device_kind(dev.name), "蓝牙设备")
            if dev.charging:
                sub += " · 充电中"
            elif dev.connected:
                sub += " · 已连接"
            else:
                sub += " · 未连接"
        sub_lbl = QLabel(sub)
        qf = QFont()
        qf.setPointSizeF(8)
        sub_lbl.setFont(qf)
        sub_lbl.setStyleSheet(f"color: {t['sub']};")

        info.addWidget(name_lbl)
        info.addWidget(sub_lbl)
        h.addLayout(info, 1)

        pct_lbl = QLabel("--" if dev.percent is None else f"{dev.percent}%")
        pf = QFont()
        pf.setPointSizeF(13)
        pf.setBold(True)
        pct_lbl.setFont(pf)
        pct_lbl.setStyleSheet(f"color: {color.name()};")
        h.addWidget(pct_lbl, 0, Qt.AlignVCenter)

        self.body_layout.addWidget(row)
        self._rows.append(row)
        return ring

    def _make_compact_ring(self, dev: DeviceInfo) -> QWidget:
        t = THEMES[self._theme_name]
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        # 精简模式：设备图标本身作为轮廓，电量数字居中。
        if self._minimal:
            ring = BatteryRing(44, tile=True)
        else:
            ring = BatteryRing(40)
        color = level_color(dev.percent, dev.charging, self._accent)
        kind = self._device_kind_for(dev)
        # 精简(tile)模式固定使用 MINIMAL_ACCENT，不随全局强调色变化
        tile_accent = MINIMAL_ACCENT if self._minimal else self._accent
        ring.setColors(t["track"], color, t["text"],
                       accent=QColor(tile_accent))
        ring.set_device_kind(kind)
        ring.animateTo(dev.percent)
        v.addWidget(ring, 0, Qt.AlignHCenter)
        if not self._minimal:
            pct = QLabel("--" if dev.percent is None else f"{dev.percent}%")
            pf = QFont()
            pf.setPointSizeF(8.5)
            pf.setBold(True)
            pct.setFont(pf)
            pct.setAlignment(Qt.AlignCenter)
            pct.setStyleSheet(f"color: {color.name()};")
            v.addWidget(pct)
        return wrap, ring

    # ------------------------------------------------------------------ #
    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.btn_refresh.setEnabled(not loading)
        self._refresh_status_ui()

    def set_status(self, text: str, dot_color: str) -> None:
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(
            f"background: {dot_color}; border-radius: 3px;")

    def set_last_update(self, text: str) -> None:
        self._last_status = text
        if not self._loading:
            self.set_status(text, "#34D399")

    def set_error(self, text: str) -> None:
        self.set_status(text, "#F87171")

    def _refresh_status_ui(self) -> None:
        if self._loading:
            self.set_status("正在刷新…", "#FBBF24")
        elif hasattr(self, "_last_status"):
            self.set_status(self._last_status, "#34D399")
        else:
            self.set_status("准备就绪", "#8A92A2")

    # ------------------------------------------------------------------ #
    def toggle_compact(self) -> None:
        self.set_compact(not self._compact)

    def set_always_on_top(self, on: bool) -> None:
        """切换“始终置顶”。setWindowFlags 会隐藏窗口，需按需重新显示。"""
        on = bool(on)
        if on == self._always_on_top:
            return
        self._always_on_top = on
        flags = Qt.Tool | Qt.FramelessWindowHint
        if on:
            flags |= Qt.WindowStaysOnTopHint
        visible = self.isVisible()
        pos = self.pos()
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.move(pos)
        if visible:
            self.show()
            self.raise_()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        t = THEMES[self._theme_name]
        self.btn_compact.setIcon(
            make_icon("chevron_up" if compact else "chevron_down",
                      t["sub"], 15))
        if hasattr(self, "_last_devices"):
            self.update_devices(self._last_devices)
        self.sig_compact_changed.emit(compact)

    def set_minimal(self, minimal: bool) -> None:
        """精简模式：只保留电量圆环，隐藏标题栏/状态栏/空状态，双击可刷新。"""
        self._minimal = minimal
        root = self.layout()
        if minimal:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)  # 取消宽度上限，由内容决定
            root.setContentsMargins(6, 6, 6, 6)
        else:
            self.setMinimumWidth(264)
            self.setMaximumWidth(264)
            root.setContentsMargins(14, 12, 12, 12)
        self.header_widget.setVisible(not minimal)
        self.footer_widget.setVisible(not minimal)
        self.empty_widget.setVisible(not minimal)
        if hasattr(self, "_last_devices"):
            self.update_devices(self._last_devices)

    # ------------------------------------------------------------------ #
    # 双击：精简模式下立即刷新电量
    # ------------------------------------------------------------------ #
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.sig_refresh.emit()
        event.accept()

    # ------------------------------------------------------------------ #
    # 拖拽
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.position().toPoint())
            if isinstance(child, QToolButton):
                return
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self.raise_()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._clamp_to_screen()
            self.sig_position_changed.emit(self.x(), self.y())

    def _clamp_to_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        area = logical_available_geometry(screen)
        x, y = self.x(), self.y()
        x = max(area.left() - self.width() + 40,
                min(x, area.right() - 40))
        y = max(area.top(), min(y, area.bottom() - 40))
        self.move(x, y)

    def show_at(self, pos: Optional[List[int]]) -> None:
        self.show()
        if pos:
            self.move(int(pos[0]), int(pos[1]))
        else:
            geo = logical_available_geometry(QApplication.primaryScreen())
            self.move(geo.right() - self.width() - 24,
                      geo.top() + 16)
        self._clamp_to_screen()
        self.raise_()

    def fade_in(self) -> None:
        # 入场动画：窗口整体由全透明渐显到完全不透明，
        # 最终背景透明度由 paintEvent 的 brush alpha（self._opacity）控制。
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._fade_anim = anim
