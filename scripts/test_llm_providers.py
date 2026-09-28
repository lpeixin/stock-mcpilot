"""LLM Provider 的离线单测：Anthropic 协议实现 + 预设路由。

为什么要起一个**真实 socket** 的假服务，而不是 monkeypatch ``httpx``：
provider 里最容易写错的是 URL 拼接、鉴权头、请求体结构、SSE 分帧这几件事。
把 httpx mock 掉就等于把待测的东西一起 mock 了 —— 那些 bug 一个都测不出来。
这里用 ``ThreadingHTTPServer`` 收真实请求，断言的是"服务端实际收到了什么"。

不联网、不需要 API Key。
跑法::

    .venv/bin/python scripts/test_llm_providers.py
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402
from backend.providers.anthropic import (  # noqa: E402
    API_VERSION,
    DEFAULT_MAX_TOKENS,
    AnthropicProvider,
    normalize_base_url,
)
from backend.providers.base import ChatMessage, LLMError  # noqa: E402
from backend.providers.factory import build_provider, resolve_kind  # noqa: E402
from backend.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from backend.routers.llm import (  # noqa: E402
    PROBE_MAX_TOKENS,
    PROBE_MIN_TOKENS,
    _probe_budget,
)


# --------------------------------------------------------------------------
# 假 Anthropic 服务
# --------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # 别把访问日志打到测试输出里
        pass

    def _serve(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw.decode("utf-8", "replace")

        record = {
            "method": method,
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": body,
        }
        self.server.records.append(record)  # type: ignore[attr-defined]
        status, ctype, payload = self.server.responder(record)  # type: ignore[attr-defined]

        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        # 固定长度：SSE 也一次性发完，省掉 chunked 编码的复杂度。
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._serve("GET")


class FakeAnthropic:
    """可编程的假服务。``responder(record) -> (status, content_type, body)``。"""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.records: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.responder = responder  # type: ignore[attr-defined]
        self._server.records = self.records  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeAnthropic:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def json_response(payload: dict, status: int = 200) -> tuple[int, str, str]:
    return status, "application/json", json.dumps(payload)


def text_message(*texts: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": t} for t in texts],
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def provider_for(base_url: str, **overrides) -> AnthropicProvider:
    settings = {
        "preset": "anthropic",
        "kind": "anthropic",
        "base_url": base_url,
        "api_key": "sk-ant-test-key",
        "model": "claude-sonnet-5",
        "temperature": 0.3,
        "max_tokens": 2048,
        "timeout": 20,
    }
    settings.update(overrides)
    return AnthropicProvider(settings)


def openai_provider_for(base_url: str, **overrides) -> OpenAICompatProvider:
    """OpenAI 兼容协议的实例（LM Studio / vLLM / OpenAI 都走这条）。

    刻意不复用上面那个 helper：两者的协议、错误文案、字段名都不一样，
    拿错一个会让测试"通过"在一个完全无关的实现上。
    """
    settings = {
        "preset": "lmstudio",
        "kind": "openai_compat",
        "base_url": base_url,
        "api_key": "",
        "model": "qwen/qwen3.8-27b",
        "temperature": 0.3,
        "max_tokens": 2048,
        "timeout": 20,
    }
    settings.update(overrides)
    return OpenAICompatProvider(settings)


USER = [ChatMessage("user", "分析一下 AAPL")]


# --------------------------------------------------------------------------
# 纯函数
# --------------------------------------------------------------------------

class TestBaseUrlNormalize(unittest.TestCase):
    def test_normalizes_common_forms(self) -> None:
        cases = {
            "https://api.anthropic.com": "https://api.anthropic.com/v1",
            "https://api.anthropic.com/": "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1": "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1/messages": "https://api.anthropic.com/v1",
            "https://api.anthropic.com/v1/models": "https://api.anthropic.com/v1",
            "https://gw.example.com/anthropic": "https://gw.example.com/anthropic/v1",
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_base_url(raw), expected)


class TestSplitSystem(unittest.TestCase):
    def test_system_is_lifted_out_and_consecutive_roles_merged(self) -> None:
        system, turns = AnthropicProvider._split_system([
            ChatMessage("system", "你是分析师"),
            ChatMessage("system", "回答用中文"),
            ChatMessage("user", "第一问"),
            ChatMessage("user", "补充"),
            ChatMessage("assistant", "好"),
            ChatMessage("user", "继续"),
        ])
        self.assertEqual(system, "你是分析师\n\n回答用中文")
        self.assertEqual([t["role"] for t in turns], ["user", "assistant", "user"])
        # 连续同角色被合并，而不是原样发出去被 400 拒掉
        self.assertEqual(turns[0]["content"], "第一问\n\n补充")

    def test_blank_messages_are_dropped(self) -> None:
        _, turns = AnthropicProvider._split_system([
            ChatMessage("user", "  "),
            ChatMessage("user", "正文"),
        ])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["content"], "正文")


class TestRouting(unittest.TestCase):
    def test_anthropic_is_resolved_from_preset_url_and_kind(self) -> None:
        cases = [
            {"preset": "anthropic"},
            {"kind": "anthropic"},
            {"base_url": "https://api.anthropic.com"},
            {"base_url": "https://api.anthropic.com/v1/messages"},
            {"base_url": "https://api.anthropic.com/v1"},  # 末尾 /v1 也要认出来
        ]
        for settings in cases:
            with self.subTest(settings=settings):
                self.assertEqual(resolve_kind(settings), "anthropic")

    def test_other_kinds_unchanged(self) -> None:
        self.assertEqual(resolve_kind({"base_url": "http://127.0.0.1:11434"}), "ollama")
        self.assertEqual(resolve_kind({"base_url": "https://api.openai.com/v1"}), "openai_compat")

    def test_factory_builds_anthropic_provider(self) -> None:
        provider = build_provider({
            "preset": "anthropic",
            "kind": "anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-5",
        })
        self.assertIsInstance(provider, AnthropicProvider)
        self.assertEqual(provider.display_name, "Anthropic Claude")

    def test_presets_are_grouped_remote_first(self) -> None:
        groups = [item["group"] for item in config.PROVIDER_PRESETS.values()]
        self.assertIn("remote", groups)
        self.assertIn("local", groups)
        # 所有 local 必须排在所有 remote 之后 —— 这正是需求里点名的那一条
        last_remote = max(i for i, g in enumerate(groups) if g == "remote")
        first_local = min(i for i, g in enumerate(groups) if g == "local")
        self.assertLess(last_remote, first_local, f"分组顺序不对：{groups}")

    def test_anthropic_preset_shape(self) -> None:
        preset = config.PROVIDER_PRESETS["anthropic"]
        self.assertEqual(preset["group"], "remote")
        self.assertEqual(preset["kind"], "anthropic")
        self.assertTrue(preset["requires_key"])
        self.assertTrue(preset["default_model"])
        # 声明了默认模型就必须能被 Anthropic provider 直接使用
        self.assertEqual(normalize_base_url(preset["base_url"]), "https://api.anthropic.com/v1")

    def test_group_order_and_labels_are_exposed(self) -> None:
        public = config.public_config()
        self.assertEqual([g["key"] for g in public["preset_groups"]], list(config.GROUP_ORDER))
        for group in public["preset_groups"]:
            self.assertTrue(group["label"])


# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------

class TestChat(unittest.TestCase):
    def test_happy_path_request_shape_and_text_extraction(self) -> None:
        captured: dict = {}

        def responder(record):
            captured.update(record)
            return json_response(text_message("第一段。", "第二段。"))

        with FakeAnthropic(responder) as fake:
            provider = provider_for(fake.base_url)
            result = provider.chat([
                ChatMessage("system", "你是分析师"),
                ChatMessage("user", "分析 AAPL"),
            ])

        self.assertEqual(result, "第一段。第二段。")
        # 端点、鉴权头、版本头
        self.assertEqual(captured["path"], "/v1/messages")
        self.assertEqual(captured["headers"]["anthropic-version"], API_VERSION)
        self.assertEqual(captured["headers"]["authorization"], "Bearer sk-ant-test-key")
        self.assertNotIn("x-api-key", captured["headers"])
        # system 必须在顶层，不能留在 messages 里
        body = captured["body"]
        self.assertEqual(body["system"], "你是分析师")
        self.assertEqual([m["role"] for m in body["messages"]], ["user"])
        self.assertEqual(body["max_tokens"], 2048)
        self.assertFalse(body["stream"])
        self.assertAlmostEqual(body["temperature"], 0.3)

    def test_thinking_blocks_are_not_treated_as_text(self) -> None:
        payload = {
            "id": "msg_x", "type": "message", "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "让我想想……", "signature": "sig"},
                {"type": "text", "text": "结论：观望。"},
            ],
            "stop_reason": "end_turn",
        }
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            result = provider_for(fake.base_url).chat(USER)
        self.assertEqual(result, "结论：观望。")

    def test_401_falls_back_to_legacy_x_api_key_header(self) -> None:
        calls: list[dict] = []

        def responder(record):
            calls.append(record)
            if len(calls) == 1:
                return json_response(
                    {"type": "error", "error": {"type": "authentication_error", "message": "invalid key"}},
                    status=401,
                )
            return json_response(text_message("回退成功"))

        with FakeAnthropic(responder) as fake:
            result = provider_for(fake.base_url).chat(USER)

        self.assertEqual(result, "回退成功")
        self.assertEqual(len(calls), 2, "应当在 401 后重试一次")
        self.assertIn("authorization", calls[0]["headers"])
        self.assertIn("x-api-key", calls[1]["headers"])
        self.assertEqual(calls[1]["headers"]["x-api-key"], "sk-ant-test-key")

    def test_401_twice_raises_auth_error(self) -> None:
        def responder(record):
            return json_response(
                {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
                status=401,
            )

        with FakeAnthropic(responder) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "auth")
        self.assertIn("401", ctx.exception.message)

    def test_no_api_key_sends_no_auth_header(self) -> None:
        captured: dict = {}

        def responder(record):
            captured.update(record)
            return json_response(text_message("ok"))

        with FakeAnthropic(responder) as fake:
            provider_for(fake.base_url, api_key="").chat(USER)
        self.assertNotIn("authorization", captured["headers"])
        self.assertNotIn("x-api-key", captured["headers"])
        # 版本头无论如何都要有
        self.assertEqual(captured["headers"]["anthropic-version"], API_VERSION)

    def test_max_tokens_defaults_when_unset(self) -> None:
        captured: dict = {}

        def responder(record):
            captured.update(record)
            return json_response(text_message("ok"))

        with FakeAnthropic(responder) as fake:
            # max_tokens 缺省 -> Anthropic 会 400，所以必须由 provider 兜底
            provider_for(fake.base_url, max_tokens=None).chat(USER)
        self.assertEqual(captured["body"]["max_tokens"], DEFAULT_MAX_TOKENS)

    def test_400_surfaces_api_message_and_request_id(self) -> None:
        def responder(record):
            return json_response(
                {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "anthropic-workspace-id is required when authenticating with an identity-linked API key",
                    },
                    "request_id": "req_011CSHoEeqs5C35K2UUqR7Fy",
                },
                status=400,
            )

        with FakeAnthropic(responder) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "config")
        # 原文比任何猜测都有用：workspace-id 这种原因猜不出来
        self.assertIn("anthropic-workspace-id", ctx.exception.message)
        self.assertIn("req_011CSHoEeqs5C35K2UUqR7Fy", ctx.exception.message)

    def test_404_is_not_found(self) -> None:
        def responder(record):
            return json_response(
                {"type": "error", "error": {"type": "not_found_error", "message": "model: claude-nope"}},
                status=404,
            )

        with FakeAnthropic(responder) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "not_found")
        self.assertIn("claude-nope", ctx.exception.message)

    def test_thinking_only_response_explains_max_tokens(self) -> None:
        payload = {
            "id": "msg_x", "type": "message", "role": "assistant",
            "content": [{"type": "thinking", "thinking": "很长很长的思考"}],
            "stop_reason": "max_tokens",
        }
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("最大输出长度", ctx.exception.message)

    def test_empty_content_with_max_tokens_stop_reason(self) -> None:
        payload = {"id": "m", "type": "message", "content": [], "stop_reason": "max_tokens"}
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("max_tokens", ctx.exception.message)

    def test_refusal_is_reported_as_such(self) -> None:
        payload = {"id": "m", "type": "message", "content": [], "stop_reason": "refusal"}
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("拒绝", ctx.exception.message)

    def test_missing_user_message_raises_config_error(self) -> None:
        with self.assertRaises(LLMError) as ctx:
            provider_for("http://127.0.0.1:1").chat([ChatMessage("system", "只有系统提示")])
        self.assertEqual(ctx.exception.kind, "config")

    def test_missing_model_raises_config_error(self) -> None:
        with self.assertRaises(LLMError) as ctx:
            provider_for("http://127.0.0.1:1", model="").chat(USER)
        self.assertEqual(ctx.exception.kind, "config")

    def test_connection_error_classification(self) -> None:
        """直接测映射函数，不走网络。

        为什么不发一个真请求到死端口：开发沙箱里 ``HTTP_PROXY`` 会把
        "connection refused" 变成一个 **502 响应**，于是走的是 HTTP 状态码分支、
        报出 ``kind="server"``。那样测的是代理的行为，不是 provider 的分类逻辑。
        """
        cases = [
            (httpx.ConnectError("refused"), "connection"),
            (httpx.ReadTimeout("too slow"), "timeout"),
            (httpx.ConnectTimeout("timeout"), "timeout"),
            (httpx.RemoteProtocolError("boom"), "connection"),
            (ValueError("something else"), "server"),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                mapped = AnthropicProvider._map_exception(exc, "https://api.anthropic.com/v1")
                self.assertEqual(mapped.kind, expected)

    def test_proxy_gateway_5xx_mentions_proxy(self) -> None:
        """502/503/504 常见于中间代理够不到上游，提示要指向代理而不是 Anthropic。"""
        for status in (502, 503, 504):
            with self.subTest(status=status):
                mapped = AnthropicProvider._map_http_error(status, "upstream connect failed")
                self.assertEqual(mapped.kind, "server")
                self.assertIn("代理", mapped.message)

    def test_plain_500_does_not_blame_proxy(self) -> None:
        mapped = AnthropicProvider._map_http_error(500, "internal error")
        self.assertNotIn("代理", mapped.message)


# --------------------------------------------------------------------------
# stream
# --------------------------------------------------------------------------

def sse(*events: tuple[str, dict]) -> str:
    """把 (event_name, payload) 拼成 Anthropic 的 named-event SSE 报文。"""
    out = []
    for name, payload in events:
        out.append(f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n")
    return "".join(out)


STREAM_OK = sse(
    ("message_start", {"type": "message_start", "message": {"id": "msg_1", "content": []}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "thinking", "thinking": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "thinking_delta", "thinking": "先看均线"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1,
                             "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
                             "delta": {"type": "text_delta", "text": "Hello"}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1,
                             "delta": {"type": "text_delta", "text": " 世界"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta",
                       "delta": {"stop_reason": "end_turn"},
                       "usage": {"output_tokens": 12}}),
    ("message_stop", {"type": "message_stop"}),
)


class TestStream(unittest.TestCase):
    def test_deltas_are_incremental_and_thinking_is_skipped(self) -> None:
        captured: dict = {}

        def responder(record):
            captured.update(record)
            return 200, "text/event-stream", STREAM_OK

        with FakeAnthropic(responder) as fake:
            pieces = list(provider_for(fake.base_url).stream(USER))

        # Anthropic 的增量是真增量，不是累积快照 —— 拼接即全文
        self.assertEqual(pieces, ["Hello", " 世界"])
        self.assertEqual("".join(pieces), "Hello 世界")
        self.assertNotIn("先看均线", "".join(pieces))
        self.assertTrue(captured["body"]["stream"])

    def test_error_event_mid_stream_raises(self) -> None:
        body = sse(
            ("message_start", {"type": "message_start", "message": {"id": "m"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": "开始"}}),
            ("error", {"type": "error",
                       "error": {"type": "overloaded_error", "message": "Overloaded"},
                       "request_id": "req_abc"}),
        )
        with FakeAnthropic(lambda r: (200, "text/event-stream", body)) as fake:
            stream = provider_for(fake.base_url).stream(USER)
            # 前半段应当已经产出，然后才抛错
            self.assertEqual(next(stream), "开始")
            with self.assertRaises(LLMError) as ctx:
                next(stream)
        self.assertIn("Overloaded", ctx.exception.message)
        self.assertIn("req_abc", ctx.exception.message)

    def test_stream_with_only_thinking_explains_max_tokens(self) -> None:
        body = sse(
            ("message_start", {"type": "message_start", "message": {"id": "m"}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "thinking", "thinking": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "thinking_delta", "thinking": "想了很久"}}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}}),
            ("message_stop", {"type": "message_stop"}),
        )
        with FakeAnthropic(lambda r: (200, "text/event-stream", body)) as fake:
            with self.assertRaises(LLMError) as ctx:
                list(provider_for(fake.base_url).stream(USER))
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("最大输出长度", ctx.exception.message)

    def test_stream_http_error_is_mapped(self) -> None:
        def responder(record):
            return json_response(
                {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
                status=429,
            )

        with FakeAnthropic(responder) as fake:
            with self.assertRaises(LLMError) as ctx:
                list(provider_for(fake.base_url).stream(USER))
        self.assertEqual(ctx.exception.kind, "rate_limit")


# --------------------------------------------------------------------------
# list_models
# --------------------------------------------------------------------------

class TestListModels(unittest.TestCase):
    def test_returns_sorted_unique_ids(self) -> None:
        captured: dict = {}

        def responder(record):
            captured.update(record)
            return json_response({
                "data": [{"id": "claude-sonnet-5"}, {"id": "claude-haiku-4-5-20251001"},
                         {"id": "claude-sonnet-5"}],
                "has_more": False,
            })

        with FakeAnthropic(responder) as fake:
            models = provider_for(fake.base_url).list_models()

        self.assertEqual(models, ["claude-haiku-4-5-20251001", "claude-sonnet-5"])
        self.assertTrue(captured["path"].startswith("/v1/models"), captured["path"])
        self.assertIn("limit=100", captured["path"])
        self.assertEqual(captured["headers"]["anthropic-version"], API_VERSION)

    def test_follows_pagination(self) -> None:
        pages = [
            ({"data": [{"id": "a"}], "has_more": True, "last_id": "a"}),
            ({"data": [{"id": "b"}], "has_more": True, "last_id": "b"}),
            ({"data": [{"id": "c"}], "has_more": False}),
        ]
        seen: list[str] = []

        def responder(record):
            seen.append(record["path"])
            return json_response(pages[min(len(seen) - 1, len(pages) - 1)])

        with FakeAnthropic(responder) as fake:
            models = provider_for(fake.base_url).list_models()

        self.assertEqual(models, ["a", "b", "c"])
        self.assertEqual(len(seen), 3)
        self.assertIn("after_id=a", seen[1])
        self.assertIn("after_id=b", seen[2])

    def test_probe_reports_model_ready(self) -> None:
        def responder(record):
            return json_response({"data": [{"id": "claude-sonnet-5"}], "has_more": False})

        with FakeAnthropic(responder) as fake:
            probe = provider_for(fake.base_url).probe()
        self.assertTrue(probe["ok"])
        self.assertTrue(probe["model_ready"])
        self.assertEqual(probe["models"], ["claude-sonnet-5"])

    def test_probe_surfaces_auth_failure(self) -> None:
        def responder(record):
            return json_response(
                {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}},
                status=401,
            )

        with FakeAnthropic(responder) as fake:
            probe = provider_for(fake.base_url).probe()
        self.assertFalse(probe["ok"])
        self.assertEqual(probe["kind"], "auth")

    def test_api_key_never_appears_in_error_messages(self) -> None:
        secret = "sk-ant-super-secret-value"

        def responder(record):
            return json_response(
                {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}},
                status=400,
            )

        with FakeAnthropic(responder) as fake:
            with self.assertRaises(LLMError) as ctx:
                provider_for(fake.base_url, api_key=secret).chat(USER)
        self.assertNotIn(secret, ctx.exception.message)


# --------------------------------------------------------------------------
# 推理模型"只有思维链"的诊断
#
# 这一组锁的是一个真实报障：LM Studio + qwen/qwen3.8-27b，用户把「最大输出长度」
# 调到 131072 仍报"模型只产出了思维链、没有正文，请调大最大输出长度"。
# 真因是**测试连接的探针把 max_tokens 写死成 32**，用户设的值在这条路径上
# 根本没被读过 —— 提示让人去改一个改不动的地方。
# --------------------------------------------------------------------------

def lmstudio_reasoning_response(
    *,
    content: str = "\n\n",
    reasoning: str = "用户要求只回复两个字：“正常”。\n我需要严格遵守这个指令。\n",
    finish: str = "length",
    reasoning_tokens: int = 31,
    completion_tokens: int = 31,
) -> dict:
    """LM Studio 对推理模型的真实响应形状（2026-09 实测）。"""
    return {
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                    "tool_calls": [],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 68,
            "completion_tokens": completion_tokens,
            "total_tokens": 68 + completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


class TestReasoningModelDiagnostics(unittest.TestCase):
    def test_truncated_reasoning_reports_token_numbers_and_limit(self) -> None:
        """被截断时，必须告诉用户"上限是多少、思考花了多少"，而不是只让他去改设置。"""
        payload = lmstudio_reasoning_response(finish="length")
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                openai_provider_for(fake.base_url).chat(USER, max_tokens=32)

        message = ctx.exception.message
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("截断", message)
        # 本次实际用的上限
        self.assertIn("32", message)
        # 思考消耗的 token 数 —— 这是用户判断"该调到多大"的唯一依据
        self.assertIn("31", message)

    def test_normal_stop_with_reasoning_does_not_blame_length(self) -> None:
        """正常收尾却没正文，是另一回事：调长度没有用，不能给这个建议。"""
        payload = lmstudio_reasoning_response(content="", finish="stop")
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                openai_provider_for(fake.base_url).chat(USER)

        message = ctx.exception.message
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("不是", message)
        self.assertNotIn("请调大「最大输出长度」", message)

    def test_whitespace_only_content_counts_as_empty(self) -> None:
        """content 只有换行也算没有正文 —— 但要走诊断分支，不是静默返回空白。"""
        payload = lmstudio_reasoning_response(content="\n\n", finish="length")
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                openai_provider_for(fake.base_url).chat(USER, max_tokens=32)
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("截断", ctx.exception.message)

    def test_plain_truncation_without_reasoning(self) -> None:
        payload = {
            "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": ""}}],
            "usage": {"completion_tokens": 512},
        }
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                openai_provider_for(fake.base_url).chat(USER, max_tokens=512)
        self.assertIn("截断", ctx.exception.message)
        self.assertIn("512", ctx.exception.message)
        # 没有思维链就不该提"推理模型"
        self.assertNotIn("推理模型", ctx.exception.message)

    def test_reasoning_field_name_variants(self) -> None:
        """不同网关的字段名不一样，都要认出来。"""
        for key in ("reasoning_content", "reasoning", "thinking"):
            with self.subTest(field=key):
                payload = lmstudio_reasoning_response(finish="stop")
                payload["choices"][0]["message"].pop("reasoning_content")
                payload["choices"][0]["message"][key] = "想了很久"
                with FakeAnthropic(lambda r: json_response(payload)) as fake:
                    with self.assertRaises(LLMError) as ctx:
                        openai_provider_for(fake.base_url).chat(USER)
                # 认出来了 -> 走"完成了思考但没写正文"这一支
                self.assertIn("思考", ctx.exception.message)

    def test_truly_empty_response_still_reports_finish_reason(self) -> None:
        payload = {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
        with FakeAnthropic(lambda r: json_response(payload)) as fake:
            with self.assertRaises(LLMError) as ctx:
                openai_provider_for(fake.base_url).chat(USER)
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("content_filter", ctx.exception.message)

    def test_stream_reasoning_only_reports_finish_reason(self) -> None:
        """流式下同样要说准：这次只产出了思维链。"""
        body = "".join(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"先想想"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":""},"finish_reason":"length"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )
        with FakeAnthropic(lambda r: (200, "text/event-stream", body)) as fake:
            with self.assertRaises(LLMError) as ctx:
                list(openai_provider_for(fake.base_url).stream(USER, max_tokens=32))
        self.assertEqual(ctx.exception.kind, "empty")
        self.assertIn("截断", ctx.exception.message)
        self.assertIn("32", ctx.exception.message)

    def test_stream_success_unaffected(self) -> None:
        """别把正常路径改坏了。"""
        body = "".join(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"想一下"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"正常"}}]}\n\n',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                "data: [DONE]\n\n",
            ]
        )
        with FakeAnthropic(lambda r: (200, "text/event-stream", body)) as fake:
            pieces = list(openai_provider_for(fake.base_url).stream(USER))
        self.assertEqual("".join(pieces), "正常")


class TestProbeBudget(unittest.TestCase):
    """测试连接的输出预算。

    不能沿用用户设置：设小了推理模型必然假失败（就是那个报障），
    设到 131072 又可能撞上模型自身的上下文限制。
    """

    def test_clamped_between_floor_and_ceiling(self) -> None:
        cases = {
            0: PROBE_MIN_TOKENS,
            None: PROBE_MIN_TOKENS,
            32: PROBE_MIN_TOKENS,
            256: PROBE_MIN_TOKENS,
            PROBE_MIN_TOKENS: PROBE_MIN_TOKENS,
            2048: 2048,
            PROBE_MAX_TOKENS: PROBE_MAX_TOKENS,
            8192: PROBE_MAX_TOKENS,
            131072: PROBE_MAX_TOKENS,
        }
        for configured, expected in cases.items():
            with self.subTest(configured=configured):
                self.assertEqual(_probe_budget({"max_tokens": configured}), expected)

    def test_garbage_values_fall_back_to_floor(self) -> None:
        for bad in ("abc", {}, [], -5):
            with self.subTest(value=bad):
                self.assertEqual(_probe_budget({"max_tokens": bad}), PROBE_MIN_TOKENS)

    def test_floor_is_large_enough_for_a_reasoning_model(self) -> None:
        """实测：qwen3.8-27b 回答"正常"要用掉 31 个思考 token。

        下限必须远大于这个量级，否则报障会重现。
        """
        self.assertGreaterEqual(PROBE_MIN_TOKENS, 512)

    def test_ceiling_is_conservative(self) -> None:
        """探针只要几十个 token，上限不该跟用户的大值一起膨胀。"""
        self.assertLessEqual(PROBE_MAX_TOKENS, 8192)


if __name__ == "__main__":
    print("LLM Provider 离线单测（Anthropic 协议 + 预设路由）")
    print("=" * 64)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    print("=" * 64)
    passed = outcome.testsRun - len(outcome.failures) - len(outcome.errors)
    print(f"通过 {passed}  失败 {len(outcome.failures)}  错误 {len(outcome.errors)}")
    sys.exit(0 if outcome.wasSuccessful() else 1)
