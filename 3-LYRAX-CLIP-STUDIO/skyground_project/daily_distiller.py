"""
Daily distiller for SkyGround agent.

Reads the append-only event journal and produces a deterministic daily learning report:
- event counts
- reflex skill usage/failures
- unknown/ambiguous commands that need brain/admin review
- skill promotion/demotion recommendations
- short memory-ready lesson lines

No LLM is required. This is the first safe layer of daily learning.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from event_journal import EventJournal
from security import sanitize_for_display
from skill_registry import SkillRegistry


class DailyDistiller:
    def __init__(self, journal: EventJournal, skills: SkillRegistry, output_dir: Path):
        self.journal = journal
        self.skills = skills
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _day(self, day: Optional[str] = None) -> str:
        return day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    def _output_path(self, day: str) -> Path:
        return self.output_dir / f"{day}.json"

    def distill(self, day: Optional[str] = None, apply: bool = False) -> Dict[str, Any]:
        day = self._day(day)
        events = self.journal.recent(limit=10000, day=day)
        counts = self.journal.summarize_counts(day=day)

        skill_stats: Dict[str, Dict[str, Any]] = {}
        unknown_commands: Dict[str, int] = {}
        blocked_or_ambiguous: Dict[str, int] = {}
        approval_missing = 0
        injections = 0

        for event in events:
            etype = event.get("type", "")
            data = event.get("data") or {}
            if etype in {"reflex.executed", "reflex.failed"}:
                skill_id = str(data.get("skill_id") or data.get("result", {}).get("resolved", {}).get("skill", {}).get("id") or "unknown")
                stat = skill_stats.setdefault(skill_id, {"success": 0, "failure": 0, "dry_run": 0, "commands": {}})
                if data.get("dry_run"):
                    stat["dry_run"] += 1
                if etype == "reflex.executed":
                    stat["success"] += 1
                else:
                    stat["failure"] += 1
                cmd = str(data.get("command") or "")[:200]
                if cmd:
                    stat["commands"][cmd] = stat["commands"].get(cmd, 0) + 1
            elif etype == "reflex.resolve_failed":
                cmd = str(data.get("command") or data.get("input") or data.get("intent_result", {}).get("input") or "")[:200]
                reason = str(data.get("reason") or "unknown")
                if reason in {"no_intent_match", "missing_skill"}:
                    unknown_commands[cmd or "[empty]"] = unknown_commands.get(cmd or "[empty]", 0) + 1
                else:
                    blocked_or_ambiguous[cmd or reason] = blocked_or_ambiguous.get(cmd or reason, 0) + 1
            elif etype in {"reflex.approval_missing", "reflex.approval_rejected", "reflex.blocked"}:
                approval_missing += 1
            elif etype == "admin.inject":
                injections += 1

        recommendations: List[Dict[str, Any]] = []
        for skill_id, stat in sorted(skill_stats.items()):
            skill = self.skills.skills.get(skill_id)
            if not skill:
                continue
            total = stat["success"] + stat["failure"]
            if total == 0:
                continue
            if stat["success"] >= 3 and stat["failure"] == 0 and skill.risk == "low" and skill.status in {"approved", "learned"}:
                recommendations.append(
                    {
                        "type": "promote_skill",
                        "skill_id": skill_id,
                        "target_status": "trusted",
                        "reason": f"{stat['success']} successful executions and no failures today",
                        "applyable": True,
                    }
                )
            if stat["failure"] >= 2:
                recommendations.append(
                    {
                        "type": "review_skill",
                        "skill_id": skill_id,
                        "reason": f"{stat['failure']} failures today",
                        "applyable": False,
                    }
                )

        for cmd, n in sorted(unknown_commands.items(), key=lambda x: x[1], reverse=True)[:20]:
            if cmd and cmd != "[empty]":
                recommendations.append(
                    {
                        "type": "candidate_intent_or_skill",
                        "command": cmd,
                        "count": n,
                        "reason": "command could not be resolved by reflex layer",
                        "applyable": False,
                    }
                )

        lesson_lines: List[str] = []
        if skill_stats:
            top = sorted(skill_stats.items(), key=lambda kv: kv[1]["success"] + kv[1]["failure"], reverse=True)[:5]
            for skill_id, stat in top:
                lesson_lines.append(f"Skill {skill_id}: success={stat['success']} failure={stat['failure']} dry_run={stat['dry_run']} on {day}.")
        if unknown_commands:
            lesson_lines.append(f"There were {sum(unknown_commands.values())} unresolved reflex commands; consider adding intents/skills for frequent commands.")
        if injections:
            lesson_lines.append(f"Admin performed {injections} injection event(s) on {day}.")
        if approval_missing:
            lesson_lines.append(f"There were {approval_missing} approval/blocked reflex events; review safety levels if workflow is too slow.")
        if not lesson_lines:
            lesson_lines.append(f"No significant learning events recorded for {day}.")

        applied: List[Dict[str, Any]] = []
        if apply:
            for rec in recommendations:
                if rec.get("type") == "promote_skill" and rec.get("applyable"):
                    res = self.skills.promote(str(rec["skill_id"]), str(rec.get("target_status", "trusted")))
                    applied.append({"recommendation": rec, "result": res})

        report = {
            "ok": True,
            "day": day,
            "event_counts": counts,
            "skill_stats": skill_stats,
            "unknown_commands": unknown_commands,
            "blocked_or_ambiguous": blocked_or_ambiguous,
            "recommendations": recommendations,
            "lesson_lines": lesson_lines,
            "applied": applied,
            "apply": apply,
        }
        report = sanitize_for_display(report, max_string=12000)
        path = self._output_path(day)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["path"] = str(path)
        return report