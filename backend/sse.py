"""Server-Sent Events 工具。

本地模型推理慢（9B 模型在消费级机器上首字可能要几秒），一次性返回会让界面长时间
空白。这里把 Provider 的流式输出包装成 SSE，让前端能边生成边渲染。
"""

from __future__ import annotations

import json
import time
from typing import Iterator

from .providers.base import ChatMessage, LLMError, LLMProvider

#: 关闭中间层缓冲，否则 Nginx / 某些代理会把整个流攒完再吐出来。
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def llm_sse(
    provider: LLMProvider,
    messages: list[ChatMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    meta: dict | None = None,
) -> Iterator[str]:
    """把 ``provider.stream`` 包装成 SSE 事件流。

    事件类型：
      - ``meta``  流开始，携带后端与模型信息
      - ``delta`` 正文增量
      - ``error`` 错误（含 kind 与可直接展示的 message）
      - ``done``  正常结束，携带耗时
    """
    started = time.perf_counter()
    if meta:
        yield sse_event({"type": "meta", **meta})

    try:
        for chunk in provider.stream(messages, temperature=temperature, max_tokens=max_tokens):
            yield sse_event({"type": "delta", "text": chunk})
    except LLMError as exc:
        yield sse_event({"type": "error", **exc.to_dict()})
        return
    except Exception as exc:  # noqa: BLE001 - 流一旦开始就只能通过事件报错
        yield sse_event({"type": "error", "kind": "server", "message": f"生成过程中断：{exc}"})
        return

    yield sse_event({"type": "done", "elapsed_ms": int((time.perf_counter() - started) * 1000)})
