"""
Append-only JSONL event journal for SkyGround.

Purpose:
- Store raw operational events locally.
- Support later daily distillation / skill promotion.
- Keep events sanitized before writing.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from security import sanitize_for_display


class EventJournal:
    def __init__(self, events_dir: Path):
        self.events_dir = Path(events_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_date(self, day: Optional[str] = None) -> Path:
        day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        return self.events_dir / f"{day}.jsonl"

    def record(self, event_type: str, data: Optional[Dict[str, Any]] = None, level: str = "info") -> Dict[str, Any]:
        event = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "type": event_type,
            "level": level,
            "data": sanitize_for_display(data or {}, max_string=8000),
        }
        path = self._path_for_date()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        return {"ok": True, "path": str(path), "event": event}

    def recent(self, limit: int = 100, day: Optional[str] = None) -> List[Dict[str, Any]]:
        path = self._path_for_date(day)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        events: List[Dict[str, Any]] = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events

    def summarize_counts(self, day: Optional[str] = None) -> Dict[str, Any]:
        events = self.recent(limit=10000, day=day)
        counts: Dict[str, int] = {}
        levels: Dict[str, int] = {}
        for event in events:
            counts[event.get("type", "unknown")] = counts.get(event.get("type", "unknown"), 0) + 1
            levels[event.get("level", "info")] = levels.get(event.get("level", "info"), 0) + 1
        return {"ok": True, "total": len(events), "counts": counts, "levels": levels, "day": day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")}