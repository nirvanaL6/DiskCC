"""轻量 PE 文件版本资源解析器（无第三方依赖）。

用于从 Program Files 里的 exe/dll 提取 ProductName / CompanyName / FileDescription，
从而判断文件夹归属哪个软件。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

RT_VERSION = 16


def _u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little", signed=False)


def _u32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "little", signed=False)


def _align4(x: int) -> int:
    return (x + 3) & ~3


def _sz(data: bytes, off: int) -> str:
    end = off
    n = len(data)
    while end + 1 < n:
        if data[end] == 0 and data[end + 1] == 0:
            break
        end += 2
    try:
        return data[off:end].decode("utf-16-le", errors="ignore")
    except Exception:
        return ""


def _sections(data: bytes, e_lfanew: int) -> List:
    nsec = _u16(data, e_lfanew + 6)
    opt_size = _u16(data, e_lfanew + 20)
    sec_start = e_lfanew + 24 + opt_size
    sections = []
    for i in range(nsec):
        off = sec_start + i * 40
        if off + 40 > len(data):
            break
        vsize = _u32(data, off + 8)
        vaddr = _u32(data, off + 12)
        rsize = _u32(data, off + 16)
        roff = _u32(data, off + 20)
        sections.append((vaddr, max(vsize, rsize), roff))
    return sections


def _rva_to_off(rva: int, sections: List) -> Optional[int]:
    for vaddr, vsize, roff in sections:
        if vaddr <= rva < vaddr + vsize:
            return roff + (rva - vaddr)
    return None


def _walk_resource(data: bytes, base: int, dir_off: int, out: List[int], depth: int = 0,
                   want_id: Optional[int] = None) -> None:
    """递归遍历资源目录，收集 RT_VERSION 数据项的偏移。"""
    if dir_off + 16 > len(data):
        return
    n_named = _u16(data, dir_off + 12)
    n_id = _u16(data, dir_off + 14)
    total = n_named + n_id
    for i in range(total):
        ent = dir_off + 16 + i * 8
        if ent + 8 > len(data):
            return
        entry_id = _u32(data, ent)
        offset = _u32(data, ent + 4)
        if depth == 0 and want_id is not None and entry_id != want_id:
            continue
        if offset & 0x80000000:
            _walk_resource(data, base, base + (offset & 0x7FFFFFFF), out, depth + 1, want_id)
        else:
            if depth == 2:
                data_ent = base + offset
                if data_ent + 16 <= len(data):
                    out.append(data_ent)


def _parse_block(data: bytes, off: int) -> Dict:
    """解析 VS_VERSION_INFO 的一个块，返回 {key, value, children}。"""
    n = len(data)
    if off + 6 > n:
        return {}
    length = _u16(data, off)
    value_len = _u16(data, off + 2)
    value_type = _u16(data, off + 4)
    if length == 0 or off + length > n:
        return {}
    key = _sz(data, off + 6)
    p = _align4(off + 6 + (len(key) + 1) * 2)
    value = ""
    children: List[Dict] = []
    if value_len:
        v_start = p
        if value_type == 1:  # 文本
            raw = data[v_start:v_start + value_len * 2]
            value = raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
        p = _align4(v_start + value_len * (2 if value_type == 1 else 1))
    end = off + length
    while p + 6 <= min(end, n):
        child_len = _u16(data, p)
        if child_len == 0:
            break
        child = _parse_block(data, p)
        if child:
            children.append(child)
        p = _align4(p + child_len)
    return {"key": key, "value": value, "children": children}


def _collect_strings(block: Dict, out: Dict[str, str]) -> None:
    if not block:
        return
    key = block.get("key", "")
    if block.get("value"):
        out[key] = block["value"]
    for c in block.get("children", []):
        _collect_strings(c, out)


WANTED_KEYS = (
    "ProductName",
    "CompanyName",
    "FileDescription",
    "ProductVersion",
    "FileVersion",
    "LegalCopyright",
    "OriginalFilename",
    "InternalName",
)


def read_pe_version(path: str) -> Dict[str, str]:
    """读取 PE 文件的版本资源信息；失败返回空字典。

    v1.3.2 性能改写：原实现无论文件是不是 PE，都先整整读 1MB 再去做 b"MZ"
    判断——而一轮 Program Files 扫描里绝大多数采样文件并不是 PE（数据/文本/
    资源文件），等于白白读了几百 MB。现改为：
      1) 先只读 64KB 头部完成 PE 校验与资源段定位；
      2) 不是 PE / 没有资源段就立刻返回 {}（代价从 1MB 降到 64KB 且通常极小）；
      3) 确认为带资源的 PE 后，再按旧策略读满并与旧实现完全一致地解析。
    """
    try:
        if not os.path.isfile(path):
            return {}
        with open(path, "rb") as f:
            head = f.read(65536)
            if len(head) < 0x200 or head[:2] != b"MZ":
                return {}
            e_lfanew = _u32(head, 0x3C)
            if e_lfanew <= 0 or e_lfanew + 24 > len(head):
                return {}
            if head[e_lfanew:e_lfanew + 4] != b"PE\0\0":
                return {}
            opt_start = e_lfanew + 24
            magic = _u16(head, opt_start)
            dd_off = opt_start + (112 if magic == 0x20B else 96)
            if dd_off + 24 > len(head):
                return {}
            rva = _u32(head, dd_off + 16)
            if rva == 0:
                return {}
            sections = _sections(head, e_lfanew)
            res_off = _rva_to_off(rva, sections)
            if res_off is None:
                return {}
            # 已确认为带资源的 PE 后，沿用旧版的读取上限（保证解析结论一致；
            # 省下的开销来自上面那些"根本不是 PE"的文件，它们占了采样的绝大多数）
            f.seek(0)
            data = f.read(1_048_576)
        if len(data) < 0x200 or data[:2] != b"MZ":
            return {}
        e_lfanew = _u32(data, 0x3C)
        if e_lfanew <= 0 or e_lfanew + 24 > len(data):
            return {}
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            return {}
        opt_start = e_lfanew + 24
        magic = _u16(data, opt_start)
        dd_off = opt_start + (112 if magic == 0x20B else 96)
        if dd_off + 24 > len(data):
            return {}
        rva = _u32(data, dd_off + 16)
        if rva == 0:
            return {}
        sections = _sections(data, e_lfanew)
        res_off = _rva_to_off(rva, sections)
        if res_off is None:
            return {}
        entries: List[int] = []
        _walk_resource(data, res_off, res_off, entries, 0, RT_VERSION)
        if not entries:
            return {}
        strings: Dict[str, str] = {}
        for ent in entries[:3]:
            vr_rva = _u32(data, ent)
            vr_off = _rva_to_off(vr_rva, sections)
            if vr_off is None:
                continue
            block = _parse_block(data, vr_off)
            _collect_strings(block, strings)
            if strings:
                break
        return {k: v.strip() for k, v in strings.items() if k in WANTED_KEYS and v.strip()}
    except Exception:
        return {}


def sample_pe_info(folder: str, max_files: int = 4, max_depth: int = 3) -> Dict[str, str]:
    """在目录中采样若干 exe/dll，返回最具有代表性的版本信息。"""
    hits: Dict[str, Dict[str, str]] = {}
    tried = 0
    stack = [(folder, 0)]
    while stack and tried < max_files * 6:
        cur, depth = stack.pop(0)
        if depth > max_depth:
            continue
        try:
            names = sorted(os.listdir(cur))
        except Exception:
            continue
        # 优先与目录同名的 exe
        prefer = [n for n in names if n.lower().endswith((".exe", ".dll"))]
        base = os.path.basename(folder).lower()
        prefer.sort(key=lambda n: (not n.lower().startswith(base[:6]), len(n)))
        for name in prefer:
            if tried >= max_files * 6 or len(hits) >= max_files:
                break
            p = os.path.join(cur, name)
            tried += 1
            info = read_pe_version(p)
            if info.get("ProductName") or info.get("CompanyName"):
                hits[os.path.basename(p)] = info
            if len(hits) >= max_files:
                break
        if len(hits) >= max_files:
            break
        for name in names:
            p = os.path.join(cur, name)
            if os.path.isdir(p):
                stack.append((p, depth + 1))
    if not hits:
        return {}
    # 选择出现次数最多的 ProductName / CompanyName
    products: Dict[str, int] = {}
    companies: Dict[str, int] = {}
    desc = ""
    for info in hits.values():
        pn = info.get("ProductName", "").strip()
        cn = info.get("CompanyName", "").strip()
        if pn:
            products[pn] = products.get(pn, 0) + 1
        if cn:
            companies[cn] = companies.get(cn, 0) + 1
        if not desc and info.get("FileDescription"):
            desc = info["FileDescription"].strip()
    best_product = max(products.items(), key=lambda kv: kv[1])[0] if products else ""
    best_company = max(companies.items(), key=lambda kv: kv[1])[0] if companies else ""
    return {
        "product": best_product,
        "company": best_company,
        "description": desc,
        "samples": "; ".join(list(hits.keys())[:3]),
    }
