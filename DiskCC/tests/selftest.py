"""内置自测：构造一棵模拟的 C 盘目录树，跑通扫描引擎与清理器。

用法：python main.py --selftest
"""

from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diskcc.cleaner import Cleaner  # noqa: E402
from diskcc.config import Config  # noqa: E402
from diskcc.models import human_size  # noqa: E402
from diskcc.scanner.appdata import AppDataScanner  # noqa: E402
from diskcc.scanner.apps_cache import AppCacheScanner  # noqa: E402
from diskcc.scanner.base import ScanContext  # noqa: E402
from diskcc.scanner.browsers import BrowserScanner  # noqa: E402
from diskcc.scanner.devtools import DevToolScanner  # noqa: E402
from diskcc.scanner.extra import ExtraScanner  # noqa: E402
from diskcc.scanner.junk import SystemJunkScanner  # noqa: E402
from diskcc.scanner.programfiles import ProgramFilesScanner  # noqa: E402
from diskcc.scanner.winupdate import WindowsUpdateScanner  # noqa: E402

SEP = os.sep


def _mkfile(path: str, size_kb: int = 64, age_days: float = 0) -> None:
    """写入一个约 size_kb*512 字节的文件；age_days>0 时把修改时间回拨。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(32)) * (size_kb * 16))
    if age_days:
        ts = __import__("time").time() - age_days * 86400
        os.utime(path, (ts, ts))


def build_fake_disk(root: str) -> None:
    """构造一棵模拟的 C 盘目录树。"""
    W = os.path.join(root, "Windows")
    U = os.path.join(root, "Users", "tester")
    APP_LOCAL = os.path.join(U, "AppData", "Local")
    APP_ROAM = os.path.join(U, "AppData", "Roaming")
    PF = os.path.join(root, "Program Files")
    PF86 = os.path.join(root, "Program Files (x86)")

    # --- Windows 临时（模拟 30 天未动的旧临时文件）---
    _mkfile(os.path.join(W, "Temp", "old1.tmp"), 800, age_days=30)
    _mkfile(os.path.join(W, "Temp", "sub", "old2.tmp"), 900, age_days=45)
    # --- 用户临时 ---
    _mkfile(os.path.join(APP_LOCAL, "Temp", "junk.dat"), 1200, age_days=20)
    # --- 预读取 ---
    for i in range(5):
        _mkfile(os.path.join(W, "Prefetch", f"APP{i}.pf"), 300)
    # --- 更新下载缓存 ---
    for i in range(4):
        _mkfile(os.path.join(W, "SoftwareDistribution", "Download", f"kb{i}.cab"), 2500)
    _mkfile(os.path.join(W, "SoftwareDistribution", "Download", "sub", "kbx.cab"), 2500)
    # --- 旧系统残留 ---
    _mkfile(os.path.join(root, "Windows.old", "Windows", "System32", "big.dll"), 3000)
    # --- 崩溃转储 ---
    _mkfile(os.path.join(APP_LOCAL, "CrashDumps", "app.exe.dmp"), 4000)
    # --- 系统日志 ---
    _mkfile(os.path.join(W, "Logs", "CBS", "CBS.log"), 1500)
    _mkfile(os.path.join(W, "CBS.log"), 1500)
    # --- 休眠文件 ---
    _mkfile(os.path.join(root, "hiberfil.sys"), 6000)

    # --- 浏览器缓存 ---
    chrome = os.path.join(APP_LOCAL, "Google", "Chrome", "User Data", "Default")
    for sub, n in (("Cache", 6), ("Code Cache", 5), ("GPUCache", 4)):
        for i in range(n):
            _mkfile(os.path.join(chrome, sub, f"f{i}.bin"), 700)
    edge = os.path.join(APP_LOCAL, "Microsoft", "Edge", "User Data", "Default")
    for i in range(5):
        _mkfile(os.path.join(edge, "Cache", f"e{i}.bin"), 700)
    ff = os.path.join(APP_LOCAL, "Mozilla", "Firefox", "Profiles", "abc.default-release")
    for i in range(5):
        _mkfile(os.path.join(ff, "cache2", "entries", f"m{i}"), 600)
    _mkfile(os.path.join(ff, "startupCache", "sc.bin"), 600)
    # --- IE 缓存 ---
    _mkfile(os.path.join(APP_LOCAL, "Microsoft", "Windows", "INetCache", "cache.bin"), 900)

    # --- 开发工具缓存 ---
    for i in range(6):
        _mkfile(os.path.join(APP_LOCAL, "npm-cache", f"p{i}.tgz"), 800)
        _mkfile(os.path.join(APP_LOCAL, "pip", "cache", f"w{i}.whl"), 800)
    for i in range(4):
        _mkfile(os.path.join(U, ".gradle", "caches", f"g{i}.jar"), 900)

    # --- 软件缓存 ---
    _mkfile(os.path.join(PF, "Steam", "Steam.exe"), 700)
    for i in range(6):
        _mkfile(os.path.join(PF, "Steam", "steamapps", "shadercache", f"s{i}.bin"), 900)
    for i in range(5):
        _mkfile(os.path.join(APP_ROAM, "Adobe", "Common", "Media Cache Files", f"m{i}.cfa"), 1100)

    # --- Program Files ---
    _mkfile(os.path.join(PF, "7-Zip", "7z.exe"), 500)
    _mkfile(os.path.join(PF, "Adobe", "Adobe Photoshop 2024", "Photoshop.exe"), 4000)
    _mkfile(os.path.join(PF, "Adobe", "Adobe Photoshop 2024", "Required", "a.dll"), 1500)
    _mkfile(os.path.join(PF, "UnknownVendor Tool", "tool.exe"), 700)      # 规则库未收录
    _mkfile(os.path.join(PF, "OldAppResidue", "readme.txt"), 600)          # 疑似残留
    _mkfile(os.path.join(PF86, "WinRAR", "WinRAR.exe"), 600)

    # --- AppData ---
    _mkfile(os.path.join(APP_LOCAL, "SomeGame", "Cache", "c1.dat"), 1200)
    _mkfile(os.path.join(APP_LOCAL, "SomeGame", "Logs", "run.log"), 500)
    _mkfile(os.path.join(APP_LOCAL, "SomeGame", "Config", "user.ini"), 300)
    _mkfile(os.path.join(APP_ROAM, "WeirdApp", "data.bin"), 2000)          # 未知目录 -> AI/默认
    _mkfile(os.path.join(APP_LOCAL, "Tencent", "WeChat", "Cache", "img.dat"), 1000)
    _mkfile(os.path.join(APP_LOCAL, "huge.log"), 4000)                     # 根级大 log

    # --- 空目录 ---
    os.makedirs(os.path.join(APP_LOCAL, "EmptyApp", "empty_sub"), exist_ok=True)
    # --- 大文件 ---
    _mkfile(os.path.join(U, "Downloads", "movie.mp4"), 90000)


def build_ctx(root: str, cfg: Config) -> ScanContext:
    ctx = ScanContext(cfg, None, log=lambda m: None)
    U = os.path.join(root, "Users", "tester")
    local = os.path.join(U, "AppData", "Local")
    roaming = os.path.join(U, "AppData", "Roaming")
    ctx.drive = root + SEP
    ctx.userprofile = U
    ctx.appdata = roaming
    ctx.localappdata = local
    ctx.locallow = os.path.join(U, "AppData", "LocalLow")
    ctx.programdata = os.path.join(root, "ProgramData")
    ctx.temp = os.path.join(local, "Temp")
    ctx.win_temp = os.path.join(root, "Windows", "Temp")
    ctx.windows_dir = os.path.join(root, "Windows")
    ctx.program_files = [os.path.join(root, "Program Files"),
                         os.path.join(root, "Program Files (x86)")]
    ctx.user_programs = os.path.join(local, "Programs")
    return ctx


def main() -> int:
    print("=" * 72)
    print("DiskCC 内置自测：构造模拟 C 盘并运行扫描引擎")
    print("=" * 72)

    root = tempfile.mkdtemp(prefix="diskcc_fake_")
    data_dir = tempfile.mkdtemp(prefix="diskcc_data_")
    os.environ["LOCALAPPDATA"] = data_dir  # 让配置/缓存落在临时目录
    os.environ["APPDATA"] = data_dir

    try:
        build_fake_disk(root)
        cfg = Config()
        cfg.set("min_size_mb", 0.05)
        cfg.set("scan_large_files", True)
        cfg.set("scan_duplicates", False)
        cfg.set("scan_bad_shortcuts", False)
        cfg.set("ai_enabled", False)
        cfg.set("large_file_mb", 10)

        ctx = build_ctx(root, cfg)
        scanners = [
            SystemJunkScanner(ctx),
            WindowsUpdateScanner(ctx),
            BrowserScanner(ctx),
            DevToolScanner(ctx),
            AppCacheScanner(ctx),
            ProgramFilesScanner(ctx),
            AppDataScanner(ctx),
            ExtraScanner(ctx),
        ]
        for s in scanners:
            print(f"\n▶ {s.title}")
            items = s.scan()
            for it in sorted(items, key=lambda x: -x.size)[:8]:
                print(f"   [{it.risk.label}] {it.category_label:<18} "
                      f"{human_size(it.size):>9}  {it.name}"
                      + (f"  <- {it.software}" if it.software else ""))
            print(f"   小计：{len(items)} 项 / {human_size(sum(i.size for i in items))}")

        all_items = list(ctx.items)
        print("\n" + "-" * 72)
        print(f"扫描项总数：{len(all_items)}，合计 {human_size(sum(i.size for i in all_items))}")

        # 关键断言
        cats = {i.category for i in all_items}
        checks = {
            "系统临时文件": "win_temp" in cats,
            "用户临时文件": "user_temp" in cats,
            "Windows 更新缓存": "win_update" in cats,
            "旧系统残留": "windows_old" in cats,
            "休眠文件命令": "hibernate" in cats,
            "浏览器缓存": "browser" in cats,
            "开发工具缓存": "dev_cache" in cats,
            "软件缓存": "app_cache" in cats,
            "Program Files 已识别": any(i.category == "pf_software" for i in all_items),
            "Program Files 残留/未知判定": any(
                i.category in ("pf_residue", "pf_unknown") for i in all_items),
            "AppData 缓存识别": "appdata_cache" in cats,
            "空目录": "empty_dir" in cats,
            "大文件": "large_file" in cats,
        }
        print("\n断言结果：")
        failed = 0
        for name, ok in checks.items():
            print(f"   {'✅' if ok else '❌'} {name}")
            if not ok:
                failed += 1

        # 软件归属识别断言
        sw = {i.name: i.software for i in all_items if i.category.startswith("pf_")}
        print("\nProgram Files 归属识别结果：")
        for k, v in sw.items():
            print(f"   {k} -> {v or '(未识别)'}")
        if sw.get("7-Zip") != "7-Zip":
            print("   ❌ 7-Zip 未正确识别")
            failed += 1
        if not sw.get("WinRAR"):
            print("   ❌ WinRAR 未识别")
            failed += 1

        # 清理器测试：对副本执行真实删除（不进回收站）
        print("\n▶ 清理器测试")
        # 挑一个真实的目录型项目（排除命令项），并把模拟盘根加入允许清理范围
        target = next(i for i in all_items if i.kind.value == "dir" and i.size > 0)
        target.checked = True   # v1.1.3 起扫描结果默认不勾选，清理测试需显式勾选
        cleaner = Cleaner(cfg, log=lambda m: print(f"   {m}"), extra_roots=[root])
        cfg.set("use_recycle_bin", False)
        cfg.set("create_backup_list", True)
        cfg.set("dry_run", False)
        before = os.path.exists(target.path)
        report = cleaner.clean([target])
        after = os.path.exists(target.path)
        print(f"   目标：{target.path}")
        print(f"   清理前存在={before}  清理后存在={after}  释放={human_size(report.freed)}")
        if before and after:
            print("   ❌ 清理未生效")
            failed += 1
        else:
            print("   ✅ 清理生效")

        # 受保护路径拒绝删除
        from diskcc.models import ItemKind, Risk, ScanItem

        dangerous = ScanItem(path=os.path.join(root, "Windows", "System32", "kernel32.dll"),
                             category="other", kind=ItemKind.FILE, size=1024,
                             risk=Risk.DANGEROUS, checked=True)
        rep2 = cleaner.clean([dangerous])
        if rep2.records and rep2.records[0].ok:
            print("   ❌ 危险项未被拦截")
            failed += 1
        else:
            print(f"   ✅ 危险项已拦截：{rep2.records[0].message if rep2.records else ''}")

        print("\n" + "=" * 72)
        if failed:
            print(f"自测失败：{failed} 项未通过")
            return 1
        print("自测全部通过 ✅")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
