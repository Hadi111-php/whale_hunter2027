"""
Vision-Language Model (VLM) Client for Visual Screen Understanding and OCR.
Supports Qwen2-VL, LLaVA, and OpenAI-compatible Vision endpoints.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("qwen_hands_eyes.vlm_client")


class VLMVisionClient:
    """Connects to multimodal vision models to analyze screenshots and inspect UI components."""

    def __init__(
        self,
        provider: str = "ollama",
        base_url: str = "http://localhost:11434",
        model: str = "qwen2-vl:7b",
        api_key: str = "",
        timeout_sec: int = 120,
    ):
        self.provider = provider.lower().strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    def analyze_image(
        self,
        base64_image: str,
        prompt: str = "Describe what is visible on this screen in detail, and list all buttons or text elements.",
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send image + text prompt to VLM and return text description / coordinates."""
        if self.provider == "ollama":
            return self._analyze_ollama(base64_image, prompt, system_prompt)
        else:
            return self._analyze_openai_vision(base64_image, prompt, system_prompt)

    def _analyze_ollama(self, base64_image: str, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [base64_image],
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "SkyGround-VLM/1.0"}

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "ok": True,
                    "response": data.get("response", ""),
                    "model": self.model,
                    "done": data.get("done", True),
                }
        except Exception as e:
            logger.error(f"Ollama VLM error: {e}")
            return {"ok": False, "error": str(e), "response": ""}

    def _analyze_openai_vision(self, base64_image: str, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        endpoint = "/chat/completions" if self.base_url.endswith("/v1") else "/v1/chat/completions"
        url = f"{self.base_url}{endpoint}"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                },
            ],
        })

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "SkyGround-VLM/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    return {"ok": True, "response": content, "model": self.model}
                return {"ok": False, "error": "No response returned from vision model", "response": ""}
        except Exception as e:
            logger.error(f"OpenAI Vision error: {e}")
            return {"ok": False, "error": str(e), "response": ""}
