"""Ollama 原生协议 Provider（``/api/chat``、``/api/tags``）。"""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from .base import ChatMessage, LLMError, LLMProvider, ThinkTagFilter, strip_think


class OllamaProvider(LLMProvider):
    display_name = "Ollama"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _endpoint(self, path: str) -> str:
        return f"{self._require_base_url().rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # Ollama 本身不校验密钥，但放在反向代理后面时可能需要。
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _options(self, temperature: float | None, max_tokens: int | None) -> dict:
        options: dict = {}
        temp = self.settings.get("temperature") if temperature is None else temperature
        if temp is not None:
            options["temperature"] = float(temp)
        limit = self.settings.get("max_tokens") if max_tokens is None else max_tokens
        if limit:
            # 推理模型会把思维链也算进 num_predict，这里留足余量，
            # 否则会出现"思考完了但正文被截断"的空回复。
            options["num_predict"] = int(limit) * 3
        return options

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
        disable_think: bool,
    ) -> dict:
        payload: dict = {
            "model": self._require_model(),
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
            "options": self._options(temperature, max_tokens),
        }
        if disable_think:
            payload["think"] = False
        return payload

    @staticmethod
    def _map_http_error(status: int, body: str) -> LLMError:
        detail = (body or "").strip()[:300]
        if status == 404:
            return LLMError(
                f"模型不存在或端点路径有误（HTTP 404）。{detail}",
                kind="not_found",
                status=status,
            )
        if status in (401, 403):
            return LLMError(
                f"认证失败（HTTP {status}）。若 Ollama 部署在反向代理后，请检查 API Key。",
                kind="auth",
                status=status,
            )
        if status == 429:
            return LLMError("请求过于频繁（HTTP 429），请稍后重试。", kind="rate_limit", status=status)
        if status >= 500:
            return LLMError(f"Ollama 服务内部错误（HTTP {status}）。{detail}", kind="server", status=status)
        return LLMError(f"Ollama 返回异常状态（HTTP {status}）。{detail}", kind="server", status=status)

    @staticmethod
    def _map_exception(exc: Exception, base_url: str) -> LLMError:
        if isinstance(exc, httpx.ConnectError):
            return LLMError(
                f"无法连接到 Ollama（{base_url}）。请确认已运行 `ollama serve`，且地址与端口正确。",
                kind="connection",
            )
        if isinstance(exc, httpx.TimeoutException):
            return LLMError(
                "Ollama 响应超时。模型首次加载或推理较慢时可能需要更长时间，可在设置页调大超时。",
                kind="timeout",
            )
        if isinstance(exc, httpx.HTTPError):
            return LLMError(f"与 Ollama 通信失败：{exc}", kind="connection")
        return LLMError(f"调用 Ollama 时发生意外错误：{exc}", kind="server")

    @staticmethod
    def _extract_content(data: dict) -> str:
        message = data.get("message") or {}
        content = message.get("content") or data.get("response") or ""
        if content and content.strip():
            return strip_think(content)
        # 内容为空但存在思维链 —— 说明 max_tokens 被思考过程吃光了。
        if message.get("thinking"):
            reason = data.get("done_reason")
            hint = "（输出长度被截断）" if reason == "length" else ""
            raise LLMError(
                f"模型只产出了思维链、没有正文{hint}。这是一个推理模型，"
                "请在设置页调大「最大输出长度」，或更换非推理模型。",
                kind="empty",
            )
        return ""

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
        url = self._endpoint("/api/chat")

        for disable_think in (True, False):
            payload = self._build_payload(
                messages,
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens,
                disable_think=disable_think,
            )
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, json=payload, headers=self._headers())
            except Exception as exc:  # noqa: BLE001 - 统一映射
                raise self._map_exception(exc, base) from exc

            if response.status_code == 200:
                try:
                    data = response.json()
                except json.JSONDecodeError as exc:
                    raise LLMError("Ollama 返回的不是合法 JSON。", kind="bad_response") from exc
                content = self._extract_content(data)
                if content:
                    return content
                raise LLMError("模型没有返回任何内容。", kind="empty")

            # 老版本 Ollama 不认 `think` 参数，会返回 400；去掉后重试一次。
            if disable_think and response.status_code == 400 and "think" in (response.text or "").lower():
                continue
            raise self._map_http_error(response.status_code, response.text)

        raise LLMError("Ollama 调用失败。", kind="server")

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        base = self._require_base_url()
        url = self._endpoint("/api/chat")
        think_filter = ThinkTagFilter()
        produced = False

        for disable_think in (True, False):
            payload = self._build_payload(
                messages,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
                disable_think=disable_think,
            )
            produced = False
            think_filter = ThinkTagFilter()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                        if response.status_code != 200:
                            body = response.read().decode("utf-8", "replace")
                            if disable_think and response.status_code == 400 and "think" in body.lower():
                                continue
                            raise self._map_http_error(response.status_code, body)

                        for line in response.iter_lines():
                            if not line:
                                continue
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            message = chunk.get("message") or {}
                            piece = message.get("content") or ""
                            if piece:
                                visible = think_filter.feed(piece)
                                if visible:
                                    produced = True
                                    yield visible
                            if chunk.get("done"):
                                tail = think_filter.flush()
                                if tail:
                                    produced = True
                                    yield tail
                                break
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._map_exception(exc, base) from exc

            if produced:
                return
            # 没有产出任何正文：可能是老版本不支持 think 参数，去掉重试。
            if disable_think:
                continue
            break

        if not produced:
            raise LLMError(
                "模型没有产出任何正文内容。若使用的是推理模型，请调大「最大输出长度」。",
                kind="empty",
            )

    def list_models(self) -> list[str]:
        url = self._endpoint("/api/tags")
        try:
            with httpx.Client(timeout=min(self.timeout, 15.0)) as client:
                response = client.get(url, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc, self.base_url) from exc

        if response.status_code != 200:
            raise self._map_http_error(response.status_code, response.text)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("Ollama 模型列表返回的不是合法 JSON。", kind="bad_response") from exc

        names: list[str] = []
        for item in data.get("models") or []:
            name = item.get("name") or item.get("model")
            if name:
                names.append(str(name))
        return sorted(set(names))
