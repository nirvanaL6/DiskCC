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

# SHFileOperation 返回码说明（微软文档明确要求优先采用这一组）：
# 它的返回值多数映射到 Winerror.h，但有若干个沿用自 pre-Win32 的专用码（DE_*），
# 这些码与 Winerror.h 里同数值的含义不同，且**必须按 DE_* 解释**。
# 用户实际遇到过的两个：
#   120 = 0x78 = DE_ACCESSDENIEDSRC → 安全设置拒绝访问（并非"函数未实现"）
#   124 = 0x7C = DE_INVALIDFILES    → 源路径无效（多为路径过长，并非"调用级别错误"）
SHFILEOP_ERRORS = {
    0x71: "源和目标为同一文件",
    0x72: "指定了多个源文件但只有一个目标",
    0x73: "重命名时目标目录不同（应改用移动）",
    0x74: "源是根目录，不能移动或重命名",
    0x75: "操作被取消",
    0x76: "目标是源的子目录",
    0x78: "安全设置拒绝访问（通常需要管理员权限，或该目录受系统保护）",
    0x79: "路径层级超过 MAX_PATH 限制",
    0x7A: "操作涉及多个目标路径",
    0x7C: "源路径无效（多为路径过长、含非法字符或已不存在）",
    0x7D: "源和目标位于同一父目录",
    0x7E: "目标路径已存在同名文件",
    0x80: "目标路径是已存在的文件夹",
    0x81: "文件名超过 MAX_PATH",
    0x82: "目标是只读 CD-ROM",
    0x83: "目标是只读 DVD",
    0x84: "目标是可刻录 CD",
    0x85: "文件对目标介质过大",
    0x86: "源是只读 CD-ROM",
    0x87: "源是只读 DVD",
    0x88: "源是可刻录 CD",
    0xB7: "操作过程中超出 MAX_PATH",
}

# 属于"路径本身不被 SHFileOperation 接受"的错误（典型：超长路径）。
# 这类错误换个删除方式就有可能成功，适合回退到长路径安全的永久删除。
SHFILEOP_PATH_ERRORS = {0x79, 0x7C, 0x81, 0xB7}

# 属于"权限/占用"的错误。回退永久删除通常同样失败，应给出针对性建议。
SHFILEOP_ACCESS_ERRORS = {0x78}

_FILE_ATTRIBUTE_READONLY = 0x0001


def explain_shfileop_error(code: int) -> str:
    """把 SHFileOperation 的返回码翻译成可操作的中文说明。"""
    if code == 0:
        return "成功"
    text = SHFILEOP_ERRORS.get(code)
    if text:
        return f"代码 {code}（0x{code:02X}）：{text}"
    return f"代码 {code}（0x{code:02X}）：Windows 错误，详见系统错误码说明"


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

    def short_path(path: str) -> str:
        """把路径转成 8.3 短名（失败返回空串）。

        SHFileOperation 不接受超过 MAX_PATH 的路径，也不支持 \\\\?\\ 前缀；
        短名是目前唯一能让它处理深路径的办法。若系统关闭了 8.3 命名则返回空。
        """
        try:
            buf = ctypes.create_unicode_buffer(4096)
            n = ctypes.windll.kernel32.GetShortPathNameW(
                ctypes.c_wchar_p(path), buf, 4096
            )
            if 0 < n < 4096:
                return buf.value
        except Exception:
            pass
        return ""

    def _clear_readonly(path: str) -> bool:
        """清掉只读属性。部分缓存/日志文件为只读，会让删除直接被拒。"""
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(ctypes.c_wchar_p(path))
            if attrs == 0xFFFFFFFF:
                return False
            if attrs & _FILE_ATTRIBUTE_READONLY:
                ctypes.windll.kernel32.SetFileAttributesW(
                    ctypes.c_wchar_p(path), attrs & ~_FILE_ATTRIBUTE_READONLY
                )
            return True
        except Exception:
            return False

    def _shfileop_delete(paths: List[str]) -> int:
        """调用 SHFileOperation 删除一批路径，返回原始返回码（0=成功）。"""
        if not paths:
            return 0
        # 规范化：SHFileOperation 要求全限定路径；带 \\?\ 前缀或末尾反斜杠都会被判为无效路径
        norm = []
        for p in paths:
            q = os.path.abspath(p)
            if q.startswith("\\\\?\\"):
                q = q[4:]
            q = q.rstrip("\\")
            if len(q) == 2 and q[1] == ":":   # 盘符根，补回反斜杠
                q += "\\"
            norm.append(q)
        buf = "\0".join(norm) + "\0\0"
        op = _SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = _FO_DELETE
        op.pFrom = buf
        op.pTo = None
        op.fFlags = (
            _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI | _FOF_SILENT
        )
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if rc != 0:
            return int(rc)
        if op.fAnyOperationsAborted:
            return 0x75                     # DE_OPCANCELLED
        return 0

    def delete_to_bin(paths: List[str]) -> Tuple[bool, str, int]:
        """移入回收站，返回 (是否成功, 说明, SHFileOperation 返回码)。

        失败时会按错误类型各做一次针对性重试：
        * 路径类（0x7C/0x79/0x81/0xB7，多为超长路径）——改用 8.3 短名重试；
        * 访问类（0x78，安全设置拒绝）——先清掉只读属性再重试。
        """
        if not paths:
            return True, "", 0
        try:
            rc = _shfileop_delete(paths)
        except Exception as e:
            return False, f"调用失败：{e}", -1
        if rc == 0:
            return True, "", 0

        # 重试 1：路径过长 → 短名
        if rc in SHFILEOP_PATH_ERRORS:
            shorts = []
            for p in paths:
                s = short_path(p)
                shorts.append(s or os.path.abspath(p))
            if shorts != [os.path.abspath(p) for p in paths]:
                try:
                    rc = _shfileop_delete(shorts)
                except Exception:
                    pass
                if rc == 0:
                    return True, "", 0

        # 重试 2：只读属性导致访问被拒
        if rc in SHFILEOP_ACCESS_ERRORS:
            for p in paths:
                _clear_readonly(p)
            try:
                rc = _shfileop_delete(paths)
            except Exception:
                pass
            if rc == 0:
                return True, "", 0

        return False, explain_shfileop_error(rc), rc

    def send_to_recycle_bin(paths: List[str]) -> Tuple[bool, str]:
        """把文件/目录移入回收站（可撤销）。保留旧的两元组签名。"""
        ok, msg, _ = delete_to_bin(paths)
        return ok, msg

else:

    def short_path(path: str) -> str:  # pragma: no cover
        return ""

    def delete_to_bin(paths: List[str]) -> Tuple[bool, str, int]:  # pragma: no cover
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
            return True, "", 0
        except Exception as e:
            return False, str(e), -1

    def send_to_recycle_bin(paths: List[str]) -> Tuple[bool, str]:  # pragma: no cover
        ok, msg, _ = delete_to_bin(paths)
        return ok, msg


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
