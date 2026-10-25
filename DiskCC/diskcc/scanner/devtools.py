"""开发工具缓存：包管理器、构建缓存、模型缓存等。"""

from __future__ import annotations

import os
from typing import List, Tuple

from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from .base import ScannerBase

# (路径模板, 软件, 说明, 风险)
DEV_CACHES: List[Tuple[str, str, str, Risk]] = [
    ("{ROAMING}/npm-cache", "npm", "npm 包缓存（_cacache），可安全清理", Risk.SAFE),
    ("{LOCAL}/npm-cache", "npm", "npm 包缓存，可安全清理", Risk.SAFE),
    ("{ROAMING}/npm/_cacache", "npm", "npm 内容寻址缓存", Risk.SAFE),
    ("{LOCAL}/Yarn/Cache", "Yarn", "Yarn 包缓存", Risk.SAFE),
    ("{ROAMING}/Yarn/cache", "Yarn", "Yarn 包缓存", Risk.SAFE),
    ("{LOCAL}/pnpm-store", "pnpm", "pnpm 全局存储", Risk.SAFE),
    ("{LOCAL}/pnpm/cache", "pnpm", "pnpm 元数据缓存", Risk.SAFE),
    ("{LOCAL}/pip/cache", "pip", "pip 下载缓存，删除后需重新下载依赖包", Risk.SAFE),
    ("{LOCAL}/conda/conda/pkgs", "Conda", "Conda 已下载的包缓存", Risk.SAFE),
    ("{LOCAL}/NuGet/Cache", "NuGet", "NuGet 包缓存", Risk.SAFE),
    ("{LOCAL}/NuGet/v3-cache", "NuGet", "NuGet v3 源缓存", Risk.SAFE),
    ("{HOME}/.nuget/packages", "NuGet", "NuGet 全局包目录（删除后首次构建需联网还原）", Risk.MEDIUM),
    ("{HOME}/.gradle/caches", "Gradle", "Gradle 构建缓存，删除后首次构建变慢", Risk.SAFE),
    ("{HOME}/.gradle/daemon", "Gradle", "Gradle 守护进程日志", Risk.SAFE),
    ("{HOME}/.m2/repository", "Maven", "Maven 本地仓库（删除后需重新下载依赖）", Risk.MEDIUM),
    ("{HOME}/.ivy2/cache", "sbt/Ivy", "Ivy 依赖缓存", Risk.MEDIUM),
    ("{LOCAL}/go-build", "Go", "Go 构建缓存，删除后首次编译变慢", Risk.SAFE),
    ("{HOME}/go/pkg/mod/cache", "Go", "Go 模块下载缓存", Risk.SAFE),
    ("{HOME}/.cargo/registry/cache", "Cargo", "Cargo 注册表缓存", Risk.SAFE),
    ("{HOME}/.cargo/registry/src", "Cargo", "Cargo 依赖源码，删除后需重新解压", Risk.MEDIUM),
    ("{LOCAL}/node-gyp/Cache", "node-gyp", "node-gyp 头文件缓存", Risk.SAFE),
    ("{LOCAL}/ms-playwright", "Playwright", "Playwright 浏览器内核下载（体积大）", Risk.MEDIUM),
    ("{LOCAL}/puppeteer", "Puppeteer", "Puppeteer 浏览器内核下载", Risk.MEDIUM),
    ("{HOME}/.cache/huggingface", "Hugging Face", "AI 模型缓存（常达数十 GB）", Risk.MEDIUM),
    ("{HOME}/.cache/torch", "PyTorch", "Torch Hub 模型缓存", Risk.MEDIUM),
    ("{HOME}/.cache/pip", "pip", "pip 缓存（Unix 风格路径）", Risk.SAFE),
    ("{HOME}/.cache/vscode", "VS Code", "VS Code 缓存", Risk.SAFE),
    ("{HOME}/.cache/bazel", "Bazel", "Bazel 构建缓存（体积较大）", Risk.SAFE),
    ("{LOCAL}/electron", "Electron", "Electron 二进制缓存", Risk.SAFE),
    ("{LOCAL}/electron-builder/Cache", "electron-builder", "打包工具缓存", Risk.SAFE),
    ("{LOCAL}/Microsoft/VisualStudio/NuGetPackages", "Visual Studio", "VS NuGet 离线包缓存", Risk.MEDIUM),
    ("{LOCAL}/JetBrains", "JetBrains", "JetBrains IDE 缓存与索引（删除后需重建索引）", Risk.MEDIUM),
    ("{LOCAL}/flutter", "Flutter", "Flutter SDK 缓存", Risk.MEDIUM),
    ("{HOME}/.dartServer", "Dart", "Dart 分析服务器缓存", Risk.SAFE),
]


class DevToolScanner(ScannerBase):
    key = "devtools"
    title = "开发工具缓存"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_devtools", True))

    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        items: List[ScanItem] = []
        ctx.log("[扫描] 开发工具缓存...")
        env = {
            "{LOCAL}": ctx.localappdata,
            "{ROAMING}": ctx.appdata,
            "{HOME}": ctx.userprofile,
        }
        for tpl, software, desc, risk in DEV_CACHES:
            if ctx.stopped():
                break
            path = tpl
            for k, v in env.items():
                path = path.replace(k, v)
            path = os.path.normpath(path)
            if not fs.is_dir(path):
                continue
            size, cnt = fs.dir_size(path, max_files=80000)
            it = ctx.add(ScanItem(
                path=path, category="dev_cache", kind=ItemKind.DIR,
                size=size, file_count=cnt, risk=risk, reason=desc,
                software=software, source="rule", mtime=fs.get_mtime(path),
            ))
            if it:
                items.append(it)
        return items
