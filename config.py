# -*- coding: utf-8 -*-
"""配置管理：JSON 持久化 + Windows 开机自启（注册表 Run 键）。"""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import List, Optional

try:
    import winreg
except ImportError:  # 非 Windows 仅用于语法检查
    winreg = None

APP_NAME = "BtBatteryWidget"
APP_VERSION = "v1.0"
DEFAULT_ACCENT = "#5B9CFF"          # 默认强调色（托盘图标固定使用，不随主题色更改）
MINIMAL_ACCENT = "#34D399"          # 精简模式固定主题色（图标与数字）
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "BluetoothBatteryWidget"


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.dirname(os.path.abspath(__file__))
    return path


def config_path() -> str:
    return os.path.join(app_data_dir(), "config.json")


def main_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")


@dataclass
class AppConfig:
    refresh_interval: int = 300          # 自动刷新间隔（秒）
    theme: str = "dark"                  # dark / light / auto
    accent: str = DEFAULT_ACCENT       # 主题色
    opacity: float = 0.96                # 悬浮窗不透明度 0.0 - 1.0
    compact: bool = False                # 紧凑模式（只显示电量环）
    minimal: bool = False                # 精简模式（仅电量圆环，无标题/按钮/状态栏）
    always_on_top: bool = True           # 悬浮窗始终置顶
    only_connected: bool = True          # 仅显示已连接设备
    show_local: bool = True              # 显示本机电池
    uncached_read: bool = False          # 强制实时读取（更慢、可能唤醒设备）
    start_minimized: bool = False        # 启动时最小化到托盘
    autostart: bool = False              # 开机自动启动（由注册表实际状态回填）
    hidden_devices: List[str] = field(default_factory=list)  # 被隐藏设备的 MAC key
    known_devices: dict = field(default_factory=dict)        # MAC key -> 名称（给设置页用）
    device_types: dict = field(default_factory=dict)         # MAC key -> 类型（"auto" 或具体 kind）
    pos: Optional[List[int]] = None      # 悬浮窗位置 [x, y]

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "AppConfig":
        data = {}
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            pass
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cfg = cls(**valid)
        cfg.clamp()
        cfg.autostart = is_autostart_enabled()
        return cfg

    def save(self) -> None:
        self.clamp()
        try:
            with open(config_path(), "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def clamp(self) -> None:
        self.refresh_interval = int(min(max(self.refresh_interval, 15), 7200))
        self.opacity = round(min(max(self.opacity, 0.0), 1.0), 2)
        if self.theme not in ("dark", "light", "auto"):
            self.theme = "dark"
        if not isinstance(self.hidden_devices, list):
            self.hidden_devices = []
        if not isinstance(self.known_devices, dict):
            self.known_devices = {}
        if not isinstance(self.device_types, dict):
            self.device_types = {}


# --------------------------------------------------------------------------- #
# 开机自启
# --------------------------------------------------------------------------- #
def _autostart_command() -> str:
    # PyInstaller 打包后 sys.executable 即 exe 本身，直接自启
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable  # 回退
    return f'"{pythonw}" "{main_script_path()}"'


def is_autostart_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """返回是否成功。"""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return is_autostart_enabled() == enabled
    except OSError:
        return False
