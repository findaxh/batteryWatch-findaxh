# -*- coding: utf-8 -*-
"""
蓝牙设备电量读取模块（Windows 10/11）。

技术方案：通过系统自带的 PowerShell 5.1 调用 WinRT API：
  1. 枚举已配对的 BLE 设备 (BluetoothLEDevice)
  2. 读取标准 GATT Battery Service (0x180F) / Battery Level (0x2A19)
  3. 回退：枚举 PnP 电池接口中来自蓝牙的设备 (Windows.Devices.Power.Battery)
本机电脑电池则使用 ctypes -> GetSystemPowerStatus，零第三方依赖。

子进程在 QThread 中运行，不会阻塞 UI。
"""

import base64
import ctypes
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QThread, Signal


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class DeviceInfo:
    name: str
    address: str
    percent: Optional[int]          # 0-100，None 表示读不到
    connected: bool
    charging: bool = False
    source: str = "ble"             # ble / pnp / local


# --------------------------------------------------------------------------- #
# 内嵌 PowerShell 脚本（输出一行一个 JSON）
# --------------------------------------------------------------------------- #
_PS_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

[Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Enumeration.DeviceInformationCollection,Windows.Devices.Enumeration,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.BluetoothConnectionStatus,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.BluetoothCacheMode,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.GenericAttributeProfile.GattDeviceServicesResult,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.GenericAttributeProfile.GattCharacteristicsResult,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IBuffer,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Power.Battery,Windows.Devices.Power,ContentType=WindowsRuntime] | Out-Null

function Await($op, $rt) {
  $m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  })[0]
  $gm = $m.MakeGenericMethod($rt)
  $task = $gm.Invoke($null, @($op))
  $task.Wait() | Out-Null
  $task.Result
}

function Emit($o) {
  ($o | ConvertTo-Json -Compress -Depth 4)
}

$batUuid  = [Guid]'0000180F-0000-1000-8000-00805F9B34FB'
$levelUuid = [Guid]'00002A19-0000-1000-8000-00805F9B34FB'
$cacheMode = [Windows.Devices.Bluetooth.BluetoothCacheMode]::Cached
if ($env:BT_UNCACHED -eq '1') { $cacheMode = [Windows.Devices.Bluetooth.BluetoothCacheMode]::Uncached }

$getByte = [System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions].GetMethod(
  'GetByte', [Type[]]@([Windows.Storage.Streams.IBuffer], [uint32]))

# ---------------- 1. BLE GATT Battery Service ---------------- #
try {
  $selector = [Windows.Devices.Bluetooth.BluetoothLEDevice]::GetDeviceSelectorFromPairingState($true)
  $coll = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector)) `
                ([Windows.Devices.Enumeration.DeviceInformationCollection])

  foreach ($d in $coll) {
    $mac = ''
    $idx = $d.Id.LastIndexOf('-')
    if ($idx -ge 0) { $mac = $d.Id.Substring($idx + 1) }

    $level = $null
    $connected = $false
    try {
      $ble = Await ([Windows.Devices.Bluetooth.BluetoothLEDevice]::FromIdAsync($d.Id)) `
                    ([Windows.Devices.Bluetooth.BluetoothLEDevice])
      if ($null -ne $ble) {
        $connected = ($ble.ConnectionStatus -eq [Windows.Devices.Bluetooth.BluetoothConnectionStatus]::Connected)
        $sr = Await ($ble.GetGattServicesForUuidAsync($batUuid)) `
                     ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattDeviceServicesResult])
        if ($sr.Status -eq 0) {
          foreach ($s in $sr.Services) {
            try {
              $cr = Await ($s.GetCharacteristicsForUuidAsync($levelUuid)) `
                           ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattCharacteristicsResult])
              foreach ($c in $cr.Characteristics) {
                try {
                  $rr = Await ($c.ReadValueAsync($cacheMode)) `
                               ([Windows.Devices.Bluetooth.GenericAttributeProfile.GattReadResult])
                  if ($rr.Status -eq 0 -and $null -ne $rr.Value -and $rr.Value.Length -gt 0) {
                    $level = [int]$getByte.Invoke($null, @($rr.Value, [uint32]0))
                    break
                  }
                } catch {}
              }
            } catch {}
            if ($null -ne $level) { break }
          }
        }
      }
    } catch {}

    Emit ([PSCustomObject]@{
      type = 'ble'; name = $d.Name; address = $mac
      connected = $connected; level = $level
    })
  }
} catch {
  Emit ([PSCustomObject]@{ type = 'error'; message = ('BLE: ' + $_.Exception.Message) })
}

# ---------------- 2. PnP 电池接口中的蓝牙设备（回退） ---------------- #
try {
  $bssel = [Windows.Devices.Power.Battery]::GetDeviceSelector()
  $bscoll = Await ([Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($bssel)) `
                   ([Windows.Devices.Enumeration.DeviceInformationCollection])
  foreach ($b in $bscoll) {
    if ($b.Id -notlike '*BTH*') { continue }
    try {
      $batt = Await ([Windows.Devices.Power.Battery]::FromIdAsync($b.Id)) `
                     ([Windows.Devices.Power.Battery])
      if ($null -eq $batt) { continue }
      $rep = $batt.GetReport()
      $level = $null
      if ($null -ne $rep.RemainingCapacityMilliwattHours -and
          $rep.FullChargeCapacityMilliwattHours -gt 0) {
        $level = [int][Math]::Round(100.0 * $rep.RemainingCapacityMilliwattHours / $rep.FullChargeCapacityMilliwattHours)
      }
      Emit ([PSCustomObject]@{
        type = 'pnp'; name = $b.Name; address = $b.Id
        connected = $true; level = $level
        charging = ($rep.Status -eq 3)
      })
    } catch {}
  }
} catch {
  Emit ([PSCustomObject]@{ type = 'error'; message = ('PnP: ' + $_.Exception.Message) })
}
"""


def _mac_key(text: str) -> str:
    """把 MAC 地址/实例 ID 归一成 12 位大写十六进制串，用于去重。"""
    return "".join(ch for ch in (text or "").upper() if ch in "0123456789ABCDEF")[-12:]


# 当前运行中的子进程（供程序退出时 kill，避免卡住）
_CHILDREN: List[subprocess.Popen] = []


def _run_powershell(uncached: bool, timeout: int) -> str:
    encoded = base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    env = os.environ.copy()
    env["BT_UNCACHED"] = "1" if uncached else "0"
    proc = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-STA",
            "-EncodedCommand", encoded,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _CHILDREN.append(proc)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        if proc in _CHILDREN:
            _CHILDREN.remove(proc)
    return stdout.decode("utf-8", errors="replace")


def kill_children() -> None:
    for proc in list(_CHILDREN):
        try:
            proc.kill()
        except OSError:
            pass


def read_local_battery() -> Optional[DeviceInfo]:
    """通过 Win32 GetSystemPowerStatus 读取本机电池（台式机通常没有，返回 None）。"""
    if not sys.platform.startswith("win"):
        return None

    class _PowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    try:
        status = _PowerStatus()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        if status.BatteryLifePercent == 255 or status.BatteryFlag == 128:
            return None
        return DeviceInfo(
            name="本机电脑",
            address="__local__",
            percent=int(status.BatteryLifePercent),
            connected=True,
            charging=status.ACLineStatus == 1,
            source="local",
        )
    except Exception:
        return None


def read_batteries(uncached: bool = False, include_local: bool = True,
                   timeout: Optional[int] = None) -> List[DeviceInfo]:
    """同步读取所有蓝牙设备电量（在子线程中调用）。"""
    if timeout is None:
        timeout = 45 if uncached else 20

    output = _run_powershell(uncached, timeout)

    devices: List[DeviceInfo] = []
    seen_keys = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        kind = obj.get("type")
        if kind == "error":
            continue
        if kind not in ("ble", "pnp"):
            continue

        key = _mac_key(obj.get("address", ""))
        if not key or key in seen_keys:
            # BLE 读到的优先；PnP 重复设备直接丢弃
            continue
        level = obj.get("level")
        if level is not None:
            level = max(0, min(100, int(level)))
        seen_keys.add(key)
        devices.append(DeviceInfo(
            name=str(obj.get("name") or "未知设备"),
            address=obj.get("address", ""),
            percent=level,
            connected=bool(obj.get("connected")),
            charging=bool(obj.get("charging")),
            source=kind,
        ))

    devices.sort(key=lambda d: (not d.connected, d.name.lower()))

    if include_local:
        local = read_local_battery()
        if local is not None:
            devices.insert(0, local)

    return devices


class BatteryReadThread(QThread):
    """后台读取线程：finished = Signal(devices, error)。"""

    finished_read = Signal(object, object)

    def __init__(self, uncached: bool = False, include_local: bool = True,
                 timeout: Optional[int] = None, parent=None):
        super().__init__(parent)
        self._uncached = uncached
        self._include_local = include_local
        self._timeout = timeout

    def run(self) -> None:
        devices, error = None, None
        try:
            devices = read_batteries(self._uncached, self._include_local, self._timeout)
        except subprocess.TimeoutExpired:
            error = "读取超时，请稍后重试"
        except FileNotFoundError:
            error = "未找到 PowerShell（系统缺少 powershell.exe）"
        except Exception as exc:  # noqa: BLE001 - 任何失败都要回到 UI
            error = str(exc) or exc.__class__.__name__
        self.finished_read.emit(devices, error)


# 公开别名
mac_key = _mac_key
