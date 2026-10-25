"""浏览器缓存扫描：自动发现所有 Chromium 系与 Firefox 系浏览器。"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..knowledge.appdata_rules import normalize
from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from .base import ScannerBase

# Chromium 系 Profile 下的缓存目录（规范化名 -> 说明）
CHROMIUM_CACHE_DIRS: Dict[str, str] = {
    "cache": "网络资源缓存",
    "code cache": "JS/WASM 代码缓存",
    "gpucache": "GPU 着色器缓存",
    "dawncache": "图形缓存",
    "dawnwebgpucache": "WebGPU 缓存",
    "shadercache": "着色器缓存",
    "subresource cache": "子资源缓存",
    "blobstorage": "Blob 数据存储",
    "sessionstorage": "会话存储",
    "videodecodestats": "视频解码统计",
    "downloadmetadata": "下载元数据",
    "extensionrules": "扩展规则缓存",
    "safebrowsing": "安全浏览缓存",
    "sharedstorage": "共享存储",
    "crowddenoise": "语音降噪缓存",
}

# Firefox Profile 下的缓存目录
FIREFOX_CACHE_DIRS: Dict[str, str] = {
    "cache2": "网络缓存",
    "startupcache": "启动缓存",
    "shadercache": "着色器缓存",
    "jumplistcache": "跳转列表缓存",
    "thumbnails": "页面缩略图缓存",
    "safebrowsing": "安全浏览缓存",
}


class BrowserScanner(ScannerBase):
    key = "browsers"
    title = "浏览器缓存"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_browsers", True))

    def _mk_cache(self, path: str, name: str, desc: str, software: str) -> Optional[ScanItem]:
        if not fs.is_dir(path):
            return None
        size, cnt = fs.dir_size(path, max_files=30000)
        return self.ctx.add(ScanItem(
            path=path, name=name, category="browser", kind=ItemKind.DIR,
            size=size, file_count=cnt, risk=Risk.SAFE,
            reason=f"{software} 的{desc}；删除后自动重建，不影响书签、密码与历史记录",
            software=software, source="rule", mtime=fs.get_mtime(path),
        ))

    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        items: List[ScanItem] = []
        ctx.log("[扫描] 浏览器缓存...")
        items += self._chromium()
        items += self._firefox()
        return [i for i in items if i]

    # ---------------------------------------------------------------- Chromium 系
    def _chromium(self) -> List[ScanItem]:
        ctx = self.ctx
        out: List[ScanItem] = []
        for base in (ctx.localappdata, ctx.appdata):
            if not fs.is_dir(base):
                continue
            for vendor in fs.subdir_names(base):   # v1.3.2：scandir 直出类型
                if ctx.stopped():
                    return out
                if vendor.lower() in ("microsoft", "temp"):
                    continue
                vdir = os.path.join(base, vendor)
                user_data = None
                for cand in ("User Data", "user_data", "UserData"):
                    p = os.path.join(vdir, cand)
                    if fs.is_dir(p):
                        user_data = p
                        break
                if not user_data:
                    continue
                software = self._vendor_name(vendor)
                for profile in fs.subdir_names(user_data):   # v1.3.2
                    pdir = os.path.join(user_data, profile)
                    for sub in fs.subdir_names(pdir):   # v1.3.2
                        sp = os.path.join(pdir, sub)
                        key = normalize(sub)
                        if key in CHROMIUM_CACHE_DIRS:
                            it = self._mk_cache(
                                sp, f"{sub} ({profile})",
                                CHROMIUM_CACHE_DIRS[key], software)
                            if it:
                                out.append(it)
                        elif key == "serviceworker":
                            for sub2 in fs.subdir_names(sp):   # v1.3.2
                                sp2 = os.path.join(sp, sub2)
                                if normalize(sub2) in ("cachestorage", "scriptcache"):
                                    it = self._mk_cache(
                                        sp2, f"Service Worker {sub2} ({profile})",
                                        "离线缓存存储", software)
                                    if it:
                                        out.append(it)
        return out

    def _vendor_name(self, vendor: str) -> str:
        mapping = {
            "google": "Google Chrome",
            "bravesoftware": "Brave",
            "operasoftware": "Opera",
            "vivaldi": "Vivaldi",
            "yandex": "Yandex Browser",
            "360chrome": "360 极速浏览器",
            "360se": "360 安全浏览器",
            "qqbrowser": "QQ 浏览器",
            "sogouexplorer": "搜狗浏览器",
            "centbrowser": "Cent Browser",
            "thorium": "Thorium",
            "supermium": "Supermium",
            "chromium": "Chromium",
            "edge": "Microsoft Edge",
        }
        return mapping.get(vendor.lower(), vendor)

    # ---------------------------------------------------------------- Firefox 系
    def _firefox(self) -> List[ScanItem]:
        ctx = self.ctx
        out: List[ScanItem] = []
        for base in (ctx.localappdata, ctx.appdata):
            prof_root = os.path.join(base, "Mozilla", "Firefox", "Profiles")
            if not fs.is_dir(prof_root):
                continue
            for prof in fs.subdir_names(prof_root):   # v1.3.2
                pdir = os.path.join(prof_root, prof)
                for sub in fs.subdir_names(pdir):   # v1.3.2
                    sp = os.path.join(pdir, sub)
                    key = normalize(sub)
                    if key in FIREFOX_CACHE_DIRS:
                        it = self._mk_cache(sp, sub, FIREFOX_CACHE_DIRS[key], "Mozilla Firefox")
                        if it:
                            out.append(it)
        # Waterfox / LibreWolf / Thunderbird
        for base in (ctx.localappdata, ctx.appdata):
            moz = os.path.join(base, "Mozilla")
            if not fs.is_dir(moz):
                continue
            for prod in fs.subdir_names(moz):   # v1.3.2
                if prod.lower() == "firefox":
                    continue
                prof_root = os.path.join(moz, prod, "Profiles")
                if not fs.is_dir(prof_root):
                    continue
                for prof in fs.subdir_names(prof_root):   # v1.3.2
                    pdir = os.path.join(prof_root, prof)
                    for sub in fs.subdir_names(pdir):   # v1.3.2
                        sp = os.path.join(pdir, sub)
                        if normalize(sub) in FIREFOX_CACHE_DIRS:
                            it = self._mk_cache(sp, sub, FIREFOX_CACHE_DIRS[normalize(sub)], prod)
                            if it:
                                out.append(it)
        return out
