"""LLM 配置探测与通用对话路由。

这里同时支持"测试未保存的配置"：请求体里可以带上 base_url / api_key 等字段覆盖
当前落盘配置，方便用户在设置页填完就点「测试连接」，不必先保存再测。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from .. import config
from ..providers.base import ChatMessage, LLMError
from ..providers.factory import build_provider
from ..schemas.llm import ChatRequest, LLMOverride
from ..sse import SSE_HEADERS, llm_sse, sse_event

router = APIRouter()

#: 允许在请求里覆盖的 LLM 字段
_OVERRIDABLE = ("preset", "kind", "base_url", "model", "temperature", "max_tokens", "timeout")

#: 测试连接时给探针的输出预算下限 / 上限。
#:
#: 这段预算**故意不直接沿用用户设置**，两个方向都有理由：
#:
#:   下限 1024：用户可能为了省钱把「最大输出长度」设成 128 之类的小值。而推理模型
#:     光是"想一想"就能用掉几百 token，探针于是必然拿到空正文。之前这里写死 32，
#:     导致 LM Studio + qwen3.8-27b 这类模型**必然**报"只产出了思维链、没有正文"，
#:     而且提示让用户去调「最大输出长度」—— 那个值在这条路径上根本没被读过，
#:     用户改到最大也不会好。这是纯粹的假失败。
#:
#:   上限 4096：探针只需要几十个 token。有人会把上限设到 131072，直接透传在某些
#:     后端上会撞到模型自身的上下文限制。给探针一个够用又保守的预算即可。
PROBE_MIN_TOKENS = 1024
PROBE_MAX_TOKENS = 4096


def _probe_budget(settings: dict) -> int:
    """给探针算一个够用的输出预算。"""
    try:
        configured = int(settings.get("max_tokens") or 0)
    except (TypeError, ValueError):
        configured = 0
    return max(PROBE_MIN_TOKENS, min(configured, PROBE_MAX_TOKENS))


def _resolve_settings(override: LLMOverride | None) -> dict:
    """把请求里的覆盖项合并到落盘配置上。

    密钥的处理是重点：前端只会拿到掩码，若它把掩码原样回传，必须识别出来并沿用
    已保存的真实密钥，否则用户"只改了模型名"就会把 Key 弄丢。
    """
    base = config.resolve_llm()
    if override is None:
        return base

    merged = dict(base)
    data = override.model_dump(exclude_unset=True, exclude_none=True)

    for field in _OVERRIDABLE:
        value = data.get(field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[field] = value

    incoming_key = data.get("api_key")
    if incoming_key:
        existing = base.get("api_key") or ""
        if incoming_key not in (config.MASK_SENTINEL, config.mask_secret(existing)):
            merged["api_key"] = incoming_key

    # 换了预设但没给 base_url 时，用预设自带的地址。
    if "base_url" not in data and data.get("preset"):
        preset_conf = config.PROVIDER_PRESETS.get(str(data["preset"])) or {}
        merged["base_url"] = preset_conf.get("base_url", merged.get("base_url", ""))

    return merged


@router.get("/presets")
def list_presets() -> dict:
    return {"presets": config.PROVIDER_PRESETS}


@router.post("/models")
def list_models(override: LLMOverride | None = Body(default=None)) -> dict:
    """列出目标后端可用模型。失败时返回 ``ok=false`` 而不是抛错，便于前端展示。"""
    try:
        provider = build_provider(_resolve_settings(override))
        models = provider.list_models()
    except LLMError as exc:
        return {"ok": False, "models": [], **exc.to_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "kind": "server", "message": str(exc)}
    return {
        "ok": True,
        "models": models,
        "kind": None,
        "message": f"发现 {len(models)} 个模型。" if models else "连接成功，但该后端没有返回任何模型。",
    }


@router.post("/test")
def test_connection(
    override: LLMOverride | None = Body(default=None),
    deep: bool = True,
) -> dict:
    """测试连接。

    ``deep=True`` 时会额外发一次极短的生成请求 —— 只列模型不足以证明能推理，
    比如 LM Studio 可能在没加载任何模型时返回空列表。
    """
    settings = _resolve_settings(override)
    try:
        provider = build_provider(settings)
    except LLMError as exc:
        return {"ok": False, "probe": None, "generation": None, **exc.to_dict()}

    probe = provider.probe()
    result: dict = {"ok": probe["ok"], "probe": probe, "generation": None, "kind": probe.get("kind"), "message": probe["message"]}
    if not probe["ok"] or not deep or not settings.get("model"):
        return result

    started = time.perf_counter()
    budget = _probe_budget(settings)
    try:
        text = provider.chat(
            [
                ChatMessage("system", "你是连通性探针，只做一件事：按要求原样输出，不要思考、不要解释。"),
                ChatMessage("user", "只回复两个字：正常"),
            ],
            temperature=0.0,
            max_tokens=budget,
        )
        result["generation"] = {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "sample": text[:200],
        }
        result["message"] = f"连接与推理均正常（{result['generation']['latency_ms']} ms）。"
    except LLMError as exc:
        result["ok"] = False
        result["kind"] = exc.kind
        # 探针用的预算和用户设置里的「最大输出长度」通常不是同一个值。不回传的话，
        # 用户会拿设置里的数字去对报错，越对越糊涂 —— 这正是那个报障的成因。
        # 但有的 provider 报错里已经写了本次上限，那就别重复一遍。
        note = ""
        if exc.kind == "empty" and str(budget) not in exc.message:
            note = f"（探针输出上限 {budget}）"
        result["message"] = f"{exc.message}{note}"
        result["generation"] = {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "sample": None}
    return result


@router.post("/chat")
def chat(request: ChatRequest = Body(...)) -> StreamingResponse:
    """通用流式对话（不注入股票上下文），用于设置页的"试用一下"。"""
    settings = _resolve_settings(request.override)
    try:
        provider = build_provider(settings)
    except LLMError as exc:

        def _err():
            yield sse_event({"type": "error", **exc.to_dict()})

        return StreamingResponse(_err(), media_type="text/event-stream", headers=SSE_HEADERS)

    messages: list[ChatMessage] = []
    if request.system:
        messages.append(ChatMessage("system", request.system))
    for item in request.messages or []:
        role = item.get("role")
        content = item.get("content")
        if role in ("system", "user", "assistant") and isinstance(content, str):
            messages.append(ChatMessage(role, content))
    if request.prompt:
        messages.append(ChatMessage("user", request.prompt))
    if not messages:
        messages.append(ChatMessage("user", "你好"))

    return StreamingResponse(
        llm_sse(
            provider,
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            meta={"provider": provider.display_name, "model": provider.model, "scope": "chat"},
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
