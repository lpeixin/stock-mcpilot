"""LLM Provider 抽象层。

这里定义三种能力（对话 / 流式对话 / 列出模型）和一个统一的错误类型。具体实现见
``ollama.py``（Ollama 原生协议）与 ``openai_compat.py``（OpenAI 兼容协议）。

改造要点
--------
原实现的 ``CloudProvider`` 是个 mock，返回 ``"[CLOUD MODEL] 模拟调用完成"``；而
``LocalProvider`` 只读 Ollama 响应的 ``message.content``，遇到推理模型
（qwen3、deepseek-r1 之类）会因为内容都在 ``message.thinking`` 里而拿到空串，
最终回退成占位文本。也就是说旧版本的 AI 分析在真机上是坏的。这里一并修掉。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


# --------------------------------------------------------------------------
# 错误
# --------------------------------------------------------------------------

ErrorKind = Literal[
    "config",       # 配置不完整，比如没填 base_url
    "connection",   # 连不上（服务没启动、端口不对、被墙）
    "auth",         # 401/403，密钥错或没权限
    "not_found",    # 404，模型不存在或端点路径不对
    "timeout",      # 超时
    "rate_limit",   # 429
    "server",       # 5xx
    "bad_response", # 返回体不是预期结构
    "empty",        # 调用成功但模型没吐出内容
]


class LLMError(Exception):
    """带机器可读 kind 的 LLM 调用错误。

    ``message`` 必须是**可以直接展示给用户**的中文说明，且绝不能包含 API Key。
    """

    def __init__(self, message: str, *, kind: ErrorKind = "server", status: int | None = None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status = status

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "status": self.status}


# --------------------------------------------------------------------------
# 文本后处理
# --------------------------------------------------------------------------

_THINK_BLOCK_RE = re.compile(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think(?:ing)?>", re.IGNORECASE)
_FINAL_ANSWER_RE = re.compile(r"^\s*Final Answer:\s*", re.IGNORECASE)

THINK_TAGS: tuple[tuple[str, str], ...] = ((" thinking", "<｜end▁of▁thinking｜>"), ("<thinking>", "</thinking>"))


def strip_think(text: str) -> str:
    """剥掉推理模型的思维链标签。未闭合的块按截断处理。"""
    if not text:
        return text
    text = _THINK_BLOCK_RE.sub("", text)
    open_match = _THINK_OPEN_RE.search(text)
    if open_match:
        text = text[: open_match.start()]
    text = _FINAL_ANSWER_RE.sub("", text)
    return text.strip()


class ThinkTagFilter:
    """流式场景下剥离 `` thinking...<｜end▁of▁thinking｜>``。

    必须跨 chunk 保持状态，因为标签可能被切在两次 yield 之间
    （比如前一个 chunk 以 ``"<thi"`` 结尾）。这里用一个小的状态机处理。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._max_open = max(len(o) for o, _ in THINK_TAGS)
        self._max_close = max(len(c) for _, c in THINK_TAGS)

    def feed(self, text: str) -> str:
        if not text:
            return ""
        self._buf += text
        out: list[str] = []

        while self._buf:
            lowered = self._buf.lower()
            if not self._inside:
                found = None
                for opener, _ in THINK_TAGS:
                    idx = lowered.find(opener)
                    if idx != -1 and (found is None or idx < found[0]):
                        found = (idx, opener)
                if found is None:
                    # 没有开标签：吐出去，但留下可能是半个标签的尾巴。
                    keep = self._max_open - 1
                    if len(self._buf) <= keep:
                        break
                    out.append(self._buf[:-keep])
                    self._buf = self._buf[-keep:]
                    break
                idx, opener = found
                out.append(self._buf[:idx])
                self._buf = self._buf[idx + len(opener):]
                self._inside = True
            else:
                found = None
                for _, closer in THINK_TAGS:
                    idx = lowered.find(closer)
                    if idx != -1 and (found is None or idx < found[0]):
                        found = (idx, closer)
                if found is None:
                    # 思维链内容整段丢弃，只留可能是半个闭标签的尾巴。
                    keep = self._max_close - 1
                    self._buf = self._buf[-keep:] if len(self._buf) > keep else self._buf
                    break
                idx, closer = found
                self._buf = self._buf[idx + len(closer):]
                self._inside = False

        return "".join(out)

    def flush(self) -> str:
        """流结束时调用。未闭合的思维链内容一律丢弃。"""
        if self._inside:
            self._buf = ""
            self._inside = False
            return ""
        rest, self._buf = self._buf, ""
        return rest


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------

class LLMProvider(ABC):
    """所有 LLM 后端的统一接口。"""

    #: 供 UI 展示的后端名称
    display_name: str = "LLM"

    def __init__(self, settings: dict):
        self.settings = settings or {}

    # -- 配置读取 ---------------------------------------------------------
    @property
    def base_url(self) -> str:
        return (self.settings.get("base_url") or "").strip()

    @property
    def api_key(self) -> str:
        return (self.settings.get("api_key") or "").strip()

    @property
    def model(self) -> str:
        return (self.settings.get("model") or "").strip()

    @property
    def timeout(self) -> float:
        try:
            value = float(self.settings.get("timeout") or 300)
        except (TypeError, ValueError):
            value = 300.0
        return max(5.0, value)

    def _require_model(self) -> str:
        if not self.model:
            raise LLMError(
                "尚未选择模型。请到设置页拉取模型列表或手动填写模型名称。",
                kind="config",
            )
        return self.model

    def _require_base_url(self) -> str:
        if not self.base_url:
            raise LLMError("尚未填写服务地址（Base URL）。", kind="config")
        return self.base_url

    # -- 能力 -------------------------------------------------------------
    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """一次性返回完整回复。"""

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """逐块返回回复增量。"""

    @abstractmethod
    def list_models(self) -> list[str]:
        """列出该后端可用的模型名。"""

    # -- 便捷方法 ---------------------------------------------------------
    def probe(self) -> dict:
        """连通性 + 配置有效性检查，供设置页的"测试连接"按钮使用。"""
        import time

        started = time.perf_counter()
        try:
            models = self.list_models()
        except LLMError as exc:
            return {
                "ok": False,
                "kind": exc.kind,
                "message": exc.message,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "models": [],
                "model_ready": False,
            }
        except Exception as exc:  # pragma: no cover - 兜底
            return {
                "ok": False,
                "kind": "server",
                "message": f"连接失败：{exc}",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "models": [],
                "model_ready": False,
            }

        latency = int((time.perf_counter() - started) * 1000)
        model_ready = bool(self.model and self.model in models) if models else bool(self.model)
        note = None
        if not self.model:
            note = "连接成功，但尚未选择模型。"
        elif models and self.model not in models:
            note = f"连接成功，但模型「{self.model}」不在可用列表中。"

        return {
            "ok": True,
            "kind": None,
            "message": note or f"连接成功，发现 {len(models)} 个模型。",
            "latency_ms": latency,
            "models": models,
            "model_ready": model_ready,
        }
