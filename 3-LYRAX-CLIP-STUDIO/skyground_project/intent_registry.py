"""
Intent registry and lightweight recognizer.

This is the small local "reflex brain" entry point: map phrases like
"کپی کن" and "copy" to the same canonical intent without calling an LLM.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class IntentDefinition:
    id: str
    description: str
    aliases: List[str]
    risk: str = "low"          # low | medium | high
    ambiguous: bool = False
    status: str = "approved"   # candidate | approved | trusted | blocked


DEFAULT_INTENTS: List[IntentDefinition] = [
    IntentDefinition("clipboard.copy", "Copy current selection", ["copy", "copy this", "copy selected", "کپی", "کپی کن", "رونوشت", "ctrl+c", "کنترل سی"], status="trusted"),
    IntentDefinition("clipboard.paste", "Paste clipboard", ["paste", "paste here", "پیست", "بچسبان", "جایگذاری", "ctrl+v", "کنترل وی"], risk="medium"),
    IntentDefinition("clipboard.cut", "Cut current selection", ["cut", "cut this", "کات", "ببر", "ctrl+x", "کنترل ایکس"], risk="medium", ambiguous=True),
    IntentDefinition("file.save_active", "Save active file/window", ["save", "save file", "save active", "ذخیره", "ذخیره کن", "ctrl+s", "کنترل اس"], status="trusted"),
    IntentDefinition("ui.escape", "Dismiss/cancel current modal", ["escape", "esc", "cancel", "لغو", "ببند", "خروج از پنجره", "فرار"], risk="low"),
    IntentDefinition("search.open", "Open search", ["search", "open search", "جستجو", "جستجو کن", "سرچ", "ctrl+f", "ctrl+k"], risk="low"),
    IntentDefinition("command_palette.open", "Open command palette", ["command palette", "open command palette", "پالت دستور", "ctrl+shift+p"], risk="low"),
    IntentDefinition("project.index", "Index the project", ["index project", "reindex", "ایندکس", "ایندکس کن", "پروژه را ایندکس کن"], risk="low", status="trusted"),
    IntentDefinition("project.search", "Search project", ["search project", "find in project", "در پروژه بگرد", "جستجوی پروژه"], risk="low"),
    IntentDefinition("git.status", "Show git status", ["git status", "وضعیت گیت", "گیت status", "وضعیت تغییرات"], risk="low", status="trusted"),
    IntentDefinition("git.diff", "Show git diff", ["git diff", "diff", "تغییرات را نشان بده", "دیف"], risk="low", status="trusted"),
    IntentDefinition("desktop.observe", "Observe registered desktop logs", ["observe logs", "desktop state", "وضعیت صفحه", "لاگ را بخوان", "چشم", "ببین کجاست"], risk="low", status="trusted"),
    IntentDefinition("memory.search", "Search memory", ["search memory", "memory search", "حافظه را بگرد", "در حافظه بگرد"], risk="low"),
    IntentDefinition("danger.delete", "Ambiguous delete/remove request", ["delete", "remove", "حذف", "حذف کن", "پاک کن", "reset"], risk="high", ambiguous=True, status="blocked"),
]


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = text.replace("\u200c", " ")
    text = re.sub(r"[\[\]{}()<>`'\".,;:!?؟،]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize ctrl + c variations.
    text = text.replace("ctrl +", "ctrl+").replace("control +", "ctrl+").replace("کنترل ", "کنترل ")
    return text


@dataclasses.dataclass
class IntentMatch:
    intent: IntentDefinition
    score: float
    matched_alias: str
    method: str

    def to_dict(self) -> Dict[str, Any]:
        return {"intent": dataclasses.asdict(self.intent), "score": self.score, "matched_alias": self.matched_alias, "method": self.method}


class IntentRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.intents: Dict[str, IntentDefinition] = {}
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for item in data.get("intents", []):
                    intent = IntentDefinition(**item)
                    self.intents[intent.id] = intent
            except Exception:
                self.intents = {}
        changed = False
        for intent in DEFAULT_INTENTS:
            if intent.id not in self.intents:
                self.intents[intent.id] = intent
                changed = True
        if changed or not self.path.exists():
            self.save()

    def save(self) -> None:
        payload = {"version": 1, "intents": [dataclasses.asdict(i) for i in self.intents.values()]}
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list_intents(self) -> List[Dict[str, Any]]:
        return [dataclasses.asdict(i) for i in self.intents.values()]

    def register_intent(self, data: Dict[str, Any], overwrite: bool = True) -> Dict[str, Any]:
        """Register or update an intent from an admin-provided JSON object."""
        intent_id = str(data.get("id", "")).strip()
        if not intent_id:
            return {"ok": False, "error": "intent id is required"}
        if intent_id in self.intents and not overwrite:
            return {"ok": False, "error": "intent already exists", "id": intent_id}
        aliases_raw = data.get("aliases", [])
        if isinstance(aliases_raw, str):
            aliases = [x.strip() for x in aliases_raw.replace(",", "\n").splitlines() if x.strip()]
        elif isinstance(aliases_raw, list):
            aliases = [str(x).strip() for x in aliases_raw if str(x).strip()]
        else:
            aliases = []
        if not aliases:
            return {"ok": False, "error": "at least one alias is required"}
        intent = IntentDefinition(
            id=intent_id,
            description=str(data.get("description", intent_id)),
            aliases=aliases,
            risk=str(data.get("risk", "low")),
            ambiguous=bool(data.get("ambiguous", False)),
            status=str(data.get("status", "approved")),
        )
        self.intents[intent.id] = intent
        self.save()
        return {"ok": True, "intent": dataclasses.asdict(intent)}

    def resolve(self, text: str, limit: int = 5) -> Dict[str, Any]: 
        norm = normalize_text(text)
        matches: List[IntentMatch] = []
        if not norm:
            return {"ok": False, "error": "empty command", "matches": []}
        for intent in self.intents.values():
            if intent.status == "blocked" and intent.risk != "high":
                continue
            for alias in intent.aliases:
                na = normalize_text(alias)
                if not na:
                    continue
                if norm == na:
                    matches.append(IntentMatch(intent, 1.0, alias, "exact"))
                elif na in norm or norm in na:
                    score = min(len(na), len(norm)) / max(len(na), len(norm))
                    matches.append(IntentMatch(intent, round(max(0.72, score), 4), alias, "contains"))
                else:
                    ratio = difflib.SequenceMatcher(None, norm, na).ratio()
                    if ratio >= 0.78:
                        matches.append(IntentMatch(intent, round(ratio, 4), alias, "fuzzy"))
        # Deduplicate by intent, keep best.
        best: Dict[str, IntentMatch] = {}
        for m in matches:
            old = best.get(m.intent.id)
            if old is None or m.score > old.score:
                best[m.intent.id] = m
        ordered = sorted(best.values(), key=lambda m: m.score, reverse=True)[:limit]
        return {"ok": True, "input": text, "normalized": norm, "matches": [m.to_dict() for m in ordered]}