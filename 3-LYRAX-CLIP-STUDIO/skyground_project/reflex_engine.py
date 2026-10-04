"""
Reflex engine: local intent -> skill -> executor without calling a big LLM.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Dict, Optional, Tuple

from event_journal import EventJournal
from intent_registry import IntentRegistry
from skill_registry import SAFETY_ORDER, SkillDefinition, SkillRegistry


class ReflexEngine:
    def __init__(self, intents: IntentRegistry, skills: SkillRegistry, journal: EventJournal):
        self.intents = intents
        self.skills = skills
        self.journal = journal

    def resolve(self, command: str) -> Dict[str, Any]:
        intent_result = self.intents.resolve(command)
        if not intent_result.get("ok") or not intent_result.get("matches"):
            return {"ok": False, "command": command, "needs_brain": True, "reason": "no_intent_match", "intent_result": intent_result}
        best = intent_result["matches"][0]
        intent = best["intent"]
        if intent.get("status") == "blocked":
            return {"ok": False, "command": command, "blocked": True, "reason": "intent_blocked", "intent_match": best}
        if intent.get("ambiguous") and best.get("score", 0) < 0.98:
            return {"ok": False, "command": command, "needs_clarification": True, "reason": "ambiguous_intent", "intent_match": best, "matches": intent_result.get("matches", [])}
        skill = self.skills.find_by_intent(intent["id"])
        if not skill:
            return {"ok": False, "command": command, "needs_brain": True, "reason": "missing_skill", "intent_match": best}
        return {"ok": True, "command": command, "intent_match": best, "skill": dataclasses.asdict(skill)}

    def should_request_approval(
        self,
        skill: SkillDefinition,
        dry_run: bool,
        auto_execute_trusted: bool = True,
        trust_threshold: float = 0.85,
        require_approval_for_confirm: bool = True,
    ) -> Tuple[bool, str]:
        if dry_run:
            return False, "dry_run"
        if skill.status == "blocked" or skill.safety_level == "blocked":
            return True, "blocked_or_admin_only"
        if skill.requires_approval:
            return True, "skill_requires_approval"
        safety = SAFETY_ORDER.get(skill.safety_level, 3)
        if safety <= SAFETY_ORDER["fast"]:
            return False, "fast_or_silent"
        if safety == SAFETY_ORDER["confirm"]:
            if auto_execute_trusted and skill.status == "trusted" and skill.confidence >= trust_threshold:
                return False, "trusted_confirm_auto"
            return require_approval_for_confirm, "confirm_level"
        return True, "approval_level"

    def execute(
        self,
        command: str,
        executor: Callable[[SkillDefinition, bool, str], Dict[str, Any]],
        dry_run: bool = False,
        approval_callback: Optional[Callable[[SkillDefinition, Dict[str, Any], str], bool]] = None,
        auto_execute_trusted: bool = True,
        trust_threshold: float = 0.85,
        require_approval_for_confirm: bool = True,
    ) -> Dict[str, Any]:
        resolved = self.resolve(command)
        if not resolved.get("ok"):
            self.journal.record("reflex.resolve_failed", resolved, level="warning")
            return resolved
        skill = SkillDefinition(**resolved["skill"])
        approval_needed, approval_reason = self.should_request_approval(
            skill,
            dry_run=dry_run,
            auto_execute_trusted=auto_execute_trusted,
            trust_threshold=trust_threshold,
            require_approval_for_confirm=require_approval_for_confirm,
        )
        if skill.status == "blocked" or skill.safety_level == "blocked":
            result = {"ok": False, "error": "skill is blocked", "resolved": resolved}
            self.journal.record("reflex.blocked", result, level="warning")
            return result
        if approval_needed:
            if approval_callback is None:
                result = {"ok": False, "needs_approval": True, "approval_reason": approval_reason, "resolved": resolved}
                self.journal.record("reflex.approval_missing", result, level="warning")
                return result
            approved = approval_callback(skill, resolved, approval_reason)
            if not approved:
                result = {"ok": False, "cancelled": True, "error": "approval rejected", "approval_reason": approval_reason, "resolved": resolved}
                self.journal.record("reflex.approval_rejected", result, level="warning")
                return result
        result = executor(skill, dry_run, approval_reason)
        ok = bool(result.get("ok"))
        self.skills.update_stats(skill.id, ok=ok)
        event_type = "reflex.executed" if ok else "reflex.failed"
        self.journal.record(event_type, {"command": command, "skill_id": skill.id, "intent": skill.intent, "dry_run": dry_run, "approval_reason": approval_reason, "result": result}, level="info" if ok else "warning")
        result["resolved"] = resolved
        result["approval_reason"] = approval_reason
        return result