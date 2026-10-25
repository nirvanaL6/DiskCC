"""扫描调度：按配置组合各扫描器并汇总结果。"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Type

from ..ai.analyzer import AIAnalyzer
from ..config import Config
from ..models import ScanResult
from ..utils import fs, win
from .appdata import AppDataScanner
from .apps_cache import AppCacheScanner
from .base import ScanContext, ScannerBase
from .browsers import BrowserScanner
from .devtools import DevToolScanner
from .extra import ExtraScanner
from .junk import SystemJunkScanner
from .programfiles import ProgramFilesScanner
from .winupdate import WindowsUpdateScanner

THREAD_PREFIX = "diskcc-scan-"   # 并行扫描线程名前缀，供进度归集识别来源


SCANNERS: List[Type[ScannerBase]] = [
    SystemJunkScanner,
    WindowsUpdateScanner,
    BrowserScanner,
    DevToolScanner,
    AppCacheScanner,
    ProgramFilesScanner,
    AppDataScanner,
    ExtraScanner,
]


class ScanManager:
    def __init__(
        self,
        cfg: Config,
        ai: Optional[AIAnalyzer] = None,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[str, float], None]] = None,
        ctx: Optional[ScanContext] = None,
    ):
        self.cfg = cfg
        self.ai = ai
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda m, p: None)
        self.cancel = threading.Event()
        # 允许注入已配置好的上下文（自测/性能基准用），为空时按真实环境创建
        self._injected_ctx = ctx
        self.ctx: Optional[ScanContext] = ctx

    def stop(self) -> None:
        self.cancel.set()

    def run(self) -> ScanResult:
        result = ScanResult()
        fs.clear_dir_size_cache()      # 每次扫描重新统计，避免复用上一次的体积
        ctx = self._injected_ctx or ScanContext(
            self.cfg, self.ai, self.log, self.progress, self.cancel)
        self.ctx = ctx
        total, free = win.disk_usage(ctx.drive)
        result.disk_total, result.disk_free = total, free
        self._t0 = time.time()
        self._orig_progress = self.progress
        self.progress = self._timed_progress

        # v1.2.0：只实例化一次。原写法 `s(ctx) for ... if s(ctx).enabled()`
        # 会为每个扫描器创建两遍实例，初始化开销直接翻倍。
        # v1.3.0：单个扫描器构造失败不得拖垮整轮扫描（v1.2.0 会直接抛出，
        # 结果变成"扫描完成 0 项"且错误列表为空，用户完全无从排查）。
        instances: List[ScannerBase] = []
        for cls in SCANNERS:
            try:
                instances.append(cls(ctx))
            except Exception as e:
                ctx.error(f"{getattr(cls, 'title', cls.__name__)} 初始化失败：{e}")
        active = []
        for s in instances:
            try:
                if s.enabled():
                    active.append(s)
            except Exception as e:
                ctx.error(f"{s.title} 启用判断失败：{e}")
        # AI 候选是在扫描过程中才收集的，无法提前得知；
        # 因此只要 AI 开启就先预留一个进度步，扫描结束后再决定用不用。
        reserve_ai = bool(self.ai and self.ai.enabled)
        n = len(active) + (1 if reserve_ai else 0)
        if n == 0:
            n = 1

        if self.cfg.get("scan_parallel", True) and len(active) > 1:
            self._run_parallel(ctx, active, n)
        else:
            self._run_sequential(ctx, active, n)

        # ---------------- 独立“AI 分析”步骤（与扫描分离，便于了解进度） ----------------
        # v1.2.0 修复：原先在扫描器运行前判断候选队列，而那时队列必然为空，
        # 导致该步骤从未真正执行（扫描阶段等于没用 AI）。
        if reserve_ai and not self.cancel.is_set():
            if ctx.ai_pf_targets or ctx.ai_ad_targets:
                idx = len(active) + 1
                self.progress("AI 分析：未知目录", (idx - 1) / n * 100)
                ctx.progress = self._step_progress(idx, n, "AI 分析")
                try:
                    self._run_ai_step(ctx)
                except Exception as e:
                    ctx.error(f"AI 分析失败：{e}")
                self.progress("AI 分析完成", 100)
            else:
                self.log("[AI] 本次扫描没有需要 AI 识别的未知目录，跳过")
                self.progress("AI 分析：无需分析", 100)

        result.items = list(ctx.items)
        result.errors = list(ctx.errors)
        # v1.3.0：写入结束时间。此前 finished_at 始终为 0，界面显示的"耗时"
        # 实际是等到读取那一刻才算，扫描与展示之间有偏差。
        result.finished_at = time.time()
        result.ai_used = self.ai.calls if self.ai else 0
        result.ai_failed = self.ai.fails if self.ai else 0
        result.stats = {
            "items": len(result.items),
            "categories": {k: len(v) for k, v in result.by_category().items()},
            "admin": win.is_admin(),
            "ai_enabled": bool(self.ai and self.ai.enabled),
        }
        if self.ai:
            self.ai.save_cache()
        self.progress = self._orig_progress
        # v1.1.3：兜底——无论规则库还是 AI 标记，扫描结束后一律不勾选任何项目，
        # 由用户自行甄别勾选，防止误删（此时扫描线程已全部结束，无需加锁）。
        for it in result.items:
            it.checked = False
        return result

    # ---------------------------------------------------------------- 扫描调度
    def _run_sequential(self, ctx: ScanContext, active: List[ScannerBase], n: int) -> None:
        """串行执行（默认回退路径，行为与旧版一致）。"""
        for idx, scanner in enumerate(active, 1):
            if self.cancel.is_set():
                self.log("[扫描] 已取消")
                break
            self.progress(f"扫描：{scanner.title}", (idx - 1) / n * 100)
            ctx.progress = self._step_progress(idx, n, f"扫描：{scanner.title}")
            try:
                scanner.scan()
            except Exception as e:
                ctx.error(f"{scanner.title} 扫描失败：{e}")
            self.progress(f"扫描：{scanner.title} 完成", idx / n * 100)

    def _run_parallel(self, ctx: ScanContext, active: List[ScannerBase], n: int) -> None:
        """并行执行各扫描器（v1.2.0）。

        扫描以目录遍历 / stat 这类等待磁盘的 I/O 为主，串行时大量时间耗在等待上；
        各扫描器的目标目录基本不重叠，天然适合并发。共享状态（项目表、去重集合、
        AI 候选队列、体积缓存）均已加锁，结果等价。
        """
        import concurrent.futures as futures

        state: Dict[int, float] = {}
        state_lock = threading.Lock()
        total_steps = max(1, n)

        def _dispatch(sub_text: str, sub_pct: float) -> None:
            """把各扫描器的子进度汇总为一条全局进度（按线程名识别来源）。"""
            name = threading.current_thread().name
            idx = 1
            if name.startswith(THREAD_PREFIX):
                try:
                    idx = int(name[len(THREAD_PREFIX):])
                except ValueError:
                    idx = 1
            pct = max(0.0, min(100.0, float(sub_pct)))
            with state_lock:
                # v1.3.0：只向前进。各扫描器的子进度允许回退（例如统计过程中又
                # 发现新目录，进度从 80% 回到 30%），直接覆盖会让总进度条倒退。
                state[idx] = max(state.get(idx, 0.0), pct)
                overall = sum(state.values()) / total_steps
            self.progress(f"[并行 {len(state)}/{len(active)}] {sub_text}", overall)

        ctx.progress = _dispatch

        def _worker(idx: int, scanner: ScannerBase) -> None:
            cur = threading.current_thread()
            old_name = cur.name
            cur.name = f"{THREAD_PREFIX}{idx}"
            try:
                scanner.scan()
            except Exception as e:
                ctx.error(f"{scanner.title} 扫描失败：{e}")
            finally:
                with state_lock:
                    state[idx] = 100.0
                cur.name = old_name

        self.progress("并行扫描启动", 1)
        workers = min(len(active), 8)
        pool = futures.ThreadPoolExecutor(max_workers=workers)
        try:
            futs = [pool.submit(_worker, i, s) for i, s in enumerate(active, 1)]
            # v1.3.0：不能用 `for f in futs: f.result()` 逐个阻塞等待 —— 那样一旦
            # 点了"停止"，仍要等最慢的那个扫描器自然跑完（实测 4×3s 的扫描器要
            # 等满 3s，界面一直卡在"扫描中"）。改为轮询：收到取消立刻丢弃尚未
            # 开始的任务并尽快返回；已在运行的任务各自会因 ctx.stopped() 提前退出。
            pending = set(futs)
            while pending:
                done, pending = futures.wait(
                    pending, timeout=0.2, return_when=futures.FIRST_COMPLETED)
                for f in done:
                    try:
                        f.result()
                    except Exception as e:  # _worker 内部已记录，这里只兜底
                        ctx.error(f"并行扫描异常：{e}")
                if self.cancel.is_set():
                    for f in pending:
                        f.cancel()      # 尚未开始的任务直接丢弃
                    for f in pending:
                        try:
                            f.result(timeout=0)
                        except futures.CancelledError:
                            pass
                        except Exception as e:
                            ctx.error(f"并行扫描异常：{e}")
                    self.log("[扫描] 已取消（并行）")
                    break
        finally:
            # 不等待仍在运行的任务：它们会各自检查 ctx.stopped() 后退出
            pool.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------------- 进度增强
    def _timed_progress(self, text: str, pct: float) -> None:
        """在进度文案上附加已耗时，便于判断"还要等多久"。"""
        elapsed = time.time() - getattr(self, "_t0", time.time())
        self._orig_progress(f"{text}（已用 {elapsed:.0f}s）", pct)

    def _step_progress(self, idx: int, n: int, label: str):
        """返回一个子进度回调：把“步骤内百分比”映射到“全局进度条”并带步骤标签。"""

        def _cb(sub_text: str, sub_pct: float) -> None:
            pct = max(0.0, min(100.0, float(sub_pct)))
            global_value = ((idx - 1) + pct / 100.0) / n * 100
            self.progress(f"[{idx}/{n}] {label}：{sub_text}", global_value)

        return _cb

    def _run_ai_step(self, ctx: ScanContext) -> None:
        """统一执行所有待分析的 AI 候选，并把结论回写到对应扫描项。"""
        if ctx.ai_pf_targets:
            self.log(f"[AI] 提交 {len(ctx.ai_pf_targets)} 个 Program Files 未知目录进行分析...")
            res = ctx.ai.analyze_program_files(ctx.ai_pf_targets)
            self.log(f"[AI] 完成，获得 {len(res)} 条结论")
            from .programfiles import _apply_ai_pf

            for it in ctx.items:
                key = it.extra.get("ai_key") if isinstance(it.extra, dict) else None
                if key and key in ctx.ai_pf_keys:
                    ai = res.get(key)
                    if ai is not None:
                        _apply_ai_pf(it, ai)
        if ctx.ai_ad_targets:
            self.log(f"[AI] 提交 {len(ctx.ai_ad_targets)} 个 AppData 未知目录进行分析...")
            res = ctx.ai.analyze_appdata(ctx.ai_ad_targets)
            self.log(f"[AI] 完成，获得 {len(res)} 条结论")
            from .appdata import _apply_ai_ad

            for it in ctx.items:
                key = it.extra.get("ai_key") if isinstance(it.extra, dict) else None
                if key and key in ctx.ai_ad_keys:
                    ai = res.get(key)
                    if ai is not None:
                        _apply_ai_ad(it, ai)
        ctx.ai.save_cache()
