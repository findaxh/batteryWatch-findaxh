# -*- coding: utf-8 -*-
"""
蓝牙电量悬浮窗 —— 主程序入口。

功能：
  * 桌面悬浮窗展示已连接蓝牙设备电量（BLE GATT Battery Service）
  * 定时自动刷新 / 手动刷新，后台线程读取不卡 UI
  * 系统托盘常驻，开机自启（注册表 HKCU\\...\\Run）
  * 深色/浅色/跟随系统主题、强调色、不透明度、紧凑模式、设备过滤等设置
"""

import copy
import ctypes
import datetime
import sys
import time


def _enable_high_dpi() -> None:
    """在创建任何 Qt 界面前，把进程设为 Per-Monitor V2 DPI 感知。

    python.exe 没有内嵌 DPI manifest，而 Qt 6.11 在本环境下不会自行把
    进程切到感知状态；若缺失这一步，DWM 会按系统缩放比（如 150%）
    位图拉伸窗口并导致坐标错位（窗口可能被定位到屏幕外）。
    """
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_high_dpi()

from PySide6.QtCore import (
    QObject, Qt, QTimer, QSharedMemory, QRectF,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QMessageBox

from bt_reader import (
    BatteryReadThread, DeviceInfo, kill_children, mac_key,
)
from config import (
    APP_VERSION, AppConfig, DEFAULT_ACCENT,
    is_autostart_enabled, set_autostart,
)
from floating import FloatingWidget, effective_theme, make_icon
from settings_dialog import SettingsDialog


def build_tray_icon() -> QIcon:
    """托盘图标固定使用默认颜色，不随主题强调色更改。"""
    pm = QPixmap(128, 128)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(DEFAULT_ACCENT))
    p.drawRoundedRect(QRectF(10, 10, 108, 108), 26, 26)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><polyline points="7,7 17,17 12,22 12,2 17,7 7,17"/>'
        '</svg>'
    ).encode("utf-8")
    QSvgRenderer(QByteArray(svg)).render(p, QRectF(34, 34, 60, 60))
    p.end()
    return QIcon(pm)


class AppController(QObject):
    def __init__(self, app: QApplication, cfg: AppConfig):
        super().__init__()
        self.app = app
        self.cfg = cfg
        self.all_devices: list[DeviceInfo] = []
        self._thread: BatteryReadThread | None = None
        self._last_update = 0.0
        # 设置对话框实时预览相关状态
        self._dlg: SettingsDialog | None = None
        self._snapshot: AppConfig | None = None
        self._suppress_persist = False

        # ---------------- 悬浮窗 ----------------
        self.widget = FloatingWidget(cfg.accent)
        self.widget.sig_refresh.connect(lambda: self.start_refresh(manual=True))
        self.widget.sig_settings.connect(self.open_settings)
        self.widget.sig_compact_changed.connect(self._on_compact_changed)
        self.widget.sig_position_changed.connect(self._on_position_changed)

        # ---------------- 定时器 ----------------
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.start_refresh(manual=False))

        # ---------------- 托盘 ----------------
        # 图标固定默认颜色，不受设置中的主题强调色影响
        self.tray = QSystemTrayIcon(build_tray_icon(), self.app)
        self.tray.setToolTip(f"蓝牙电量监控 {APP_VERSION}")
        menu = QMenu()
        self.act_show = QAction("显示悬浮窗", menu)
        self.act_refresh = QAction("立即刷新", menu)
        self.act_on_top = QAction("悬浮窗置顶", menu)
        self.act_on_top.setCheckable(True)
        self.act_minimal = QAction("精简模式", menu)
        self.act_minimal.setCheckable(True)
        self.act_settings = QAction("设置…", menu)
        self.act_autostart = QAction("开机自动启动", menu)
        self.act_autostart.setCheckable(True)
        self.act_quit = QAction("退出", menu)
        menu.addAction(self.act_show)
        menu.addAction(self.act_refresh)
        menu.addAction(self.act_on_top)
        menu.addAction(self.act_minimal)
        menu.addSeparator()
        menu.addAction(self.act_settings)
        menu.addAction(self.act_autostart)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)

        self.act_show.triggered.connect(self.toggle_window)
        self.act_refresh.triggered.connect(lambda: self.start_refresh(manual=True))
        self.act_on_top.triggered.connect(self._toggle_on_top)
        self.act_minimal.triggered.connect(self._toggle_minimal)
        self.act_settings.triggered.connect(self.open_settings)
        self.act_autostart.triggered.connect(self._toggle_autostart)
        self.act_quit.triggered.connect(self.quit_app)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.apply_config_to_ui()
        if not cfg.start_minimized:
            self.widget.show_at(cfg.pos)
            self.widget.fade_in()

        QTimer.singleShot(700, lambda: self.start_refresh(manual=False))

    # ------------------------------------------------------------------ #
    # 刷新
    # ------------------------------------------------------------------ #
    def start_refresh(self, manual: bool = False) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.widget.set_loading(True)
        self._thread = BatteryReadThread(
            uncached=self.cfg.uncached_read,
            include_local=True,  # 本机由过滤控制，读一次无妨
            parent=self,
        )
        self._thread.finished_read.connect(self._on_refresh_done)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self) -> None:
        self._thread = None

    def _on_refresh_done(self, devices, error) -> None:
        self.widget.set_loading(False)
        if error or devices is None:
            self.widget.set_error(f"刷新失败：{error or '未知错误'}")
            if error:
                self.tray.showMessage(
                    "蓝牙电量监控", f"电量刷新失败：{error}",
                    QSystemTrayIcon.Warning, 3000)
            return

        self.all_devices = devices
        self._last_update = time.time()
        changed = self._remember_devices(devices)

        visible = self._filter_devices(devices)
        self.widget.update_devices(visible, self.cfg.device_types)
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        interval_text = self._interval_text(self.cfg.refresh_interval)
        self.widget.set_last_update(f"已更新 {stamp} · 每{interval_text}")

        self._update_tray_tooltip(visible)
        if changed:
            self.cfg.save()

    def _remember_devices(self, devices) -> bool:
        changed = False
        for d in devices:
            if d.source == "local":
                continue
            key = mac_key(d.address)
            if key and self.cfg.known_devices.get(key) != d.name:
                self.cfg.known_devices[key] = d.name
                changed = True
        return changed

    def _filter_devices(self, devices):
        out = []
        for d in devices:
            if d.source == "local":
                if self.cfg.show_local:
                    out.append(d)
                continue
            key = mac_key(d.address)
            if key in self.cfg.hidden_devices:
                continue
            if self.cfg.only_connected and not d.connected:
                continue
            out.append(d)
        return out

    def _update_tray_tooltip(self, visible) -> None:
        parts = []
        for d in visible[:6]:
            if d.percent is not None:
                parts.append(f"{d.name} {d.percent}%")
        tip = f"蓝牙电量监控 {APP_VERSION}"
        if parts:
            tip += "\n" + " · ".join(parts)
        self.tray.setToolTip(tip)

    @staticmethod
    def _interval_text(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}小时"
        if seconds % 60 == 0:
            return f"{seconds // 60}分钟"
        return f"{seconds}秒"

    # ------------------------------------------------------------------ #
    # 设置
    # ------------------------------------------------------------------ #
    def open_settings(self) -> None:
        theme = effective_theme(self.cfg.theme)
        sub_color = "#9AA2B2" if theme == "dark" else "#4B5563"
        dlg = SettingsDialog(self.cfg, sub_color, self.widget)
        self._dlg = dlg
        # 打开时快照当前配置：预览期间直接改动 cfg，取消时据此还原
        self._snapshot = copy.deepcopy(self.cfg)
        dlg.preview_changed.connect(self._on_preview)
        accepted = dlg.exec()
        dlg.preview_changed.disconnect(self._on_preview)
        self._dlg = None

        if accepted:
            dlg.apply_to_config()
            if self.cfg.autostart != is_autostart_enabled():
                ok = set_autostart(self.cfg.autostart)
                if not ok:
                    QMessageBox.warning(
                        self.widget, "开机自启",
                        "修改开机启动项失败，请检查权限或安全软件设置。")
                self.cfg.autostart = is_autostart_enabled()
            self.cfg.save()
            self.apply_config_to_ui()
        else:
            # 取消：丢弃预览期间的临时改动，恢复外观
            self._restore_snapshot(self._snapshot)
            self.apply_config_to_ui()
        self._snapshot = None

    def _restore_snapshot(self, snapshot: AppConfig) -> None:
        """把快照值原地写回 self.cfg（保持对象引用不变）。"""
        for name in self.cfg.__dataclass_fields__:
            setattr(self.cfg, name,
                    copy.deepcopy(getattr(snapshot, name)))

    def _on_preview(self) -> None:
        """设置对话框中任意选项改变时，按差异粒度实时更新悬浮窗（不落盘）。"""
        if self._dlg is None:
            return
        cfg = self.cfg
        old_theme = effective_theme(cfg.theme)
        old = (
            cfg.accent, cfg.opacity, cfg.compact, cfg.minimal,
            cfg.always_on_top, cfg.only_connected, cfg.show_local,
            list(cfg.hidden_devices), dict(cfg.device_types),
            cfg.refresh_interval,
        )
        # 读取控件当前值到 cfg（此时尚未保存）
        self._dlg.apply_to_config()
        new_theme = effective_theme(cfg.theme)

        # 主题切换是离散操作，整体应用（内部会重建设备行）
        if new_theme != old_theme:
            self.widget.apply_theme(new_theme, cfg.accent, cfg.opacity)

        # 强调色：标题图标与精简模式原地变色，不整窗重建
        if cfg.accent != old[0]:
            self.widget.set_accent(cfg.accent)

        # 不透明度：仅重绘背景，拖动滑块也不会让圆环重播动画
        if cfg.opacity != old[1]:
            self.widget.set_opacity(cfg.opacity)

        # 紧凑/精简切换会触发悬浮窗自身信号，预览期间屏蔽其落盘动作
        self._suppress_persist = True
        if cfg.compact != old[2]:
            self.widget.set_compact(cfg.compact)
        if cfg.minimal != old[3]:
            self.widget.set_minimal(cfg.minimal)
        self._suppress_persist = False

        if cfg.always_on_top != old[4]:
            self.widget.set_always_on_top(cfg.always_on_top)
            self.act_on_top.setChecked(cfg.always_on_top)

        # 设备过滤 / 可见性 / 手动类型：重新过滤并渲染
        filters_changed = (
            cfg.only_connected != old[5]
            or cfg.show_local != old[6]
            or list(cfg.hidden_devices) != old[7]
            or cfg.device_types != old[8]
        )
        if filters_changed and self.all_devices:
            self.widget.update_devices(
                self._filter_devices(self.all_devices), cfg.device_types)

        # 刷新间隔：即时生效到定时器（取消时随快照还原）
        if cfg.refresh_interval != old[9]:
            self.timer.setInterval(cfg.refresh_interval * 1000)

    def apply_config_to_ui(self) -> None:
        theme = effective_theme(self.cfg.theme)
        self.widget.apply_theme(theme, self.cfg.accent, self.cfg.opacity)
        self.widget.set_compact(self.cfg.compact)
        self.widget.set_minimal(self.cfg.minimal)
        self.widget.set_always_on_top(self.cfg.always_on_top)
        if self.all_devices:
            self.widget.update_devices(self._filter_devices(self.all_devices),
                                       self.cfg.device_types)
        self.timer.setInterval(self.cfg.refresh_interval * 1000)
        self.timer.start()
        self.act_autostart.setChecked(is_autostart_enabled())
        self.act_on_top.setChecked(self.cfg.always_on_top)
        self.act_minimal.setChecked(self.cfg.minimal)
        # 托盘图标固定默认颜色，主题色变化时不重建

    def _toggle_on_top(self) -> None:
        self.cfg.always_on_top = self.act_on_top.isChecked()
        self.cfg.save()
        self.widget.set_always_on_top(self.cfg.always_on_top)

    def _toggle_autostart(self) -> None:
        wanted = self.act_autostart.isChecked()
        ok = set_autostart(wanted)
        self.act_autostart.setChecked(is_autostart_enabled())
        self.cfg.autostart = is_autostart_enabled()
        self.cfg.save()
        if not ok:
            QMessageBox.warning(self.widget, "开机自启",
                                "修改开机启动项失败，请检查权限设置。")

    # ------------------------------------------------------------------ #
    def _on_compact_changed(self, compact: bool) -> None:
        self.cfg.compact = compact
        # 设置对话框实时预览触发的切换不落盘，保存/取消时统一处理
        if not self._suppress_persist:
            self.cfg.save()

    def _toggle_minimal(self) -> None:
        self.cfg.minimal = self.act_minimal.isChecked()
        self.cfg.save()
        self.widget.set_minimal(self.cfg.minimal)

    def _on_position_changed(self, x: int, y: int) -> None:
        self.cfg.pos = [x, y]
        self.cfg.save()

    def toggle_window(self) -> None:
        if self.widget.isVisible():
            self.widget.hide()
            self.act_show.setText("显示悬浮窗")
        else:
            self.widget.show_at(self.cfg.pos)
            self.widget.raise_()
            self.act_show.setText("隐藏悬浮窗")

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()

    def quit_app(self) -> None:
        self.timer.stop()
        self.cfg.save()
        kill_children()
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(1500)
        self.tray.hide()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("蓝牙电量悬浮窗")
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    # 单实例保护
    shm = QSharedMemory("BtBatteryWidget-SingleInstance-v1")
    if shm.attach():
        shm.detach()
        box = QMessageBox()
        box.setWindowTitle("蓝牙电量悬浮窗")
        box.setText("程序已经在运行中（请查看系统托盘）。")
        box.setIcon(QMessageBox.Information)
        box.exec()
        return 0
    shm.create(1)

    cfg = AppConfig.load()
    controller = AppController(app, cfg)  # noqa: F841
    app.aboutToQuit.connect(kill_children)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
