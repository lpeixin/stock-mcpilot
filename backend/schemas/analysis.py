"""AI 分析相关的请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMOverride


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    market: str = "US"
    question: str | None = None
    days: int = Field(180, ge=20, le=1000)
    language: str | None = Field(None, pattern="^(en|zh)$")

    #: 分析侧重：technical / fundamental / news / valuation / risk
    focus: list[str] | None = None

    #: 逐项开关上下文段落；缺省用配置里的默认值
    include: dict[str, bool] | None = None
    news_limit: int | None = Field(None, ge=0, le=30)

    #: 关掉则只把用户问题发给模型（不注入行情上下文）
    use_context: bool = True

    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=16, le=131072)
    override: LLMOverride | None = None


class ContextMeta(BaseModel):
    """本次实际注入了什么 —— 让"喂给模型的内容"可核对。"""

    included: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    trimmed: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    prompt_chars: int = 0
    context_chars: int = 0
    budget_chars: int = 0
    generated_at: str | None = None


class AnalysisResponse(BaseModel):
    symbol: str
    market: str
    analysis: str
    provider: str | None = None
    model: str | None = None
    elapsed_ms: int | None = None
    context_meta: ContextMeta | None = None


class ContextPreviewResponse(BaseModel):
    symbol: str
    market: str
    meta: ContextMeta
    text: str
    structured: dict
