"""
Safe desktop I/O scaffolding for SkyGround.

Principle requested by user:
- Eye/hand should rely on shortcuts and log files as the normal path.
- Screenshots are exceptional and should require explicit approval/policy later.
- Agent learns stable navigation patterns from logs and stores them as experience.

This module is intentionally conservative: it does not click/type or take screenshots.
It provides:
- shortcut registry
- log registry
- log-tail observation
- current desktop/app state inference
- state timeline
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from security import sanitize_for_display
from text_intelligence import detect_text_profile


KEY_VALUE_RE = re.compile(r"(?P<key>\b[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)")

SCREEN_KEYS = {"screen", "view", "page", "window", "activity", "component"}
ROUTE_KEYS = {"route", "path", "url", "uri", "location", "href"}
STATE_KEYS = {"state", "status", "mode", "phase"}
ACTION_KEYS = {"action", "event", "intent", "command"}
RESULT_KEYS = {"result", "outcome", "level", "severity"}
TITLE_KEYS = {"title", "caption", "heading"}
ERROR_KEYS = {"error", "exception", "message", "msg"}


@dataclasses.dataclass
class ShortcutAction:
    name: str
    description: str
    keys: List[str]
    app: str = "global"
    risk: str = "low"  # low | medium | high
    requires_approval: bool = False


@dataclasses.dataclass
class DesktopObservation:
    created_at: str
    source: str
    app: str
    location: str
    summary: str
    raw_tail: str
    text_profile: Dict[str, Any]
    markers: Dict[str, str]
    confidence: float


class DesktopIORegistry:
    def __init__(self, root: Path, state_path: Optional[Path] = None):
        self.root = root.resolve()
        self.state_path = state_path or (self.root / ".sg_agent" / "desktop_state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.shortcuts: Dict[str, ShortcutAction] = {}
        self.log_paths: List[Path] = []
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self.state: Dict[str, Any] = {"shortcuts": {}, "log_paths": [], "observations": [], "current_by_app": {}}
            return
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.state.setdefault("shortcuts", {})
            self.state.setdefault("log_paths", [])
            self.state.setdefault("observations", [])
            self.state.setdefault("current_by_app", {})
            for name, data in self.state.get("shortcuts", {}).items():
                self.shortcuts[name] = ShortcutAction(**data)
            self.log_paths = [Path(p) for p in self.state.get("log_paths", [])]
        except Exception:
            self.state = {"shortcuts": {}, "log_paths": [], "observations": [], "current_by_app": {}}

    def save(self) -> None:
        self.state["shortcuts"] = {name: dataclasses.asdict(action) for name, action in self.shortcuts.items()}
        self.state["log_paths"] = [str(p) for p in self.log_paths]
        self.state.setdefault("observations", [])
        self.state.setdefault("current_by_app", {})
        tmp = self.state_path.with_name(f".{self.state_path.name}.tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def register_shortcut(self, action: ShortcutAction) -> Dict[str, Any]:
        self.shortcuts[action.name] = action
        self.save()
        return {"ok": True, "shortcut": dataclasses.asdict(action)}

    def execute_shortcut(
        self,
        name: str,
        dry_run: bool = False,
        method: str = "powershell_sendkeys",
        delay_ms: int = 120,
    ) -> Dict[str, Any]:
        """Execute a registered shortcut.

        Conservative by design:
        - Only registered shortcut names can be executed.
        - No free typing/clicking is supported.
        - On non-Windows, only dry_run is supported for now.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "shortcut name cannot be empty"}
        action = self.shortcuts.get(name)
        if not action:
            return {"ok": False, "error": f"shortcut not registered: {name}", "known_shortcuts": list(self.shortcuts.keys())}
        sendkeys = self._to_windows_sendkeys(action.keys)
        execution = {
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "name": name,
            "shortcut": dataclasses.asdict(action),
            "method": method,
            "dry_run": dry_run,
            "sendkeys": sendkeys,
            "platform": platform.system(),
        }
        if dry_run:
            execution.update({"ok": True, "message": "dry run only; no keys sent"})
            self._record_execution(execution)
            return execution
        if platform.system().lower() != "windows":
            execution.update({"ok": False, "error": "actual shortcut execution is currently supported only on Windows; use dry_run elsewhere"})
            self._record_execution(execution)
            return execution
        if method != "powershell_sendkeys":
            execution.update({"ok": False, "error": f"unsupported shortcut method: {method}"})
            self._record_execution(execution)
            return execution
        ps_sendkeys = sendkeys.replace("'", "''")
        ps = (
            "$wshell = New-Object -ComObject WScript.Shell; "
            f"Start-Sleep -Milliseconds {max(0, int(delay_ms))}; "
            f"$wshell.SendKeys('{ps_sendkeys}')"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=8,
            )
            execution.update(
                {
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": sanitize_for_display(proc.stdout, max_string=2000),
                    "stderr": sanitize_for_display(proc.stderr, max_string=2000),
                }
            )
        except Exception as e:
            execution.update({"ok": False, "error": str(e)})
        self._record_execution(execution)
        return execution

    def _record_execution(self, execution: Dict[str, Any]) -> None:
        self.state.setdefault("executions", []).append(execution)
        self.state["executions"] = self.state.get("executions", [])[-200:]
        self.save()

    def _to_windows_sendkeys(self, keys: List[str]) -> str:
        modifiers = []
        normals = []
        for raw in keys:
            key = str(raw).strip()
            low = key.lower()
            if low in {"ctrl", "control"}:
                modifiers.append("^")
            elif low == "alt":
                modifiers.append("%")
            elif low == "shift":
                modifiers.append("+")
            elif low in {"win", "windows", "meta", "cmd", "command"}:
                # WScript SendKeys does not reliably support Windows key. Keep explicit.
                normals.append("{WIN}")
            else:
                normals.append(self._normal_key_to_sendkeys(key))
        if not normals:
            return "".join(modifiers)
        # Common shortcut form: modifiers + final key. If multiple normal keys exist, send sequentially.
        first = "".join(modifiers) + normals[0]
        return first + "".join(normals[1:])

    def _normal_key_to_sendkeys(self, key: str) -> str:
        low = key.lower()
        special = {
            "enter": "{ENTER}",
            "return": "{ENTER}",
            "tab": "{TAB}",
            "esc": "{ESC}",
            "escape": "{ESC}",
            "space": " ",
            "backspace": "{BACKSPACE}",
            "delete": "{DELETE}",
            "del": "{DELETE}",
            "insert": "{INSERT}",
            "home": "{HOME}",
            "end": "{END}",
            "pageup": "{PGUP}",
            "pgup": "{PGUP}",
            "pagedown": "{PGDN}",
            "pgdn": "{PGDN}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
        }
        if low in special:
            return special[low]
        if re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", low):
            return "{" + low.upper() + "}"
        if len(key) == 1:
            return key.lower()
        # For unknown named keys, try SendKeys named-key syntax.
        return "{" + key.upper() + "}"

    def register_log_path(self, path: str) -> Dict[str, Any]:
        p = Path(path).expanduser().resolve()
        # Log files can be outside workspace because many apps write logs elsewhere.
        # We only read tails and sanitize; future policy can restrict this.
        if p not in self.log_paths:
            self.log_paths.append(p)
        self.save()
        return {"ok": True, "log_path": str(p), "exists": p.exists()}

    def read_log_tail(self, path: Path, max_chars: int = 8000) -> str:
        if not path.exists() or not path.is_file():
            return ""
        data = path.read_bytes()
        tail = data[-max_chars:]
        return tail.decode("utf-8", errors="replace")

    def observe_from_logs(self, max_chars_per_log: int = 8000) -> Dict[str, Any]:
        observations: List[Dict[str, Any]] = []
        for p in self.log_paths:
            raw = self.read_log_tail(p, max_chars=max_chars_per_log)
            if not raw:
                continue
            safe_raw = sanitize_for_display(raw, max_string=max_chars_per_log)
            lines = [line for line in safe_raw.splitlines() if line.strip()]
            tail_line = lines[-1] if lines else ""
            app = self._guess_app_name(p, lines)
            markers = self._extract_recent_markers(lines)
            location = self._build_location(markers, lines)
            summary = self._build_summary(markers, tail_line)
            confidence = self._confidence(markers, location)
            obs = DesktopObservation(
                created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                source=str(p),
                app=app,
                location=location,
                summary=summary,
                raw_tail=safe_raw,
                text_profile=detect_text_profile(safe_raw).to_dict(),
                markers=markers,
                confidence=confidence,
            )
            obs_dict = dataclasses.asdict(obs)
            observations.append(obs_dict)
            self.state.setdefault("observations", []).append(obs_dict)
            self._update_current_state(obs_dict)
        self.state["observations"] = self.state.get("observations", [])[-300:]
        self.save()
        return {
            "ok": True,
            "observations": observations,
            "state": self.get_state_snapshot(),
            "known_shortcuts": [dataclasses.asdict(s) for s in self.shortcuts.values()],
        }

    def _guess_app_name(self, path: Path, lines: List[str]) -> str:
        markers = self._extract_recent_markers(lines)
        for key in ("app", "application", "process", "service"):
            if key in markers:
                return markers[key]
        return path.stem

    def _extract_recent_markers(self, lines: List[str]) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for line in lines[-80:]:
            for match in KEY_VALUE_RE.finditer(line):
                key = match.group("key").strip().lower()
                value = match.group("value").strip().strip("'\"")
                if len(value) > 500:
                    value = value[-500:]
                merged[key] = value
        return merged

    def _build_location(self, markers: Dict[str, str], lines: List[str]) -> str:
        parts: List[str] = []
        for keys, label in ((SCREEN_KEYS, "screen"), (ROUTE_KEYS, "route"), (STATE_KEYS, "state"), (TITLE_KEYS, "title")):
            for key in keys:
                if key in markers:
                    parts.append(f"{label}={markers[key]}")
                    break
        if parts:
            return " ".join(parts)[-500:]
        return self._guess_location(lines)

    def _build_summary(self, markers: Dict[str, str], tail_line: str) -> str:
        parts: List[str] = []
        for keys, label in ((ACTION_KEYS, "action"), (RESULT_KEYS, "result"), (ERROR_KEYS, "message")):
            for key in keys:
                if key in markers:
                    parts.append(f"{label}={markers[key]}")
                    break
        if parts:
            return " ".join(parts)[-600:]
        return tail_line[-600:] if tail_line else "No recent log line"

    def _confidence(self, markers: Dict[str, str], location: str) -> float:
        score = 0.15
        if any(k in markers for k in SCREEN_KEYS):
            score += 0.25
        if any(k in markers for k in ROUTE_KEYS):
            score += 0.25
        if any(k in markers for k in STATE_KEYS):
            score += 0.15
        if any(k in markers for k in ACTION_KEYS | RESULT_KEYS | ERROR_KEYS):
            score += 0.10
        if location != "unknown":
            score += 0.10
        return round(min(score, 1.0), 3)

    def _update_current_state(self, obs: Dict[str, Any]) -> None:
        app = str(obs.get("app") or "unknown")
        markers = obs.get("markers") or {}
        current = {
            "app": app,
            "last_seen_at": obs.get("created_at"),
            "source": obs.get("source"),
            "location": obs.get("location"),
            "summary": obs.get("summary"),
            "confidence": obs.get("confidence"),
            "screen": self._first_marker(markers, SCREEN_KEYS),
            "route": self._first_marker(markers, ROUTE_KEYS),
            "state": self._first_marker(markers, STATE_KEYS),
            "title": self._first_marker(markers, TITLE_KEYS),
            "last_action": self._first_marker(markers, ACTION_KEYS),
            "last_result": self._first_marker(markers, RESULT_KEYS),
            "last_message": self._first_marker(markers, ERROR_KEYS),
        }
        self.state.setdefault("current_by_app", {})[app] = current

    @staticmethod
    def _first_marker(markers: Dict[str, str], keys: set[str]) -> Optional[str]:
        for key in keys:
            if key in markers:
                return markers[key]
        return None

    def _guess_location(self, lines: List[str]) -> str:
        # Fallback heuristic; apps should prefer explicit markers.
        for line in reversed(lines[-50:]):
            lower = line.lower()
            for marker in ("route=", "path=", "url=", "screen=", "view=", "window=", "page="):
                if marker in lower:
                    return line.strip()[-300:]
        return "unknown"

    def get_state_snapshot(self, limit: int = 30) -> Dict[str, Any]:
        observations = self.state.get("observations", [])[-limit:]
        return {
            "ok": True,
            "state_path": str(self.state_path),
            "registered_logs": [{"path": str(p), "exists": p.exists()} for p in self.log_paths],
            "current_by_app": self.state.get("current_by_app", {}),
            "timeline": observations,
            "shortcuts": [dataclasses.asdict(s) for s in self.shortcuts.values()],
            "executions": self.state.get("executions", [])[-limit:],
        }

    def suggest_shortcut(self, intent: str, app: Optional[str] = None) -> Dict[str, Any]:
        intent_l = intent.lower()
        candidates: List[ShortcutAction] = []
        for action in self.shortcuts.values():
            if app and action.app not in {app, "global"}:
                continue
            hay = f"{action.name} {action.description} {' '.join(action.keys)}".lower()
            if any(token in hay for token in intent_l.split() if len(token) >= 2):
                candidates.append(action)
        return {"ok": True, "intent": intent, "candidates": [dataclasses.asdict(c) for c in candidates[:10]]}