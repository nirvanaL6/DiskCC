"""常用软件缓存：Steam / Adobe / Office / Teams / 微信等可安全清理的缓存目录。"""

from __future__ import annotations

import os
from typing import List, Tuple

from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from .base import ScannerBase

# (路径模板, 软件, 说明, 风险)
APP_CACHES: List[Tuple[str, str, str, Risk]] = [
    # Steam / 游戏平台
    ("{PF}/Steam/steamapps/shadercache", "Steam", "Steam 着色器缓存，删除后会重新编译着色器", Risk.SAFE),
    ("{PF}/Steam/steamapps/downloading", "Steam", "Steam 未完成的下载临时文件", Risk.SAFE),
    ("{PF}/Steam/steamapps/temp", "Steam", "Steam 临时下载目录", Risk.SAFE),
    ("{PF}/Steam/logs", "Steam", "Steam 日志文件", Risk.SAFE),
    ("{PF}/Steam/appcache", "Steam", "Steam 客户端缓存", Risk.SAFE),
    ("{PF}/Steam/dumps", "Steam", "Steam 崩溃转储", Risk.SAFE),
    ("{LOCAL}/Steam/htmlcache", "Steam", "Steam 内置浏览器缓存", Risk.SAFE),
    ("{LOCAL}/EpicGamesLauncher/Saved/webcache", "Epic Games", "Epic 启动器网页缓存", Risk.SAFE),
    ("{LOCAL}/EpicGamesLauncher/Saved/Logs", "Epic Games", "Epic 启动器日志", Risk.SAFE),
    ("{LOCAL}/EpicGamesLauncher/Saved/CrashContexts", "Epic Games", "Epic 崩溃报告", Risk.SAFE),
    ("{LOCAL}/Ubisoft Game Launcher/cache", "Ubisoft Connect", "育碧启动器缓存", Risk.SAFE),
    ("{LOCAL}/Riot Games/Riot Client/Data", "Riot Client", "Riot 客户端缓存数据", Risk.SAFE),
    ("{LOCAL}/GOG Galaxy/webcache", "GOG Galaxy", "GOG 网页缓存", Risk.SAFE),
    ("{LOCAL}/Battle.net/Cache", "暴雪战网", "战网缓存", Risk.SAFE),

    # Adobe
    ("{ROAMING}/Adobe/Common/Media Cache Files", "Adobe", "Adobe 媒体缓存（视频预览缓存，体积极大）", Risk.SAFE),
    ("{ROAMING}/Adobe/Common/Media Cache", "Adobe", "Adobe 媒体缓存数据库", Risk.SAFE),
    ("{LOCAL}/Adobe/Common/Media Cache", "Adobe", "Adobe 媒体缓存", Risk.SAFE),
    ("{ROAMING}/Adobe/Common/Peak Files", "Adobe", "Adobe 音频峰值文件", Risk.SAFE),
    ("{LOCAL}/Adobe/CameraRaw/Cache", "Adobe CameraRaw", "CameraRaw 预览缓存", Risk.SAFE),
    ("{LOCAL}/Adobe/Adobe Media Encoder", "Adobe", "Media Encoder 缓存", Risk.LOW),

    # 微软办公
    ("{LOCAL}/Microsoft/Office/16.0/OfficeFileCache", "Microsoft Office", "Office 文件缓存", Risk.SAFE),
    ("{LOCAL}/Microsoft/Office/16.0/Wef", "Microsoft Office", "Office Web 扩展缓存", Risk.SAFE),
    ("{ROAMING}/Microsoft/Teams/Cache", "Microsoft Teams", "Teams 缓存", Risk.SAFE),
    ("{ROAMING}/Microsoft/Teams/application cache/cache", "Microsoft Teams", "Teams 应用缓存", Risk.SAFE),
    ("{ROAMING}/Microsoft/Teams/media-stack", "Microsoft Teams", "Teams 媒体缓存（常达数 GB）", Risk.SAFE),
    ("{ROAMING}/Microsoft/Teams/Service Worker/CacheStorage", "Microsoft Teams", "Teams 离线缓存", Risk.SAFE),
    ("{LOCAL}/Microsoft/OneDrive/logs", "OneDrive", "OneDrive 日志", Risk.SAFE),
    ("{LOCAL}/Microsoft/Outlook", "Outlook", "Outlook 临时缓存", Risk.LOW),
    ("{LOCAL}/Microsoft/Windows/FileHistory", "Windows", "文件历史记录备份（非系统还原）", Risk.MEDIUM),

    # 显卡 / 驱动
    ("{LOCAL}/NVIDIA/DXCache", "NVIDIA", "NVIDIA DX 着色器缓存", Risk.SAFE),
    ("{LOCAL}/NVIDIA/GLCache", "NVIDIA", "NVIDIA GL 着色器缓存", Risk.SAFE),
    ("{LOCAL}/AMD/DxCache", "AMD", "AMD 着色器缓存", Risk.SAFE),
    ("{LOCAL}/AMD/GLCache", "AMD", "AMD GL 缓存", Risk.SAFE),
    ("{LOCAL}/Intel/ShaderCache", "Intel", "Intel 着色器缓存", Risk.SAFE),

    # 国内常用
    ("{LOCAL}/Tencent/WeChat/xplugin", "微信", "微信插件缓存", Risk.LOW),
    ("{ROAMING}/Tencent/WeChat/Cache", "微信", "微信缓存数据", Risk.LOW),
    ("{LOCAL}/Tencent/WeChatAppStore", "微信", "微信小程序商店缓存", Risk.SAFE),
    ("{ROAMING}/Tencent/WeChatWeb", "微信", "微信网页缓存", Risk.SAFE),
    ("{LOCAL}/Tencent/QQ/Temp", "QQ", "QQ 临时文件", Risk.SAFE),
    ("{LOCAL}/Xunlei", "迅雷", "迅雷缓存与日志", Risk.LOW),
    ("{LOCAL}/Thunder Network/DownloadSDK", "迅雷", "迅雷下载 SDK 缓存", Risk.LOW),
    ("{LOCAL}/BaiduYunGuanjia", "百度网盘", "百度网盘缓存", Risk.LOW),
    ("{ROAMING}/baidu/BaiduNetdisk/cache", "百度网盘", "百度网盘缓存", Risk.LOW),
    ("{LOCAL}/DingTalk", "钉钉", "钉钉缓存", Risk.LOW),
    ("{ROAMING}/DingTalk", "钉钉", "钉钉缓存与日志", Risk.LOW),
    ("{LOCAL}/Feishu", "飞书", "飞书缓存", Risk.LOW),
    ("{LOCAL}/Netease/CloudMusic/Cache", "网易云音乐", "音乐缓存", Risk.SAFE),
    ("{LOCAL}/QQMusic/Cache", "QQ 音乐", "音乐缓存", Risk.SAFE),
    ("{LOCAL}/Tencent/QQLive/Cache", "腾讯视频", "视频缓存", Risk.SAFE),
    ("{LOCAL}/bilibili", "哔哩哔哩", "B 站客户端缓存", Risk.SAFE),
    ("{ROAMING}/bilibili", "哔哩哔哩", "B 站客户端缓存", Risk.SAFE),
    ("{LOCAL}/iqiyi", "爱奇艺", "视频缓存", Risk.SAFE),
    ("{LOCAL}/Youku", "优酷", "视频缓存", Risk.SAFE),

    # 其它
    ("{LOCAL}/Spotify/Data", "Spotify", "Spotify 播放缓存", Risk.SAFE),
    ("{LOCAL}/Spotify/Storage", "Spotify", "Spotify 离线缓存", Risk.SAFE),
    ("{ROAMING}/Spotify/Cache", "Spotify", "Spotify 缓存", Risk.SAFE),
    ("{LOCAL}/Discord/Cache", "Discord", "Discord 缓存", Risk.SAFE),
    ("{LOCAL}/Discord/Code Cache", "Discord", "Discord 代码缓存", Risk.SAFE),
    ("{LOCAL}/Discord/GPUCache", "Discord", "Discord GPU 缓存", Risk.SAFE),
    ("{ROAMING}/Zoom/data", "Zoom", "Zoom 缓存数据", Risk.SAFE),
    ("{ROAMING}/Zoom/logs", "Zoom", "Zoom 日志", Risk.SAFE),
    ("{ROAMING}/Telegram Desktop/tdata/temp", "Telegram", "Telegram 临时文件", Risk.SAFE),
    ("{ROAMING}/Sunlogin", "向日葵", "向日葵远程控制日志与缓存", Risk.LOW),
    ("{ROAMING}/ToDesk", "ToDesk", "ToDesk 缓存", Risk.LOW),
    ("{LOCAL}/Wondershare", "万兴科技", "万兴软件缓存", Risk.LOW),
    ("{LOCAL}/Kingsoft/WPS Office/cache", "WPS", "WPS 缓存", Risk.SAFE),
    ("{ROAMING}/kingsoft/wps", "WPS", "WPS 日志与临时数据", Risk.LOW),
]


class AppCacheScanner(ScannerBase):
    key = "appcache"
    title = "常用软件缓存"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_app_cache", True))

    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        items: List[ScanItem] = []
        ctx.log("[扫描] 常用软件缓存...")
        pf_list = ctx.program_files or [os.path.join(ctx.drive, "Program Files")]
        env = {
            "{LOCAL}": ctx.localappdata,
            "{ROAMING}": ctx.appdata,
            "{HOME}": ctx.userprofile,
        }
        for tpl, software, desc, risk in APP_CACHES:
            if ctx.stopped():
                break
            if "{PF}" in tpl:
                for pf in pf_list:
                    path = os.path.normpath(tpl.replace("{PF}", pf))
                    it = self._mk_item(path, software, desc, risk)
                    if it:
                        items.append(it)
                continue
            path = tpl
            for k, v in env.items():
                path = path.replace(k, v)
            path = os.path.normpath(path)
            it = self._mk_item(path, software, desc, risk)
            if it:
                items.append(it)
        return items

    def _mk_item(self, path: str, software: str, desc: str, risk: Risk) -> object:
        if not fs.is_dir(path):
            return None
        size, cnt = fs.dir_size(path, max_files=60000)
        return self.ctx.add(ScanItem(
            path=path, category="app_cache", kind=ItemKind.DIR,
            size=size, file_count=cnt, risk=risk, reason=desc,
            software=software, source="rule", mtime=fs.get_mtime(path),
        ))
