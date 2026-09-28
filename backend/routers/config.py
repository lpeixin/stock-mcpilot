"""配置读写路由。

挂载两次：``/config``（新）与 ``/settings``（兼容旧前端）。两者路径都不带尾斜杠，
避免 FastAPI 默认的 307 重定向 —— 旧实现里 ``/settings`` 会 307 到 ``/settings/``，
POST 时依赖客户端跟随重定向，属于隐患。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .. import config

router = APIRouter()


class LLMConfigPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preset: str | None = None
    kind: str | None = None
    base_url: str | None = None
    # 传空串表示清空；传掩码或 __KEEP__ 表示保持原值不变。
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, ge=16, le=131072)
    timeout: float | None = Field(None, ge=5.0, le=3600.0)
    system_prompt: str | None = None


class AnalysisConfigPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    language: str | None = Field(None, pattern="^(en|zh)$")
    news_limit: int | None = Field(None, ge=0, le=30)
    candle_days: int | None = Field(None, ge=20, le=500)
    max_context_chars: int | None = Field(None, ge=2000, le=200000)
    include: dict[str, bool] | None = None


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    llm: LLMConfigPatch | None = None
    analysis: AnalysisConfigPatch | None = None
    ui: dict[str, Any] | None = None


@router.get("")
def read_config() -> dict:
    """返回生效配置。密钥一律以掩码形式返回，明文永不离开本机。"""
    return config.public_config()


@router.post("")
def write_config(patch: ConfigPatch = Body(...)) -> dict:
    dumped = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not dumped:
        return config.public_config()
    try:
        config.save_config(dumped)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败：{exc}") from exc
    return config.public_config()
