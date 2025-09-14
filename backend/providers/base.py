import os
from abc import ABC, abstractmethod
import json
from typing import Optional

import httpx

settings_state = {
    "mode": os.getenv("LLM_MODE", "local"),
    "api_key": os.getenv("LLM_API_KEY"),
    "local_model": os.getenv("LLM_LOCAL_MODEL", "llama3"),
    "language": os.getenv("APP_LANGUAGE", "en"),  # 'en' or 'zh'
}

class BaseProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:  # pragma: no cover - simple stub
        ...

class LocalProvider(BaseProvider):
    def _ollama_endpoint(self) -> str:
        return os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")

    def _postprocess(self, text: str) -> str:
        if not text:
            return text
        # Remove common reasoning/thinking tags emitted by some models (e.g., deepseek-r1)
        import re
        # Strip <think>...</think> blocks
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        # Strip XML-ish thinking blocks
        text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
        # Remove leading 'Final Answer:' if present
        text = re.sub(r"^\s*Final Answer:\s*", "", text, flags=re.IGNORECASE)
        return text.strip()

    def _try_ollama(self, prompt: str) -> Optional[str]:
        model = settings_state.get('local_model') or 'llama3'
        url = self._ollama_endpoint().rstrip('/') + '/api/chat'
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是资深量化与基本面结合的股票分析助手, 输出要结构化列出: 1) 概览 2) 短期动量 3) 波动与风险 4) 机会与关注点 5) 免责声明。避免过度乐观措辞。"},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
        }
        try:
            # Increase timeout to support slower local models (e.g., deepseek-r1:8b)
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json=payload)
            if resp.status_code != 200:
                return self._try_ollama_generate(prompt, model)
            data = resp.json()
            # Ollama (non-stream) 返回包含 message/content
            message = data.get('message') or {}
            content = message.get('content')
            if content:
                return self._postprocess(content)
            # 某些版本可能直接有 'content'
            if 'content' in data and isinstance(data['content'], str):
                return self._postprocess(data['content'])
            # If chat returns nothing, try generate endpoint
            return self._try_ollama_generate(prompt, model)
        except Exception:
            return self._try_ollama_generate(prompt, model)

    def _try_ollama_generate(self, prompt: str, model: Optional[str] = None) -> Optional[str]:
        model = model or (settings_state.get('local_model') or 'llama3')
        url = self._ollama_endpoint().rstrip('/') + '/api/generate'
        sys = "你是资深量化与基本面结合的股票分析助手, 输出要结构化列出: 1) 概览 2) 短期动量 3) 波动与风险 4) 机会与关注点 5) 免责声明。避免过度乐观措辞。"
        full_prompt = f"{sys}\n\n用户输入:\n{prompt}"
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            # /api/generate returns { response: string, ... }
            content = data.get('response')
            if isinstance(content, str) and content.strip():
                return self._postprocess(content)
            return None
        except Exception:
            return None

    def generate(self, prompt: str) -> str:
        # 优先尝试本地 Ollama, 失败则回退占位文本
        result = self._try_ollama(prompt)
        if result:
            return result
        lang = settings_state.get('language', 'en')
        if lang == 'zh':
            return f"[LOCAL MODEL {settings_state.get('local_model')}] (Ollama 不可用或调用失败, 使用占位结果) 摘要分析: 输入长度 {len(prompt)} 字符。"
        else:
            return f"[LOCAL MODEL {settings_state.get('local_model')}] (Ollama unavailable, fallback placeholder). Prompt length {len(prompt)} chars."

class CloudProvider(BaseProvider):
    def generate(self, prompt: str) -> str:
        # TODO: 使用 LiteLLM / OpenAI 接口
        key = settings_state.get('api_key')
        lang = settings_state.get('language', 'en')
        if not key:
            return "[CLOUD] 缺少 API Key, 返回占位分析。" if lang == 'zh' else "[CLOUD] Missing API Key, placeholder analysis."
        return (f"[CLOUD MODEL] 模拟调用完成。Prompt 长度 {len(prompt)} 字符。" if lang == 'zh' 
                else f"[CLOUD MODEL] Mock call complete. Prompt length {len(prompt)} chars.")

def get_provider() -> BaseProvider:
    return LocalProvider() if settings_state.get("mode") == "local" else CloudProvider()
