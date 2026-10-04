"""
Bidirectional Persian <-> English Translation Bridge for Dual-Brain Architecture.
Allows Qwen (Front/Orchestrator) and DeepSeek R1 (Deep Thinker) to collaborate seamlessly.
Preserves code blocks, JSON structures, math equations, and technical identifiers.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from core.llm_client import UniversalLLMClient

logger = logging.getLogger("qwen_hands_eyes.translator")

# Regex to isolate code blocks, inline code, and math
CODE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9_-]*\n[\s\S]*?```")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
THINK_TAG_RE = re.compile(r"<think>([\s\S]*?)</think>", re.IGNORECASE)


class DualBrainTranslatorBridge:
    """Orchestrates translation between Persian user requests and English-centric reasoning models."""

    def __init__(self, primary_client: UniversalLLMClient):
        self.primary_client = primary_client

    def extract_reasoning_and_answer(self, raw_text: str) -> Tuple[str, str]:
        """Extract <think>...</think> tags and the remaining answer."""
        think_match = THINK_TAG_RE.search(raw_text)
        if think_match:
            thought = think_match.group(1).strip()
            answer = THINK_TAG_RE.sub("", raw_text).strip()
            return thought, answer
        return "", raw_text.strip()

    def translate_persian_to_english_prompt(self, user_text: str, context: Optional[str] = None) -> str:
        """Translate a Persian user task into an accurate English prompt for DeepSeek R1."""
        # If user text is already mostly English or code, keep it directly
        persian_char_count = len(re.findall(r"[\u0600-\u06FF]", user_text))
        if persian_char_count < 5 and len(user_text) > 10:
            return user_text

        system_prompt = (
            "You are an expert technical translator. Translate the following user request from Persian to clear, "
            "precise English for a deep reasoning AI model (like DeepSeek R1). "
            "Preserve all code, variable names, file paths, numbers, and technical constraints exactly as they are. "
            "Output ONLY the translated English prompt without any preamble or explanation."
        )

        messages = [{"role": "user", "content": user_text}]
        if context:
            messages.insert(0, {"role": "system", "content": f"Context for task: {context}"})

        res = self.primary_client.chat(messages=messages, system_prompt=system_prompt, temperature=0.3)
        if res.get("ok") and res.get("content"):
            translated = res["content"].strip()
            # Clean possible markdown wrapping
            translated = re.sub(r"^```[a-zA-Z]*\n", "", translated)
            translated = re.sub(r"\n```$", "", translated)
            return translated

        # Fallback if primary client unavailable: return original text
        logger.warning("Translation to English failed or timed out; forwarding original text.")
        return user_text

    def translate_english_to_persian_response(
        self,
        english_answer: str,
        thought_process: str = "",
        user_original_query: str = "",
    ) -> Dict[str, Any]:
        """Translate English reasoning result back to fluent, friendly Persian, preserving code and math."""
        # If answer is very short or already contains Persian, return directly
        persian_char_count = len(re.findall(r"[\u0600-\u06FF]", english_answer))
        if persian_char_count > len(english_answer) * 0.3:
            return {
                "ok": True,
                "persian_text": english_answer,
                "thought_process": thought_process,
            }

        # Mask code blocks to prevent alteration during translation
        placeholders: Dict[str, str] = {}
        counter = 0

        def replace_block(match):
            nonlocal counter
            key = f"__CODE_BLOCK_{counter}__"
            placeholders[key] = match.group(0)
            counter += 1
            return key

        masked_text = CODE_BLOCK_RE.sub(replace_block, english_answer)

        system_prompt = (
            "You are an expert Persian AI assistant. Translate the following technical response into natural, fluent Persian (فارسی روان و محترمانه). "
            "CRITICAL RULES:\n"
            "1. NEVER translate placeholder tokens like __CODE_BLOCK_0__, __CODE_BLOCK_1__, etc. Keep them EXACTLY as they are.\n"
            "2. Keep programming keywords, function names, and technical terms accurate.\n"
            "3. Provide a clear, natural Persian explanation for the user.\n"
            "Output ONLY the translated Persian text without commentary."
        )

        prompt = f"Original user question: {user_original_query}\n\nContent to translate to Persian:\n{masked_text}"
        res = self.primary_client.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
            temperature=0.4,
        )

        if res.get("ok") and res.get("content"):
            translated = res["content"].strip()
            # Restore code blocks
            for key, block in placeholders.items():
                translated = translated.replace(key, block)

            return {
                "ok": True,
                "persian_text": translated,
                "thought_process": thought_process,
                "raw_english": english_answer,
            }

        # Fallback if primary client translation fails: restore code and return raw
        unmasked = masked_text
        for key, block in placeholders.items():
            unmasked = unmasked.replace(key, block)

        return {
            "ok": False,
            "persian_text": unmasked,
            "thought_process": thought_process,
            "raw_english": english_answer,
            "warning": "Translation backend unavailable; returned English response.",
        }
