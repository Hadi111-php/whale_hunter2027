"""
Skill registry for SkyGround reflex layer.

Skills connect canonical intents to concrete executors/tools.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


SAFETY_ORDER = {"silent": 0, "fast": 1, "confirm": 2, "approval": 3, "blocked": 4}


@dataclasses.dataclass
class SkillDefinition:
    id: str
    intent: str
    description: str
    executor: str
    args: Dict[str, Any]
    safety_level: str = "fast"     # silent | fast | confirm | approval | blocked
    risk: str = "low"              # low | medium | high
    status: str = "approved"       # candidate | learned | approved | trusted | deprecated | blocked
    confidence: float = 0.8
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    requires_approval: bool = False
    reporting_on_success: str = "event_only"  # silent | event_only | summary | brain_report
    reporting_on_failure: str = "brain_report"


DEFAULT_SKILLS: List[SkillDefinition] = [
    SkillDefinition("shortcut.copy", "clipboard.copy", "Copy selection using Ctrl+C", "execute_shortcut", {"name": "copy"}, "fast", "low", "trusted", 0.95, requires_approval=False, reporting_on_success="silent"),
    SkillDefinition("shortcut.paste", "clipboard.paste", "Paste clipboard using Ctrl+V", "execute_shortcut", {"name": "paste"}, "confirm", "medium", "approved", 0.8),
    SkillDefinition("shortcut.cut", "clipboard.cut", "Cut selection using Ctrl+X", "execute_shortcut", {"name": "cut"}, "confirm", "medium", "approved", 0.75),
    SkillDefinition("shortcut.save", "file.save_active", "Save active file using Ctrl+S", "execute_shortcut", {"name": "save"}, "fast", "low", "trusted", 0.95, requires_approval=False, reporting_on_success="silent"),
    SkillDefinition("shortcut.escape", "ui.escape", "Press Escape", "execute_shortcut", {"name": "escape"}, "fast", "low", "trusted", 0.9),
    SkillDefinition("shortcut.open_search", "search.open", "Open search using Ctrl+K", "execute_shortcut", {"name": "open_search"}, "fast", "low", "approved", 0.85),
    SkillDefinition("shortcut.command_palette", "command_palette.open", "Open command palette using Ctrl+Shift+P", "execute_shortcut", {"name": "command_palette"}, "fast", "low", "approved", 0.85),
    SkillDefinition("project.index", "project.index", "Rebuild project index", "index_project", {}, "silent", "low", "trusted", 0.95, reporting_on_success="silent"),
    SkillDefinition("git.status", "git.status", "Read git status", "git_status", {}, "silent", "low", "trusted", 0.95, reporting_on_success="silent"),
    SkillDefinition("git.diff", "git.diff", "Read git diff", "git_diff", {}, "silent", "low", "trusted", 0.95, reporting_on_success="event_only"),
    SkillDefinition("desktop.observe", "desktop.observe", "Observe registered desktop logs", "observe_desktop_logs", {}, "silent", "low", "trusted", 0.9, reporting_on_success="silent"),
    SkillDefinition("memory.search", "memory.search", "Search memory; requires query", "search_memory", {"query_from_command": True}, "fast", "low", "approved", 0.7),
]


class SkillRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skills: Dict[str, SkillDefinition] = {}
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for item in data.get("skills", []):
                    skill = SkillDefinition(**item)
                    self.skills[skill.id] = skill
            except Exception:
                self.skills = {}
        changed = False
        for skill in DEFAULT_SKILLS:
            if skill.id not in self.skills:
                self.skills[skill.id] = skill
                changed = True
        if changed or not self.path.exists():
            self.save()

    def save(self) -> None:
        payload = {"version": 1, "skills": [dataclasses.asdict(s) for s in self.skills.values()]}
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list_skills(self) -> List[Dict[str, Any]]:
        return [dataclasses.asdict(s) for s in self.skills.values()]

    def register_skill(self, data: Dict[str, Any], overwrite: bool = True) -> Dict[str, Any]:
        """Register or update a skill from an admin-provided JSON object."""
        skill_id = str(data.get("id", "")).strip()
        intent = str(data.get("intent", "")).strip()
        executor = str(data.get("executor", "")).strip()
        if not skill_id:
            return {"ok": False, "error": "skill id is required"}
        if not intent:
            return {"ok": False, "error": "skill intent is required"}
        if not executor:
            return {"ok": False, "error": "skill executor is required"}
        if skill_id in self.skills and not overwrite:
            return {"ok": False, "error": "skill already exists", "id": skill_id}
        args = data.get("args", {})
        if not isinstance(args, dict):
            return {"ok": False, "error": "skill args must be an object"}
        skill = SkillDefinition(
            id=skill_id,
            intent=intent,
            description=str(data.get("description", skill_id)),
            executor=executor,
            args=args,
            safety_level=str(data.get("safety_level", "fast")),
            risk=str(data.get("risk", "low")),
            status=str(data.get("status", "approved")),
            confidence=float(data.get("confidence", 0.8)),
            usage_count=int(data.get("usage_count", 0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            requires_approval=bool(data.get("requires_approval", False)),
            reporting_on_success=str(data.get("reporting_on_success", "event_only")),
            reporting_on_failure=str(data.get("reporting_on_failure", "brain_report")),
        )
        if skill.safety_level not in SAFETY_ORDER:
            return {"ok": False, "error": f"invalid safety_level: {skill.safety_level}"}
        if skill.status not in {"candidate", "learned", "approved", "trusted", "deprecated", "blocked"}:
            return {"ok": False, "error": f"invalid status: {skill.status}"}
        self.skills[skill.id] = skill
        self.save()
        return {"ok": True, "skill": dataclasses.asdict(skill)}

    def find_by_intent(self, intent_id: str) -> Optional[SkillDefinition]:
        candidates = [s for s in self.skills.values() if s.intent == intent_id and s.status not in {"deprecated"}]
        if not candidates:
            return None
        candidates.sort(key=lambda s: (s.status == "trusted", s.confidence, s.success_count - s.failure_count), reverse=True)
        return candidates[0]

    def update_stats(self, skill_id: str, ok: bool) -> None:
        skill = self.skills.get(skill_id)
        if not skill:
            return
        skill.usage_count += 1
        if ok:
            skill.success_count += 1
            # Promote trusted after repeated success for non-dangerous skills.
            if skill.success_count >= 5 and skill.failure_count == 0 and skill.risk == "low" and skill.status in {"approved", "learned"}:
                skill.status = "trusted"
                skill.confidence = max(skill.confidence, 0.9)
            else:
                skill.confidence = min(0.99, skill.confidence + 0.01)
        else:
            skill.failure_count += 1
            skill.confidence = max(0.1, skill.confidence - 0.08)
            if skill.failure_count >= 3 and skill.failure_count > skill.success_count:
                skill.status = "learned" if skill.status == "trusted" else skill.status
        self.save()

    def promote(self, skill_id: str, status: str = "trusted") -> Dict[str, Any]:
        if status not in {"candidate", "learned", "approved", "trusted", "deprecated", "blocked"}:
            return {"ok": False, "error": "invalid status"}
        skill = self.skills.get(skill_id)
        if not skill:
            return {"ok": False, "error": "skill not found"}
        skill.status = status
        if status == "trusted":
            skill.confidence = max(skill.confidence, 0.9)
        self.save()
        return {"ok": True, "skill": dataclasses.asdict(skill)}