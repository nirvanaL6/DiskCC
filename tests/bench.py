"""DiskCC 性能基准（v1.3.2 引入）。

构造一棵确定性的合成磁盘树，跑通完整扫描流程并输出耗时，用于在改造前后
量化对比性能。扫描以 I/O 为主，单次结果波动较大，默认取多轮最小值。

用法：
    python tests/bench.py                  # 复用 /tmp/diskcc_bench 下的树
    python tests/bench.py --rebuild        # 重新生成树
    python tests/bench.py --runs 5
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import statistics
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from diskcc.config import Config  # noqa: E402
from diskcc.scanner.manager import ScanManager  # noqa: E402
from diskcc.utils import fs  # noqa: E402

TREE = "/tmp/diskcc_bench"
DATA = "/tmp/diskcc_bench_data"
BLOCK = b"diskcc-bench-payload-" + bytes(range(256))[:64]


def _write(path: str, size: int, jitter: int = 0) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = max(1, size // len(BLOCK))
    with open(path, "wb") as f:
        f.write(BLOCK * n)
        if jitter:
            f.write(bytes([jitter & 0xFF]) * 32)


def build_tree(root: str, n_dirs: int = 60, n_files_per_dir: int = 60,
               dup_groups: int = 40) -> None:
    """生成一棵规模适中但足以体现 I/O 与哈希开销的树。"""
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    rng = random.Random(20250101)
    U = os.path.join(root, "Users", "tester")
    local = os.path.join(U, "AppData", "Local")
    roaming = os.path.join(U, "AppData", "Roaming")
    dirs = [
        os.path.join(root, "Windows", "Temp"),
        os.path.join(local, "Temp"),
        os.path.join(local, "Programs"),
        os.path.join(roaming, "Cache"),
        os.path.join(root, "Program Files"),
        os.path.join(root, "ProgramData"),
        os.path.join(local, "Microsoft", "Windows", "INetCache"),
    ]
    # 1) 大量小文件：体现遍历 / stat 开销
    for d in dirs:
        base = os.path.join(d, "bulk")
        for i in range(n_dirs):
            sub = os.path.join(base, f"dir{i:03d}")
            for j in range(n_files_per_dir):
                _write(os.path.join(sub, f"f{j:03d}.dat"), rng.randint(512, 8192), j)
    # 2) 重复文件组：体现重复文件扫描的哈希开销
    for g in range(dup_groups):
        grp = os.path.join(local, "Temp", "dups", f"g{g:02d}")
        payload_size = 4096 * (1 + g % 4)
        for k in range(3):
            _write(os.path.join(grp, f"copy{k}.bin"), payload_size)
    # 3) 大文件：体现 large file 扫描
    for i in range(4):
        _write(os.path.join(local, "BigFiles", f"big{i}.bin"), 2 * 1024 * 1024, i)
    # 4) 空目录与深层目录
    for i in range(20):
        os.makedirs(os.path.join(local, "Empty", f"e{i}"), exist_ok=True)
    deep = os.path.join(local, "Deep")
    for i in range(8):
        deep = os.path.join(deep, f"l{i}")
    _write(os.path.join(deep, "leaf.dat"), 2048)


def make_ctx(root: str, cfg: Config):
    from diskcc.scanner.base import ScanContext

    U = os.path.join(root, "Users", "tester")
    local = os.path.join(U, "AppData", "Local")
    ctx = ScanContext(cfg, None, log=lambda m: None)
    ctx.drive = root + os.sep
    ctx.userprofile = U
    ctx.appdata = os.path.join(U, "AppData", "Roaming")
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


def make_cfg() -> Config:
    cfg = Config()
    cfg.set("min_size_mb", 0.001)
    cfg.set("ai_enabled", False)
    cfg.set("scan_windows_update", True)
    cfg.set("scan_browsers", True)
    cfg.set("scan_devtools", True)
    cfg.set("scan_app_cache", True)
    cfg.set("scan_program_files", True)
    cfg.set("scan_appdata", True)
    cfg.set("scan_large_files", True)
    cfg.set("large_file_mb", 1)
    cfg.set("scan_duplicates", True)
    cfg.set("scan_empty_dirs", True)
    return cfg


def bench_scan(root: str, cfg: Config, parallel: bool = True) -> float:
    ctx = make_ctx(root, cfg)
    cfg.set("scan_parallel", parallel)
    mgr = ScanManager(cfg, None, ctx=ctx)
    t0 = time.perf_counter()
    res = mgr.run()
    dt = time.perf_counter() - t0
    print(f"    {'并行' if parallel else '串行'}扫描: {dt:.3f}s  项目 {len(res.items)} 项  "
          f"错误 {len(res.errors)} 条")
    return dt


def bench_micro(root: str) -> None:
    target = os.path.join(root, "Users", "tester", "AppData", "Local", "Temp", "bulk")
    fs.clear_dir_size_cache()
    t0 = time.perf_counter()
    for _ in range(3):
        size, cnt = fs.dir_size(target)
    dt = (time.perf_counter() - t0) / 3
    print(f"    dir_size(冷): {dt:.3f}s  ({cnt} 文件, {size // 1024} KB)")

    fs.clear_dir_size_cache()
    _ = fs.dir_size(target)
    t0 = time.perf_counter()
    for _ in range(50):
        size, cnt = fs.dir_size(target)
    dt = (time.perf_counter() - t0) / 50
    print(f"    dir_size(热/缓存): {dt * 1000:.3f}ms")

    t0 = time.perf_counter()
    n = len(list(fs.iter_files(target, ["*.dat"], max_depth=6, max_results=100000)))
    dt = time.perf_counter() - t0
    print(f"    iter_files(*.dat): {dt:.3f}s  ({n} 命中)")


def bench_hash(root: str) -> None:
    from diskcc.scanner.extra import ExtraScanner

    files = []
    for d, _, fs_ in os.walk(os.path.join(root, "Users", "tester", "AppData",
                                          "Local", "Temp", "dups")):
        files.extend(os.path.join(d, f) for f in fs_)
    files = files[:600]
    if not files:
        return
    t0 = time.perf_counter()
    for p in files:
        ExtraScanner._hash_head(p)
    dt = time.perf_counter() - t0
    print(f"    _hash_head × {len(files)}: {dt:.3f}s")
    subset = files[:120]
    t0 = time.perf_counter()
    for p in subset:
        ExtraScanner._hash_full(p)
    dt2 = time.perf_counter() - t0
    print(f"    _hash_full × {len(subset)}: {dt2:.3f}s")


def main() -> int:
    ap = argparse.ArgumentParser(description="DiskCC 性能基准")
    ap.add_argument("--rebuild", action="store_true", help="重新生成测试树")
    ap.add_argument("--runs", type=int, default=3, help="扫描轮次（取最小值）")
    ap.add_argument("--dirs", type=int, default=60)
    ap.add_argument("--files", type=int, default=60)
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    os.environ["LOCALAPPDATA"] = DATA
    os.environ["APPDATA"] = DATA

    if args.rebuild or not os.path.isdir(TREE):
        print("== 生成测试树 ...")
        t0 = time.perf_counter()
        build_tree(TREE, args.dirs, args.files)
        print(f"   完成，用时 {time.perf_counter() - t0:.1f}s -> {TREE}")
    cfg = make_cfg()

    print("== 微基准 ==")
    bench_micro(TREE)
    bench_hash(TREE)

    print(f"== 全扫描（{args.runs} 轮取最小值）==")
    par, seq = [], []
    for _ in range(args.runs):
        par.append(bench_scan(TREE, cfg, parallel=True))
    for _ in range(max(1, args.runs - 2)):
        seq.append(bench_scan(TREE, cfg, parallel=False))
    print(f"\n   并行最优 {min(par):.3f}s（中位 {statistics.median(par):.3f}s）")
    print(f"   串行最优 {min(seq):.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
