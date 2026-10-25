"""Windows 专有能力封装：UAC 提权、回收站删除、磁盘信息、注册表、进程占用。

在非 Windows 平台上所有函数安全降级，便于开发/自测。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from .fs import IS_WINDOWS

# ---------------------------------------------------------------- UAC


def is_admin() -> bool:
    if not IS_WINDOWS:
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """以管理员权限重新启动本程序，成功则当前进程应退出。"""
    if not IS_WINDOWS or is_admin():
        return False
    try:
        params = " ".join(f'"{a}"' for a in sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        return int(rc) > 32
    except Exception:
        return False


# ---------------------------------------------------------------- 磁盘信息


def disk_usage(path: str = "C:\\") -> Tuple[int, int]:
    """返回 (总容量, 可用空间)。"""
    if IS_WINDOWS:
        try:
            free_bytes = ctypes.c_ulonglong()
            total_bytes = ctypes.c_ulonglong()
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path),
                None,
                ctypes.byref(total_bytes),
                ctypes.byref(free_bytes),
            )
            return int(total_bytes.value), int(free_bytes.value)
        except Exception:
            pass
    try:
        import shutil

        total, used, free = shutil.disk_usage(path if os.path.exists(path) else "/")
        return int(total), int(free)
    except Exception:
        return 0, 0


def free_space_gb(path: str = "C:\\") -> float:
    _, free = disk_usage(path)
    return round(free / (1024 ** 3), 2)


# ---------------------------------------------------------------- 回收站


_FO_DELETE = 3
_FOF_ALLOWUNDO = 0x0040
_FOF_NOCONFIRMATION = 0x0010
_FOF_NOERRORUI = 0x0400
_FOF_SILENT = 0x0004
_FOF_WANTNUKEWARNING = 0x4000


if IS_WINDOWS:  # pragma: no cover - 仅在 Windows 生效

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    def send_to_recycle_bin(paths: List[str]) -> Tuple[bool, str]:
        """把文件/目录移入回收站（可撤销）。"""
        if not paths:
            return True, ""
        buf = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
        op = _SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = _FO_DELETE
        op.pFrom = buf
        op.pTo = None
        op.fFlags = (
            _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI | _FOF_SILENT
        )
        try:
            rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        except Exception as e:
            return False, str(e)
        if rc != 0:
            return False, f"SHFileOperation 返回 {rc}"
        if op.fAnyOperationsAborted:
            return False, "操作被中止"
        return True, ""

else:

    def send_to_recycle_bin(paths: List[str]) -> Tuple[bool, str]:  # pragma: no cover
        """非 Windows 平台：移动到临时回收目录模拟。"""
        import shutil
        import tempfile
        import time

        bin_root = os.path.join(tempfile.gettempdir(), "DiskCC_RecycleBin")
        os.makedirs(bin_root, exist_ok=True)
        try:
            for p in paths:
                if not os.path.exists(p):
                    continue
                dst = os.path.join(bin_root, f"{int(time.time() * 1000)}_{os.path.basename(p)}")
                shutil.move(p, dst)
            return True, ""
        except Exception as e:
            return False, str(e)


def empty_recycle_bin() -> Tuple[bool, str]:
    try:
        if IS_WINDOWS:
            rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0007)
            return (rc == 0), f"code={rc}"
        return True, "非 Windows 平台，跳过"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------- 注册表


def read_installed_software() -> Dict[str, Dict[str, str]]:
    """读取卸载信息，返回 {规范化安装目录: {name, publisher, version, uninstall, root}}。"""
    result: Dict[str, Dict[str, str]] = {}
    if not IS_WINDOWS:
        return result
    try:
        import winreg
    except Exception:
        return result

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root, sub in roots:
        try:
            key = winreg.OpenKey(root, sub)
        except Exception:
            continue
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            try:
                subkey = winreg.OpenKey(key, name)
            except Exception:
                continue
            info: Dict[str, str] = {}
            for field_name, field_key in (
                ("name", "DisplayName"),
                ("publisher", "Publisher"),
                ("version", "DisplayVersion"),
                ("install_location", "InstallLocation"),
                ("uninstall", "UninstallString"),
                ("install_date", "InstallDate"),
                ("estimated_size", "EstimatedSize"),
            ):
                try:
                    v, _ = winreg.QueryValueEx(subkey, field_key)
                    info[field_name] = str(v)
                except Exception:
                    info.setdefault(field_name, "")
            try:
                winreg.CloseKey(subkey)
            except Exception:
                pass
            loc = info.get("install_location", "").strip().strip('"')
            if not loc:
                # 从卸载命令反推安装目录（去引号、去参数）
                uninst = info.get("uninstall", "").strip()
                exe = ""
                if uninst.startswith('"'):
                    end = uninst.find('"', 1)
                    exe = uninst[1:end] if end > 0 else uninst[1:]
                elif uninst.lower().endswith(".exe"):
                    exe = uninst
                elif " " in uninst:
                    exe = uninst.split(" ")[0]
                cand = os.path.dirname(exe) if exe else ""
                if cand and os.path.isdir(cand):
                    loc = cand
            if loc:
                loc = os.path.normpath(loc).rstrip("\\/").lower()
                if len(loc) >= 4:
                    result[loc] = {
                        "name": info.get("name", ""),
                        "publisher": info.get("publisher", ""),
                        "version": info.get("version", ""),
                        "uninstall": info.get("uninstall", ""),
                        "root": "HKLM" if root == winreg.HKEY_LOCAL_MACHINE else "HKCU",
                    }
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    return result


def read_registry_value(root_name: str, sub_key: str, value_name: str) -> Optional[str]:
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        root = getattr(winreg, root_name)
        key = winreg.OpenKey(root, sub_key)
        v, _ = winreg.QueryValueEx(key, value_name)
        winreg.CloseKey(key)
        return str(v)
    except Exception:
        return None


# ---------------------------------------------------------------- 进程占用


def running_process_names() -> set:
    """返回当前运行的进程可执行文件集合（小写路径），用于跳过占用文件。"""
    names = set()
    try:
        import psutil  # type: ignore

        for p in psutil.process_iter(["exe", "name"]):
            try:
                info = p.info
                if info.get("exe"):
                    names.add(str(info["exe"]).lower())
                if info.get("name"):
                    names.add(str(info["name"]).lower())
            except Exception:
                continue
        return names
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                timeout=15,
            ).stdout
            for line in out.splitlines():
                parts = line.split(",")
                if parts:
                    names.add(parts[0].strip('"').lower())
        except Exception:
            pass
    return names


# ---------------------------------------------------------------- 命令执行


def run_command(cmd: str, timeout: int = 600, shell: bool = True) -> Tuple[int, str]:
    """执行外部命令，返回 (返回码, 输出)。"""
    try:
        cp = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="ignore",
            creationflags=(0x08000000 if IS_WINDOWS else 0),  # CREATE_NO_WINDOW
        )
        out = (cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")
        return cp.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, "执行超时"
    except Exception as e:
        return -2, str(e)


def open_in_explorer(path: str) -> bool:
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False
