"""附加清理项：空目录、大文件、重复文件、失效快捷方式。"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from typing import Dict, List, Tuple

from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from .base import ScannerBase


class ExtraScanner(ScannerBase):
    key = "extra"
    title = "附加清理项"

    def enabled(self) -> bool:
        cfg = self.ctx.cfg
        return any((
            cfg.get("scan_empty_dirs"),
            cfg.get("scan_large_files"),
            cfg.get("scan_duplicates"),
            cfg.get("scan_bad_shortcuts"),
        ))

    def scan(self) -> List[ScanItem]:
        items: List[ScanItem] = []
        cfg = self.ctx.cfg
        if cfg.get("scan_empty_dirs"):
            items += self._empty_dirs()
        if cfg.get("scan_bad_shortcuts"):
            items += self._bad_shortcuts()
        if cfg.get("scan_large_files"):
            items += self._large_files()
        if cfg.get("scan_duplicates"):
            items += self._duplicates()
        return items

    # ---------------------------------------------------------------- 空目录
    def _empty_dirs(self) -> List[ScanItem]:
        ctx = self.ctx
        out: List[ScanItem] = []
        ctx.log("[扫描] 空目录...")
        roots = [ctx.localappdata, ctx.appdata, ctx.programdata, ctx.temp]
        roots += ctx.program_files
        for root in roots:
            if not fs.is_dir(root):
                continue
            stack = [(root, 0)]
            while stack:
                cur, depth = stack.pop()
                if ctx.stopped() or depth > 4:
                    continue
                try:
                    entries = list(os.scandir(cur))
                except Exception:
                    continue
                if not entries and depth > 0:
                    it = ctx.add(ScanItem(
                        path=cur, category="empty_dir", kind=ItemKind.DIR, size=0,
                        risk=Risk.SAFE, reason="空文件夹，无内容", source="system",
                    ))
                    if it:
                        out.append(it)
                    continue
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append((e.path, depth + 1))
                    except OSError:
                        continue
        return out

    # ---------------------------------------------------------------- 失效快捷方式
    def _bad_shortcuts(self) -> List[ScanItem]:
        ctx = self.ctx
        out: List[ScanItem] = []
        if not fs.IS_WINDOWS:
            return out
        ctx.log("[扫描] 失效快捷方式...")
        targets = [
            os.path.join(ctx.userprofile, "Desktop"),
            os.path.join(ctx.userprofile, "OneDrive", "Desktop"),
            os.path.join(ctx.appdata, "Microsoft", "Windows", "Start Menu"),
            os.path.join(ctx.programdata, "Microsoft", "Windows", "Start Menu"),
        ]
        for root in targets:
            if not fs.is_dir(root):
                continue
            for path in fs.iter_files(root, ["*.lnk"], max_depth=4, max_results=3000):
                if ctx.stopped():
                    return out
                tgt = fs.shortcut_target(path)
                if not tgt:
                    continue  # 无法解析目标时不作判断，避免误删
                if not fs.exists(tgt):
                    it = ctx.add(ScanItem(
                        path=path, category="bad_shortcut", kind=ItemKind.FILE,
                        size=fs.get_size(path), risk=Risk.SAFE,
                        reason=f"快捷方式指向的目标已不存在（{tgt}）",
                        source="system", mtime=fs.get_mtime(path),
                    ))
                    if it:
                        out.append(it)
        return out

    # ---------------------------------------------------------------- 大文件
    def _large_files(self) -> List[ScanItem]:
        ctx = self.ctx
        out: List[ScanItem] = []
        threshold = int(float(ctx.cfg.get("large_file_mb", 500)) * 1024 * 1024)
        ctx.log(f"[扫描] 大文件（>{threshold // 1024 // 1024}MB）...")
        roots = [
            os.path.join(ctx.userprofile, "Downloads"),
            os.path.join(ctx.userprofile, "Documents"),
            os.path.join(ctx.userprofile, "Desktop"),
            os.path.join(ctx.userprofile, "Videos"),
            ctx.drive,
        ]
        for root in roots:
            if not fs.is_dir(root):
                continue
            depth = 1 if root == ctx.drive else 4
            for path in fs.iter_files(root, ["*"], max_depth=depth, max_results=8000):
                if ctx.stopped():
                    return out
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if size < threshold:
                    continue
                it = ctx.add(ScanItem(
                    path=path, category="large_file", kind=ItemKind.FILE, size=size,
                    risk=Risk.MEDIUM, reason="大文件，需人工判断是否仍然需要（不会自动勾选）",
                    source="system", mtime=fs.get_mtime(path),
                ))
                if it:
                    out.append(it)
        return out

    # ---------------------------------------------------------------- 重复文件
    def _duplicates(self) -> List[ScanItem]:
        """按内容哈希查找重复文件。

        性能保护（v1.1.2）：全文哈希对大文件（视频/镜像）非常慢，会把"重复文件"
        扫描拖到十几分钟。这里加三道闸：
        1. 小于 dup_min_size_mb 的文件不参与（碎文件价值低）；
        2. 大于 dup_max_file_mb 的单个文件跳过（可在设置中调大）；
        3. 本次扫描哈希总字节数超过 dup_budget_mb 后停止，并明确告知用户。
        """
        ctx = self.ctx
        out: List[ScanItem] = []
        cfg = ctx.cfg
        min_size = int(float(cfg.get("dup_min_size_mb", 1)) * 1024 * 1024)
        max_size = int(float(cfg.get("dup_max_file_mb", 512)) * 1024 * 1024)
        budget = int(float(cfg.get("dup_budget_mb", 2048)) * 1024 * 1024)
        ctx.log(f"[扫描] 重复文件（>{min_size // 1024 // 1024}MB，"
                f"单文件上限 {max_size // 1024 // 1024}MB，总哈希预算 {budget // 1024 // 1024}MB）...")
        roots = [
            os.path.join(ctx.userprofile, "Downloads"),
            os.path.join(ctx.userprofile, "Documents"),
            os.path.join(ctx.userprofile, "Pictures"),
        ]
        by_size: Dict[int, List[str]] = defaultdict(list)
        scanned = 0
        for root in roots:
            if not fs.is_dir(root):
                continue
            for path in fs.iter_files(root, ["*"], max_depth=4, max_results=6000):
                if ctx.stopped():
                    return out
                scanned += 1
                if scanned % 500 == 0:
                    ctx.progress(f"枚举文件 {scanned}", min(40, scanned / 60.0))
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                if min_size <= size <= max_size:
                    by_size[size].append(path)

        hashed = 0
        stopped_by_budget = False
        groups = sorted(by_size.items(), key=lambda kv: -kv[0] * (len(kv[1]) - 1))
        for gi, (size, paths) in enumerate(groups):
            if len(paths) < 2 or ctx.stopped():
                continue
            if hashed + size * len(paths) > budget:
                stopped_by_budget = True
                continue
            ctx.progress(f"校验重复 {gi + 1}/{len(groups)} 组", 40 + (gi + 1) / max(1, len(groups)) * 55)
            hashes: Dict[str, List[str]] = defaultdict(list)
            for p in paths:
                if ctx.stopped():   # v1.3.1：长循环加检查点，保证"停止"能立即生效
                    break
                h = self._hash_head(p)
                if h:
                    hashes[h].append(p)
            for h, group in hashes.items():
                if len(group) < 2:
                    continue
                # 头部哈希一致后再做全文哈希校验，避免误判
                full: Dict[str, List[str]] = defaultdict(list)
                for p in group:
                    if ctx.stopped():
                        break
                    fh = self._hash_full(p)
                    if fh:
                        full[fh].append(p)
                    hashed += size
                for _, group in full.items():
                    if len(group) < 2:
                        continue
                    group = sorted(group)
                    for dup in group[1:]:
                        it = ctx.add(ScanItem(
                            path=dup, category="duplicate", kind=ItemKind.FILE, size=size,
                            risk=Risk.MEDIUM,
                            reason=f"与 {os.path.basename(group[0])} 内容完全相同（全文哈希一致），可删除副本",
                            source="system", mtime=fs.get_mtime(dup),
                            extra={"keep": group[0]},
                        ))
                        if it:
                            out.append(it)
        if stopped_by_budget:
            ctx.log("[扫描] 重复文件：已达哈希预算上限，剩余组未校验（可在设置中调大预算）")
        return out

    @staticmethod
    def _hash_full(path: str) -> str:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 512), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _hash_head(path: str, block: int = 1024 * 1024) -> str:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                h.update(f.read(block))
            return h.hexdigest()
        except Exception:
            return ""
