"""AI 分析器：批量识别 Program Files 归属与 AppData 目录作用，带本地缓存。"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..config import Config
from ..models import Risk, parse_risk
from ..utils.fs import app_data_dir
from .client import AIError, ChatClient, extract_json
from .prompts import build_appdata_prompt, build_program_files_prompt

CACHE_FILE = "ai_cache.json"


@dataclass
class AIAnalysis:
    """AI 对某一项的分析结论。"""

    software: str = ""
    purpose: str = ""
    data_type: str = ""        # 缓存 / 日志 / 配置 / 用户数据 / 组件 ...
    installed: str = ""        # 已安装 / 残留 / 组件 / 未知（Program Files 用）
    deletable: bool = False
    risk: Risk = Risk.MEDIUM
    reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "software": self.software,
            "purpose": self.purpose,
            "data_type": self.data_type,
            "installed": self.installed,
            "deletable": self.deletable,
            "risk": self.risk.value,
            "reason": self.reason,
            "confidence": self.confidence,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AIAnalysis":
        return AIAnalysis(
            software=d.get("software", ""),
            purpose=d.get("purpose", ""),
            data_type=d.get("data_type", ""),
            installed=d.get("installed", ""),
            deletable=bool(d.get("deletable", False)),
            risk=parse_risk(d.get("risk", 2)),
            reason=d.get("reason", ""),
            confidence=float(d.get("confidence", 0) or 0),
        )


class AIAnalyzer:
    """封装 AI 调用、批处理、缓存与失败降级。"""

    def __init__(self, cfg: Config, logger: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self.log = logger or (lambda m: None)
        self.client = ChatClient(
            base_url=cfg.get("ai_base_url"),
            api_key=cfg.get("ai_api_key"),
            model=cfg.get("ai_model"),
            timeout=int(cfg.get("ai_timeout", 60)),
        )
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_dirty = False
        self._lock = threading.Lock()
        self.calls = 0
        self.hits = 0
        self.fails = 0
        self.last_error = ""
        self._load_cache()

    # ------------------------------------------------------------ 缓存
    @property
    def cache_path(self) -> str:
        return os.path.join(app_data_dir(), CACHE_FILE)

    def _load_cache(self) -> None:
        try:
            if os.path.isfile(self.cache_path):
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def save_cache(self) -> None:
        if not self._cache_dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=1)
            self._cache_dirty = False
        except Exception as e:
            self.log(f"[AI] 缓存写入失败: {e}")

    def _cache_get(self, key: str) -> Optional[AIAnalysis]:
        max_days = int(self.cfg.get("ai_cache_days", 30))
        with self._lock:
            rec = self._cache.get(key)
        if not rec:
            return None
        ts = float(rec.get("ts", 0))
        if max_days > 0 and (time.time() - ts) / 86400.0 > max_days:
            return None
        self.hits += 1
        return AIAnalysis.from_dict(rec.get("value", {}))

    def _cache_put(self, key: str, value: AIAnalysis) -> None:
        with self._lock:
            self._cache[key] = {"ts": time.time(), "value": value.to_dict()}
            self._cache_dirty = True

    # ------------------------------------------------------------ 状态
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("ai_enabled")) and self.client.configured

    def status_text(self) -> str:
        if not self.enabled:
            return "AI 未启用（使用内置规则库）"
        return f"AI 已启用 · {self.cfg.get('ai_model')} · 调用 {self.calls} 次 / 缓存命中 {self.hits}"

    # ------------------------------------------------------------ 通用批量
    def _batch_analyze(
        self,
        kind: str,
        features: List[Dict[str, Any]],
        key_of: Callable[[Dict[str, Any]], str],
        prompt_builder: Callable[[List[Dict[str, Any]]], List[Dict[str, str]]],
        parse_item: Callable[[Dict[str, Any], Dict[str, Any]], AIAnalysis],
    ) -> Dict[str, AIAnalysis]:
        """批量分析，返回 {key: AIAnalysis}。"""
        result: Dict[str, AIAnalysis] = {}
        pending: List[Dict[str, Any]] = []
        for feat in features:
            key = f"{kind}:{key_of(feat)}"
            cached = self._cache_get(key) if self.enabled else None
            if cached:
                result[key] = cached
            else:
                feat["_key"] = key
                pending.append(feat)
        if not pending or not self.enabled:
            if pending and not self.enabled:
                self.log(f"[AI] 未启用，{len(pending)} 项使用规则库判断")
            return result

        size = max(1, int(self.cfg.get("ai_batch_size", 15)))
        batches = [pending[i:i + size] for i in range(0, len(pending), size)]
        workers = max(1, min(int(self.cfg.get("ai_concurrency", 3)), len(batches)))

        def run(batch: List[Dict[str, Any]]) -> Dict[str, AIAnalysis]:
            out: Dict[str, AIAnalysis] = {}
            try:
                content = self.client.chat(prompt_builder(batch), max_tokens=2048)
                data = extract_json(content)
                items: List[Dict[str, Any]] = []
                if isinstance(data, dict):
                    items = data.get("results") or []
                elif isinstance(data, list):
                    items = data
                # 先按字段匹配，再按顺序兜底
                by_field: Dict[str, Dict[str, Any]] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    fk = str(it.get("folder", "") or it.get("path", "")).strip().lower()
                    if fk:
                        by_field[fk] = it
                for idx, feat in enumerate(batch):
                    raw = None
                    fk = str(feat.get("folder", "") or feat.get("path", "")).strip().lower()
                    if fk in by_field:
                        raw = by_field[fk]
                    elif idx < len(items) and isinstance(items[idx], dict):
                        raw = items[idx]
                    if raw is None:
                        continue
                    out[feat["_key"]] = parse_item(feat, raw)
            except AIError as e:
                self.fails += 1
                self.last_error = str(e)
                self.log(f"[AI] 请求失败: {e}")
            except Exception as e:  # pragma: no cover
                self.fails += 1
                self.last_error = str(e)
                self.log(f"[AI] 解析失败: {e}")
            return out

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run, b) for b in batches]
            for fu in as_completed(futures):
                try:
                    got = fu.result()
                except Exception as e:
                    self.log(f"[AI] 线程异常: {e}")
                    continue
                for k, v in got.items():
                    result[k] = v
                    self._cache_put(k, v)
                self.calls += 1
        return result

    # ------------------------------------------------------------ Program Files
    def analyze_program_files(self, features: List[Dict[str, Any]]) -> Dict[str, AIAnalysis]:
        def key_of(f: Dict[str, Any]) -> str:
            return str(f.get("folder", "")).lower()

        def parse_item(feat: Dict[str, Any], raw: Dict[str, Any]) -> AIAnalysis:
            return AIAnalysis(
                software=str(raw.get("software", "") or "").strip(),
                purpose=str(raw.get("purpose", "") or "").strip(),
                installed=str(raw.get("installed", "") or "").strip(),
                data_type=str(raw.get("installed", "") or "").strip(),
                deletable=bool(raw.get("deletable", False)),
                risk=parse_risk(raw.get("risk", "high"), Risk.HIGH),
                reason=str(raw.get("reason", "") or "").strip(),
                confidence=float(raw.get("confidence", 0) or 0),
            )

        return self._batch_analyze("pf", features, key_of, build_program_files_prompt, parse_item)

    # ------------------------------------------------------------ AppData
    def analyze_appdata(self, features: List[Dict[str, Any]]) -> Dict[str, AIAnalysis]:
        def key_of(f: Dict[str, Any]) -> str:
            return str(f.get("path", "")).lower().replace("\\", "/")

        def parse_item(feat: Dict[str, Any], raw: Dict[str, Any]) -> AIAnalysis:
            return AIAnalysis(
                software=str(raw.get("software", "") or "").strip(),
                purpose=str(raw.get("purpose", "") or "").strip(),
                data_type=str(raw.get("data_type", "") or "").strip(),
                deletable=bool(raw.get("deletable", False)),
                risk=parse_risk(raw.get("risk", "medium"), Risk.MEDIUM),
                reason=str(raw.get("reason", "") or "").strip(),
                confidence=float(raw.get("confidence", 0) or 0),
            )

        return self._batch_analyze("ad", features, key_of, build_appdata_prompt, parse_item)

    # ------------------------------------------------------------ 连接测试
    def test(self) -> Any:
        return self.client.test_connection()
