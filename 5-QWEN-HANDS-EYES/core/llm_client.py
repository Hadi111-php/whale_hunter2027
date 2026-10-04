"""
Unified LLM Client supporting Ollama, vLLM, llama.cpp, and OpenAI-compatible APIs (DeepSeek, OpenRouter, etc.).
Pure Python standard library implementation with zero required third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("qwen_hands_eyes.llm_client")


class LLMClientError(Exception):
    pass


class UniversalLLMClient:
    """Universal LLM client for local and remote models."""

    def __init__(
        self,
        provider: str = "ollama",
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct-q4_K_M",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 0.9,
        num_ctx: int = 8192,
        api_key: str = "",
        timeout_sec: int = 120,
    ):
        self.provider = provider.lower().strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.num_ctx = num_ctx
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    def is_available(self) -> bool:
        """Check if LLM backend is reachable."""
        try:
            if self.provider == "ollama":
                url = f"{self.base_url}/api/tags"
                req = urllib.request.Request(url, headers={"User-Agent": "SkyGround-LLMClient/1.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    return resp.status == 200
            else:
                # OpenAI compatible or vLLM
                url = f"{self.base_url}/models" if "/v1" in self.base_url else f"{self.base_url}/v1/models"
                headers = {"User-Agent": "SkyGround-LLMClient/1.0"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available models from provider."""
        try:
            if self.provider == "ollama":
                url = f"{self.base_url}/api/tags"
                req = urllib.request.Request(url, headers={"User-Agent": "SkyGround-LLMClient/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return [m.get("name", "") for m in data.get("models", [])]
            else:
                url = f"{self.base_url}/models" if "/v1" in self.base_url else f"{self.base_url}/v1/models"
                headers = {"User-Agent": "SkyGround-LLMClient/1.0"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return [m.get("id", "") for m in data.get("data", [])]
        except Exception as e:
            logger.debug(f"Could not list models: {e}")
            return []

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send chat request and return full assistant response."""
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        start_time = time.time()
        if self.provider == "ollama":
            res = self._chat_ollama(formatted_messages, temp, tokens, extra_options)
        else:
            res = self._chat_openai_compatible(formatted_messages, temp, tokens, extra_options)

        elapsed = time.time() - start_time
        res["elapsed_sec"] = round(elapsed, 3)
        res["model"] = self.model
        res["provider"] = self.provider
        return res

    def _chat_ollama(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        extra_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        options = {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": self.top_p,
            "num_ctx": self.num_ctx,
        }
        if extra_options:
            options.update(extra_options)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SkyGround-LLMClient/1.0",
        }

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                message = result.get("message", {})
                content = message.get("content", "")
                return {
                    "ok": True,
                    "content": content,
                    "role": message.get("role", "assistant"),
                    "done": result.get("done", True),
                    "prompt_eval_count": result.get("prompt_eval_count", 0),
                    "eval_count": result.get("eval_count", 0),
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"Ollama HTTP error {e.code}: {err_body}")
            return {"ok": False, "error": f"HTTP {e.code}: {err_body}", "content": ""}
        except Exception as e:
            logger.error(f"Ollama connection error: {e}")
            return {"ok": False, "error": str(e), "content": ""}

    def _chat_openai_compatible(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        extra_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        endpoint = "/chat/completions" if self.base_url.endswith("/v1") else "/v1/chat/completions"
        url = f"{self.base_url}{endpoint}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": self.top_p,
            "stream": False,
        }
        if extra_options:
            payload.update(extra_options)

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SkyGround-LLMClient/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                choices = result.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")
                    reasoning_content = msg.get("reasoning_content", "")
                    return {
                        "ok": True,
                        "content": content,
                        "reasoning_content": reasoning_content,
                        "role": msg.get("role", "assistant"),
                        "usage": result.get("usage", {}),
                    }
                return {"ok": False, "error": "No choices returned from model", "content": ""}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error(f"OpenAI compatible HTTP error {e.code}: {err_body}")
            return {"ok": False, "error": f"HTTP {e.code}: {err_body}", "content": ""}
        except Exception as e:
            logger.error(f"OpenAI compatible connection error: {e}")
            return {"ok": False, "error": str(e), "content": ""}
