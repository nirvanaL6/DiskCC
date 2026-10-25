"""AppData 目录作用规则库。

* APPDATA_DIRS：目录名 -> (软件名, 作用说明, 是否可整目录清理)
  可整目录清理=True 表示该目录纯粹是缓存/临时数据，删了不影响软件配置。
* CACHE_DIR_NAMES：任意软件目录下出现这些子目录名，即可判定为"可放心清理的缓存"。
* CACHE_FILE_PATTERNS：任意目录下匹配这些模式的文件，属于日志/临时文件，可清理。
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

_NON = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def normalize(name: str) -> str:
    return _NON.sub("", (name or "").lower())


# 目录名 -> (软件名, 作用, 可整目录清理)
APPDATA_DIRS: Dict[str, Tuple[str, str, bool]] = {
    # 浏览器
    "googlechrome": ("Google Chrome", "浏览器配置与缓存", False),
    "chrome": ("Google Chrome", "浏览器配置与缓存", False),
    "microsoftedge": ("Microsoft Edge", "浏览器配置与缓存", False),
    "msedge": ("Microsoft Edge", "浏览器配置与缓存", False),
    "mozillafirefox": ("Mozilla Firefox", "浏览器配置与缓存", False),
    "firefox": ("Mozilla Firefox", "浏览器配置与缓存", False),
    "opera": ("Opera 浏览器", "浏览器配置与缓存", False),
    "operasoftware": ("Opera 浏览器", "浏览器配置与缓存", False),
    "bravesoftware": ("Brave 浏览器", "浏览器配置与缓存", False),
    "vivaldi": ("Vivaldi", "浏览器配置与缓存", False),
    "360chrome": ("360 极速浏览器", "浏览器配置与缓存", False),
    "qqbrowser": ("QQ 浏览器", "浏览器配置与缓存", False),
    "sogouexplorer": ("搜狗浏览器", "浏览器配置与缓存", False),
    "thorium": ("Thorium 浏览器", "浏览器配置与缓存", False),
    "supermium": ("Supermium 浏览器", "浏览器配置与缓存", False),

    # 腾讯系
    "tencent": ("腾讯系软件", "微信/QQ 等腾讯软件的公共数据", False),
    "wechat": ("微信", "聊天图片、文件缓存与配置", False),
    "weixin": ("微信", "聊天图片、文件缓存与配置", False),
    "wechatfiles": ("微信", "接收的文件与缓存（含聊天文件）", False),
    "xwechatfiles": ("微信", "接收的文件与缓存（含聊天文件）", False),
    "wechatweb": ("微信网页版", "网页版运行数据", True),
    "wxwork": ("企业微信", "企业微信缓存与文件", False),
    "qq": ("腾讯 QQ", "QQ 缓存与接收文件", False),
    "tencentqq": ("腾讯 QQ", "QQ 缓存与接收文件", False),
    "qqfiles": ("腾讯 QQ", "QQ 接收的文件", False),
    "tim": ("TIM", "TIM 缓存与文件", False),
    "qqlive": ("腾讯视频", "视频缓存与播放记录", False),
    "qqmusic": ("QQ 音乐", "音乐缓存与下载", False),
    "qqgame": ("QQ 游戏", "游戏缓存", True),
    "tencentvideo": ("腾讯视频", "视频缓存", False),
    "wegame": ("WeGame", "游戏平台缓存", False),
    "wechatdevtools": ("微信开发者工具", "小程序开发工具缓存", False),
    "qqpcmgr": ("电脑管家", "安全软件数据与日志", False),

    # 常用软件
    "dingtalk": ("钉钉", "钉钉缓存与文件", False),
    "dingding": ("钉钉", "钉钉缓存与文件", False),
    "feishu": ("飞书", "飞书缓存与文件", False),
    "lark": ("飞书", "飞书缓存与文件", False),
    "baidunetdisk": ("百度网盘", "网盘缓存与下载", False),
    "baiduyunguanjia": ("百度网盘", "网盘缓存", False),
    "aliyunpan": ("阿里云盘", "网盘缓存", False),
    "quark": ("夸克网盘", "网盘缓存", False),
    "thunder": ("迅雷", "下载缓存", False),
    "xunlei": ("迅雷", "下载缓存", False),
    "thundernetwork": ("迅雷", "下载缓存与日志", False),
    "neteasemusic": ("网易云音乐", "音乐缓存与下载", False),
    "cloudmusic": ("网易云音乐", "音乐缓存与下载", False),
    "kugou": ("酷狗音乐", "音乐缓存", False),
    "kuwo": ("酷我音乐", "音乐缓存", False),
    "bilibili": ("哔哩哔哩", "视频缓存", False),
    "iqiyi": ("爱奇艺", "视频缓存", False),
    "youku": ("优酷", "视频缓存", False),
    "mgtv": ("芒果 TV", "视频缓存", False),
    "spotify": ("Spotify", "音乐缓存", True),
    "discord": ("Discord", "聊天与语音缓存", True),
    "telegramdesktop": ("Telegram", "聊天媒体缓存", False),
    "slack": ("Slack", "消息缓存", True),
    "zoom": ("Zoom", "会议缓存与日志", False),
    "notion": ("Notion", "本地缓存", True),
    "obsidian": ("Obsidian", "笔记配置", False),
    "typora": ("Typora", "编辑器缓存", False),
    "wps": ("WPS Office", "WPS 缓存与备份", False),
    "kingsoft": ("金山办公", "WPS 缓存与日志", False),
    "microsoftoffice": ("Microsoft Office", "Office 缓存与日志", False),
    "onenote": ("OneNote", "笔记缓存", False),
    "onedrive": ("OneDrive", "同步缓存与日志", False),
    "dropbox": ("Dropbox", "同步缓存", True),
    "nutstore": ("坚果云", "同步缓存", False),
    "evernote": ("印象笔记", "笔记缓存", False),
    "youdaonote": ("有道云笔记", "笔记缓存", False),
    "sogouinput": ("搜狗输入法", "输入法词库与配置", False),
    "baiduinput": ("百度输入法", "输入法词库与配置", False),
    "microsoftinputmethod": ("微软输入法", "输入法数据", False),
    "qqpinyin": ("QQ 拼音", "输入法词库", False),

    # 开发
    "npm": ("npm", "npm 全局缓存", True),
    "npmcache": ("npm", "npm 缓存", True),
    "yarn": ("Yarn", "Yarn 缓存", True),
    "pnpm": ("pnpm", "pnpm 缓存", True),
    "pip": ("pip", "Python 包缓存", True),
    "python": ("Python", "Python 用户数据", False),
    "code": ("VS Code", "编辑器配置与扩展", False),
    "vscodecli": ("VS Code CLI", "CLI 数据", False),
    "cursor": ("Cursor", "编辑器缓存与扩展", False),
    "trae": ("Trae", "编辑器缓存与扩展", False),
    "jetbrains": ("JetBrains", "IDE 配置与缓存", False),
    "jetbrainstoolbox": ("JetBrains Toolbox", "IDE 管理工具缓存", True),
    "google": ("Google", "Google 相关组件数据", False),
    "github": ("GitHub", "GitHub 客户端缓存", True),
    "git": ("Git", "Git 配置与凭据", False),
    "docker": ("Docker", "Docker 配置与日志", False),
    "go": ("Go", "Go 模块缓存", True),
    "golang": ("Go", "Go 构建缓存", True),
    "rustup": ("Rust", "Rust 工具链", False),
    "cargo": ("Cargo", "Cargo 注册表缓存", True),
    "nuget": ("NuGet", "NuGet 包缓存", True),
    "gradle": ("Gradle", "Gradle 构建缓存", True),
    "javadeployment": ("Java", "Java 部署缓存", True),
    "sun": ("Java", "Java 运行时数据", True),
    "oracle": ("Oracle/Java", "Java 相关数据", True),
    "microsoft": ("Microsoft", "微软组件数据", False),
    "microsoftvscode": ("VS Code", "编辑器配置与扩展", False),
    "android": ("Android SDK", "Android 构建数据", True),
    "unity": ("Unity", "Unity 编辑器缓存", False),
    "nodejs": ("Node.js", "Node 数据", False),
    "electron": ("Electron 应用", "Electron 应用缓存", True),
    "flutter": ("Flutter", "Flutter SDK 缓存", True),
    "conda": ("Conda", "Conda 包缓存", True),
    "huggingface": ("Hugging Face", "AI 模型缓存（体积大）", True),
    "torch": ("PyTorch", "模型缓存", True),
    "ollama": ("Ollama", "本地大模型缓存（体积大）", True),
    "lmstudio": ("LM Studio", "本地模型缓存（体积大）", True),

    # 系统 / 微软
    "microsoftwindows": ("Windows", "系统组件数据", False),
    "explorer": ("资源管理器", "资源管理器历史记录", True),
    "d3dscache": ("DirectX", "着色器缓存", True),
    "nvidia": ("NVIDIA", "显卡驱动缓存", True),
    "nvidiacorporation": ("NVIDIA", "显卡驱动缓存", True),
    "amd": ("AMD", "显卡驱动缓存", True),
    "intel": ("Intel", "显卡驱动缓存", True),
    "crashdumps": ("Windows", "应用程序崩溃转储", True),
    "d3ds": ("DirectX", "着色器缓存", True),
    "iconcachedb": ("Windows", "图标缓存数据库", True),
    "microsoftedgeupdate": ("Edge 更新", "浏览器更新程序", False),
    "packages": ("Microsoft Store", "Store 应用包缓存", False),
    "storedata": ("Microsoft Store", "Store 数据", False),
    "winx": ("Windows", "Win+X 菜单数据", False),
    "temp": ("系统临时", "临时文件", True),
    "tempinternetfiles": ("IE", "IE 临时文件", True),
    "virtualstore": ("VirtualStore", "兼容性重定向数据", False),
    "wsjtx": ("WSJT-X", "软件数据", False),
}

# 任意软件目录下的"通用可清理子目录"
CACHE_DIR_NAMES = {
    "cache": "通用缓存目录",
    "cache2": "浏览器网络缓存",
    "caches": "缓存目录",
    "codecache": "JS 代码缓存",
    "gpucache": "GPU 缓存",
    "shadercache": "着色器缓存",
    "shader_cache": "着色器缓存",
    "dawncache": "图形缓存",
    "graphitecache": "图形缓存",
    "diskcache": "磁盘缓存",
    "blobstorage": "浏览器 Blob 存储",
    "sessionstorage": "会话存储",
    "localstorageleveldb": "本地存储",
    "serviceworker": "Service Worker 缓存",
    "cachestorage": "缓存存储",
    "webdata": "浏览器数据库（含历史，可清）",
    "thumbnails": "缩略图缓存",
    "thumbs": "缩略图缓存",
    "logs": "日志目录",
    "log": "日志文件",
    "crashreports": "崩溃报告",
    "crashpad": "崩溃报告组件",
    "crashdumps": "崩溃转储",
    "dumps": "转储文件",
    "temp": "临时目录",
    "tmp": "临时目录",
    "temporaryfiles": "临时文件",
    "downloaded": "下载缓存",
    "downloadcache": "下载缓存",
    "updatecache": "更新缓存",
    "updater": "更新程序缓存",
    "backup": "备份文件",
    "backups": "备份文件",
    "history": "历史记录",
    "sessions": "会话数据",
    "diagnostics": "诊断数据",
    "telemetry": "遥测数据",
    "minidump": "小型转储",
    "ebwebview": "内嵌浏览器缓存",
    "webview2": "WebView2 缓存",
    "cef": "内嵌浏览器缓存",
    "cefuserdata": "内嵌浏览器缓存",
    "qcefviewcache": "内嵌浏览器缓存",
    "qtwebengine": "Qt 浏览器引擎缓存",
    "cacheddata": "缓存数据",
    "mediacache": "媒体缓存",
    "imagecache": "图片缓存",
    "videocache": "视频缓存",
    "audiodata": "音频缓存",
    "emoticoncache": "表情缓存",
    "avatar": "头像缓存",
    "avatars": "头像缓存",
    "filecache": "文件缓存",
    "httpcache": "HTTP 缓存",
    "networkcache": "网络缓存",
    "pendingdeletes": "待删除文件",
    "old": "旧版本残留",
    "cache4": "缓存目录",
}

# 通用可清理文件模式（按文件名匹配）
CACHE_FILE_PATTERNS = (
    "*.log", "*.log.*", "*.old", "*.bak", "*.tmp", "*.temp", "*.dmp",
    "*.crash", "*.etl", "thumbs.db", "*.mdmp", "*.hdmp", "*.stackdump",
    "*.txt.bak", "*.swp", "*.part", "*.crdownload", "*.!ut",
)

# 明确不可整目录删除（含用户数据/配置）
DO_NOT_DELETE_DIRS = {
    "roaming", "local", "locallow", "microsoft", "windows", "default",
    "desktop", "documents", "downloads", "pictures", "videos", "music",
}

# 已知"大体积且可安全清理"的 AppData 具体路径（相对 Local/Roaming）
KNOWN_BIG_CACHE_PATHS = [
    ("Local", "Google\\Chrome\\User Data\\Default\\Cache", "Chrome 网络缓存"),
    ("Local", "Google\\Chrome\\User Data\\Default\\Code Cache", "Chrome 代码缓存"),
    ("Local", "Google\\Chrome\\User Data\\Default\\GPUCache", "Chrome GPU 缓存"),
    ("Local", "Google\\Chrome\\User Data\\Default\\Service Worker\\CacheStorage", "Chrome SW 缓存"),
    ("Local", "Microsoft\\Edge\\User Data\\Default\\Cache", "Edge 网络缓存"),
    ("Local", "Microsoft\\Edge\\User Data\\Default\\Code Cache", "Edge 代码缓存"),
    ("Local", "Microsoft\\Edge\\User Data\\Default\\GPUCache", "Edge GPU 缓存"),
    ("Local", "Microsoft\\Windows\\Explorer", "资源管理器缩略图缓存"),
    ("Local", "Microsoft\\Windows\\INetCache", "IE/系统网络缓存"),
    ("Local", "Microsoft\\Windows\\WebCache", "系统 Web 缓存数据库"),
    ("Local", "Microsoft\\Windows\\WER", "Windows 错误报告"),
    ("Local", "Microsoft\\Windows\\Temporary Internet Files", "IE 临时文件"),
    ("Local", "D3DSCache", "DirectX 着色器缓存"),
    ("Local", "NVIDIA", "NVIDIA 着色器/驱动缓存"),
    ("Local", "CrashDumps", "应用崩溃转储"),
    ("Local", "pip\\cache", "pip 包缓存"),
    ("Local", "npm-cache", "npm 包缓存"),
    ("Local", "Yarn\\Cache", "Yarn 包缓存"),
    ("Local", "NuGet\\Cache", "NuGet 包缓存"),
    ("Local", "go-build", "Go 构建缓存"),
    ("Local", "Microsoft\\Windows\\DeliveryOptimization", "传递优化缓存"),
    ("Local", "Temp", "用户临时目录"),
]


def lookup_dir(name: str) -> Optional[Tuple[str, str, bool]]:
    """查 AppData 一级目录的作用。"""
    key = normalize(name)
    if key in APPDATA_DIRS:
        return APPDATA_DIRS[key]
    trimmed = re.sub(r"\d+$", "", key)
    if trimmed and trimmed in APPDATA_DIRS:
        return APPDATA_DIRS[trimmed]
    best = None
    for k, v in APPDATA_DIRS.items():
        if len(k) >= 5 and (k in key or key in k):
            if best is None or len(k) > len(best[0]):
                best = (k, v)
    return best[1] if best else None


def is_cache_dir(name: str) -> bool:
    return normalize(name) in CACHE_DIR_NAMES


def cache_dir_desc(name: str) -> str:
    return CACHE_DIR_NAMES.get(normalize(name), "缓存目录")


def is_reserved(name: str) -> bool:
    return normalize(name) in {normalize(x) for x in DO_NOT_DELETE_DIRS}
