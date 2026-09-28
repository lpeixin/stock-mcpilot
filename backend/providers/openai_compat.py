"""OpenAI 兼容协议 Provider。

覆盖 LM Studio、OpenAI、DeepSeek、Moonshot、通义（兼容模式）、智谱、SiliconFlow、
vLLM、LocalAI、one-api 等所有实现 ``/v1/chat/completions`` 的服务。
"""

from __future__ import annotations

import json
from typing import Iterator
from urllib.parse import urlparse

import httpx

from .base import ChatMessage, LLMError, LLMProvider, ThinkTagFilter, strip_think

# 这些模型不接受 temperature 参数（OpenAI 的推理系列）。
_NO_TEMPERATURE_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def normalize_base_url(raw: str) -> str:
    """把用户填的各种写法归一成可直接拼 ``/chat/completions`` 的基址。

    处理三种常见输入：
      - ``http://localhost:1234``            → 补 ``/v1``
      - ``https://api.openai.com``           → 补 ``/v1``
      - ``https://x/v1/chat/completions``    → 去掉多余的端点后缀
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    for suffix in ("/chat/completions", "/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
    parsed = urlparse(url)
    if parsed.path in ("", "/"):
        url = f"{url}/v1"
    return url


class OpenAICompatProvider(LLMProvider):
    display_name = "OpenAI 兼容"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return normalize_base_url(self.settings.get("base_url") or "")

    def _endpoint(self, path: str) -> str:
        return f"{self._require_base_url().rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _supports_temperature(self) -> bool:
        model = (self.model or "").lower()
        return not model.startswith(_NO_TEMPERATURE_PREFIXES)

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict:
        payload: dict = {
            "model": self._require_model(),
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        temp = self.settings.get("temperature") if temperature is None else temperature
        if temp is not None and self._supports_temperature():
            payload["temperature"] = float(temp)
        limit = self.settings.get("max_tokens") if max_tokens is None else max_tokens
        if limit:
            # max_tokens 是较通用的字段名；部分新接口只认 max_completion_tokens。
            payload["max_tokens"] = int(limit)
        return payload

    @staticmethod
    def _map_http_error(status: int, body: str) -> LLMError:
        detail = (body or "").strip()[:300]
        if status == 401:
            return LLMError(
                "认证失败（HTTP 401）。请检查 API Key 是否正确、是否已过期。",
                kind="auth",
                status=status,
            )
        if status == 403:
            return LLMError(
                "没有访问权限（HTTP 403）。可能是密钥权限不足，或该模型未开通。",
                kind="auth",
                status=status,
            )
        if status == 404:
            return LLMError(
                f"端点或模型不存在（HTTP 404）。请检查 Base URL 是否包含 /v1，以及模型名是否正确。{detail}",
                kind="not_found",
                status=status,
            )
        if status == 429:
            return LLMError("触发限流或余额不足（HTTP 429），请稍后重试或检查账户额度。", kind="rate_limit", status=status)
        if status >= 500:
            return LLMError(f"服务端错误（HTTP {status}）。{detail}", kind="server", status=status)
        return LLMError(f"服务返回异常状态（HTTP {status}）。{detail}", kind="server", status=status)

    @staticmethod
    def _map_exception(exc: Exception, base_url: str) -> LLMError:
        if isinstance(exc, httpx.ConnectError):
            return LLMError(
                f"无法连接到 {base_url}。请确认服务已启动、地址与端口正确，"
                "本地服务还需确认已开启「允许局域网/本地访问」。",
                kind="connection",
            )
        if isinstance(exc, httpx.TimeoutException):
            return LLMError("请求超时。可在设置页调大超时时间。", kind="timeout")
        if isinstance(exc, httpx.HTTPError):
            return LLMError(f"网络通信失败：{exc}", kind="connection")
        return LLMError(f"调用模型服务时发生意外错误：{exc}", kind="server")

    #: 各后端存放思维链的字段名。LM Studio / vLLM / DeepSeek 用 ``reasoning_content``，
    #: 部分网关用 ``reasoning``，还有的沿用 ``thinking``。
    _REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")

    @classmethod
    def _reasoning_text(cls, payload: dict) -> str:
        """取出思维链文本（message 或 delta 都适用）。没有则返回空串。"""
        for key in cls._REASONING_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @classmethod
    def _explain_empty(
        cls,
        *,
        finish_reason: str | None,
        has_reasoning: bool,
        reasoning_tokens: int | None = None,
        total_tokens: int | None = None,
        limit: int | None = None,
    ) -> LLMError:
        """正文为空时，根据 finish_reason 与 usage 给出**可操作**的诊断。

        关键是分清两种"没有正文"，它们的处置完全相反：

          - ``finish_reason == "length"``：输出被上限截断了，调大上限确实有用；
          - ``finish_reason == "stop"``：模型正常收尾但没写正文，调上限没有用。

        旧实现不看 finish_reason，一律说"请在设置页调大「最大输出长度」"。
        对推理模型这句话经常是**错的**：用户照着提示把上限改到最大也不会好，
        因为真正的原因是"思考吃掉了输出预算"或"这个模型就是不肯写正文"，
        而用户完全无从判断。更糟的情况是这条路径的输出上限根本不是用户设的那个值
        （测试连接的探针就是），提示等于把人引向一个改不动的地方。

        所以这里把 ``limit``、``reasoning_tokens``、``total_tokens`` 一并写进消息 ——
        让用户看到"上限多少、思考花了多少"，而不是只收到一句无法验证的指令。
        """
        facts: list[str] = []
        if isinstance(reasoning_tokens, int) and reasoning_tokens > 0:
            facts.append(f"思考占用 {reasoning_tokens} token")
        if isinstance(total_tokens, int) and total_tokens > 0:
            facts.append(f"共输出 {total_tokens} token")
        facts_text = f"（{'，'.join(facts)}）" if facts else ""
        limit_text = f"（本次输出上限 {limit}）" if limit else ""

        if finish_reason == "length":
            if has_reasoning:
                return LLMError(
                    f"输出在写出正文之前就被截断了{limit_text}{facts_text}。"
                    "推理模型会先用输出预算思考，请把「最大输出长度」调到"
                    "明显大于思考所需的量。",
                    kind="empty",
                )
            return LLMError(
                f"输出被截断{limit_text}{facts_text}，没有产出正文。"
                "请调大「最大输出长度」。",
                kind="empty",
            )

        if has_reasoning:
            return LLMError(
                f"模型完成了思考，但没有输出正文{facts_text}。"
                "输出是正常收尾的，所以**不是**长度问题："
                "可以换一个更明确的提问，或改用非推理模型。",
                kind="empty",
            )

        if finish_reason:
            return LLMError(
                f"模型没有返回任何内容（finish_reason={finish_reason}）。", kind="empty"
            )
        return LLMError("模型没有返回任何内容。", kind="empty")

    @classmethod
    def _extract_content(cls, data: dict, *, limit: int | None = None) -> str:
        """取正文。取不到一定抛错（不会返回空串），错误信息带诊断细节。"""
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("服务返回的响应中没有 choices 字段。", kind="bad_response")

        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            # 少数服务把 content 拆成结构化数组
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if content and str(content).strip():
            return strip_think(str(content))

        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = details.get("reasoning_tokens")
        raise cls._explain_empty(
            finish_reason=choice.get("finish_reason"),
            has_reasoning=bool(cls._reasoning_text(message)),
            reasoning_tokens=reasoning_tokens if isinstance(reasoning_tokens, int) else None,
            total_tokens=usage.get("completion_tokens")
            if isinstance(usage.get("completion_tokens"), int)
            else None,
            limit=limit,
        )

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
        url = self._endpoint("/chat/completions")
        payload = self._build_payload(
            messages, stream=False, temperature=temperature, max_tokens=max_tokens
        )
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc, base) from exc

        if response.status_code != 200:
            raise self._map_http_error(response.status_code, response.text)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("服务返回的不是合法 JSON。", kind="bad_response") from exc

        # 正文为空的情况已经在 _extract_content 里抛出带诊断的错误，
        # 这里不需要再兜一层"没有返回任何内容"。
        return self._extract_content(data, limit=payload.get("max_tokens"))

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        base = self._require_base_url()
        url = self._endpoint("/chat/completions")
        payload = self._build_payload(
            messages, stream=True, temperature=temperature, max_tokens=max_tokens
        )
        think_filter = ThinkTagFilter()
        produced = False
        # 流式下这两样只在"一个字都没产出"时才用得上，用来把报错说准：
        # finish_reason 区分"被截断"和"正常收尾却没写正文"，
        # 是否出现过思维链决定要不要提"推理模型"。
        finish_reason: str | None = None
        saw_reasoning = False

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                    if response.status_code != 200:
                        body = response.read().decode("utf-8", "replace")
                        raise self._map_http_error(response.status_code, body)

                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0] or {}
                        if choice.get("finish_reason"):
                            finish_reason = str(choice["finish_reason"])
                        delta = choice.get("delta") or {}
                        # reasoning_content 是思维链，不展示给用户。
                        if self._reasoning_text(delta):
                            saw_reasoning = True
                        piece = delta.get("content") or ""
                        if isinstance(piece, list):
                            piece = "".join(
                                part.get("text", "") for part in piece if isinstance(part, dict)
                            )
                        if piece:
                            visible = think_filter.feed(str(piece))
                            if visible:
                                produced = True
                                yield visible
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._map_exception(exc, base) from exc

        tail = think_filter.flush()
        if tail:
            produced = True
            yield tail

        if not produced:
            raise self._explain_empty(
                finish_reason=finish_reason,
                has_reasoning=saw_reasoning,
                limit=payload.get("max_tokens"),
            )

    def list_models(self) -> list[str]:
        url = self._endpoint("/models")
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
            raise LLMError("模型列表返回的不是合法 JSON。", kind="bad_response") from exc

        names: list[str] = []
        for item in data.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
        if not names:
            # LM Studio 在未加载模型时会返回空列表，这不算错误。
            return []
        return sorted(set(names))
