"""核心数据模型：扫描项、分类、风险等级。"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Risk(int, Enum):
    """风险等级：数值越大越危险。"""

    SAFE = 0        # 可放心清理（缓存、临时文件）
    LOW = 1         # 低风险（日志、历史记录）
    MEDIUM = 2      # 中等（需要判断，可能丢失使用记录）
    HIGH = 3        # 高风险（软件残留、用户数据）
    DANGEROUS = 4   # 危险（系统文件、已安装软件本体）

    @property
    def label(self) -> str:
        return RISK_LABELS[self.value]

    @property
    def color(self) -> str:
        return RISK_COLORS[self.value]


RISK_LABELS = {
    0: "安全",
    1: "低风险",
    2: "中等",
    3: "高风险",
    4: "危险",
}

RISK_COLORS = {
    0: "#2ecc71",
    1: "#7bd389",
    2: "#f5b041",
    3: "#e8734a",
    4: "#e74c3c",
}

# 字符串 -> Risk
RISK_ALIASES = {
    "safe": Risk.SAFE,
    "安全": Risk.SAFE,
    "low": Risk.LOW,
    "低": Risk.LOW,
    "低风险": Risk.LOW,
    "medium": Risk.MEDIUM,
    "中": Risk.MEDIUM,
    "中等": Risk.MEDIUM,
    "中风险": Risk.MEDIUM,
    "high": Risk.HIGH,
    "高": Risk.HIGH,
    "高风险": Risk.HIGH,
    "dangerous": Risk.DANGEROUS,
    "危险": Risk.DANGEROUS,
    "critical": Risk.DANGEROUS,
}


def parse_risk(value: Any, default: Risk = Risk.MEDIUM) -> Risk:
    """把任意来源（枚举 / 数字 / 字符串）解析成 Risk。"""
    if isinstance(value, Risk):
        return value
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        for r in Risk:
            if r.value == value:
                return r
        return default
    if isinstance(value, str):
        key = value.strip().lower()
        if key in RISK_ALIASES:
            return RISK_ALIASES[key]
        # 兼容 "risk: 2" 之类
        for ch in key:
            if ch.isdigit():
                return parse_risk(int(ch), default)
    return default


class ItemKind(str, Enum):
    DIR = "dir"          # 目录（递归删除）
    FILE = "file"        # 单文件
    FILES = "files"      # 符合规则的一组文件（按 pattern 匹配）
    COMMAND = "command"  # 需要执行外部命令（dism / powercfg / vssadmin 等）

    @property
    def label(self) -> str:
        return {
            "dir": "目录",
            "file": "文件",
            "files": "多文件",
            "command": "命令",
        }[self.value]


@dataclass
class Category:
    """扫描项分类。"""

    key: str
    name: str
    desc: str = ""
    default_checked: bool = True   # 是否默认勾选（保守策略：仅最安全项 True）
    default_risk: Risk = Risk.SAFE
    order: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "desc": self.desc,
            "default_checked": self.default_checked,
            "default_risk": self.default_risk.value,
            "order": self.order,
        }


CATEGORIES: Dict[str, Category] = {
    c.key: c
    for c in [
        Category("user_temp", "用户临时文件", "%TEMP% 下可安全删除的临时数据", True, Risk.SAFE, 10),
        Category("win_temp", "Windows 临时文件", "C:\\Windows\\Temp 系统临时目录", True, Risk.SAFE, 11),
        Category("recycle_bin", "回收站", "各分区回收站中的已删除文件", True, Risk.SAFE, 12),
        Category("thumbnail", "缩略图缓存", "Explorer 生成的 thumbs.db 缓存数据库", True, Risk.SAFE, 13),
        Category("prefetch", "预读取文件", "Prefetch 预读取缓存，删除后可自动重建", True, Risk.LOW, 14),
        Category("font_cache", "字体缓存", "系统字体缓存文件", True, Risk.SAFE, 15),
        Category("icon_cache", "图标缓存", "Explorer 图标缓存 db", True, Risk.SAFE, 16),
        Category("wer", "Windows 错误报告", "WER 报告队列与归档", True, Risk.SAFE, 20),
        Category("crash_dump", "崩溃转储文件", "内存转储 .dmp / MEMORY.DMP", True, Risk.LOW, 21),
        Category("win_log", "系统日志", "CBS / DISM / Windows Update 等日志", True, Risk.LOW, 22),
        Category("win_update", "Windows 更新缓存", "SoftwareDistribution\\Download 更新下载缓存", True, Risk.SAFE, 30),
        Category("win_update_log", "Windows 更新日志", "更新相关日志文件", True, Risk.LOW, 31),
        Category("winsxs", "WinSxS 组件存储", "需执行 DISM 组件清理，耗时较长", False, Risk.MEDIUM, 32),
        Category("windows_old", "旧系统残留", "Windows.old / $WINDOWS.~BT 等升级残留", False, Risk.HIGH, 33),
        Category("delivery_opt", "传递优化缓存", "Delivery Optimization 分发缓存", True, Risk.SAFE, 34),
        Category("hibernate", "休眠文件", "hiberfil.sys，关闭休眠可释放等同内存大小空间", False, Risk.MEDIUM, 35),
        Category("restore_point", "系统还原点", "卷影副本，删除后无法系统还原", False, Risk.HIGH, 36),
        Category("browser", "浏览器缓存", "Chrome/Edge/Firefox 等浏览器缓存与 GPU 缓存", True, Risk.SAFE, 40),
        Category("dev_cache", "开发工具缓存", "npm/pip/NuGet/Gradle/Maven/Go/Cargo 等包管理缓存", True, Risk.SAFE, 50),
        Category("app_cache", "常用软件缓存", "微信/QQ/钉钉/Steam 等软件产生的缓存", True, Risk.LOW, 60),
        Category("pf_software", "Program Files 已安装程序", "识别到的已安装软件目录，删除即卸载，需谨慎", False, Risk.DANGEROUS, 70),
        Category("pf_residue", "Program Files 残留目录", "软件已卸载但目录仍残留", False, Risk.HIGH, 71),
        Category("pf_unknown", "Program Files 未知目录", "需 AI 进一步确认归属", False, Risk.HIGH, 72),
        Category("appdata_cache", "AppData 可清理缓存", "应用缓存/日志/临时目录，可放心清理", True, Risk.SAFE, 80),
        Category("appdata_data", "AppData 数据目录", "含配置/用户数据，删除会丢失设置", False, Risk.MEDIUM, 81),
        Category("appdata_residue", "AppData 残留目录", "对应软件已卸载，目录无用", False, Risk.MEDIUM, 82),
        Category("empty_dir", "空目录", "扫描发现的空文件夹", True, Risk.SAFE, 90),
        Category("large_file", "大文件", "超过阈值的文件，供人工判断", False, Risk.MEDIUM, 91),
        Category("duplicate", "重复文件", "内容完全相同的重复文件", False, Risk.MEDIUM, 92),
        Category("bad_shortcut", "失效快捷方式", "指向目标已不存在的快捷方式", True, Risk.SAFE, 93),
        Category("other", "其他", "未归类项", False, Risk.MEDIUM, 99),
    ]
}


def category_name(key: str) -> str:
    return CATEGORIES[key].name if key in CATEGORIES else "其他"


@dataclass
class ScanItem:
    """一个可清理项。"""

    path: str
    name: str = ""
    category: str = "other"
    kind: ItemKind = ItemKind.DIR
    size: int = 0
    file_count: int = 0
    risk: Risk = Risk.SAFE
    reason: str = ""            # 作用说明 / 为什么可清理
    software: str = ""          # 归属软件
    source: str = "rule"        # rule / registry / pe / ai / system
    checked: bool = False
    protected: bool = False     # 系统保护，禁止删除
    command: str = ""           # kind=command 时执行的命令
    command_note: str = ""
    patterns: List[str] = field(default_factory=list)  # kind=files 时的匹配模式
    mtime: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(self.path.rstrip("\\/")) or self.path

    @property
    def size_text(self) -> str:
        return human_size(self.size)

    @property
    def category_label(self) -> str:
        return category_name(self.category)

    @property
    def risk_label(self) -> str:
        return self.risk.label

    @property
    def can_clean(self) -> bool:
        return not self.protected and self.size >= 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "category": self.category,
            "kind": self.kind.value,
            "size": self.size,
            "file_count": self.file_count,
            "risk": self.risk.value,
            "reason": self.reason,
            "software": self.software,
            "source": self.source,
            "checked": self.checked,
            "protected": self.protected,
            "command": self.command,
            "patterns": self.patterns,
            "mtime": self.mtime,
            "extra": self.extra,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScanItem":
        return ScanItem(
            path=d.get("path", ""),
            name=d.get("name", ""),
            category=d.get("category", "other"),
            kind=ItemKind(d.get("kind", "dir")),
            size=d.get("size", 0),
            file_count=d.get("file_count", 0),
            risk=parse_risk(d.get("risk", 0)),
            reason=d.get("reason", ""),
            software=d.get("software", ""),
            source=d.get("source", "rule"),
            checked=d.get("checked", False),
            protected=d.get("protected", False),
            command=d.get("command", ""),
            patterns=d.get("patterns", []),
            mtime=d.get("mtime", 0),
            extra=d.get("extra", {}),
            id=d.get("id", uuid.uuid4().hex),
        )


@dataclass
class ScanResult:
    """一次完整扫描的结果。"""

    items: List[ScanItem] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    disk_total: int = 0
    disk_free: int = 0
    ai_used: int = 0
    ai_failed: int = 0
    errors: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_size(self) -> int:
        return sum(i.size for i in self.items)

    @property
    def checked_size(self) -> int:
        return sum(i.size for i in self.items if i.checked and not i.protected)

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def by_category(self) -> Dict[str, List[ScanItem]]:
        out: Dict[str, List[ScanItem]] = {}
        for it in self.items:
            out.setdefault(it.category, []).append(it)
        return out


@dataclass
class CleanRecord:
    """清理执行记录，用于回滚/审计。"""

    path: str
    kind: str
    ok: bool
    method: str          # recycle / delete / command
    message: str = ""
    size: int = 0
    # v1.3.0：回连到被清理的 ScanItem。界面此前只能按 path 剔除已清理项，
    # 而"同路径不同清理方式"（目录项 / 文件模式项）会被一并误剔除。
    item_id: str = ""


@dataclass
class CleanReport:
    records: List[CleanRecord] = field(default_factory=list)
    freed: int = 0
    failed: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    log_file: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.records if r.ok)


def human_size(num: float, suffix: str = "B") -> str:
    """字节数转人类可读字符串。"""
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "0 B"
    if num < 0:
        return "-"
    for unit in ("", "K", "M", "G", "T", "P"):
        if abs(num) < 1024.0:
            if unit == "":
                return f"{int(num)} {unit}{suffix}".strip()
            return f"{num:.2f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.2f} E{suffix}"
