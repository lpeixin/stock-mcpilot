"""LLM 配置相关的请求模型。

``LLMOverride`` 被 ``/llm/*`` 与 ``/analysis/*`` 共用：用户在设置页改了地址/模型
但还没点保存时，可以直接带着覆盖项发起一次分析试跑。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LLMOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str | None = None
    kind: str | None = None
    base_url: str | None = None
    # 传掩码或 __KEEP__ 表示沿用已保存的密钥。
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=16, le=131072)
    timeout: float | None = Field(None, ge=5.0, le=3600.0)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    messages: list[dict] = Field(default_factory=list)
    prompt: str | None = None
    system: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    override: LLMOverride | None = None
