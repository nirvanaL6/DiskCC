"""配置管理：JSON 持久化到用户目录。"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List

from .utils.fs import app_data_dir

CONFIG_FILE = "config.json"

DEFAULT_AI_PRESETS: List[Dict[str, str]] = [
    {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"name": "通义千问(兼容模式)", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"name": "月之暗面 Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"name": "本地 Ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b"},
]

DEFAULTS: Dict[str, Any] = {
    # ---- AI ----
    "ai_enabled": False,
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_api_key": "",
    "ai_model": "deepseek-chat",
    "ai_timeout": 60,
    "ai_batch_size": 15,
    "ai_concurrency": 3,
    "ai_cache_days": 30,
    "ai_only_unknown": True,      # 只对规则库无法识别的项调用 AI
    # ---- 扫描 ----
    "min_size_mb": 1.0,           # 小于该大小的项不展示
    "scan_parallel": True,        # 并行执行各扫描器（I/O 密集，明显提速）
    "scan_program_files": True,
    "scan_appdata": True,
    "scan_browsers": True,
    "scan_devtools": True,
    "scan_app_cache": True,
    "scan_windows_update": True,
    "scan_system_junk": True,
    "scan_large_files": False,
    "scan_duplicates": False,
    "scan_empty_dirs": True,
    "scan_bad_shortcuts": True,
    "large_file_mb": 500,
    "idle_days": 90,              # 超过该天数未修改视为"长期未使用"
    "max_depth_appdata": 3,
    # ---- 重复文件（性能保护） ----
    "dup_min_size_mb": 1,         # 小于该大小的文件不参与重复判定
    "dup_max_file_mb": 512,       # 单文件超过该大小直接跳过（全文哈希太慢）
    "dup_budget_mb": 2048,        # 单次扫描哈希总字节预算，超出即停止
    # ---- 清理 ----
    "use_recycle_bin": True,      # 优先送回收站
    "create_backup_list": True,   # 清理前生成备份清单
    "dry_run": False,
    "exclude_paths": [],
    # ---- 界面 ----
    "theme": "dark",
    "window_width": 1180,
    "window_height": 760,
    "show_disclaimer": True,      # 启动时显示免责声明（勾选"不再提示"后关闭）
}

BOOL_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, bool)}
INT_KEYS = {"ai_timeout", "ai_batch_size", "ai_concurrency", "ai_cache_days", "idle_days",
            "max_depth_appdata", "window_width", "window_height"}
FLOAT_KEYS = {"min_size_mb", "large_file_mb"}


class Config:
    """线程安全的配置对象（简易实现）。"""

    def __init__(self, data: Dict[str, Any] | None = None):
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = dict(DEFAULTS)
        if data:
            self._data.update(data)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        path = path or os.path.join(app_data_dir(), CONFIG_FILE)
        data: Dict[str, Any] = {}
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception:
            data = {}
        cfg = cls(data)
        cfg._path = path  # type: ignore[attr-defined]
        return cfg

    def save(self, path: str | None = None) -> str:
        path = path or getattr(self, "_path", None) or os.path.join(app_data_dir(), CONFIG_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        return path

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
            return DEFAULTS.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in BOOL_KEYS:
                value = str(value).lower() in ("1", "true", "yes", "on")
            elif key in INT_KEYS:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = DEFAULTS.get(key, 0)
            elif key in FLOAT_KEYS:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = DEFAULTS.get(key, 0.0)
            self._data[key] = value

    def update(self, mapping: Dict[str, Any]) -> None:
        for k, v in mapping.items():
            self.set(k, v)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    @property
    def file_path(self) -> str:
        return getattr(self, "_path", os.path.join(app_data_dir(), CONFIG_FILE))
