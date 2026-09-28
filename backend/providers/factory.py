"""根据配置构造具体的 Provider 实例。"""

from __future__ import annotations

from .. import config
from .anthropic import AnthropicProvider
from .base import LLMError, LLMProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compat": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}


def resolve_kind(settings: dict) -> str:
    """确定后端协议类型。

    优先用显式配置的 ``kind``；缺失时回退到预设定义；再不行按 base_url 猜。
    """
    kind = (settings.get("kind") or "").strip()
    if kind in _REGISTRY:
        return kind

    preset = (settings.get("preset") or "").strip()
    preset_kind = (config.PROVIDER_PRESETS.get(preset) or {}).get("kind")
    if preset_kind in _REGISTRY:
        return preset_kind

    base_url = (settings.get("base_url") or "").lower()
    # Anthropic 的地址特征很明确，即使用户把它填在"自定义"里也应该走对协议。
    if "api.anthropic.com" in base_url or "/v1/messages" in base_url:
        return "anthropic"
    if ":11434" in base_url or base_url.endswith("/api"):
        return "ollama"
    return "openai_compat"


def build_provider(settings: dict | None = None) -> LLMProvider:
    """构造 Provider。``settings`` 缺省时读取当前生效配置。"""
    resolved = dict(settings if settings is not None else config.resolve_llm())

    # 未填 base_url 时用预设默认值兜底，避免用户只选了服务商就点分析却报错。
    if not (resolved.get("base_url") or "").strip():
        preset = (resolved.get("preset") or "").strip()
        preset_conf = config.PROVIDER_PRESETS.get(preset) or {}
        resolved["base_url"] = preset_conf.get("base_url", "")

    kind = resolve_kind(resolved)
    provider_cls = _REGISTRY.get(kind)
    if provider_cls is None:  # pragma: no cover - resolve_kind 已保证
        raise LLMError(f"不支持的模型后端类型：{kind}", kind="config")
    return provider_cls(resolved)


__all__ = [
    "build_provider",
    "resolve_kind",
    "AnthropicProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
]
