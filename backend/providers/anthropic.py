"""Anthropic Claude 原生 Messages API Provider（``POST /v1/messages``）。

为什么不能复用 ``OpenAICompatProvider``
--------------------------------------
Anthropic 的 Messages API 不是 OpenAI 兼容协议，有四处结构性差异，靠改 base_url
是绕不过去的：

1. **鉴权头不同**。官方当前推荐 ``Authorization: Bearer <key>``；
   ``x-api-key: <key>`` 是仍在支持但已标注为 legacy 的旧写法。两种都试，
   因为自建的 Anthropic 兼容网关（one-api 等）往往只认后者。
2. **``system`` 是顶层字段**，不是一条 ``role="system"`` 的消息。传进 messages
   会被直接拒掉。
3. **``max_tokens`` 必填**。缺了就是 400，不像 OpenAI 那样可以省略。
4. **响应结构不同**。正文在 ``content`` 数组里按块组织（``text`` / ``thinking`` /
   ``redacted_thinking`` / ``tool_use`` …），流式事件的类型名与增量语义也都不一样。

第 4 点尤其容易写错：Anthropic 的流式增量是**真增量**（``" Hello"``、``" my"``），
不是 OpenAI 那种累积快照，所以不能像有些实现那样"取最后一条 delta 当全文"。
"""

from __future__ import annotations

import json
from typing import Iterator
from urllib.parse import urlparse

import httpx

from .base import ChatMessage, LLMError, LLMProvider, Role

#: Messages API 目前只有一个版本号，且必须显式发送。
API_VERSION = "2023-06-01"

#: 缺省输出上限。Anthropic 要求 max_tokens 必填，这里是最后的兜底。
DEFAULT_MAX_TOKENS = 4096

#: 模型列表分页拉取的页数上限，防止 has_more 异常时死循环。
_MAX_MODEL_PAGES = 5


def normalize_base_url(raw: str) -> str:
    """把用户填的地址归一成可直接拼 ``/messages`` 的基址。

    与 OpenAI 兼容那套不同，这里**只要路径末尾不是 /v1 就补上**，因为 Anthropic
    的 ``/v1`` 是协议里写死的（端点就是 ``POST /v1/messages``），没有"省略 /v1"
    这种写法。所以：

      - ``https://api.anthropic.com``              → 补 ``/v1``
      - ``https://api.anthropic.com/v1``           → 原样
      - ``https://api.anthropic.com/v1/messages``  → 去掉端点后缀
      - ``https://gw.example.com/anthropic``       → 补 ``/v1``
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    for suffix in ("/messages", "/models", "/complete"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    if not urlparse(url).path.rstrip("/").endswith("/v1"):
        url = f"{url}/v1"
    return url


class AnthropicProvider(LLMProvider):
    display_name = "Anthropic Claude"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return normalize_base_url(self.settings.get("base_url") or "")

    def _endpoint(self, path: str) -> str:
        return f"{self._require_base_url().rstrip('/')}{path}"

    def _headers(self, *, use_legacy_auth: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": API_VERSION,
        }
        if self.api_key:
            if use_legacy_auth:
                headers["x-api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _max_tokens(self, override: int | None) -> int:
        limit = self.settings.get("max_tokens") if override is None else override
        try:
            value = int(limit) if limit else 0
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else DEFAULT_MAX_TOKENS

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        """抽出 system 文本，并把剩余消息整理成 Anthropic 接受的形式。

        Anthropic 要求 messages 里只有 user / assistant 两种角色，且**同一角色不能
        连续出现**。合并连续同角色消息比直接报错友好，而且不改变语义。
        """
        system_parts: list[str] = []
        turns: list[dict] = []

        for message in messages:
            content = (message.content or "").strip()
            if not content:
                continue
            if message.role == "system":
                system_parts.append(content)
                continue
            role: Role = message.role
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] = f"{turns[-1]['content']}\n\n{content}"
            else:
                turns.append({"role": role, "content": content})

        return "\n\n".join(system_parts), turns

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        system, turns = self._split_system(messages)
        if not turns:
            raise LLMError("没有可发送的对话内容（缺少 user 消息）。", kind="config")

        payload: dict = {
            "model": self._require_model(),
            "max_tokens": self._max_tokens(max_tokens),
            "messages": turns,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        temp = self.settings.get("temperature") if temperature is None else temperature
        if temp is not None:
            payload["temperature"] = float(temp)
        return payload

    @staticmethod
    def _error_detail(body: str) -> tuple[str, str | None]:
        """从 Anthropic 的错误体里取出人话消息与 request_id。

        形如 ``{"type":"error","error":{"type":"invalid_request_error",
        "message":"..."},"request_id":"req_..."}``。拿不到就退回原始文本。
        """
        try:
            data = json.loads(body or "")
        except json.JSONDecodeError:
            return (body or "").strip()[:300], None
        if not isinstance(data, dict):
            return (body or "").strip()[:300], None
        error = data.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        request_id = data.get("request_id")
        return (str(message or "").strip()[:300] or (body or "").strip()[:300], request_id)

    @classmethod
    def _map_http_error(cls, status: int, body: str) -> LLMError:
        detail, request_id = cls._error_detail(body)
        suffix = f"（request_id: {request_id}）" if request_id else ""
        if status == 400:
            # 400 最常见的原因是 max_tokens 缺失/超限、messages 角色不合法、
            # 或多工作区密钥缺 anthropic-workspace-id。原文比任何猜测都有用。
            return LLMError(f"请求被拒绝（HTTP 400）：{detail}{suffix}", kind="config", status=status)
        if status == 401:
            return LLMError(
                f"认证失败（HTTP 401）。请检查 API Key 是否正确、是否已过期或已被禁用。{suffix}",
                kind="auth",
                status=status,
            )
        if status == 403:
            return LLMError(
                f"没有访问权限（HTTP 403）。可能是密钥权限不足或该模型未开通。{detail}{suffix}",
                kind="auth",
                status=status,
            )
        if status == 404:
            return LLMError(
                f"模型或端点不存在（HTTP 404）。请检查模型名是否为当前可用的 Claude 模型。{detail}{suffix}",
                kind="not_found",
                status=status,
            )
        if status == 413:
            return LLMError(
                "请求体过大（HTTP 413）。请在设置页调小「上下文预算」或「K 线天数」。",
                kind="config",
                status=status,
            )
        if status == 429:
            return LLMError(
                f"触发限流或余额不足（HTTP 429），请稍后重试或检查账户额度。{detail}{suffix}",
                kind="rate_limit",
                status=status,
            )
        if status >= 500:
            # 502/503/504 常常不是 Anthropic 挂了，而是中间代理够不到上游。
            # 配了代理的用户如果只看到"服务端错误"会去查错方向。
            proxy_note = ""
            if status in (502, 503, 504):
                proxy_note = "若配置了 HTTP(S) 代理，请确认代理能访问目标地址。"
            return LLMError(
                f"Anthropic 服务端错误（HTTP {status}）。{proxy_note}{detail}{suffix}",
                kind="server",
                status=status,
            )
        return LLMError(f"服务返回异常状态（HTTP {status}）。{detail}{suffix}", kind="server", status=status)

    @staticmethod
    def _map_exception(exc: Exception, base_url: str) -> LLMError:
        if isinstance(exc, httpx.ConnectError):
            return LLMError(
                f"无法连接到 {base_url}。请确认地址与端口正确、网络可达"
                "（部分地区访问 api.anthropic.com 需要代理）。",
                kind="connection",
            )
        if isinstance(exc, httpx.TimeoutException):
            return LLMError("请求超时。Claude 长文本推理较慢，可在设置页调大超时时间。", kind="timeout")
        if isinstance(exc, httpx.HTTPError):
            return LLMError(f"网络通信失败：{exc}", kind="connection")
        return LLMError(f"调用 Anthropic 时发生意外错误：{exc}", kind="server")

    @staticmethod
    def _extract_text(data: dict) -> str:
        """把 content 数组里的 text 块拼起来。

        刻意**不**对正文做 ``strip_think``：Anthropic 的思维链是结构上独立的
        ``thinking`` 块，不走正文；对正文跑标签剥离反而可能误伤合法内容。
        """
        blocks = data.get("content") or []
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "".join(parts).strip()

    @classmethod
    def _explain_empty(cls, data: dict) -> LLMError:
        """正文为空时给出尽量具体的解释，而不是一句"没返回内容"。"""
        blocks = data.get("content") or []
        kinds = {b.get("type") for b in blocks if isinstance(b, dict)}
        stop_reason = data.get("stop_reason")
        if "thinking" in kinds or "redacted_thinking" in kinds:
            return LLMError(
                "模型只产出了思维链、没有正文。请调大「最大输出长度」"
                "（Anthropic 会把思考 token 也算进 max_tokens）。",
                kind="empty",
            )
        if stop_reason == "max_tokens":
            return LLMError(
                "输出在正文产出前就被 max_tokens 截断。请在设置页调大「最大输出长度」。",
                kind="empty",
            )
        if stop_reason == "refusal":
            return LLMError("模型拒绝回答该请求。可调整提问方式后重试。", kind="empty")
        return LLMError("模型没有返回任何正文内容。", kind="empty")

    # ------------------------------------------------------------------
    # 能力实现
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        base = self._require_base_url()
        url = self._endpoint("/messages")
        payload = self._build_payload(
            messages, stream=False, temperature=temperature, max_tokens=max_tokens
        )

        # 新式 Bearer 优先；401 时回退到 legacy 的 x-api-key，兼容自建网关。
        response: httpx.Response | None = None
        for legacy in (False, True):
            if legacy and not self.api_key:
                break
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload, headers=self._headers(use_legacy_auth=legacy))
            except Exception as exc:  # noqa: BLE001 - 统一映射
                raise self._map_exception(exc, base) from exc
            if response.status_code == 401 and not legacy:
                continue
            break

        assert response is not None  # 循环至少执行一次
        if response.status_code != 200:
            raise self._map_http_error(response.status_code, response.text)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("Anthropic 返回的不是合法 JSON。", kind="bad_response") from exc

        content = self._extract_text(data)
        if content:
            return content
        raise self._explain_empty(data)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        base = self._require_base_url()
        url = self._endpoint("/messages")
        payload = self._build_payload(
            messages, stream=True, temperature=temperature, max_tokens=max_tokens
        )

        produced = False
        stop_reason: str | None = None
        saw_thinking = False

        for legacy in (False, True):
            if legacy and not self.api_key:
                break
            produced = False
            stop_reason = None
            saw_thinking = False
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream(
                        "POST", url, json=payload, headers=self._headers(use_legacy_auth=legacy)
                    ) as response:
                        if response.status_code != 200:
                            body = response.read().decode("utf-8", "replace")
                            if response.status_code == 401 and not legacy:
                                continue
                            raise self._map_http_error(response.status_code, body)

                        for line in response.iter_lines():
                            if not line:
                                continue
                            # Anthropic 用的是 named event（`event: xxx` 行），
                            # 但 data 载荷自带 type 字段，只解析 data 行就够了。
                            if line.startswith("event:"):
                                continue
                            if line.startswith("data:"):
                                line = line[5:].strip()
                            if not line:
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(chunk, dict):
                                continue

                            kind = chunk.get("type")
                            if kind == "content_block_delta":
                                delta = chunk.get("delta") or {}
                                delta_type = delta.get("type")
                                if delta_type == "text_delta":
                                    piece = delta.get("text") or ""
                                    if piece:
                                        produced = True
                                        yield piece
                                elif delta_type == "thinking_delta":
                                    # 思维链不展示给用户，仅记下它出现过，
                                    # 以便正文为空时给出可诊断的报错。
                                    saw_thinking = True
                            elif kind == "content_block_start":
                                block = chunk.get("content_block") or {}
                                if block.get("type") in ("thinking", "redacted_thinking"):
                                    saw_thinking = True
                            elif kind == "message_delta":
                                stop_reason = (chunk.get("delta") or {}).get("stop_reason") or stop_reason
                            elif kind == "error":
                                detail, request_id = self._error_detail(json.dumps(chunk))
                                suffix = f"（request_id: {request_id}）" if request_id else ""
                                raise LLMError(f"流式响应中途出错：{detail}{suffix}", kind="server")
                            elif kind == "message_stop":
                                break
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._map_exception(exc, base) from exc

            if produced:
                return

        if not produced:
            raise self._explain_empty(
                {"content": ([{"type": "thinking"}] if saw_thinking else []), "stop_reason": stop_reason}
            )

    def list_models(self) -> list[str]:
        base = self._require_base_url()
        names: list[str] = []
        after: str | None = None

        for _ in range(_MAX_MODEL_PAGES):
            params = {"limit": 100}
            if after:
                params["after_id"] = after
            for legacy in (False, True):
                if legacy and not self.api_key:
                    break
                try:
                    with httpx.Client(timeout=min(self.timeout, 15.0)) as client:
                        response = client.get(
                            self._endpoint("/models"),
                            params=params,
                            headers=self._headers(use_legacy_auth=legacy),
                        )
                except Exception as exc:  # noqa: BLE001
                    raise self._map_exception(exc, base) from exc
                if response.status_code == 401 and not legacy:
                    continue
                break

            if response.status_code != 200:
                raise self._map_http_error(response.status_code, response.text)
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise LLMError("Anthropic 模型列表返回的不是合法 JSON。", kind="bad_response") from exc

            for item in data.get("data") or []:
                if isinstance(item, dict) and item.get("id"):
                    names.append(str(item["id"]))

            if not data.get("has_more"):
                break
            after = data.get("last_id")
            if not after:
                break

        return sorted(set(names))
