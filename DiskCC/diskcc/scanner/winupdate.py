"""Windows 更新相关清理：更新下载缓存、旧系统残留、WinSxS、休眠文件、还原点。"""

from __future__ import annotations

import os
from typing import List

from ..models import ItemKind, Risk, ScanItem
from ..utils import fs, win
from .base import ScannerBase


class WindowsUpdateScanner(ScannerBase):
    key = "winupdate"
    title = "Windows 更新与系统组件"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_windows_update", True))

    def _cmd(self, category: str, name: str, cmd: str, reason: str, risk: Risk,
             size: int = 0, note: str = "", protected: bool = False) -> ScanItem:
        return ScanItem(
            path=name,
            name=name,
            category=category,
            kind=ItemKind.COMMAND,
            size=size,
            risk=risk,
            reason=reason,
            source="system",
            command=cmd,
            command_note=note,
            protected=protected,
        )

    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        items: List[ScanItem] = []
        ctx.log("[扫描] Windows 更新与系统组件...")

        # 1. Windows Update 下载缓存
        dl = os.path.join(ctx.windows_dir, "SoftwareDistribution", "Download")
        if fs.is_dir(dl):
            size, cnt = fs.dir_size(dl)
            items.append(ScanItem(
                path=dl,
                category="win_update",
                kind=ItemKind.DIR,
                size=size,
                file_count=cnt,
                risk=Risk.SAFE,
                reason="Windows Update 已下载的安装包缓存，删除后不影响系统，仅会导致已下载补丁需重新下载",
                source="system",
            ))

        # 2. 更新日志
        log_dir = os.path.join(ctx.windows_dir, "SoftwareDistribution", "DataStore", "Logs")
        if fs.is_dir(log_dir):
            size, cnt = fs.dir_size(log_dir)
            items.append(ScanItem(
                path=log_dir, category="win_update_log", kind=ItemKind.DIR, size=size,
                file_count=cnt, risk=Risk.LOW, reason="Windows 更新数据库日志", source="system"))

        # 3. 旧系统残留
        for folder in ("Windows.old", "$WINDOWS.~BT", "$WINDOWS.~WS", "Windows.old.000", "ESD"):
            p = os.path.join(ctx.drive, folder)
            if not fs.is_dir(p):
                continue
            size, cnt = fs.dir_size(p, max_files=50000)
            items.append(ScanItem(
                path=p,
                category="windows_old",
                kind=ItemKind.COMMAND,
                size=size,
                file_count=cnt,
                risk=Risk.HIGH,
                reason=f"系统升级/回退产生的 {folder} 残留目录，删除后将无法回退到旧版本系统",
                source="system",
                command=f'rd /s /q "{p}"',
                command_note="若失败：需在【设置→系统→存储→临时文件】中使用“以前的 Windows 安装”清理，或以管理员命令行执行 takeown + icacls 后再删除",
            ))

        # 4. WinSxS 组件清理（纯命令项：v1.3.1 起仅在 Windows 上给出，
        #    避免非 Windows 环境列出无法执行的系统命令）
        if fs.IS_WINDOWS:
            items.append(self._cmd(
                "winsxs", "DISM 组件存储清理（安全模式，保留可卸载更新）",
                "dism.exe /Online /Cleanup-Image /StartComponentCleanup",
                "清理 WinSxS 中被替代的旧组件版本，通常可释放 1-4GB，耗时数分钟",
                Risk.MEDIUM,
                note="执行期间请勿关闭窗口；系统会自动跳过正使用的组件",
            ))
            items.append(self._cmd(
                "winsxs", "DISM 深度清理（ResetBase，不可卸载已装更新）",
                "dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase",
                "进一步删除所有被替代组件，释放空间更多，但已安装更新将无法卸载",
                Risk.HIGH,
                note="仅在确认系统稳定、无需回滚补丁时执行",
            ))

        # 5. 休眠文件
        hiber = os.path.join(ctx.drive, "hiberfil.sys")
        hiber_size = fs.get_size(hiber) if fs.exists(hiber) else 0
        if hiber_size:
            items.append(self._cmd(
                "hibernate", "关闭休眠并删除 hiberfil.sys",
                "powercfg.exe -h off",
                "休眠文件通常占用内存大小的 40%-75%，关闭休眠后无法使用休眠功能（不影响睡眠与关机）",
                Risk.MEDIUM,
                size=hiber_size,
                note="如需恢复：powercfg -h on",
            ))

        # 6. 系统还原点（纯命令项：仅 Windows）
        if fs.IS_WINDOWS:
            total, free = win.disk_usage(ctx.drive)
            if total:
                items.append(self._cmd(
                    "restore_point", "删除 C 盘系统还原点（卷影副本）",
                    f'vssadmin delete shadows /for={ctx.drive.rstrip(chr(92))} /all /quiet',
                    "删除 C 盘所有系统还原点，可释放数十 GB，但将无法使用系统还原恢复到此前状态",
                    Risk.HIGH,
                    note="删除后可手动新建还原点；建议先确认系统当前状态正常",
                ))

        # 7. MSI 安装包缓存（不默认勾选，删除后可能需要原始安装源）
        inst_cache = os.path.join(ctx.windows_dir, "Downloaded Installations")
        if fs.is_dir(inst_cache):
            size, cnt = fs.dir_size(inst_cache)
            items.append(ScanItem(
                path=inst_cache, category="other", kind=ItemKind.DIR, size=size, file_count=cnt,
                risk=Risk.MEDIUM,
                reason="MSI 安装包缓存，修复/修改安装时可能需要，删除后可能需重新提供安装介质",
                source="system"))

        # 8. Windows 升级临时
        for folder in ("Windows10Upgrade", "Windows Upgrade", "Panther"):
            p = os.path.join(ctx.drive, folder)
            if fs.is_dir(p):
                size, cnt = fs.dir_size(p)
                items.append(ScanItem(
                    path=p, category="windows_old", kind=ItemKind.DIR, size=size, file_count=cnt,
                    risk=Risk.MEDIUM, reason=f"{folder} 升级临时目录", source="system"))

        out: List[ScanItem] = []
        for it in items:
            if not it:
                continue
            # 命令类项不要求路径真实存在；目录/文件类项必须存在
            if it.kind != ItemKind.COMMAND and not fs.exists(it.path):
                continue
            added = ctx.add(it)
            if added:
                out.append(added)
        return out
