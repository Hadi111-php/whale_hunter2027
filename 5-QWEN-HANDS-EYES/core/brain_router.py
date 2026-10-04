"""
Dual-Brain Router & Multi-Model Orchestrator for Qwen-Hands-Eyes.
Routes requests parametrically between Qwen (Primary/Front/Maestro) and DeepSeek R1 (Reasoning Brain) or APIs.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from config.settings import AppConfig
from core.llm_client import UniversalLLMClient
from core.translator_bridge import DualBrainTranslatorBridge
from hands.web_operator import WebOperator

logger = logging.getLogger("qwen_hands_eyes.brain_router")


DEFAULT_EXECUTIVE_SYSTEM_PROMPT = (
    "تو دستیار هوشمند و سیستم‌عامل خودکار SkyGround هستی که به طور مستقیم به حواس چشم (Eyes: اسکرین‌کپچر و بینایی)، "
    "دست (Hands: کنترل ماوس، کیبورد، فایل‌ها و ترمینال)، موتور جستجوی وب و دروازه موبایل (Feet) مجهز هستی.\n"
    "دستورالعمل‌های حیاتی:\n"
    "۱. هرگز نباید بگویی «من یک هوش مصنوعی متنی هستم و نمی‌توانم به سیستم یا صفحه دسترسی داشته باشم». تو مجوز کامل سیستمی از هادی داری.\n"
    "۲. وقتی با سوالات روز، خطاهای کدنویسی یا درخواست سرچ مواجه می‌شوی، از ابزار جستجوی وب استفاده می‌کنی و اطلاعات مستند را ادغام می‌کنی.\n"
    "۳. برای کارهای استدلالی، ریاضی و برنامه‌نویسی، گام‌به‌گام و دقیق پاسخ بده و کدها را در بلاک‌های استاندارد بنویس."
)


class DualBrainRouter:
    """Manages routing between Qwen front model and DeepSeek-R1 / API reasoning backends."""

    def __init__(self, config: AppConfig, web_operator: Optional[WebOperator] = None):
        self.config = config
        self.web_operator = web_operator or WebOperator()
        self.primary_client = UniversalLLMClient(
            provider=config.primary_brain.provider,
            base_url=config.primary_brain.base_url,
            model=config.primary_brain.model,
            temperature=config.primary_brain.temperature,
            max_tokens=config.primary_brain.max_tokens,
            top_p=config.primary_brain.top_p,
            num_ctx=config.primary_brain.num_ctx,
            api_key=config.primary_brain.api_key,
            timeout_sec=config.primary_brain.timeout_sec,
        )

        self.reasoning_client = UniversalLLMClient(
            provider=config.reasoning_brain.provider,
            base_url=config.reasoning_brain.base_url,
            model=config.reasoning_brain.model,
            temperature=config.reasoning_brain.temperature,
            max_tokens=config.reasoning_brain.max_tokens,
            api_key=config.reasoning_brain.api_key,
            timeout_sec=config.reasoning_brain.timeout_sec,
        )

        self.translator = DualBrainTranslatorBridge(self.primary_client)

    def set_mode(self, mode: str) -> Dict[str, Any]:
        """Dynamically update execution mode."""
        valid_modes = {"dual_brain", "qwen_direct", "deepseek_direct", "api_bridge", "hybrid_auto"}
        if mode not in valid_modes:
            return {"ok": False, "error": f"Invalid mode '{mode}'. Choose from {valid_modes}"}
        self.config.mode = mode
        logger.info(f"Switched agent mode to: {mode}")
        return {"ok": True, "mode": mode}

    def should_route_to_reasoning_brain(self, message: str) -> Tuple[bool, str]:
        """Determine if a query should be handed over to DeepSeek R1."""
        mode = self.config.mode.lower()
        if mode == "deepseek_direct":
            return True, "Mode is deepseek_direct"
        if mode == "qwen_direct":
            return False, "Mode is qwen_direct"

        # Explicit user prefix overrides
        msg_trimmed = message.strip()
        if msg_trimmed.startswith(("/r1", "/deepseek", "!reason", "!think")):
            return True, "User explicit prefix command"
        if msg_trimmed.startswith(("/qwen", "!fast")):
            return False, "User explicit qwen command"

        # Check keyword matches
        msg_lower = message.lower()
        for kw in self.config.reasoning_brain.routing_keywords:
            if kw.lower() in msg_lower:
                return True, f"Keyword match: '{kw}'"

        # Check code / math patterns
        if any(indicator in message for indicator in ["def ", "class ", "import ", "function", "=>", "```", "∫", "∑", "\\frac"]):
            return True, "Code or mathematical notation detected"

        # Check length & complexity heuristic
        words = message.split()
        if len(words) > 40 and ("چرا" in message or "چگونه" in message or "تحلیل" in message or "مقایسه" in message or "why" in msg_lower or "how" in msg_lower):
            return True, "Complex analytical query heuristic"

        return False, "Standard query routed to Qwen"

    def process(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        force_brain: Optional[str] = None,  # "primary" | "reasoning" | None
    ) -> Dict[str, Any]:
        """Main processing pipeline coordinating primary model and reasoning brain."""
        history = conversation_history or []
        start_time = time.time()

        # Decide brain route
        if force_brain == "reasoning":
            route_reasoning = True
            route_reason = "Forced reasoning brain by caller"
        elif force_brain == "primary":
            route_reasoning = False
            route_reason = "Forced primary brain by caller"
        else:
            route_reasoning, route_reason = self.should_route_to_reasoning_brain(message)

        result: Dict[str, Any] = {
            "query": message,
            "mode": self.config.mode,
            "routed_to": "deepseek_reasoner" if route_reasoning else "qwen_primary",
            "route_reason": route_reason,
            "thought_process": "",
            "response": "",
            "intermediate_translation": None,
        }

        eff_system_prompt = system_prompt or DEFAULT_EXECUTIVE_SYSTEM_PROMPT

        # Autonomous Web Search Check
        search_triggers = ["سرچ کن", "جستجو کن", "سرچ", "search", "آخرین قیمت", "اخبار جدید", "دیباگ", "خطای", "چرا کار نمیکنه", "حل مشکل"]
        web_context = ""
        msg_lower = message.lower()
        if any(trig in msg_lower for trig in search_triggers) and len(message.strip()) > 5:
            # Extract clean search query
            clean_q = re.sub(r"^(لطفا|لطفاً|برام|بی زحمت|بی‌زحمت|سرچ کن|جستجو کن|search for|search)?\s*", "", message).strip()
            if clean_q:
                try:
                    s_res = self.web_operator.search(clean_q, max_results=3)
                    if s_res.get("ok") and s_res.get("results"):
                        snippets = [f"- {r['title']}: {r['snippet']} ({r['url']})" for r in s_res["results"]]
                        web_context = "Web Search Live Results:\n" + "\n".join(snippets)
                        result["web_search_used"] = True
                        result["search_query"] = clean_q
                except Exception as e:
                    logger.debug(f"Auto web search error: {e}")

        # Merge Context
        full_context = context or ""
        if web_context:
            full_context = f"{full_context}\n\n{web_context}".strip()

        if not route_reasoning:
            # Route directly to Qwen
            messages = []
            if full_context:
                messages.append({"role": "system", "content": f"Relevant Context / Web Data:\n{full_context}"})
            messages.append({"role": "user", "content": message})

            res = self.primary_client.chat(
                messages=messages,
                system_prompt=eff_system_prompt,
            )
            result["response"] = res.get("content", "")
            result["raw_result"] = res
            result["ok"] = res.get("ok", False)
            result["elapsed_sec"] = round(time.time() - start_time, 3)
            return result

        # Route to DeepSeek R1 / Reasoning Brain
        logger.info(f"Routing to DeepSeek R1 reasoner. Reason: {route_reason}")

        # Step 1: Translate to English if configured
        prompt_for_reasoner = message
        english_prompt = ""
        if self.config.reasoning_brain.auto_translate_persian:
            english_prompt = self.translator.translate_persian_to_english_prompt(message, context=full_context)
            prompt_for_reasoner = english_prompt
            result["intermediate_translation"] = {"persian_to_english": english_prompt}

        # Step 2: Query DeepSeek R1
        reasoner_messages = [{"role": "user", "content": prompt_for_reasoner}]
        if full_context:
            reasoner_messages.insert(0, {"role": "system", "content": f"Task context:\n{full_context}"})

        reasoner_res = self.reasoning_client.chat(
            messages=reasoner_messages,
            system_prompt="You are DeepSeek R1, an advanced reasoning and coding AI. Think thoroughly and provide rigorous, step-by-step solutions.",
        )

        if not reasoner_res.get("ok"):
            logger.warning(f"Reasoner call failed: {reasoner_res.get('error')}. Falling back to primary Qwen.")
            fallback_res = self.primary_client.chat(
                messages=[{"role": "user", "content": message}],
                system_prompt=eff_system_prompt,
            )
            result["response"] = fallback_res.get("content", "")
            result["fallback_used"] = True
            result["fallback_error"] = reasoner_res.get("error")
            result["ok"] = fallback_res.get("ok", False)
            result["elapsed_sec"] = round(time.time() - start_time, 3)
            return result

        raw_reasoner_output = reasoner_res.get("content", "")
        # Check if reasoning_content is returned separately (e.g. OpenAI format for R1)
        separate_thought = reasoner_res.get("reasoning_content", "")
        extracted_thought, extracted_answer = self.translator.extract_reasoning_and_answer(raw_reasoner_output)

        thought = separate_thought or extracted_thought
        answer = extracted_answer if separate_thought == "" else raw_reasoner_output

        result["thought_process"] = thought
        result["raw_english_answer"] = answer

        # Step 3: Translate answer back to Persian
        if self.config.reasoning_brain.auto_translate_persian:
            trans_res = self.translator.translate_english_to_persian_response(
                english_answer=answer,
                thought_process=thought,
                user_original_query=message,
            )
            result["response"] = trans_res.get("persian_text", answer)
            if trans_res.get("warning"):
                result["translation_warning"] = trans_res["warning"]
        else:
            result["response"] = answer

        result["ok"] = True
        result["elapsed_sec"] = round(time.time() - start_time, 3)
        return result
