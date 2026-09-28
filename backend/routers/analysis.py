"""AI 分析路由。

三条路径：
  - ``POST /analysis``        一次性返回完整分析
  - ``POST /analysis/stream`` SSE 流式返回（本地模型慢，流式体验差别很大）
  - ``GET  /analysis/context`` 只返回"将要喂给模型的上下文"，供用户核对

改造前的实现只把统计摘要（6 个数字）塞进 prompt，模型看不到价格走势、技术指标、
财报和新闻，因此输出基本是套话。现在上下文由 ``analysis.context`` 装配。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import config
from ..analysis import context as context_builder
from ..providers.base import ChatMessage, LLMError
from ..providers.factory import build_provider
from ..schemas.analysis import (
    AnalysisRequest,
    AnalysisResponse,
    ContextMeta,
    ContextPreviewResponse,
)
from ..schemas.llm import LLMOverride
from ..sse import SSE_HEADERS, llm_sse
from ..storage import cache

router = APIRouter()

#: 与 /llm 路由保持一致的可覆盖字段
_OVERRIDABLE = ("preset", "kind", "base_url", "model", "temperature", "max_tokens", "timeout")


def _resolve_llm_settings(override: LLMOverride | None) -> dict:
    """合并落盘配置与请求级覆盖。密钥掩码回传时沿用已保存的真实值。"""
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

    if "base_url" not in data and data.get("preset"):
        preset_conf = config.PROVIDER_PRESETS.get(str(data["preset"])) or {}
        merged["base_url"] = preset_conf.get("base_url", merged.get("base_url", ""))

    return merged


def _prepare_context(request: AnalysisRequest) -> tuple[dict, list[str], dict]:
    """构建（并裁剪到预算内的）上下文。返回 ``(context, trimmed, analysis_conf)``。"""
    analysis_conf = config.resolve_analysis()
    include = dict(analysis_conf.get("include") or {})
    if request.include:
        include.update({k: bool(v) for k, v in request.include.items()})

    news_limit = request.news_limit
    if news_limit is None:
        news_limit = int(analysis_conf.get("news_limit") or 10)

    frame = cache.get_price_frame_with_indicators(request.symbol, request.market, request.days)

    context = context_builder.build_context(
        request.symbol,
        request.market,
        frame,
        include=include,
        news_limit=news_limit,
    )

    budget = int(analysis_conf.get("max_context_chars") or 32000)
    context, trimmed = context_builder.fit_budget(context, budget)
    return context, trimmed, analysis_conf


def _meta_from(context: dict, trimmed: list[str], prompt: str, budget: int) -> ContextMeta:
    context_text = context_builder.render_context_text(context)
    return ContextMeta(
        included=context.get("included") or [],
        missing=context.get("missing") or [],
        trimmed=trimmed,
        errors=context.get("errors") or {},
        prompt_chars=len(prompt),
        context_chars=len(context_text),
        budget_chars=budget,
        generated_at=context.get("generated_at"),
    )


def _build_messages(request: AnalysisRequest, context: dict, analysis_conf: dict) -> tuple[list[ChatMessage], str]:
    language = request.language or analysis_conf.get("language") or "zh"
    if language not in ("en", "zh"):
        language = "zh"

    system_prompt = config.resolve_llm().get("system_prompt") or context_builder.build_system_prompt(language)

    if request.use_context:
        prompt = context_builder.build_question_prompt(
            context,
            question=request.question,
            language=language,
            focus=request.focus,
        )
    else:
        fallback = request.question or ("请给出你对这只股票的看法。" if language == "zh" else "Share your view.")
        prompt = fallback

    messages = [
        ChatMessage("system", system_prompt),
        ChatMessage("user", prompt),
    ]
    return messages, prompt


# --------------------------------------------------------------------------
# 上下文预览
# --------------------------------------------------------------------------

@router.get("/context", response_model=ContextPreviewResponse)
def preview_context(
    symbol: str = Query(..., min_length=1, max_length=16),
    market: str = Query("US", pattern="^(US|HK|CN)$"),
    days: int = Query(180, ge=20, le=1000),
    news_limit: int | None = Query(None, ge=0, le=30),
) -> ContextPreviewResponse:
    """返回实际会注入模型的上下文文本，供用户核对。"""
    code = symbol.upper().strip()
    request = AnalysisRequest(
        symbol=code, market=market, days=days, news_limit=news_limit, use_context=True
    )
    context, trimmed, analysis_conf = _prepare_context(request)
    messages, prompt = _build_messages(request, context, analysis_conf)
    budget = int(analysis_conf.get("max_context_chars") or 32000)

    return ContextPreviewResponse(
        symbol=code,
        market=market,
        meta=_meta_from(context, trimmed, prompt, budget),
        text=context_builder.render_context_text(context),
        structured={
            "system_prompt": messages[0].content,
            "user_prompt": prompt,
            "sections": sorted((context.get("sections") or {}).keys()),
        },
    )


# --------------------------------------------------------------------------
# 非流式分析
# --------------------------------------------------------------------------

@router.post("", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest = Body(...)) -> AnalysisResponse:
    code = request.symbol.upper().strip()
    request = request.model_copy(update={"symbol": code})

    try:
        provider = build_provider(_resolve_llm_settings(request.override))
    except LLMError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    context: dict = {}
    trimmed: list[str] = []
    meta: ContextMeta | None = None
    analysis_conf = config.resolve_analysis()

    if request.use_context:
        context, trimmed, analysis_conf = _prepare_context(request)

    messages, prompt = _build_messages(request, context, analysis_conf)
    if request.use_context:
        budget = int(analysis_conf.get("max_context_chars") or 32000)
        meta = _meta_from(context, trimmed, prompt, budget)

    started = time.perf_counter()
    try:
        text = provider.chat(messages, temperature=request.temperature, max_tokens=request.max_tokens)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc

    return AnalysisResponse(
        symbol=code,
        market=request.market,
        analysis=text,
        provider=provider.display_name,
        model=provider.model,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        context_meta=meta,
    )


# --------------------------------------------------------------------------
# 流式分析
# --------------------------------------------------------------------------

@router.post("/stream")
def analyze_stream(request: AnalysisRequest = Body(...)) -> StreamingResponse:
    code = request.symbol.upper().strip()
    request = request.model_copy(update={"symbol": code})

    try:
        provider = build_provider(_resolve_llm_settings(request.override))
    except LLMError as exc:
        from ..sse import sse_event

        def _error_only():
            yield sse_event({"type": "error", **exc.to_dict()})

        return StreamingResponse(_error_only(), media_type="text/event-stream", headers=SSE_HEADERS)

    context: dict = {}
    trimmed: list[str] = []
    meta: ContextMeta | None = None
    analysis_conf = config.resolve_analysis()

    if request.use_context:
        try:
            context, trimmed, analysis_conf = _prepare_context(request)
        except Exception as exc:  # noqa: BLE001 - 上下文装配失败仍允许纯问答
            from ..sse import sse_event

            def _context_error():
                yield sse_event(
                    {
                        "type": "error",
                        "kind": "server",
                        "message": f"上下文数据获取失败：{exc}",
                    }
                )

            return StreamingResponse(
                _context_error(), media_type="text/event-stream", headers=SSE_HEADERS
            )

    messages, prompt = _build_messages(request, context, analysis_conf)
    if request.use_context:
        budget = int(analysis_conf.get("max_context_chars") or 32000)
        meta = _meta_from(context, trimmed, prompt, budget)

    return StreamingResponse(
        llm_sse(
            provider,
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            meta={
                "provider": provider.display_name,
                "model": provider.model,
                "symbol": code,
                "market": request.market,
                "context_meta": meta.model_dump() if meta else None,
            },
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
