"""OpenAI 兼容 Chat Completions 客户端（仅依赖标准库 urllib）。

支持：OpenAI / DeepSeek / 通义千问兼容模式 / 智谱 / Kimi / 本地 Ollama 等。
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class AIError(Exception):
    pass


def extract_json(text: str) -> Any:
    """从模型输出中提取 JSON（兼容代码块包裹、前后废话）。"""
    if not text:
        raise AIError("空响应")
    s = text.strip()
    m = _JSON_BLOCK.search(s)
    if m:
        s = m.group(1).strip()
    # 截取第一个 [ 或 { 起到最后一个 ] 或 }
    starts = [p for p in (s.find("["), s.find("{")) if p >= 0]
    if starts:
        start = min(starts)
        end = max(s.rfind("]"), s.rfind("}"))
        if end > start:
            s = s[start:end + 1]
    try:
        return json.loads(s)
    except Exception:
        # 尝试去除尾随逗号
        cleaned = re.sub(r",\s*([}\]])", r"\1", s)
        try:
            return json.loads(cleaned)
        except Exception as e:
            raise AIError(f"JSON 解析失败: {e}; 原文前 200 字: {text[:200]}")


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "deepseek-chat",
        timeout: int = 60,
        temperature: float = 0.1,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 2048,
        json_mode: bool = True,
    ) -> str:
        if not self.configured:
            raise AIError("未配置 AI 接口")
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        # 安全：https 默认严格校验证书（v1.3.1 修复：此前无条件关闭校验，API Key 可被中间人劫持）。
        # 仅明文 http（如本地 Ollama）不传 context。
        if self.endpoint.startswith("http://"):
            ctx = None
        else:
            ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")[:300]
            except Exception:
                pass
            raise AIError(f"HTTP {e.code}: {body}")
        except Exception as e:
            raise AIError(f"请求失败: {e}")
        try:
            obj = json.loads(raw)
        except Exception:
            raise AIError(f"响应不是 JSON: {raw[:200]}")
        try:
            return obj["choices"][0]["message"]["content"] or ""
        except Exception:
            # 兼容部分网关直接返回 content
            if isinstance(obj.get("content"), str):
                return obj["content"]
            raise AIError(f"响应结构异常: {raw[:200]}")

    def test_connection(self) -> Tuple[bool, str]:
        """用一次极小请求验证配置是否可用。"""
        try:
            t0 = time.time()
            content = self.chat(
                [{"role": "user", "content": "回复 ok"}],
                max_tokens=16,
                json_mode=False,
            )
            return True, f"可用（{time.time() - t0:.1f}s）：{content.strip()[:40]}"
        except Exception as e:
            return False, str(e)
