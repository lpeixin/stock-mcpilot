"""配置层：本地持久化 + 环境变量覆盖 + 密钥掩码。

设计目标
--------
1. **持久化**：原实现把配置放在模块级 dict（``providers/base.py`` 的
   ``settings_state``），进程一重启用户填的 API Key 就没了。这里改为落盘到
   ``~/.stock-mcpilot/config.json``。
2. **权限**：目录 0700、文件 0600，与 ``~/.codex/auth.json`` 等 agent 的既有
   惯例一致。密钥只存在本机，不出网。
3. **不泄漏**：明文密钥绝不出现在 API 响应、日志或异常信息里；对外只暴露
   掩码（``sk-1****cdef``）和一个 ``api_key_set`` 布尔位。
4. **环境变量优先**：便于开发与 CI。被环境变量锁定的字段会在 public view 里
   标记 ``locked_by_env``，避免用户改了 UI 却"没生效"却查不出原因。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------

def _config_dir() -> Path:
    override = os.getenv("STOCK_MCPILOT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".stock-mcpilot"


CONFIG_DIR = _config_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"

# 掩码哨兵：前端把当前掩码原样回传时表示"不要改动这个字段"。
MASK_SENTINEL = "__KEEP__"

# --------------------------------------------------------------------------
# Provider 预设
# --------------------------------------------------------------------------
# kind 只有三种，因为绝大多数服务都提供 OpenAI 兼容端点，只有 Anthropic 是例外：
#   - ollama          : Ollama 原生协议（/api/chat、/api/tags）
#   - openai_compat   : OpenAI 兼容协议（/v1/chat/completions、/v1/models）
#   - anthropic       : Anthropic 原生 Messages API（/v1/messages）
# 这样新增一家兼容服务商只需加一行预设，不必写新 Provider 类。
#
# group 决定设置页里的分组与排序：``remote`` 一律排在 ``local`` 之前。
# 前端按 group 显式排序，**不依赖下面字典的书写顺序** —— 顺序会被后来者
# 随手插一行打乱，而分组语义是产品意图，应该显式表达。
GROUP_REMOTE = "remote"
GROUP_LOCAL = "local"

PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    # ---------------------------- 远程服务商 ----------------------------
    "openai": {
        "label": "OpenAI",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
        "default_model": "gpt-4o-mini",
        "hint": "需要 API Key（sk-…），密钥仅保存在本机。",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "group": GROUP_REMOTE,
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "requires_key": True,
        "default_model": "claude-sonnet-5",
        "hint": "使用 Anthropic 原生 Messages API，需要 API Key（sk-ant-…）。"
                "可选 claude-opus-5-5（最强）、claude-sonnet-5（速度与智能兼顾，默认）、"
                "claude-haiku-4-5-20251001（最便宜）。",
    },
    "deepseek": {
        "label": "DeepSeek",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "requires_key": True,
        "default_model": "deepseek-chat",
        "hint": "国内可直连，性价比高。",
    },
    "moonshot": {
        "label": "Moonshot / Kimi",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://api.moonshot.cn/v1",
        "requires_key": True,
        "default_model": "moonshot-v1-8k",
        "hint": "",
    },
    "dashscope": {
        "label": "通义千问 (阿里云)",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "requires_key": True,
        "default_model": "qwen-plus",
        "hint": "使用阿里云百炼的 OpenAI 兼容模式端点。",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "requires_key": True,
        "default_model": "glm-4-flash",
        "hint": "",
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "https://api.siliconflow.cn/v1",
        "requires_key": True,
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "hint": "聚合了多家开源模型。",
    },
    "custom": {
        "label": "自定义 / 自建服务",
        "group": GROUP_REMOTE,
        "kind": "openai_compat",
        "base_url": "http://127.0.0.1:8000/v1",
        "requires_key": False,
        "default_model": "",
        "hint": "任何提供 /v1/chat/completions 的服务，如 vLLM、LocalAI、one-api、"
                "公司内网网关等。若指向 Anthropic 兼容网关，填 /v1/messages 的地址也能自动识别。",
    },
    # ------------------------------ 本地模型 ------------------------------
    "ollama": {
        "label": "Ollama (本地)",
        "group": GROUP_LOCAL,
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "requires_key": False,
        "default_model": "qwen3.5:9b",
        "hint": "本地推理，无需 API Key。需先 `ollama serve` 并 `ollama pull <模型>`。",
    },
    "lmstudio": {
        "label": "LM Studio (本地)",
        "group": GROUP_LOCAL,
        "kind": "openai_compat",
        "base_url": "http://127.0.0.1:1234/v1",
        "requires_key": False,
        "default_model": "",
        "hint": "在 LM Studio 中开启 Local Server（默认 1234 端口），模型名需与其加载的模型一致。",
    },
}

#: 分组展示顺序。新增分组时改这里即可，前端不硬编码。
GROUP_ORDER: tuple[str, ...] = (GROUP_REMOTE, GROUP_LOCAL)

#: 分组标题（前端 i18n 只做兜底，服务端给中文便于接口自解释）。
#: 远程组特意叫"远程 / 自建"而不是"远程服务商"——``custom`` 预设常被用来接
#: vLLM、LocalAI、one-api、公司内网网关，说成"远程"是不准确的。
GROUP_LABELS: dict[str, str] = {
    GROUP_REMOTE: "远程 / 自建服务",
    GROUP_LOCAL: "本地模型",
}

# --------------------------------------------------------------------------
# 默认配置
# --------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "llm": {
        "preset": "ollama",
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "api_key": "",
        "model": "",
        "temperature": 0.3,
        "max_tokens": 2048,
        "timeout": 300,
        "system_prompt": "",
    },
    "analysis": {
        "language": "zh",
        "news_limit": 10,
        "candle_days": 120,
        "max_context_chars": 32000,
        "include": {
            "quote": True,
            "indicators": True,
            "candles": True,
            "financials": True,
            "earnings": True,
            "analyst": True,
            "news": True,
            "profile": True,
        },
    },
    "ui": {
        "language": "zh",
    },
}

_lock = threading.RLock()
_cache: dict[str, Any] | None = None
_cache_mtime: float = -1.0


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def mask_secret(value: str | None) -> str:
    """把密钥转成可安全展示的掩码。短密钥一律全遮蔽。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 4}{value[-4:]}"


def _deep_merge(base: dict, patch: dict) -> dict:
    """递归合并，patch 覆盖 base。dict 类型递归，其余类型直接替换。"""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _atomic_write(path: Path, payload: dict) -> None:
    """原子写入，权限 0600。避免进程中途被杀导致配置文件损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_file() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # 配置损坏时退回默认值而不是让整个服务起不来。
        return {}


def _apply_env_overrides(cfg: dict) -> tuple[dict, set[str]]:
    """把环境变量叠加到配置上，返回 (配置, 被环境变量锁定的字段集合)。

    兼容改造前就存在的变量名（LLM_MODE / LLM_API_KEY / LLM_LOCAL_MODEL /
    OLLAMA_ENDPOINT / APP_LANGUAGE），避免老用户的 .env 突然失效。
    """
    locked: set[str] = set()
    llm = dict(cfg.get("llm", {}))
    analysis = dict(cfg.get("analysis", {}))

    legacy_mode = os.getenv("LLM_MODE")
    legacy_key = os.getenv("LLM_API_KEY")
    legacy_model = os.getenv("LLM_LOCAL_MODEL")
    legacy_endpoint = os.getenv("OLLAMA_ENDPOINT")

    # 新的、更明确的变量名优先。
    env_preset = os.getenv("SMP_LLM_PRESET")
    env_kind = os.getenv("SMP_LLM_KIND")
    env_base = os.getenv("SMP_LLM_BASE_URL")
    env_key = os.getenv("SMP_LLM_API_KEY")
    env_model = os.getenv("SMP_LLM_MODEL")

    if env_preset:
        llm["preset"] = env_preset
        locked.add("llm.preset")
    elif legacy_mode == "cloud" and not env_preset:
        # 旧配置里 cloud 模式指向的是一堆还没实现的东西，这里不强推预设，
        # 只记录用户曾经选过云端，交给前端展示时提示需要重新选择服务商。
        llm["preset"] = llm.get("preset") or "openai"

    if env_kind:
        llm["kind"] = env_kind
        locked.add("llm.kind")
    if env_base:
        llm["base_url"] = env_base
        locked.add("llm.base_url")
    elif legacy_endpoint:
        llm["base_url"] = legacy_endpoint
        locked.add("llm.base_url")

    resolved_key = env_key or legacy_key
    if resolved_key:
        llm["api_key"] = resolved_key
        locked.add("llm.api_key")

    if env_model:
        llm["model"] = env_model
        locked.add("llm.model")
    elif legacy_model:
        llm["model"] = legacy_model
        locked.add("llm.model")

    env_lang = os.getenv("SMP_ANALYSIS_LANGUAGE") or os.getenv("APP_LANGUAGE")
    if env_lang:
        analysis["language"] = env_lang
        locked.add("analysis.language")

    cfg = dict(cfg)
    cfg["llm"] = llm
    cfg["analysis"] = analysis
    return cfg, locked


def load_config(force: bool = False) -> dict:
    """读取生效配置（文件 + 环境变量叠加）。带 mtime 缓存。"""
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            mtime = -1.0
        if not force and _cache is not None and mtime == _cache_mtime:
            return _cache

        merged = _deep_merge(DEFAULT_CONFIG, _read_file())
        merged, _ = _apply_env_overrides(merged)
        _cache = merged
        _cache_mtime = mtime
        return merged


def locked_fields() -> set[str]:
    """返回当前被环境变量锁定的字段路径。"""
    _, locked = _apply_env_overrides(_deep_merge(DEFAULT_CONFIG, _read_file()))
    return locked


def save_config(patch: dict) -> dict:
    """合并写入磁盘。``api_key`` 收到掩码或哨兵时保持原值不变。"""
    global _cache, _cache_mtime
    with _lock:
        current_on_disk = _deep_merge(DEFAULT_CONFIG, _read_file())

        patch = dict(patch or {})
        llm_patch = patch.get("llm")
        if isinstance(llm_patch, dict) and "api_key" in llm_patch:
            llm_patch = dict(llm_patch)
            incoming = llm_patch["api_key"]
            existing = current_on_disk.get("llm", {}).get("api_key", "")
            if incoming is None or incoming == MASK_SENTINEL or (
                existing and incoming == mask_secret(existing)
            ):
                # 前端只是把掩码回显后原样提交，视为"不改动"。
                llm_patch.pop("api_key", None)
            patch["llm"] = llm_patch

        merged = _deep_merge(current_on_disk, patch)
        merged["version"] = DEFAULT_CONFIG["version"]
        _atomic_write(CONFIG_PATH, merged)
        _cache = None
        _cache_mtime = -1.0
        return load_config(force=True)


def public_config() -> dict:
    """对外暴露的配置视图：密钥替换为掩码，并附带元信息。

    这是唯一允许流向 HTTP 响应的配置形态。
    """
    cfg = load_config()
    llm = dict(cfg.get("llm", {}))
    raw_key = llm.get("api_key") or ""
    locked = locked_fields()

    llm_public = {
        "preset": llm.get("preset", "ollama"),
        "kind": llm.get("kind", "ollama"),
        "base_url": llm.get("base_url", ""),
        "api_key": mask_secret(raw_key),
        "api_key_set": bool(raw_key),
        "model": llm.get("model", ""),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": llm.get("max_tokens", 2048),
        "timeout": llm.get("timeout", 300),
        "system_prompt": llm.get("system_prompt", ""),
    }

    analysis = cfg.get("analysis", {})
    ui = cfg.get("ui", {})

    return {
        "llm": llm_public,
        "analysis": analysis,
        "ui": ui,
        "presets": PROVIDER_PRESETS,
        # 分组元信息由服务端下发，前端不硬编码 —— 以后加"企业内网"之类的分组
        # 只需改 config.py 一处。
        "preset_groups": [
            {"key": key, "label": GROUP_LABELS.get(key, key)} for key in GROUP_ORDER
        ],
        "locked_by_env": sorted(locked),
        "config_path": str(CONFIG_PATH),
    }


def resolve_llm() -> dict:
    """返回含明文密钥的生效 LLM 配置。**仅限服务端内部调用**，不得写入响应或日志。"""
    return dict(load_config().get("llm", {}))


def resolve_analysis() -> dict:
    return dict(load_config().get("analysis", {}))
