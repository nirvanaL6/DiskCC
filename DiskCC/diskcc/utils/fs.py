"""跨平台文件系统工具（以 Windows 为主要目标）。"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
import sys
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

IS_WINDOWS = os.name == "nt"

# 目录体积缓存：key(norm 路径) -> (字节数, 文件数, 目录 mtime, 写入时刻)
_SIZE_CACHE: Dict[str, Tuple[int, int, float, float]] = {}
_SIZE_CACHE_LOCK = threading.RLock()
_SIZE_CACHE_TTL = 30.0      # 秒；仅用于单次扫描内的重复统计复用，每次新扫描会清空
_SIZE_CACHE_MAX = 8192

# v1.3.2：并发"单飞"表。并行扫描时多个线程常同时对同一个目录求大小，
# 若各算各的，不仅重复 CPU/IO，还会让缓存形同虚设（实测并行反而比串行慢一倍）。
# 这里让后到的线程等待先到的线程算完并复用其结果。
_SIZE_INFLIGHT: Dict[str, threading.Event] = {}
_SIZE_INFLIGHT_LOCK = threading.RLock()

# ---------------------------------------------------------------- 路径工具


def _looks_win(path: str) -> bool:
    """判断是否为 Windows 风格路径（含盘符或反斜杠）。"""
    if IS_WINDOWS:
        return True
    if "\\" in path:
        return True
    return len(path) >= 2 and path[0].isalpha() and path[1] == ":"


def norm(path: str) -> str:
    """统一路径格式：去除尾部分隔符，Windows 风格路径转小写用于比较。

    说明：Windows 路径比较不区分大小写，因此即便是非 Windows 平台上处理
    Windows 风格路径（例如单元测试），也应统一转小写，保证系统关键路径
    拦截规则始终生效。
    """
    try:
        p = os.path.normpath(path).rstrip("\\/")
    except Exception:
        p = str(path).rstrip("\\/")
    if _looks_win(path) or _looks_win(p):
        return p.lower()
    return p


def join(*parts: str) -> str:
    return os.path.join(*parts)


def safe_listdir(path: str) -> List[str]:
    """列出目录内容，出错返回空列表。"""
    try:
        return os.listdir(path)
    except Exception:
        return []


def scan_dir(path: str) -> Tuple[List[str], List[str]]:
    """scandir 版 listdir：一次遍历同时返回 (子目录名列表, 文件名列表)。

    v1.3.2：原先几乎每个调用点都写成 `for name in listdir(p): join + is_dir(...)`，
    等于给每个子项多加一次 stat 系统调用（实测这类调用占全扫描约 1/3 时间）。
    scandir 在枚举时就拿到了类型信息（Linux d_type / Windows 文件属性），
    无需额外 stat，结果与原写法等价且不会过期。
    出错返回 ([], [])。
    """
    dirs: List[str] = []
    files: List[str] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        dirs.append(entry.name)
                    else:
                        files.append(entry.name)
                except OSError:
                    continue
    except OSError:
        return [], []
    return dirs, files


def subdir_names(path: str) -> List[str]:
    """列出目录下的【子目录名】（无需额外 stat）。出错返回空列表。"""
    return scan_dir(path)[0]


def file_names(path: str) -> List[str]:
    """列出目录下的【文件名】（无需额外 stat）。出错返回空列表。"""
    return scan_dir(path)[1]


def is_dir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except Exception:
        return False


def is_file(path: str) -> bool:
    try:
        return os.path.isfile(path)
    except Exception:
        return False


def exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except Exception:
        return False


def get_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def get_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def days_since(ts: float) -> float:
    if not ts:
        return -1.0
    return (time.time() - ts) / 86400.0


# ---------------------------------------------------------------- 目录大小


def dir_size(
    path: str,
    max_files: int = 200000,
    on_error: Optional[Callable[[OSError], None]] = None,
    use_cache: bool = True,
) -> Tuple[int, int]:
    """递归统计目录大小，返回 (字节数, 文件数)。

    多个扫描器（垃圾 / 浏览器 / 开发工具 / AppData ...）经常会对同一目录重复
    递归统计，这是扫描最慢的来源之一。这里做一层带失效校验的进程内缓存：
    目录 mtime 未变且未超过 TTL 时直接复用上次结果。
    """
    if not use_cache:
        return _dir_size_calc(path, max_files, on_error)

    key = norm(path)
    try:
        mt = os.path.getmtime(path)
    except Exception:
        mt = -1.0
    now = time.time()
    with _SIZE_CACHE_LOCK:
        hit = _SIZE_CACHE.get(key)
    if hit and hit[2] == mt and (now - hit[3]) < _SIZE_CACHE_TTL:
        return hit[0], hit[1]

    # --- 单飞：同一目录并发求值时，后来者等待首个线程的结果而不重复遍历 ---
    owner = False
    with _SIZE_INFLIGHT_LOCK:
        ev = _SIZE_INFLIGHT.get(key)
        if ev is None:
            ev = threading.Event()
            _SIZE_INFLIGHT[key] = ev
            owner = True
    if not owner:
        ev.wait(timeout=60.0)
        hit2 = None
        with _SIZE_CACHE_LOCK:
            hit2 = _SIZE_CACHE.get(key)
        if hit2 and (time.time() - hit2[3]) < _SIZE_CACHE_TTL:
            return hit2[0], hit2[1]
        # 首线程未能写入结果（如出错/被截断），自己算一次兜底
        return _dir_size_calc(path, max_files, on_error)

    try:
        size, count = _dir_size_calc(path, max_files, on_error, fill_cache=True)
        with _SIZE_CACHE_LOCK:
            _cache_put(key, size, count, mt)
        return size, count
    finally:
        with _SIZE_INFLIGHT_LOCK:
            _SIZE_INFLIGHT.pop(key, None)
        ev.set()


def _cache_put(key: str, size: int, count: int, mt: float) -> None:
    """写入缓存（调用方需已持锁）。超出上限时淘汰最早写入的一批。"""
    if len(_SIZE_CACHE) > _SIZE_CACHE_MAX:
        for k in list(_SIZE_CACHE)[: _SIZE_CACHE_MAX // 4]:
            _SIZE_CACHE.pop(k, None)
    _SIZE_CACHE[key] = (size, count, mt, time.time())


def cache_put(path: str, size: int, count: int, mt: float = -1.0) -> None:
    """外部( binder)写入目录体积结果，供其它扫描器复用。"""
    with _SIZE_CACHE_LOCK:
        _cache_put(norm(path), size, count, mt)


def clear_dir_size_cache() -> None:
    """清空目录体积缓存（每次新扫描前调用，保证结果新鲜）。"""
    with _SIZE_CACHE_LOCK:
        _SIZE_CACHE.clear()
    with _SIZE_INFLIGHT_LOCK:
        _SIZE_INFLIGHT.clear()


def _dir_size_calc(
    path: str,
    max_files: int = 200000,
    on_error: Optional[Callable[[OSError], None]] = None,
    fill_cache: bool = False,
) -> Tuple[int, int]:
    """递归统计目录大小，返回 (字节数, 文件数)。

    v1.3.2 性能改写：
    - 每个目录项只做【一次】stat：原先要依次调用 is_symlink() / is_dir() /
      stat()，实测占全扫描约 40% 时间；现直接按 st_mode 的位判断。
    - 采用带"帧"的显式遍历，子 dir 走完后即可把它的大小写进缓存；扫描器常
      在同一棵树里先后统计多个目录，由此大量重复递归被消除。
    """
    S_ISDIR = stat.S_ISDIR
    S_ISREG = stat.S_ISREG
    truncated = [False]           # 是否因超过 max_files 提前收尾
    seen = [0]                    # 全局文件计数（与原实现的 max_files 语义一致）
    result: Tuple[int, int] = (0, 0)

    def _frame(cur: str, mt: float = -1.0) -> list:
        # [迭代器, 目录路径, 已累计字节, 已累计文件数, 该目录 mtime]
        return [os.scandir(cur), cur, 0, 0, mt]

    stack = [_frame(path)]
    while stack:
        frame = stack[-1]
        it, cur = frame[0], frame[1]
        advanced = False
        try:
            for entry in it:
                if seen[0] > max_files:
                    truncated[0] = True
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as e:
                    if on_error:
                        on_error(e)
                    continue
                mode = st.st_mode
                if S_ISDIR(mode):
                    try:
                        stack.append(_frame(entry.path, st.st_mtime))
                    except OSError as e:
                        if on_error:
                            on_error(e)
                        continue
                    advanced = True
                    break
                elif S_ISREG(mode):
                    frame[2] += st.st_size
                    frame[3] += 1
                    seen[0] += 1
        except OSError as e:
            if on_error:
                on_error(e)
        if advanced:
            continue
        # 本层遍历结束：结算该目录，并把结果回填父帧
        try:
            it.close()
        except Exception:
            pass
        stack.pop()
        dpath, dsize, dcnt, dmt = frame[1], frame[2], frame[3], frame[4]
        if fill_cache and not truncated[0]:
            try:
                with _SIZE_CACHE_LOCK:
                    _cache_put(norm(dpath), dsize, dcnt, dmt)
            except Exception:
                pass
        if stack:
            stack[-1][2] += dsize
            stack[-1][3] += dcnt
        else:
            result = (dsize, dcnt)   # 根帧结算完成
    return result


def count_entries(path: str) -> Tuple[int, int]:
    """只统计直接子项，返回 (目录数, 文件数)。"""
    dirs = files = 0
    for name in safe_listdir(path):
        p = os.path.join(path, name)
        if is_dir(p):
            dirs += 1
        else:
            files += 1
    return dirs, files


def iter_files(
    path: str,
    patterns: Optional[Iterable[str]] = None,
    max_depth: int = 6,
    max_results: int = 5000,
) -> Iterable[str]:
    """遍历目录下符合 pattern 的文件。

    v1.3.2：改用 scandir（省掉逐项 is_dir 的 stat）+ 预编译匹配
    （原先每个文件名对每个 pattern 都要走一遍 fnmatch 的字符串处理）。
    """
    pats = list(patterns or [])
    compiled = [re.compile(fnmatch.translate(p.lower()), re.I) for p in pats]
    stack: List[Tuple[str, int]] = [(path, 0)]
    found = 0
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth or found >= max_results:
            continue
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        try:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, depth + 1))
                        continue
                except OSError:
                    continue
                name = entry.name
                if not pats or any(c.match(name) for c in compiled):
                    found += 1
                    yield entry.path
        finally:
            try:
                it.close()
            except Exception:
                pass


def match_files(path: str, patterns: Iterable[str], max_depth: int = 3) -> List[str]:
    return list(iter_files(path, patterns, max_depth=max_depth))


def sum_files(paths: Iterable[str]) -> Tuple[int, int]:
    total = 0
    n = 0
    for p in paths:
        try:
            total += os.path.getsize(p)
            n += 1
        except OSError:
            continue
    return total, n


# ---------------------------------------------------------------- 删除


def make_writable(path: str) -> None:
    """尽量去掉只读属性，避免删除失败。"""
    if not IS_WINDOWS:
        return
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def force_remove_file(path: str) -> bool:
    """删除单个文件，失败时尝试去掉只读后重试。"""
    try:
        os.remove(path)
        return True
    except Exception:
        make_writable(path)
        try:
            os.remove(path)
            return True
        except Exception:
            return False


def remove_dir_tree(path: str) -> Tuple[bool, str]:
    """递归删除目录（永久删除，慎用）。"""
    import shutil

    def _on_error(func, p, exc):
        make_writable(p)
        try:
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=_on_error)
        return True, ""
    except Exception as e:
        return False, str(e)


def is_empty_dir(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            for _ in it:
                return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 环境路径


def app_data_dir() -> str:
    """DiskCC 自身数据目录（配置、缓存、日志）。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = os.path.expanduser("~")
        base = os.path.join(base, ".local", "share")
    return os.path.join(base, "DiskCC")


def env_path(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


# ---------------------------------------------------------------- 安全校验

# 任何情况下都禁止删除的路径前缀（规范化后比较）
FORBIDDEN_PREFIXES = (
    "c:\\windows\\system32",
    "c:\\windows\\syswow64",
    "c:\\windows\\winsxs",
    "c:\\windows\\boot",
    "c:\\windows\\fonts",
    "c:\\windows\\security",
    "c:\\windows\\systemresources",
    "c:\\programdata\\microsoft\\windows defender",
    "c:\\users\\default",
    "c:\\users\\public",
    "c:\\programdata\\application data",
    "c:\\program files\\windows nt",
    "c:\\$recycle.bin\\system",
)

# 允许清理的根目录（扫描项必须落在其中之一）
ALLOWED_ROOTS = (
    "c:\\",
    "%temp%",
    "%localappdata%",
    "%appdata%",
)


def is_forbidden(path: str) -> bool:
    p = norm(path)
    for prefix in FORBIDDEN_PREFIXES:
        if p == prefix or p.startswith(prefix + "\\") or p.startswith(prefix + "/"):
            return True
    return False


def is_safe_target(path: str, allowed_roots: Iterable[str]) -> bool:
    """路径必须在允许根内，且不在禁止名单中。"""
    if is_forbidden(path):
        return False
    p = norm(path)
    for root in allowed_roots:
        r = norm(root)
        if not r:
            continue
        if p == r or p.startswith(r + "\\") or p.startswith(r + "/"):
            return True
    return False


def shortcut_target(lnk_path: str) -> str:
    """读取 .lnk 快捷方式目标（需 pywin32）。

    v1.3.1 修复：移除二进制正则降级提取——该方式会把 lnk 内任意可见字符串
    误判为目标路径，进而把"存在的路径"误判成失效目标导致误删。
    解析失败返回空字符串，调用方应跳过而不是判定为失效。
    """
    if not IS_WINDOWS:
        return ""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore

        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortCut(lnk_path)
            return str(sc.Targetpath)
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        pass
    return ""


def unique_path(path: str) -> str:
    """若路径已存在，追加序号生成新路径。"""
    if not exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = f"{base}_{i}{ext}"
        if not exists(cand):
            return cand
    return path


def format_ts(ts: float) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def mtime_text(path: str) -> str:
    ts = get_mtime(path)
    if not ts:
        return "-"
    d = days_since(ts)
    if d < 1:
        return "今天"
    if d < 30:
        return f"{int(d)} 天前"
    if d < 365:
        return f"{int(d // 30)} 个月前"
    return f"{int(d // 365)} 年前"
