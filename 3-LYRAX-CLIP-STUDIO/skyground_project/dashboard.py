"""
Dashboard and admin supervision layer for SkyGround Local Coding Agent.

Dependency-free implementation based on Python standard library:
- ThreadingHTTPServer
- Polling JSON API
- Dark-mode single-page dashboard

The dashboard provides:
- Live status/events
- Approval queue for writes/commands
- Ask-admin queue for questions
- Runtime config updates
- Session permissions / access grants
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import fnmatch
import html
import json
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from security import mask_secrets as shared_mask_secrets, sanitize_for_display as shared_sanitize_for_display


JsonDict = Dict[str, Any]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def local_now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def shorten(value: Any, limit: int = 6000) -> Any:
    """Keep dashboard payloads reasonably small."""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + f"\n... [truncated {len(value) - limit} chars]"
        return value
    if isinstance(value, list):
        return [shorten(v, limit=limit) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k): shorten(v, limit=limit) for k, v in value.items()}
    return value


def normalize_list(value: Any) -> List[str]:
    """Accept list or textarea string and return clean policy entries."""
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        text = str(value).replace(",", "\n")
        raw_items = text.splitlines()
    items: List[str] = []
    for item in raw_items:
        s = str(item).strip()
        if not s or s.startswith("#"):
            continue
        items.append(s)
    return items


def match_any(text: str, patterns: List[str]) -> bool:
    """Case-insensitive fnmatch against a normalized text value."""
    if not patterns:
        return False
    value = text.replace("\\", "/").lower()
    for pattern in patterns:
        p = pattern.replace("\\", "/").lower()
        if fnmatch.fnmatch(value, p):
            return True
    return False


def contains_any(text: str, fragments: List[str]) -> bool:
    value = text.lower()
    return any(fragment.lower() in value for fragment in fragments if fragment)


def mask_secrets(text: str, keep: int = 4) -> str:
    """Best-effort masking for tokens/keys in URLs, headers, logs, and config snippets."""
    if not text:
        return text
    masked = text
    masked = re_sub_secret(r"(?i)(api[_-]?key|token|access[_-]?token|auth|authorization|secret|password)(=|:)([^&\s,}]+)", masked, keep=keep)
    masked = re_sub_secret(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{12,})", masked, keep=keep, group=2)
    return masked


def re_sub_secret(pattern: str, text: str, keep: int = 4, group: int = 3) -> str:
    import re

    def repl(match: Any) -> str:
        value = match.group(group)
        if len(value) <= keep:
            replacement = "****"
        else:
            replacement = value[:keep] + "****"
        parts = list(match.groups())
        parts[group - 1] = replacement
        return "".join(parts)

    return re.sub(pattern, repl, text)


@dataclasses.dataclass
class ApprovalRequest:
    id: str
    kind: str
    title: str
    details: JsonDict
    created_at: str
    status: str = "pending"  # pending | approved | rejected | expired
    decided_at: Optional[str] = None
    decision_reason: str = ""


@dataclasses.dataclass
class AdminQuestion:
    id: str
    question: str
    options: List[str]
    created_at: str
    status: str = "pending"  # pending | answered | expired
    answer: str = ""
    answered_at: Optional[str] = None


def default_permissions() -> JsonDict:
    return {
        "read_only_mode": False,
        "auto_approve_writes": False,
        "auto_approve_commands": False,
        "auto_answer_questions": False,
        "auto_question_answer": "",

        # Granular session policy. Empty allowlists mean "any" when auto-approve is enabled.
        # Denylists always win.
        "allowed_write_globs": [],
        "denied_write_globs": [],
        "reject_unmatched_writes": False,
        "allowed_command_globs": [],
        "denied_command_fragments": [],
        "reject_unmatched_commands": False,
    }


COMMON_DENIED_COMMAND_FRAGMENTS = [
    "rm -rf",
    "del /s",
    "rmdir /s",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    "reg delete",
    "Remove-Item -Recurse -Force",
]


POLICY_TEMPLATES: Dict[str, JsonDict] = {
    "cautious_manual": {
        "label": "Cautious Manual",
        "description": "حالت پیش‌فرض امن: همه write/commandها approval دستی می‌خواهند، با deny-list پایه.",
        "permissions": {
            "read_only_mode": False,
            "auto_approve_writes": False,
            "auto_approve_commands": False,
            "denied_write_globs": [".env", "*.pem", "*.key", "**/secrets/**", "**/.env*"],
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
        },
    },
    "read_only_review": {
        "label": "Read-only Review",
        "description": "فقط بررسی و خواندن؛ همه write/edit/commandها reject می‌شوند.",
        "permissions": {
            "read_only_mode": True,
            "auto_approve_writes": False,
            "auto_approve_commands": False,
            "reject_unmatched_writes": True,
            "reject_unmatched_commands": True,
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
        },
    },
    "safe_python": {
        "label": "Safe Python",
        "description": "مناسب پروژه Python: اجرای خودکار تست/لینت امن؛ ویرایش‌ها همچنان approval می‌خواهند.",
        "permissions": {
            "read_only_mode": False,
            "auto_approve_writes": False,
            "auto_approve_commands": True,
            "allowed_write_globs": ["src/**", "tests/**", "*.py", "pyproject.toml", "README.md", "docs/**"],
            "denied_write_globs": [".env", "*.pem", "*.key", "**/secrets/**", "**/.env*"],
            "allowed_command_globs": [
                "python -m pytest*",
                "pytest*",
                "python -m unittest*",
                "python -m ruff check*",
                "ruff check*",
                "python -m mypy*",
                "mypy*",
            ],
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
            "reject_unmatched_commands": True,
        },
    },
    "safe_node": {
        "label": "Safe Node",
        "description": "مناسب پروژه Node/Frontend: اجرای خودکار test/build/lint؛ ویرایش‌ها approval می‌خواهند.",
        "permissions": {
            "read_only_mode": False,
            "auto_approve_writes": False,
            "auto_approve_commands": True,
            "allowed_write_globs": ["src/**", "tests/**", "test/**", "app/**", "components/**", "README.md", "docs/**"],
            "denied_write_globs": [".env", ".env.*", "*.pem", "*.key", "**/secrets/**"],
            "allowed_command_globs": [
                "npm test*",
                "npm run test*",
                "npm run build*",
                "npm run lint*",
                "pnpm test*",
                "pnpm run test*",
                "pnpm run build*",
                "pnpm run lint*",
                "yarn test*",
                "yarn build*",
                "yarn lint*",
            ],
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
            "reject_unmatched_commands": True,
        },
    },
    "docs_only": {
        "label": "Docs Only",
        "description": "فقط مستندات auto-approve می‌شوند؛ commandها approval دستی می‌خواهند.",
        "permissions": {
            "read_only_mode": False,
            "auto_approve_writes": True,
            "auto_approve_commands": False,
            "allowed_write_globs": ["README.md", "docs/**", "*.md", "**/*.md"],
            "denied_write_globs": [".env", "*.pem", "*.key", "**/secrets/**"],
            "reject_unmatched_writes": True,
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
        },
    },
    "src_tests_dev": {
        "label": "Src + Tests Development",
        "description": "ویرایش خودکار فقط در src/tests و اجرای خودکار تست‌های رایج.",
        "permissions": {
            "read_only_mode": False,
            "auto_approve_writes": True,
            "auto_approve_commands": True,
            "allowed_write_globs": ["src/**", "tests/**", "test/**"],
            "denied_write_globs": [".env", ".env.*", "*.pem", "*.key", "**/secrets/**"],
            "reject_unmatched_writes": True,
            "allowed_command_globs": ["python -m pytest*", "pytest*", "npm test*", "npm run test*", "npm run build*", "npm run lint*"],
            "denied_command_fragments": COMMON_DENIED_COMMAND_FRAGMENTS,
            "reject_unmatched_commands": True,
        },
    },
}


class AdminControlCenter:
    """Shared control plane between the agent runtime and dashboard HTTP API."""

    def __init__(self, approval_timeout_sec: int = 0):
        self.approval_timeout_sec = approval_timeout_sec
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.approvals: Dict[str, ApprovalRequest] = {}
        self.questions: Dict[str, AdminQuestion] = {}
        self.events: List[JsonDict] = []
        self.max_events = 1000
        self.server_url: Optional[str] = None
        self.dashboard_enabled = False
        self.status_provider: Optional[Callable[[], JsonDict]] = None
        self.config_getter: Optional[Callable[[], JsonDict]] = None
        self.config_updater: Optional[Callable[[JsonDict], JsonDict]] = None
        self.task_submitter: Optional[Callable[[str, str], JsonDict]] = None
        self.task_getter: Optional[Callable[[], JsonDict]] = None
        self.task_controller: Optional[Callable[[str, Optional[str]], JsonDict]] = None
        self.agent_ops_handler: Optional[Callable[[str, JsonDict], JsonDict]] = None
        self.emergency_stop_active = False
        self.policy_path: Optional[Path] = None
        self.policy_last_loaded_at: Optional[str] = None
        self.policy_last_saved_at: Optional[str] = None

        # Session-level admin grants/policies. They can optionally be persisted by dashboard action.
        self.permissions: JsonDict = default_permissions()

    # ---------- integration callbacks ----------

    def set_status_provider(self, fn: Callable[[], JsonDict]) -> None:
        self.status_provider = fn

    def set_config_callbacks(self, getter: Callable[[], JsonDict], updater: Callable[[JsonDict], JsonDict]) -> None:
        self.config_getter = getter
        self.config_updater = updater

    def set_task_callbacks(
        self,
        submitter: Callable[[str, str], JsonDict],
        getter: Callable[[], JsonDict],
        controller: Callable[[str, Optional[str]], JsonDict],
    ) -> None:
        self.task_submitter = submitter
        self.task_getter = getter
        self.task_controller = controller

    def set_agent_ops_handler(self, handler: Callable[[str, JsonDict], JsonDict]) -> None:
        self.agent_ops_handler = handler

    def set_server_url(self, url: str) -> None:
        with self.lock:
            self.server_url = url
            self.dashboard_enabled = True
        self.emit("dashboard.started", "Dashboard started", {"url": url})

    def set_policy_storage(self, path: Path, auto_load: bool = True) -> None:
        self.policy_path = Path(path)
        if auto_load and self.policy_path.exists():
            self.load_policy_from_disk()
        else:
            self.emit("policy.storage", "Policy storage configured", {"path": str(self.policy_path), "exists": self.policy_path.exists()})

    def get_policy_templates(self) -> List[JsonDict]:
        return [
            {
                "id": template_id,
                "label": data.get("label", template_id),
                "description": data.get("description", ""),
                "permissions": data.get("permissions", {}),
            }
            for template_id, data in POLICY_TEMPLATES.items()
        ]

    # ---------- events ----------

    def emit(self, event_type: str, message: str, data: Optional[JsonDict] = None, level: str = "info") -> None:
        safe_message = shared_mask_secrets(message)
        safe_data = shared_sanitize_for_display(data or {}, max_string=4000)
        event = {
            "id": str(uuid.uuid4()),
            "time": local_now(),
            "utc": utc_now(),
            "type": event_type,
            "level": level,
            "message": safe_message,
            "data": shorten(safe_data, limit=4000),
        }
        with self.lock:
            self.events.append(event)
            if len(self.events) > self.max_events:
                self.events = self.events[-self.max_events :]
            self.condition.notify_all()

    def get_events(self, limit: int = 200) -> List[JsonDict]:
        with self.lock:
            return list(self.events[-limit:])

    # ---------- granular policy ----------

    def _approval_paths(self, details: JsonDict) -> List[str]:
        paths: List[str] = []
        raw_paths = details.get("paths")
        if isinstance(raw_paths, list):
            paths.extend(str(p).replace("\\", "/") for p in raw_paths if str(p).strip())
        raw_path = details.get("path")
        if raw_path:
            paths.append(str(raw_path).replace("\\", "/"))
        return list(dict.fromkeys(paths))

    def _evaluate_policy(self, kind: str, title: str, details: JsonDict) -> JsonDict:
        """Return {action: ask|auto_approve|reject, reason, ...}. Denylists always win."""
        perms = self.permissions
        if perms.get("read_only_mode") and kind in {"write", "edit", "command", "shortcut"}:
            return {"action": "reject", "reason": "read_only_mode is enabled"}

        if kind in {"write", "edit"}:
            paths = self._approval_paths(details)
            allowed = normalize_list(perms.get("allowed_write_globs"))
            denied = normalize_list(perms.get("denied_write_globs"))
            denied_paths = [p for p in paths if match_any(p, denied)]
            if denied_paths:
                return {"action": "reject", "reason": "path denied by policy", "paths": denied_paths}

            unmatched = [p for p in paths if allowed and not match_any(p, allowed)]
            if unmatched and perms.get("reject_unmatched_writes"):
                return {"action": "reject", "reason": "path not in allowed_write_globs", "paths": unmatched}

            if perms.get("auto_approve_writes"):
                if allowed and unmatched:
                    return {"action": "ask", "reason": "auto-write enabled, but some paths are outside allowlist", "paths": unmatched}
                return {"action": "auto_approve", "reason": "auto_approve_writes policy matched", "paths": paths}

            return {"action": "ask", "reason": "manual approval required", "paths": paths}

        if kind == "command":
            command = str(details.get("command") or title)
            allowed_cmds = normalize_list(perms.get("allowed_command_globs"))
            denied_fragments = normalize_list(perms.get("denied_command_fragments"))
            if contains_any(command, denied_fragments):
                return {"action": "reject", "reason": "command contains denied fragment", "command": command}

            matched_allowed = (not allowed_cmds) or match_any(command, allowed_cmds)
            if not matched_allowed and perms.get("reject_unmatched_commands"):
                return {"action": "reject", "reason": "command not in allowed_command_globs", "command": command}

            if perms.get("auto_approve_commands"):
                if not matched_allowed:
                    return {"action": "ask", "reason": "auto-command enabled, but command is outside allowlist", "command": command}
                return {"action": "auto_approve", "reason": "auto_approve_commands policy matched", "command": command}

            return {"action": "ask", "reason": "manual approval required", "command": command}

        return {"action": "ask", "reason": "manual approval required"}

    # ---------- approvals ----------

    def request_approval(
        self,
        kind: str,
        title: str,
        details: JsonDict,
        console_fallback: Optional[Callable[[], bool]] = None,
        timeout_sec: Optional[int] = None,
    ) -> bool:
        """Create an approval request and wait for admin decision.

        If dashboard is not enabled, falls back to console_fallback when available.
        """
        with self.lock:
            if self.emergency_stop_active:
                self.emit(
                    "approval.emergency_rejected",
                    f"Rejected by emergency stop: {title}",
                    {"kind": kind, "details": details},
                    level="error",
                )
                return False
            policy = self._evaluate_policy(kind, title, details)
            if policy.get("action") == "reject":
                self.emit(
                    "approval.policy_rejected",
                    f"Rejected by policy: {title}",
                    {"kind": kind, "reason": policy.get("reason"), "policy": policy, "details": details},
                    level="warning",
                )
                return False
            if policy.get("action") == "auto_approve":
                self.emit(
                    "approval.policy_auto_approved",
                    f"Auto-approved by policy: {title}",
                    {"kind": kind, "reason": policy.get("reason"), "policy": policy, "details": details},
                )
                return True
            dashboard_enabled = self.dashboard_enabled
            server_url = self.server_url

        if not dashboard_enabled:
            if console_fallback is not None:
                return bool(console_fallback())
            return False

        req_id = str(uuid.uuid4())
        request_details = dict(details)
        request_details["policy"] = policy
        req = ApprovalRequest(
            id=req_id,
            kind=kind,
            title=shared_mask_secrets(title),
            details=shorten(shared_sanitize_for_display(request_details, max_string=8000), limit=8000),
            created_at=local_now(),
        )
        with self.condition:
            self.approvals[req_id] = req
            self.emit("approval.requested", title, {"approval_id": req_id, "kind": kind, "details": details})
            self.condition.notify_all()

            print("\n[admin approval required]")
            print(f"Open dashboard: {server_url}")
            print(f"Approval: {title}")

            timeout = self.approval_timeout_sec if timeout_sec is None else timeout_sec
            deadline = None if not timeout or timeout <= 0 else time.time() + timeout
            while req.status == "pending":
                remaining = None if deadline is None else max(0.0, deadline - time.time())
                if deadline is not None and remaining <= 0:
                    req.status = "expired"
                    req.decided_at = local_now()
                    self.emit("approval.expired", title, {"approval_id": req_id}, level="warning")
                    self.condition.notify_all()
                    return False
                self.condition.wait(timeout=remaining if remaining is not None else 1.0)

            approved = req.status == "approved"
            self.emit(
                "approval.decided",
                f"{'Approved' if approved else 'Rejected'}: {title}",
                {"approval_id": req_id, "status": req.status, "reason": req.decision_reason},
                level="info" if approved else "warning",
            )
            return approved

    def decide_approval(self, approval_id: str, approved: bool, reason: str = "") -> JsonDict:
        with self.condition:
            req = self.approvals.get(approval_id)
            if not req:
                return {"ok": False, "error": "approval not found"}
            if req.status != "pending":
                return {"ok": False, "error": f"approval already {req.status}"}
            req.status = "approved" if approved else "rejected"
            req.decided_at = local_now()
            req.decision_reason = reason
            self.condition.notify_all()
            return {"ok": True, "approval": dataclasses.asdict(req)}

    # ---------- questions ----------

    def ask_admin(
        self,
        question: str,
        options: Optional[List[str]] = None,
        console_fallback: Optional[Callable[[], str]] = None,
        timeout_sec: int = 0,
    ) -> JsonDict:
        options = options or []
        with self.lock:
            if self.emergency_stop_active:
                self.emit("question.emergency_rejected", question, {}, level="error")
                return {"ok": False, "error": "emergency stop is active"}
            if self.permissions.get("auto_answer_questions"):
                answer = str(self.permissions.get("auto_question_answer") or "")
                self.emit("question.auto_answered", question, {"answer": answer})
                return {"ok": True, "answer": answer, "auto": True}
            dashboard_enabled = self.dashboard_enabled
            server_url = self.server_url

        if not dashboard_enabled:
            if console_fallback is not None:
                return {"ok": True, "answer": console_fallback(), "auto": False}
            return {"ok": False, "error": "dashboard disabled and no console fallback"}

        qid = str(uuid.uuid4())
        q = AdminQuestion(id=qid, question=question, options=options, created_at=local_now())
        with self.condition:
            self.questions[qid] = q
            self.emit("question.requested", question, {"question_id": qid, "options": options})
            self.condition.notify_all()

            print("\n[admin answer required]")
            print(f"Open dashboard: {server_url}")
            print(f"Question: {question}")

            deadline = None if timeout_sec <= 0 else time.time() + timeout_sec
            while q.status == "pending":
                remaining = None if deadline is None else max(0.0, deadline - time.time())
                if deadline is not None and remaining <= 0:
                    q.status = "expired"
                    q.answered_at = local_now()
                    self.emit("question.expired", question, {"question_id": qid}, level="warning")
                    self.condition.notify_all()
                    return {"ok": False, "error": "question expired", "question_id": qid}
                self.condition.wait(timeout=remaining if remaining is not None else 1.0)

            return {"ok": True, "answer": q.answer, "question_id": qid, "auto": False}

    def answer_question(self, question_id: str, answer: str) -> JsonDict:
        with self.condition:
            q = self.questions.get(question_id)
            if not q:
                return {"ok": False, "error": "question not found"}
            if q.status != "pending":
                return {"ok": False, "error": f"question already {q.status}"}
            q.status = "answered"
            q.answer = answer
            q.answered_at = local_now()
            self.emit("question.answered", q.question, {"question_id": question_id, "answer": answer})
            self.condition.notify_all()
            return {"ok": True, "question": dataclasses.asdict(q)}

    # ---------- permissions/config/state ----------

    def update_permissions(self, updates: JsonDict) -> JsonDict:
        allowed = set(self.permissions.keys())
        list_fields = {
            "allowed_write_globs",
            "denied_write_globs",
            "allowed_command_globs",
            "denied_command_fragments",
        }
        with self.lock:
            for k, v in updates.items():
                if k not in allowed:
                    continue
                if k in list_fields:
                    self.permissions[k] = normalize_list(v)
                elif isinstance(self.permissions[k], bool):
                    self.permissions[k] = bool(v)
                else:
                    self.permissions[k] = str(v)
            self.emit("permissions.updated", "Session permissions updated", {"permissions": self.permissions})
            return {"ok": True, "permissions": dict(self.permissions)}

    def apply_policy_template(self, template_id: str, merge: bool = False) -> JsonDict:
        template = POLICY_TEMPLATES.get(template_id)
        if not template:
            return {"ok": False, "error": f"unknown policy template: {template_id}"}
        template_perms = dict(template.get("permissions") or {})
        with self.lock:
            if not merge:
                self.permissions = default_permissions()
            result = self.update_permissions(template_perms)
            self.emit(
                "policy.template_applied",
                f"Policy template applied: {template.get('label', template_id)}",
                {"template_id": template_id, "merge": merge, "permissions": self.permissions},
            )
            return {"ok": True, "template_id": template_id, "merge": merge, "permissions": dict(self.permissions), "update_result": result}

    def save_policy_to_disk(self) -> JsonDict:
        if self.policy_path is None:
            return {"ok": False, "error": "policy storage path is not configured"}
        with self.lock:
            payload = {
                "version": 1,
                "saved_at": local_now(),
                "permissions": dict(self.permissions),
            }
            path = self.policy_path
            path.parent.mkdir(parents=True, exist_ok=True)
            backup_path: Optional[Path] = None
            if path.exists():
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_path = path.with_name(f"{path.name}.bak-{stamp}")
                backup_path.write_bytes(path.read_bytes())
            tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:8]}")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            self.policy_last_saved_at = payload["saved_at"]
            self.emit(
                "policy.saved",
                "Policy saved to disk",
                {"path": str(path), "backup": str(backup_path) if backup_path else None, "permissions": self.permissions},
            )
            return {"ok": True, "path": str(path), "backup": str(backup_path) if backup_path else None, "saved_at": self.policy_last_saved_at}

    def load_policy_from_disk(self) -> JsonDict:
        if self.policy_path is None:
            return {"ok": False, "error": "policy storage path is not configured"}
        path = self.policy_path
        if not path.exists():
            return {"ok": False, "error": f"policy file does not exist: {path}"}
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"ok": False, "error": f"failed to read policy file: {e}"}
        permissions = obj.get("permissions", obj) if isinstance(obj, dict) else {}
        if not isinstance(permissions, dict):
            return {"ok": False, "error": "policy file must contain an object or {permissions: object}"}
        with self.lock:
            self.permissions = default_permissions()
            result = self.update_permissions(permissions)
            self.policy_last_loaded_at = local_now()
            self.emit("policy.loaded", "Policy loaded from disk", {"path": str(path), "permissions": self.permissions})
            return {"ok": True, "path": str(path), "loaded_at": self.policy_last_loaded_at, "permissions": dict(self.permissions), "update_result": result}

    def reset_policy(self, delete_file: bool = False) -> JsonDict:
        with self.lock:
            self.permissions = default_permissions()
            deleted = False
            if delete_file and self.policy_path is not None and self.policy_path.exists():
                self.policy_path.unlink()
                deleted = True
            self.emit("policy.reset", "Session policy reset", {"delete_file": delete_file, "deleted": deleted})
            return {"ok": True, "permissions": dict(self.permissions), "deleted_file": deleted}

    # ---------- task control / emergency ----------

    def submit_task(self, task: str, source: str = "dashboard") -> JsonDict:
        if not self.task_submitter:
            return {"ok": False, "error": "task submitter not registered"}
        if self.emergency_stop_active:
            return {"ok": False, "error": "emergency stop is active"}
        result = self.task_submitter(task, source)
        self.emit("task.submitted_from_dashboard", "Task submitted", {"task": shorten(task, 1000), "result": result})
        return result

    def get_tasks(self) -> JsonDict:
        if not self.task_getter:
            return {"ok": True, "registered": False, "tasks": []}
        try:
            result = self.task_getter()
            result["registered"] = True
            return result
        except Exception as e:
            return {"ok": False, "registered": True, "error": str(e), "traceback": traceback.format_exc(limit=2)}

    def control_task(self, action: str, task_id: Optional[str] = None) -> JsonDict:
        if action == "emergency_stop":
            self.trigger_emergency_stop("dashboard")
        elif action == "clear_emergency_stop":
            self.clear_emergency_stop()
        if not self.task_controller:
            return {"ok": False, "error": "task controller not registered"}
        result = self.task_controller(action, task_id)
        self.emit("task.control", f"Task control: {action}", {"task_id": task_id, "result": result}, level="warning" if action == "emergency_stop" else "info")
        return result

    def agent_op(self, operation: str, payload: JsonDict) -> JsonDict:
        if not self.agent_ops_handler:
            return {"ok": False, "error": "agent operations handler not registered"}
        try:
            result = self.agent_ops_handler(operation, payload)
            self.emit("agent.op", f"Agent operation: {operation}", {"payload": payload, "result": result}, level="info" if result.get("ok") else "warning")
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e), "traceback": traceback.format_exc(limit=2)}
            self.emit("agent.op.error", f"Agent operation failed: {operation}", result, level="error")
            return result

    def trigger_emergency_stop(self, source: str = "system") -> JsonDict:
        with self.condition:
            self.emergency_stop_active = True
            self.permissions = default_permissions()
            self.permissions["read_only_mode"] = True
            for req in self.approvals.values():
                if req.status == "pending":
                    req.status = "rejected"
                    req.decided_at = local_now()
                    req.decision_reason = "emergency stop"
            for q in self.questions.values():
                if q.status == "pending":
                    q.status = "expired"
                    q.answered_at = local_now()
                    q.answer = "emergency stop"
            self.emit("emergency_stop", "Emergency stop activated", {"source": source}, level="error")
            self.condition.notify_all()
            return {"ok": True, "emergency_stop_active": True, "permissions": dict(self.permissions)}

    def clear_emergency_stop(self) -> JsonDict:
        with self.condition:
            self.emergency_stop_active = False
            self.emit("emergency_stop.cleared", "Emergency stop cleared", {}, level="warning")
            self.condition.notify_all()
            return {"ok": True, "emergency_stop_active": False}

    # ---------- external prompt API playground ----------

    def call_external_prompt_api(self, request: JsonDict) -> JsonDict:
        """Proxy one prompt to a user-provided API endpoint.

        This is intentionally generic so the user can paste the same endpoint/body they already use
        from PowerShell. Secrets are not stored server-side and are masked in events.
        """
        endpoint = str(request.get("endpoint") or request.get("url") or "").strip()
        prompt = str(request.get("prompt") or "")
        method = str(request.get("method") or "POST").upper()
        body_template = str(request.get("body_template") or '{"prompt":{{prompt_json}}}')
        headers_raw = request.get("headers") or {}
        timeout = int(request.get("timeout_sec") or 120)

        if not endpoint:
            return {"ok": False, "error": "endpoint/url is required"}
        if method not in {"POST", "GET"}:
            return {"ok": False, "error": "method must be POST or GET"}
        model = str(request.get("model") or "").strip()
        if timeout <= 0 or timeout > 600:
            return {"ok": False, "error": "timeout_sec must be between 1 and 600"}

        if isinstance(headers_raw, str):
            try:
                headers = json.loads(headers_raw) if headers_raw.strip() else {}
            except json.JSONDecodeError as e:
                return {"ok": False, "error": f"headers must be valid JSON: {e}"}
        elif isinstance(headers_raw, dict):
            headers = dict(headers_raw)
        else:
            return {"ok": False, "error": "headers must be an object or JSON string"}

        if not isinstance(headers, dict):
            return {"ok": False, "error": "headers must decode to an object"}
        headers = {str(k): str(v) for k, v in headers.items()}

        safe_endpoint = mask_secrets(endpoint)
        started = time.time()
        try:
            if method == "GET":
                sep = "&" if "?" in endpoint else "?"
                url = endpoint + sep + urllib.parse.urlencode({"prompt": prompt})
                req = urllib.request.Request(url, headers=headers, method="GET")
                data = None
            else:
                rendered_body = (
                    body_template
                    .replace("{{model}}", model)
                    .replace("{{model_json}}", json.dumps(model, ensure_ascii=False))
                    .replace("{{prompt_json}}", json.dumps(prompt, ensure_ascii=False))
                    .replace("{{prompt}}", prompt)
                )
                body_bytes = rendered_body.encode("utf-8")
                if not any(k.lower() == "content-type" for k in headers):
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(endpoint, data=body_bytes, headers=headers, method="POST")
                data = rendered_body

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                text = raw.decode("utf-8", errors="replace")
                elapsed = round(time.time() - started, 3)
                parsed: Any = None
                if "json" in content_type.lower() or text.strip().startswith(("{", "[")):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = None
                self.emit(
                    "external_api.called",
                    "External prompt API call completed",
                    {"endpoint": safe_endpoint, "method": method, "status": resp.status, "elapsed_sec": elapsed, "response_chars": len(text)},
                )
                return {
                    "ok": True,
                    "status": resp.status,
                    "content_type": content_type,
                    "elapsed_sec": elapsed,
                    "text": text,
                    "json": parsed,
                    "request_preview": {"endpoint": safe_endpoint, "method": method, "body": mask_secrets(data or "")[:2000]},
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            self.emit("external_api.http_error", "External prompt API returned HTTP error", {"endpoint": safe_endpoint, "status": e.code, "body_preview": mask_secrets(body)[:1000]}, level="warning")
            return {"ok": False, "error": f"HTTP {e.code}: {e.reason}", "status": e.code, "text": body}
        except Exception as e:
            self.emit("external_api.error", "External prompt API call failed", {"endpoint": safe_endpoint, "error": str(e)}, level="error")
            return {"ok": False, "error": str(e), "traceback": traceback.format_exc(limit=2)}

    def get_state(self) -> JsonDict:
        with self.lock:
            approvals = [dataclasses.asdict(a) for a in self.approvals.values()]
            questions = [dataclasses.asdict(q) for q in self.questions.values()]
            permissions = dict(self.permissions)
            events = list(self.events[-250:])
            server_url = self.server_url
            policy_path = str(self.policy_path) if self.policy_path else None
            policy_exists = bool(self.policy_path and self.policy_path.exists())
        status: JsonDict = {}
        config: JsonDict = {}
        if self.status_provider:
            try:
                status = self.status_provider()
            except Exception as e:  # pragma: no cover - defensive
                status = {"ok": False, "error": str(e), "traceback": traceback.format_exc(limit=2)}
        if self.config_getter:
            try:
                config = self.config_getter()
            except Exception as e:  # pragma: no cover - defensive
                config = {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "server_url": server_url,
            "emergency_stop_active": self.emergency_stop_active,
            "status": shorten(status, limit=5000),
            "config": shorten(config, limit=5000),
            "tasks": shorten(self.get_tasks(), limit=5000),
            "permissions": permissions,
            "policy_storage": {
                "path": policy_path,
                "exists": policy_exists,
                "last_loaded_at": self.policy_last_loaded_at,
                "last_saved_at": self.policy_last_saved_at,
            },
            "policy_templates": self.get_policy_templates(),
            "approvals": approvals[-100:],
            "questions": questions[-100:],
            "events": events,
        }

    def update_config(self, updates: JsonDict) -> JsonDict:
        if not self.config_updater:
            return {"ok": False, "error": "config updater not registered"}
        try:
            result = self.config_updater(updates)
            self.emit("config.updated", "Runtime config update requested", {"updates": updates, "result": result})
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e), "traceback": traceback.format_exc(limit=3)}
            self.emit("config.update_failed", "Runtime config update failed", result, level="error")
            return result


class DashboardServer:
    def __init__(self, center: AdminControlCenter, host: str = "127.0.0.1", port: int = 8765, auth_token: str = ""):
        self.center = center
        self.host = host
        self.port = int(port)
        self.auth_token = auth_token
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start_background(self) -> str:
        center = self.center
        auth_token = self.auth_token

        class Handler(DashboardRequestHandler):
            control_center = center

        Handler.auth_token = auth_token
        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        actual_host, actual_port = self.httpd.server_address[:2]
        url = f"http://{actual_host}:{actual_port}"
        self.center.set_server_url(url)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="SkyGroundDashboard", daemon=True)
        self.thread.start()
        return url

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()


class DashboardRequestHandler(BaseHTTPRequestHandler):
    control_center: AdminControlCenter
    auth_token: str = ""

    server_version = "SkyGroundDashboard/0.5"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep terminal clean; events are visible in dashboard.
        return

    def _is_authorized(self) -> bool:
        if not self.auth_token:
            return True
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        header_token = self.headers.get("X-Admin-Token", "")
        return query_token == self.auth_token or header_token == self.auth_token

    def _send_auth_required(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._send_json({"ok": False, "error": "unauthorized"}, status=401)
        else:
            self._send_html(AUTH_HTML, status=401)

    # ---------- response helpers ----------

    def _send_json(self, obj: JsonDict, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> JsonDict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
            return {"value": obj}
        except json.JSONDecodeError:
            return {"_raw": raw}

    # ---------- HTTP ----------

    def do_GET(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self._send_auth_required()
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/":
            self._send_html(DASHBOARD_HTML)
            return
        if path == "/api/state":
            self._send_json(self.control_center.get_state())
            return
        if path == "/api/events":
            limit = int(qs.get("limit", ["200"])[0])
            self._send_json({"ok": True, "events": self.control_center.get_events(limit=limit)})
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self._send_auth_required()
            return
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path == "/api/approval":
            approval_id = str(body.get("id", ""))
            decision = str(body.get("decision", "")).lower()
            reason = str(body.get("reason", ""))
            if decision not in {"approve", "approved", "reject", "rejected"}:
                self._send_json({"ok": False, "error": "decision must be approve or reject"}, status=400)
                return
            self._send_json(self.control_center.decide_approval(approval_id, decision.startswith("approve"), reason))
            return

        if path == "/api/question":
            question_id = str(body.get("id", ""))
            answer = str(body.get("answer", ""))
            self._send_json(self.control_center.answer_question(question_id, answer))
            return

        if path == "/api/task":
            task = str(body.get("task", body.get("prompt", "")))
            source = str(body.get("source", "dashboard"))
            self._send_json(self.control_center.submit_task(task, source=source))
            return

        if path == "/api/task/control":
            action = str(body.get("action", ""))
            task_id = body.get("id", body.get("task_id"))
            self._send_json(self.control_center.control_task(action, str(task_id) if task_id else None))
            return

        if path == "/api/external_prompt":
            self._send_json(self.control_center.call_external_prompt_api(body))
            return

        if path == "/api/agent/op":
            operation = str(body.get("operation", body.get("op", "")))
            payload = body.get("payload", {})
            if not isinstance(payload, dict):
                payload = {"value": payload}
            self._send_json(self.control_center.agent_op(operation, payload))
            return

        if path == "/api/permissions":
            self._send_json(self.control_center.update_permissions(body))
            return

        if path == "/api/policy/template":
            template_id = str(body.get("id", body.get("template_id", "")))
            merge = bool(body.get("merge", False))
            self._send_json(self.control_center.apply_policy_template(template_id, merge=merge))
            return

        if path == "/api/policy/save":
            self._send_json(self.control_center.save_policy_to_disk())
            return

        if path == "/api/policy/load":
            self._send_json(self.control_center.load_policy_from_disk())
            return

        if path == "/api/policy/reset":
            self._send_json(self.control_center.reset_policy(delete_file=bool(body.get("delete_file", False))))
            return

        if path == "/api/config":
            self._send_json(self.control_center.update_config(body))
            return

        self._send_json({"ok": False, "error": "not found"}, status=404)


AUTH_HTML = r"""
<!doctype html>
<html lang="fa" dir="rtl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SkyGround Login</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;color:#edf4ff;font-family:system-ui,Tahoma}.box{width:min(440px,92vw);background:#111a2e;border:1px solid #22304d;border-radius:18px;padding:24px;box-shadow:0 18px 60px rgba(0,0,0,.35)}input,button{width:100%;padding:12px;border-radius:12px;border:1px solid #22304d;margin-top:10px}input{background:#070b14;color:#edf4ff}button{background:#6ee7ff;color:#031018;font-weight:900;cursor:pointer}.small{color:#8ea0c0;font-size:12px}</style></head>
<body><div class="box"><h2>SkyGround Admin Token</h2><p class="small">برای ورود، dashboard token را وارد کن.</p><input id="t" type="password" placeholder="Admin token"><button onclick="go()">ورود</button><p class="small">اگر token تنظیم نکرده‌ای، مقدار dashboard_token را در config بررسی کن.</p></div>
<script>function go(){const t=document.getElementById('t').value.trim(); if(!t)return; localStorage.setItem('sg_admin_token',t); location.href='/?token='+encodeURIComponent(t);}</script></body></html>
"""


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>SkyGround Admin Dashboard</title>
  <style>
    :root{
      --bg:#070b14;--panel:#0d1424;--panel2:#111a2e;--muted:#8ea0c0;--text:#edf4ff;
      --line:#22304d;--brand:#6ee7ff;--ok:#22c55e;--warn:#f59e0b;--err:#ef4444;--purple:#a78bfa;
      --shadow:0 18px 60px rgba(0,0,0,.35);--radius:18px;
    }
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top left,#10214b 0,#070b14 36%,#05070c 100%);color:var(--text);font:14px/1.55 system-ui,-apple-system,Segoe UI,Tahoma,Arial,sans-serif;min-height:100vh}
    .app{max-width:1480px;margin:0 auto;padding:22px}.top{display:flex;gap:14px;align-items:center;justify-content:space-between;margin-bottom:18px}
    .brand{display:flex;gap:12px;align-items:center}.logo{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,var(--brand),var(--purple));box-shadow:0 0 35px rgba(110,231,255,.25)}
    h1{margin:0;font-size:22px}.sub{color:var(--muted);font-size:12px}.pill{border:1px solid var(--line);background:rgba(17,26,46,.7);border-radius:999px;padding:7px 11px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:1.3fr .9fr;gap:16px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
    .card,.panel{background:linear-gradient(180deg,rgba(17,26,46,.94),rgba(13,20,36,.94));border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
    .card{padding:15px}.k{color:var(--muted);font-size:12px}.v{font-size:18px;font-weight:800;margin-top:4px;direction:ltr;text-align:right}.panel{padding:15px;margin-bottom:16px}.panel h2{margin:0 0 12px;font-size:16px;display:flex;align-items:center;justify-content:space-between}
    .badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 9px;font-size:12px;border:1px solid var(--line);background:#0b1222;color:var(--muted)}
    .badge.ok{color:#bbf7d0;border-color:rgba(34,197,94,.35)}.badge.warn{color:#fde68a;border-color:rgba(245,158,11,.35)}.badge.err{color:#fecaca;border-color:rgba(239,68,68,.35)}
    .list{display:flex;flex-direction:column;gap:10px}.item{background:rgba(7,11,20,.55);border:1px solid rgba(34,48,77,.8);border-radius:14px;padding:12px}.item-head{display:flex;justify-content:space-between;gap:12px;align-items:start}.title{font-weight:800}.meta{color:var(--muted);font-size:12px;direction:ltr;text-align:left}.pre{direction:ltr;text-align:left;white-space:pre-wrap;word-break:break-word;background:#050812;border:1px solid var(--line);border-radius:12px;padding:10px;color:#d7e6ff;max-height:320px;overflow:auto}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.btn{border:0;border-radius:12px;padding:9px 12px;font-weight:800;cursor:pointer;color:#031018;background:var(--brand)}.btn.secondary{background:#1f2a44;color:var(--text);border:1px solid var(--line)}.btn.ok{background:var(--ok)}.btn.err{background:var(--err);color:white}.btn.warn{background:var(--warn)}.btn:disabled{opacity:.55;cursor:not-allowed}
    input,select,textarea{width:100%;background:#070b14;color:var(--text);border:1px solid var(--line);border-radius:12px;padding:10px;outline:none}textarea{min-height:74px;resize:vertical}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.field label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}.switch{display:flex;align-items:center;gap:9px;margin:7px 0;color:var(--muted)}.switch input{width:auto}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.tab{padding:8px 11px;border:1px solid var(--line);background:#0b1222;border-radius:999px;color:var(--muted);cursor:pointer}.tab.active{color:#031018;background:var(--brand);border-color:transparent;font-weight:900}.hide{display:none}.log{max-height:520px;overflow:auto}.event{border-bottom:1px solid rgba(34,48,77,.55);padding:9px 2px}.event:last-child{border-bottom:0}.ltr{direction:ltr;text-align:left}.empty{color:var(--muted);padding:14px;text-align:center;border:1px dashed var(--line);border-radius:14px}.small{font-size:12px;color:var(--muted)}
    @media(max-width:1050px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.formgrid{grid-template-columns:1fr}}
    @media(max-width:600px){.cards{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
  </style>
</head>
<body>
<div class="app">
  <div class="top">
    <div class="brand"><div class="logo"></div><div><h1>SkyGround Admin Dashboard</h1><div class="sub">نظارت، Approval، Ask، دسترسی و تنظیمات پارامتریک ایجنت محلی</div></div></div>
    <div class="row"><span class="pill" id="serverUrl">...</span><span class="pill" id="lastRefresh">...</span></div>
  </div>

  <div class="cards">
    <div class="card"><div class="k">Agent</div><div class="v" id="agentState">...</div></div>
    <div class="card"><div class="k">Model</div><div class="v" id="modelName">...</div></div>
    <div class="card"><div class="k">Brain route</div><div class="v" id="brainRouteTop">...</div></div>
    <div class="card"><div class="k">Pending approvals</div><div class="v" id="pendingApprovals">0</div></div>
    <div class="card"><div class="k">Pending asks</div><div class="v" id="pendingQuestions">0</div></div>
  </div>

  <div class="grid">
    <main>
      <div class="panel">
        <h2>Admin Injection Center <span class="badge ok">Memory + Skills</span></h2>
        <div class="small">تزریق دستی یا فایل به حافظه، vector memory، intentها، skillها و shortcutها. برای فایل، محتوا در مرورگر خوانده و به agent ارسال می‌شود.</div>
        <div class="formgrid" style="margin-top:10px">
          <div class="field"><label>Namespace</label><input id="injectNamespace" class="ltr" value="admin_injection" /></div>
          <div class="field"><label>Kind</label><input id="injectKind" class="ltr" value="admin_note" /></div>
        </div>
        <div class="row" style="margin:8px 0">
          <label class="switch"><input type="checkbox" id="injectMemory" checked> Memory</label>
          <label class="switch"><input type="checkbox" id="injectVector" checked> Vector</label>
          <label class="switch"><input type="checkbox" id="injectOverwrite" checked> Overwrite skills/intents</label>
        </div>
        <div class="field"><label>فایل تزریق اختیاری: txt/json/md</label><input id="injectFile" type="file" /></div>
        <div class="field"><label>Injection text یا JSON bundle</label><textarea id="injectText" class="ltr" placeholder='متن آموزشی یا JSON bundle مثل {"memories":[],"intents":[],"skills":[],"shortcuts":[]}'></textarea></div>
        <div class="row" style="margin-top:10px">
          <button class="btn secondary" onclick="loadInjectFile()">Load File</button>
          <button class="btn" onclick="injectTextMode()">Inject Text</button>
          <button class="btn ok" onclick="injectJsonBundle()">Inject JSON Bundle</button>
          <button class="btn secondary" onclick="fillSampleInjection()">Sample Bundle</button>
        </div>
        <pre class="pre" id="injectOutput">Injection output...</pre>
      </div>

      <div class="panel">
        <h2>Reflex / Skills <span class="badge ok">Fast Local Brain</span></h2>
        <div class="small">دستورهای پایه مثل «کپی کن»، «ذخیره کن»، «git status» بدون مغز بزرگ resolve می‌شوند. برای شروع Dry Run را تست کن.</div>
        <div class="formgrid" style="margin-top:10px">
          <div class="field"><label>Reflex command</label><input id="reflexCommand" placeholder="مثلاً: کپی کن یا save یا git status" /></div>
          <div class="field"><label>Promote skill id اختیاری</label><input id="promoteSkillId" class="ltr" placeholder="shortcut.copy" /></div>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="btn secondary" onclick="reflexResolve()">Resolve</button>
          <button class="btn secondary" onclick="reflexExecute(true)">Dry Run</button>
          <button class="btn ok" onclick="reflexExecute(false)">Execute</button>
          <button class="btn secondary" onclick="skillList()">List Skills</button>
          <button class="btn secondary" onclick="promoteSkill('trusted')">Promote Trusted</button>
          <button class="btn warn" onclick="eventCounts()">Event Counts</button>
          <button class="btn secondary" onclick="dailyDistill(false)">Daily Distill</button>
          <button class="btn ok" onclick="dailyDistill(true)">Distill + Apply</button>
        </div>
        <pre class="pre" id="reflexOutput">Reflex output...</pre>
      </div>

      <div class="panel">
        <h2>Project Factory <span class="badge ok">Scaffold</span></h2>
        <div class="small">برای درخواست‌هایی مثل «یک وب‌سایت با پایتون بساز»، پروژه را مستقیم با فایل‌ها می‌سازد؛ نیازی به VS Code UI نیست. اول Preview را بزن.</div>
        <div class="formgrid" style="margin-top:10px">
          <div class="field"><label>Template</label><select id="scaffoldTemplate"><option value="python_flask_site">Python Flask Website</option><option value="python_fastapi_api">Python FastAPI API</option><option value="static_html_site">Static HTML Site</option><option value="python_cli_tool">Python CLI Tool</option></select></div>
          <div class="field"><label>Project folder name</label><input id="scaffoldProjectName" class="ltr" placeholder="my_python_site" /></div>
        </div>
        <div class="field"><label>Description</label><textarea id="scaffoldDescription" placeholder="مثلاً: یک وب‌سایت معرفی نمونه‌کار با ظاهر مدرن"></textarea></div>
        <label class="switch"><input type="checkbox" id="scaffoldOverwrite"> Overwrite existing files</label>
        <div class="row" style="margin-top:10px">
          <button class="btn secondary" onclick="scaffoldProject(true)">Preview / Dry Run</button>
          <button class="btn ok" onclick="scaffoldProject(false)">Create Project</button>
          <button class="btn secondary" onclick="submitScaffoldAsTask()">Ask Agent to Customize</button>
        </div>
        <pre class="pre" id="scaffoldOutput">Scaffold output...</pre>
      </div>

      <div class="panel">
        <h2>Task Manager <span class="badge ok">Command Center</span></h2>
        <div class="field"><label>Task جدید برای ایجنت</label><textarea id="newTask" placeholder="مثلاً: خطای login را بررسی کن و قبل از تغییرات approval بگیر..."></textarea></div>
        <div class="row" style="margin-top:10px">
          <button class="btn" onclick="submitTask()">Submit Task</button>
          <button class="btn secondary" onclick="controlTask('pause')">Pause</button>
          <button class="btn secondary" onclick="controlTask('resume')">Resume</button>
          <button class="btn err" onclick="controlTask('emergency_stop')">Emergency Stop</button>
          <button class="btn warn" onclick="controlTask('clear_emergency_stop')">Clear Stop</button>
        </div>
        <div class="small" id="taskRuntimeInfo">...</div>
        <div class="list" id="tasks"></div>
      </div>

      <div class="panel">
        <h2>Vector Memory + Desktop Logs <span class="badge ok">Learning Eye</span></h2>
        <div class="formgrid">
          <div class="field"><label>جستجو در حافظه برداری</label><input id="vecQuery" placeholder="مثلاً: login token خطا" /></div>
          <div class="field"><label>Namespace</label><input id="vecNamespace" class="ltr" placeholder="general یا monthly_experience" /></div>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="btn" onclick="vectorSearch()">Search Vector Memory</button>
          <button class="btn secondary" onclick="monthlyInject()">Monthly Inject</button>
        </div>
        <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
        <div class="formgrid">
          <div class="field"><label>Log file path برای چشم ایجنت</label><input id="desktopLogPath" class="ltr" placeholder="C:\\path\\to\\app.log" /></div>
          <div class="field"><label>Shortcut intent</label><input id="shortcutIntent" placeholder="مثلاً open search یا go back" /></div>
        </div>
        <div class="formgrid">
          <div class="field"><label>Shortcut name</label><input id="shortcutName" class="ltr" placeholder="open_search" /></div>
          <div class="field"><label>Shortcut keys با +</label><input id="shortcutKeys" class="ltr" placeholder="Ctrl+K" /></div>
        </div>
        <div class="field"><label>Shortcut description</label><input id="shortcutDescription" placeholder="Open global search" /></div>
        <div class="row" style="margin-top:10px">
          <button class="btn secondary" onclick="registerDesktopLog()">Register Log</button>
          <button class="btn" onclick="observeDesktopLogs()">Observe Logs</button>
          <button class="btn secondary" onclick="getDesktopState()">Desktop State</button>
          <button class="btn secondary" onclick="registerShortcut()">Register Shortcut</button>
          <button class="btn secondary" onclick="suggestShortcut()">Suggest Shortcut</button>
          <button class="btn secondary" onclick="executeShortcut(true)">Dry Run Shortcut</button>
          <button class="btn ok" onclick="executeShortcut(false)">Execute Shortcut</button>
        </div>
        <div id="desktopStateView" style="margin-top:12px"></div>
        <pre class="pre" id="opsOutput">Vector/Desktop operation output...</pre>
      </div>

      <div class="panel">
        <h2>External API Chat / کمک‌برنامه‌نویس <span class="badge ok">Prompt API</span></h2>
        <div class="small">URL/API که با PowerShell تست کردی را اینجا بده؛ بعد مثل چت باهاش سؤال برنامه‌نویسی بپرس. خروجی را می‌توانی با یک دکمه تبدیل به Task برای agent داخلی کنی.</div>
        <div class="row" style="margin:8px 0">
          <button class="btn secondary" onclick="presetOpenAICompatible()">Preset OpenAI-compatible</button>
          <button class="btn secondary" onclick="presetGapGPT()">Preset GapGPT</button>
        </div>
        <div class="formgrid" style="margin-top:10px">
          <div class="field"><label>Endpoint URL</label><input id="extEndpoint" class="ltr" placeholder="https://example.com/v1/chat/completions یا base /v1" /></div>
          <div class="field"><label>Method</label><select id="extMethod"><option>POST</option><option>GET</option></select></div>
          <div class="field"><label>Model اختیاری</label><input id="extModel" class="ltr" placeholder="gpt-4o" /></div>
          <div class="field"><label>Response JSON path اختیاری</label><input id="extResponsePath" class="ltr" placeholder="choices.0.message.content" /></div>
        </div>
        <div class="field"><label>Headers JSON</label><textarea id="extHeaders" class="ltr" placeholder='{"Authorization":"Bearer YOUR_KEY"}'></textarea></div>
        <div class="field"><label>Body template</label><textarea id="extBody" class="ltr">{"prompt":{{prompt_json}}}</textarea></div>
        <div class="field"><label>System / Instruction اختیاری</label><textarea id="extSystemPrompt" placeholder="تو یک دستیار برنامه‌نویس دقیق هستی. پاسخ را کاربردی، مرحله‌ای و همراه کد بده.">تو یک دستیار برنامه‌نویس دقیق هستی. اگر کد لازم است، کد کامل و قابل اجرا بده. اگر نیاز به تغییر پروژه است، پیشنهاد patch یا مراحل دقیق بده.</textarea></div>
        <div class="field"><label>Context / Code اختیاری</label><textarea id="extContext" class="ltr" placeholder="کد، خطا، لاگ یا توضیح پروژه را اینجا paste کن..."></textarea></div>
        <div class="row" style="margin:8px 0">
          <button class="btn secondary" onclick="setExtPrompt('این کد/کانتکست را تحلیل کن و مشکل‌های احتمالی را بگو.')">Analyze</button>
          <button class="btn secondary" onclick="setExtPrompt('برای این مسئله کد تمیز، کامل و قابل اجرا بنویس.')">Generate Code</button>
          <button class="btn secondary" onclick="setExtPrompt('این خطا را debug کن و راه‌حل مرحله‌ای بده.')">Debug</button>
          <button class="btn secondary" onclick="setExtPrompt('برای این کد تست مناسب بنویس.')">Write Tests</button>
          <button class="btn secondary" onclick="setExtPrompt('این کد را refactor کن و نسخه بهتر را بده.')">Refactor</button>
        </div>
        <div class="field"><label>Prompt / سوال</label><textarea id="extPrompt" placeholder="مثلاً: این تابع را refactor کن و کد کامل بده..."></textarea></div>
        <div class="row" style="margin-top:10px">
          <button class="btn" onclick="sendExternalPrompt()">Ask API</button>
          <button class="btn secondary" onclick="sendApiResponseAsTask('review')">Review with Agent</button>
          <button class="btn ok" onclick="sendApiResponseAsTask('implement')">Implement Safely</button>
          <button class="btn warn" onclick="sendApiResponseAsTask('patch')">Apply as Patch</button>
          <button class="btn secondary" onclick="copyApiResponse()">Copy Response</button>
          <button class="btn warn" onclick="clearExternalChat()">Clear Chat</button>
        </div>
        <div class="list" id="extChat" style="margin-top:10px"></div>
        <pre class="pre" id="extOutput">API response...</pre>
      </div>

      <div class="panel">
        <h2>درخواست‌های Approval <span class="badge warn">Admin Gate</span></h2>
        <div class="list" id="approvals"></div>
      </div>

      <div class="panel">
        <h2>پرسش‌های ایجنت از ادمین <span class="badge">Ask Admin</span></h2>
        <div class="list" id="questions"></div>
      </div>

      <div class="panel">
        <h2>رویدادها و لاگ زنده <span class="badge">Polling Live</span></h2>
        <div class="log" id="events"></div>
      </div>
    </main>

    <aside>
      <div class="panel">
        <h2>Policy Templates <span class="badge ok">Preset + Persist</span></h2>
        <div class="field"><label>Template</label><select id="policyTemplate"></select></div>
        <div class="row" style="margin-top:10px">
          <button class="btn" onclick="applyTemplate(false)">اعمال Template</button>
          <button class="btn secondary" onclick="applyTemplate(true)">Merge</button>
        </div>
        <div style="height:10px"></div>
        <div class="row">
          <button class="btn ok" onclick="savePolicy()">Save Policy</button>
          <button class="btn secondary" onclick="loadPolicy()">Load Policy</button>
          <button class="btn warn" onclick="resetPolicy(false)">Reset Session</button>
        </div>
        <div class="small" id="policyStorageInfo">policy storage...</div>
        <div class="small">Templateها سریع policy امن می‌سازند؛ Save آن را در workspace ذخیره می‌کند.</div>
      </div>

      <div class="panel">
        <h2>دسترسی‌های Session <span class="badge warn">غیر دائمی</span></h2>
        <div class="switch"><input type="checkbox" id="readOnly"> <label for="readOnly">Read-only mode؛ همه write/command رد شوند</label></div>
        <div class="switch"><input type="checkbox" id="autoWrites"> <label for="autoWrites">Auto-approve برای write/edit</label></div>
        <div class="switch"><input type="checkbox" id="autoCommands"> <label for="autoCommands">Auto-approve برای command</label></div>
        <div class="switch"><input type="checkbox" id="autoQuestions"> <label for="autoQuestions">Auto-answer برای Ask</label></div>
        <div class="field"><label>پاسخ خودکار Ask</label><input id="autoQuestionAnswer" placeholder="مثلاً: ادامه بده" /></div>
        <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
        <div class="small">Policy جزئی‌تر؛ هر مورد یک خط. Deny همیشه اولویت دارد.</div>
        <div class="field"><label>Allowed write globs</label><textarea id="allowedWriteGlobs" class="ltr" placeholder="src/**&#10;README.md"></textarea></div>
        <div class="field"><label>Denied write globs</label><textarea id="deniedWriteGlobs" class="ltr" placeholder=".env&#10;**/secrets/**"></textarea></div>
        <div class="switch"><input type="checkbox" id="rejectUnmatchedWrites"> <label for="rejectUnmatchedWrites">Reject write/edit خارج از allowlist</label></div>
        <div class="field"><label>Allowed command globs</label><textarea id="allowedCommandGlobs" class="ltr" placeholder="python -m pytest*&#10;npm test*&#10;npm run build*"></textarea></div>
        <div class="field"><label>Denied command fragments</label><textarea id="deniedCommandFragments" class="ltr" placeholder="rm -rf&#10;del /s&#10;format "></textarea></div>
        <div class="switch"><input type="checkbox" id="rejectUnmatchedCommands"> <label for="rejectUnmatchedCommands">Reject command خارج از allowlist</label></div>
        <div style="height:10px"></div>
        <button class="btn" onclick="savePermissions()">ذخیره دسترسی‌های Session</button>
        <div class="small">مثال امن: auto-approve command را روشن کن، allowed command را فقط <span class="ltr">python -m pytest*</span> بگذار، و reject unmatched را فعال کن.</div>
      </div>

      <div class="panel">
        <h2>تنظیمات پارامتریک Runtime <span class="badge ok">Hot Update</span></h2>
        <div class="formgrid">
          <div class="field"><label>LLM Provider</label><select id="cfg_llm_provider"><option value="ollama">ollama</option><option value="openai_compatible">openai_compatible</option><option value="auto">auto / smart routing</option></select></div>
          <div class="field"><label>Model</label><input id="cfg_model" class="ltr" /></div>
          <div class="field"><label>Ollama URL</label><input id="cfg_ollama_url" class="ltr" /></div>
          <div class="field"><label>OpenAI-compatible base URL</label><input id="cfg_openai_base_url" class="ltr" placeholder="https://api.gapgpt.app/v1" /></div>
          <div class="field"><label>API key env var</label><input id="cfg_openai_api_key_env" class="ltr" placeholder="GAPGPT_API_KEY" /></div>
          <div class="field"><label>OpenAI max tokens / 0 default</label><input id="cfg_openai_max_tokens" type="number" min="0" /></div>
          <div class="field"><label>OpenAI timeout sec</label><input id="cfg_openai_timeout_sec" type="number" min="1" /></div>
          <div class="field"><label>Simple brain</label><select id="cfg_brain_routing_simple_provider"><option value="ollama">ollama</option><option value="openai_compatible">openai_compatible</option></select></div>
          <div class="field"><label>Complex brain</label><select id="cfg_brain_routing_complex_provider"><option value="openai_compatible">openai_compatible</option><option value="ollama">ollama</option></select></div>
          <div class="field"><label>Sensitive brain</label><select id="cfg_brain_routing_sensitive_provider"><option value="ollama">ollama</option><option value="openai_compatible">openai_compatible</option></select></div>
          <div class="field"><label>Temperature</label><input id="cfg_temperature" type="number" step="0.05" min="0" max="2" /></div>
          <div class="field"><label>num_ctx فقط Ollama</label><input id="cfg_num_ctx" type="number" step="512" min="1024" /></div>
          <div class="field"><label>max_steps</label><input id="cfg_max_steps" type="number" min="1" /></div>
          <div class="field"><label>command_timeout_sec</label><input id="cfg_command_timeout_sec" type="number" min="1" /></div>
          <div class="field"><label>max_file_read_chars</label><input id="cfg_max_file_read_chars" type="number" min="1000" /></div>
        </div>
        <div class="switch"><input type="checkbox" id="cfg_brain_routing_enabled"> <label for="cfg_brain_routing_enabled">Enable smart brain routing</label></div>
        <div class="switch"><input type="checkbox" id="cfg_brain_routing_allow_api_for_sensitive"> <label for="cfg_brain_routing_allow_api_for_sensitive">Allow API for sensitive tasks</label></div>
        <hr style="border:0;border-top:1px solid var(--line);margin:14px 0">
        <div class="switch"><input type="checkbox" id="cfg_enable_shortcut_execution"> <label for="cfg_enable_shortcut_execution">Enable registered shortcut execution</label></div>
        <div class="switch"><input type="checkbox" id="cfg_require_approval_for_shortcuts"> <label for="cfg_require_approval_for_shortcuts">Require approval for shortcuts</label></div>
        <div class="switch"><input type="checkbox" id="cfg_shortcut_execution_dry_run"> <label for="cfg_shortcut_execution_dry_run">Shortcut dry-run mode</label></div>
        <div class="switch"><input type="checkbox" id="cfg_allow_shortcut_without_desktop_state"> <label for="cfg_allow_shortcut_without_desktop_state">Allow shortcut without desktop state</label></div>
        <div class="formgrid"><div class="field"><label>Min desktop confidence</label><input id="cfg_min_desktop_confidence_for_shortcut" type="number" min="0" max="1" step="0.05" /></div><div class="field"><label>Shortcut delay ms</label><input id="cfg_shortcut_execution_delay_ms" type="number" min="0" /></div></div>
        <div class="switch"><input type="checkbox" id="cfg_require_approval_for_writes"> <label for="cfg_require_approval_for_writes">Require approval for writes</label></div>
        <div class="switch"><input type="checkbox" id="cfg_require_approval_for_commands"> <label for="cfg_require_approval_for_commands">Require approval for commands</label></div>
        <div class="switch"><input type="checkbox" id="cfg_mask_secrets"> <label for="cfg_mask_secrets">Mask secrets in logs/diffs/context</label></div>
        <div class="switch"><input type="checkbox" id="cfg_mask_secrets_in_memory"> <label for="cfg_mask_secrets_in_memory">Mask secrets in memory DB</label></div>
        <div class="switch"><input type="checkbox" id="cfg_block_sensitive_file_reads"> <label for="cfg_block_sensitive_file_reads">Block sensitive file reads</label></div>
        <button class="btn" onclick="saveConfig()">اعمال تنظیمات Runtime</button>
        <div class="small">این تغییرات روی runtime فعلی اعمال می‌شوند؛ برای دائمی‌سازی، config.json را هم بعداً همگام کن.</div>
      </div>

      <div class="panel">
        <h2>وضعیت سیستم</h2>
        <pre class="pre" id="statusJson">{}</pre>
      </div>
    </aside>
  </div>
</div>

<script>
let state = null;
let configLoadedOnce = false;
let templatesLoadedOnce = false;
let apiResponseText = '';
let apiChatHistory = [];
let lastDesktopState = null;
const urlToken = new URLSearchParams(location.search).get('token');
if(urlToken) localStorage.setItem('sg_admin_token', urlToken);
function adminToken(){ return localStorage.getItem('sg_admin_token') || ''; }
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
async function api(path, opts={}){
  const headers = {'Content-Type':'application/json', ...(opts.headers||{})};
  const token = adminToken(); if(token) headers['X-Admin-Token'] = token;
  const res = await fetch(path, {...opts, headers});
  if(res.status===401){ alert('Unauthorized: dashboard token اشتباه است یا وارد نشده.'); throw new Error('unauthorized'); }
  return await res.json();
}
function badgeStatus(status){
  if(status==='approved'||status==='answered') return 'ok';
  if(status==='rejected'||status==='expired') return 'err';
  return 'warn';
}
function listToText(v){ return Array.isArray(v) ? v.join('\n') : (v || ''); }
function textToList(id){ return (document.getElementById(id).value || '').split(/\r?\n|,/).map(x=>x.trim()).filter(Boolean); }
function renderPolicyTemplates(){
  const sel = document.getElementById('policyTemplate');
  const templates = state?.policy_templates || [];
  if(!sel || templatesLoadedOnce || !templates.length) return;
  sel.innerHTML = templates.map(t=>`<option value="${esc(t.id)}">${esc(t.label)} — ${esc(t.description)}</option>`).join('');
  templatesLoadedOnce = true;
}
function renderApprovals(items){
  const pending = items.filter(x=>x.status==='pending').reverse();
  const recent = items.filter(x=>x.status!=='pending').slice(-8).reverse();
  const all = [...pending, ...recent];
  document.getElementById('pendingApprovals').textContent = pending.length;
  const el = document.getElementById('approvals');
  if(!all.length){el.innerHTML='<div class="empty">فعلاً approval pending وجود ندارد.</div>';return;}
  el.innerHTML = all.map(a=>`<div class="item">
    <div class="item-head"><div><div class="title">${esc(a.title)}</div><div class="small">${esc(a.kind)} · ${esc(a.created_at)}</div></div><span class="badge ${badgeStatus(a.status)}">${esc(a.status)}</span></div>
    <pre class="pre">${esc(JSON.stringify(a.details,null,2))}</pre>
    ${a.status==='pending'?`<div class="row"><input id="reason_${a.id}" placeholder="reason optional" /><button class="btn ok" onclick="decideApproval('${a.id}',true)">Approve</button><button class="btn err" onclick="decideApproval('${a.id}',false)">Reject</button></div>`:''}
  </div>`).join('');
}
function renderQuestions(items){
  const pending = items.filter(x=>x.status==='pending').reverse();
  const recent = items.filter(x=>x.status!=='pending').slice(-8).reverse();
  const all = [...pending, ...recent];
  document.getElementById('pendingQuestions').textContent = pending.length;
  const el = document.getElementById('questions');
  if(!all.length){el.innerHTML='<div class="empty">فعلاً سوال pending وجود ندارد.</div>';return;}
  el.innerHTML = all.map(q=>`<div class="item">
    <div class="item-head"><div><div class="title">${esc(q.question)}</div><div class="small">${esc(q.created_at)}</div></div><span class="badge ${badgeStatus(q.status)}">${esc(q.status)}</span></div>
    ${q.options && q.options.length ? `<div class="row">${q.options.map(o=>`<button class="btn secondary" onclick="quickAnswer('${q.id}', '${esc(o).replace(/'/g,'\\&#39;')}')">${esc(o)}</button>`).join('')}</div>`:''}
    ${q.status==='pending'?`<textarea id="answer_${q.id}" placeholder="پاسخ ادمین..."></textarea><button class="btn" onclick="answerQuestion('${q.id}')">ارسال پاسخ</button>`:`<pre class="pre">${esc(q.answer)}</pre>`}
  </div>`).join('');
}
function renderEvents(items){
  const el = document.getElementById('events');
  if(!items.length){el.innerHTML='<div class="empty">هنوز رویدادی ثبت نشده.</div>';return;}
  el.innerHTML = items.slice().reverse().map(e=>`<div class="event"><div class="row"><span class="badge ${e.level==='error'?'err':e.level==='warning'?'warn':''}">${esc(e.level)}</span><b>${esc(e.type)}</b><span class="small ltr">${esc(e.time)}</span></div><div>${esc(e.message)}</div>${e.data&&Object.keys(e.data).length?`<pre class="pre">${esc(JSON.stringify(e.data,null,2))}</pre>`:''}</div>`).join('');
}
function brainBadge(provider){
  if(provider === 'openai_compatible') return 'ok';
  if(provider === 'ollama') return '';
  return 'warn';
}
function renderBrainRoute(route){
  if(!route) return '<span class="badge">not selected yet</span>';
  const provider = route.provider || 'unknown';
  const bits = [
    `<span class="badge ${brainBadge(provider)}">${esc(provider)}</span>`,
    `<span class="badge">${esc(route.reason || 'configured')}</span>`
  ];
  if(route.sensitive) bits.push('<span class="badge err">sensitive</span>');
  if(route.complex) bits.push('<span class="badge warn">complex</span>');
  if(route.fallback) bits.push(`<span class="badge err">fallback: ${esc(route.fallback)}</span>`);
  return `<div class="row">${bits.join('')}</div>`;
}
function renderTasks(taskState){
  const el = document.getElementById('tasks');
  const info = document.getElementById('taskRuntimeInfo');
  const tasks = taskState?.tasks || [];
  const running = tasks.find(t=>t.status==='running');
  const lastRoute = state?.status?.last_brain_route || running?.brain_route || tasks.slice().reverse().find(t=>t.brain_route)?.brain_route;
  info.innerHTML = `paused: ${taskState?.paused ? 'yes' : 'no'} · queue: ${taskState?.queue_size ?? 0} · emergency: ${state?.emergency_stop_active ? 'ACTIVE' : 'off'}<br>current brain: ${renderBrainRoute(lastRoute)}`;
  if(!tasks.length){el.innerHTML='<div class="empty">هنوز task ثبت نشده.</div>';return;}
  const visible = tasks.slice(-20).reverse();
  el.innerHTML = visible.map(t=>`<div class="item">
    <div class="item-head"><div><div class="title">${esc(t.prompt || t.task || '')}</div><div class="small ltr">${esc(t.id)} · ${esc(t.created_at)} · source=${esc(t.source)}</div></div><span class="badge ${t.status==='completed'?'ok':(t.status==='failed'||t.status==='cancelled')?'err':'warn'}">${esc(t.status)}</span></div>
    <div style="margin:8px 0">${renderBrainRoute(t.brain_route)}</div>
    ${t.language_profile?`<div class="small">language: ${esc(t.language_profile.primary_script)} · direction: ${esc(t.language_profile.direction)}</div>`:''}
    ${t.result?`<pre class="pre">${esc(t.result)}</pre>`:''}
    ${t.error?`<pre class="pre">${esc(t.error)}</pre>`:''}
    ${(t.status==='queued'||t.status==='running'||t.status==='cancelling')?`<div class="row"><button class="btn err" onclick="controlTask('cancel','${t.id}')">Cancel</button></div>`:''}
  </div>`).join('');
}
function confidenceBadge(conf){
  const n = Number(conf || 0);
  if(n >= .75) return 'ok';
  if(n >= .45) return 'warn';
  return 'err';
}
function renderDesktopState(ds){
  lastDesktopState = ds || lastDesktopState;
  const el = document.getElementById('desktopStateView');
  if(!el) return;
  const stateObj = ds?.state || ds || {};
  const current = stateObj.current_by_app || {};
  const apps = Object.values(current);
  const timeline = stateObj.timeline || ds?.observations || [];
  const logs = stateObj.registered_logs || [];
  if(!apps.length && !timeline.length && !logs.length){
    el.innerHTML = '<div class="empty">هنوز desktop state نداریم. اول Register Log و سپس Observe Logs را بزن.</div>';
    return;
  }
  const appCards = apps.length ? `<div class="cards" style="grid-template-columns:repeat(2,minmax(0,1fr));margin-bottom:12px">${apps.map(a=>`<div class="card"><div class="row"><span class="badge ${confidenceBadge(a.confidence)}">confidence ${esc(a.confidence ?? '-')}</span><span class="badge">${esc(a.app || 'app')}</span></div><div class="v" style="font-size:15px;text-align:right;direction:rtl">${esc(a.screen || a.location || 'unknown')}</div><div class="small ltr">route: ${esc(a.route || '-')}</div><div class="small">state: ${esc(a.state || '-')} · result: ${esc(a.last_result || '-')}</div><div class="small">message: ${esc(a.last_message || a.summary || '-')}</div></div>`).join('')}</div>` : '';
  const logList = logs.length ? `<div class="small">Registered logs: ${logs.map(l=>`${esc(l.path)} (${l.exists?'ok':'missing'})`).join(' · ')}</div>` : '';
  const tl = timeline.slice(-8).reverse().map(o=>`<div class="event"><div class="row"><span class="badge ${confidenceBadge(o.confidence)}">${esc(o.app || 'app')}</span><span class="small ltr">${esc(o.created_at || '')}</span></div><div><b>${esc(o.location || 'unknown')}</b></div><div class="small">${esc(o.summary || '')}</div></div>`).join('');
  el.innerHTML = `${appCards}${logList}<div class="log" style="max-height:300px;margin-top:10px">${tl || '<div class="empty">timeline خالی است.</div>'}</div>`;
}
function loadFormFromState(){
  const cfg = state.config?.config || state.config || {};
  const perms = state.permissions || {};
  document.getElementById('readOnly').checked = !!perms.read_only_mode;
  document.getElementById('autoWrites').checked = !!perms.auto_approve_writes;
  document.getElementById('autoCommands').checked = !!perms.auto_approve_commands;
  document.getElementById('autoQuestions').checked = !!perms.auto_answer_questions;
  document.getElementById('autoQuestionAnswer').value = perms.auto_question_answer || '';
  document.getElementById('allowedWriteGlobs').value = listToText(perms.allowed_write_globs);
  document.getElementById('deniedWriteGlobs').value = listToText(perms.denied_write_globs);
  document.getElementById('rejectUnmatchedWrites').checked = !!perms.reject_unmatched_writes;
  document.getElementById('allowedCommandGlobs').value = listToText(perms.allowed_command_globs);
  document.getElementById('deniedCommandFragments').value = listToText(perms.denied_command_fragments);
  document.getElementById('rejectUnmatchedCommands').checked = !!perms.reject_unmatched_commands;
  for(const k of ['llm_provider','model','ollama_url','openai_base_url','openai_api_key_env','openai_max_tokens','openai_timeout_sec','brain_routing_simple_provider','brain_routing_complex_provider','brain_routing_sensitive_provider','temperature','num_ctx','max_steps','command_timeout_sec','max_file_read_chars','min_desktop_confidence_for_shortcut','shortcut_execution_delay_ms']){
    const input = document.getElementById('cfg_'+k); if(input && cfg[k]!==undefined) input.value = cfg[k];
  }
  const br = document.getElementById('cfg_brain_routing_enabled'); if(br) br.checked = !!cfg.brain_routing_enabled || cfg.llm_provider === 'auto';
  const bas = document.getElementById('cfg_brain_routing_allow_api_for_sensitive'); if(bas) bas.checked = !!cfg.brain_routing_allow_api_for_sensitive;
  const ese = document.getElementById('cfg_enable_shortcut_execution'); if(ese) ese.checked = !!cfg.enable_shortcut_execution;
  const ras = document.getElementById('cfg_require_approval_for_shortcuts'); if(ras) ras.checked = cfg.require_approval_for_shortcuts !== false;
  const sdr = document.getElementById('cfg_shortcut_execution_dry_run'); if(sdr) sdr.checked = !!cfg.shortcut_execution_dry_run;
  const aws = document.getElementById('cfg_allow_shortcut_without_desktop_state'); if(aws) aws.checked = cfg.allow_shortcut_without_desktop_state !== false;
  const w = document.getElementById('cfg_require_approval_for_writes'); if(w) w.checked = !!cfg.require_approval_for_writes;
  const c = document.getElementById('cfg_require_approval_for_commands'); if(c) c.checked = !!cfg.require_approval_for_commands;
  const ms = document.getElementById('cfg_mask_secrets'); if(ms) ms.checked = cfg.mask_secrets !== false;
  const msm = document.getElementById('cfg_mask_secrets_in_memory'); if(msm) msm.checked = cfg.mask_secrets_in_memory !== false;
  const bsr = document.getElementById('cfg_block_sensitive_file_reads'); if(bsr) bsr.checked = !!cfg.block_sensitive_file_reads;
}
async function refresh(){
  try{
    state = await api('/api/state');
    document.getElementById('serverUrl').textContent = state.server_url || location.href;
    document.getElementById('lastRefresh').textContent = new Date().toLocaleTimeString();
    const st = state.status || {};
    document.getElementById('agentState').textContent = state.emergency_stop_active ? 'STOP' : (st.task_running ? 'RUNNING' : 'IDLE');
    document.getElementById('modelName').textContent = (st.model || state.config?.config?.model || '...').slice(0,28);
    const topRoute = st.last_brain_route || null;
    document.getElementById('brainRouteTop').innerHTML = topRoute ? `${esc(topRoute.provider || '-')}` : (st.brain_routing_enabled ? 'auto' : (st.llm_provider || '...'));
    renderPolicyTemplates();
    renderTasks(state.tasks || {});
    renderApprovals(state.approvals || []);
    renderQuestions(state.questions || []);
    renderEvents(state.events || []);
    const ps = state.policy_storage || {};
    document.getElementById('policyStorageInfo').textContent = `file: ${ps.path || 'not configured'} · exists: ${ps.exists ? 'yes' : 'no'} · saved: ${ps.last_saved_at || '-'} · loaded: ${ps.last_loaded_at || '-'}`;
    document.getElementById('statusJson').textContent = JSON.stringify(st,null,2);
    if(!configLoadedOnce){ loadFormFromState(); configLoadedOnce = true; }
  }catch(e){ console.error(e); }
}
async function decideApproval(id, approved){
  const r = document.getElementById('reason_'+id)?.value || '';
  await api('/api/approval',{method:'POST',body:JSON.stringify({id,decision:approved?'approve':'reject',reason:r})});
  await refresh();
}
async function answerQuestion(id){
  const answer = document.getElementById('answer_'+id)?.value || '';
  await api('/api/question',{method:'POST',body:JSON.stringify({id,answer})});
  await refresh();
}
async function quickAnswer(id, answer){
  await api('/api/question',{method:'POST',body:JSON.stringify({id,answer})});
  await refresh();
}
function loadExternalApiSettings(){
  try{
    const s = JSON.parse(localStorage.getItem('sg_external_api') || '{}');
    if(s.endpoint) document.getElementById('extEndpoint').value = s.endpoint;
    if(s.method) document.getElementById('extMethod').value = s.method;
    if(s.headers) document.getElementById('extHeaders').value = s.headers;
    if(s.body) document.getElementById('extBody').value = s.body;
    if(s.model) document.getElementById('extModel').value = s.model;
    if(s.responsePath) document.getElementById('extResponsePath').value = s.responsePath;
    if(s.systemPrompt) document.getElementById('extSystemPrompt').value = s.systemPrompt;
    apiChatHistory = JSON.parse(localStorage.getItem('sg_external_chat') || '[]');
    renderExternalChat();
  }catch(e){ apiChatHistory = []; }
}
function saveExternalApiSettings(){
  localStorage.setItem('sg_external_api', JSON.stringify({
    endpoint:document.getElementById('extEndpoint').value,
    method:document.getElementById('extMethod').value,
    headers:document.getElementById('extHeaders').value,
    body:document.getElementById('extBody').value,
    model:document.getElementById('extModel').value,
    responsePath:document.getElementById('extResponsePath').value,
    systemPrompt:document.getElementById('extSystemPrompt').value
  }));
}
function setExtPrompt(text){ document.getElementById('extPrompt').value = text; }
function presetOpenAICompatible(){
  document.getElementById('extMethod').value = 'POST';
  document.getElementById('extModel').value = document.getElementById('extModel').value || 'gpt-4o';
  document.getElementById('extHeaders').value = JSON.stringify({Authorization:'Bearer YOUR_API_KEY','Content-Type':'application/json'}, null, 2);
  document.getElementById('extBody').value = JSON.stringify({model:'{{model}}', messages:[{role:'user', content:'__PROMPT__'}]}, null, 2).replace('"__PROMPT__"','{{prompt_json}}');
  document.getElementById('extResponsePath').value = 'choices.0.message.content';
  saveExternalApiSettings();
}
function presetGapGPT(){
  document.getElementById('extEndpoint').value = 'https://api.gapgpt.app/v1/chat/completions';
  document.getElementById('extModel').value = 'gpt-4o';
  presetOpenAICompatible();
  document.getElementById('extEndpoint').value = 'https://api.gapgpt.app/v1/chat/completions';
  saveExternalApiSettings();
}
function saveExternalChat(){ localStorage.setItem('sg_external_chat', JSON.stringify(apiChatHistory.slice(-20))); }
function clearExternalChat(){ apiChatHistory=[]; apiResponseText=''; localStorage.removeItem('sg_external_chat'); renderExternalChat(); document.getElementById('extOutput').textContent='API response...'; }
function renderExternalChat(){
  const el = document.getElementById('extChat'); if(!el) return;
  if(!apiChatHistory.length){ el.innerHTML='<div class="empty">هنوز چتی با API ثبت نشده.</div>'; return; }
  el.innerHTML = apiChatHistory.slice(-8).map(m=>`<div class="item"><div class="item-head"><div class="title">${m.role==='user'?'You':'API'}</div><span class="badge">${esc(m.time||'')}</span></div><pre class="pre">${esc(m.content)}</pre></div>`).join('');
}
function extractJsonPath(obj, path){
  if(!obj || !path) return null;
  let cur = obj;
  for(const part of path.split('.').filter(Boolean)){
    const key = /^\d+$/.test(part) ? Number(part) : part;
    if(cur == null || !(key in cur)) return null;
    cur = cur[key];
  }
  return typeof cur === 'string' ? cur : JSON.stringify(cur,null,2);
}
function buildExternalPrompt(){
  const sys = (document.getElementById('extSystemPrompt').value || '').trim();
  const ctx = (document.getElementById('extContext').value || '').trim();
  const user = (document.getElementById('extPrompt').value || '').trim();
  const history = apiChatHistory.slice(-6).map(m=>`${m.role==='user'?'User':'Assistant'}: ${m.content}`).join('\n\n');
  return `${sys?`Instruction:\n${sys}\n\n`:''}${ctx?`Context / Code:\n${ctx}\n\n`:''}${history?`Recent conversation:\n${history}\n\n`:''}User request:\n${user}`.trim();
}
async function sendExternalPrompt(){
  saveExternalApiSettings();
  const userPrompt = (document.getElementById('extPrompt').value || '').trim();
  if(!userPrompt){ alert('Prompt خالی است'); return; }
  const finalPrompt = buildExternalPrompt();
  const body = {
    endpoint:document.getElementById('extEndpoint').value,
    method:document.getElementById('extMethod').value,
    headers:document.getElementById('extHeaders').value,
    body_template:document.getElementById('extBody').value,
    model:document.getElementById('extModel').value,
    prompt:finalPrompt,
    timeout_sec:120
  };
  document.getElementById('extOutput').textContent = 'Calling external API...';
  apiChatHistory.push({role:'user', content:userPrompt, time:new Date().toLocaleTimeString()});
  renderExternalChat();
  const res = await api('/api/external_prompt',{method:'POST',body:JSON.stringify(body)});
  const extracted = res.ok ? (extractJsonPath(res.json, document.getElementById('extResponsePath').value.trim()) || res.text || JSON.stringify(res.json,null,2) || '') : (res.text || res.error || JSON.stringify(res,null,2));
  apiResponseText = extracted;
  document.getElementById('extOutput').textContent = res.ok ? extracted : ('ERROR:\n'+extracted);
  apiChatHistory.push({role:'assistant', content:extracted, time:new Date().toLocaleTimeString()});
  saveExternalChat();
  renderExternalChat();
}
async function sendApiResponseAsTask(mode='implement'){
  const text = apiResponseText || document.getElementById('extOutput').textContent || '';
  if(!text || text==='API response...'){ alert('اول API را صدا بزن.'); return; }
  const prompt = document.getElementById('extPrompt').value || '';
  const ctx = document.getElementById('extContext').value || '';
  let instruction = '';
  if(mode === 'review'){
    instruction = `فقط بررسی و تحلیل کن. هیچ فایلی را تغییر نده.\n- پاسخ API خارجی را با پروژه مقایسه کن.\n- فایل‌های مرتبط را با search_project/read_file پیدا و بررسی کن.\n- بگو آیا پیشنهاد API قابل اعمال است یا نه.\n- اگر تغییر لازم است، فقط برنامه اجرا و diff پیشنهادی را توضیح بده، اما write/edit/apply_patch انجام نده.`;
  } else if(mode === 'patch'){
    instruction = `اگر پاسخ API شامل unified diff یا patch معتبر است، آن را بررسی کن و با ابزار apply_patch اعمال کن؛ اما فقط بعد از validation و approval داشبورد.\n- اول git_status بگیر.\n- اگر patch ناقص/نامعتبر است، فایل‌های مرتبط را بخوان و از من/ادمین سوال بپرس یا گزارش بده.\n- بعد از اعمال، git_diff بگیر و خلاصه کن.\n- اگر تست مناسب واضح است، قبل از اجرا approval بگیر.`;
  } else {
    instruction = `پاسخ API خارجی را به عنوان پیشنهاد برنامه‌نویسی استفاده کن و آن را امن و کنترل‌شده روی پروژه بررسی و در صورت درست بودن اعمال کن.\nمراحل اجباری:\n1. اول git_status بگیر.\n2. با search_project/list_dir/read_file فایل‌های مرتبط را پیدا و بررسی کن.\n3. کورکورانه به پاسخ API اعتماد نکن؛ آن را با کد واقعی پروژه تطبیق بده.\n4. اگر تغییر لازم است، ترجیحاً apply_patch یا edit_file_multi استفاده کن.\n5. قبل از هر write/edit/apply_patch داشبورد approval می‌گیرد؛ diff/patch باید واضح باشد.\n6. بعد از تغییر، git_diff بگیر و خلاصه تغییرات را بگو.\n7. اگر تست مناسب مشخص است، برای اجرای آن approval بگیر.\n8. اگر اطلاعات کافی نیست، با ask_admin سوال بپرس.`;
  }
  const task = `${instruction}\n\nOriginal user prompt to external API:\n${prompt}\n\nOptional context/code pasted by user:\n${ctx}\n\nExternal API response:\n${text}`;
  const res = await api('/api/task',{method:'POST',body:JSON.stringify({task,source:'external_api_chat_'+mode})});
  if(!res.ok) alert('Task submit error: '+(res.error||JSON.stringify(res)));
  await refresh();
}
async function copyApiResponse(){
  const text = apiResponseText || document.getElementById('extOutput').textContent || '';
  await navigator.clipboard.writeText(text);
}
async function loadInjectFile(){
  const input = document.getElementById('injectFile');
  const file = input.files && input.files[0];
  if(!file){ alert('فایلی انتخاب نشده'); return; }
  const text = await file.text();
  document.getElementById('injectText').value = text;
  document.getElementById('injectOutput').textContent = `Loaded ${file.name} (${text.length} chars)`;
}
function injectPayload(mode){
  const file = document.getElementById('injectFile').files?.[0];
  return {
    mode,
    text:document.getElementById('injectText').value,
    json:document.getElementById('injectText').value,
    namespace:document.getElementById('injectNamespace').value,
    kind:document.getElementById('injectKind').value,
    memory:document.getElementById('injectMemory').checked,
    vector:document.getElementById('injectVector').checked,
    overwrite:document.getElementById('injectOverwrite').checked,
    filename:file ? file.name : undefined,
    source:'dashboard_admin'
  };
}
async function injectTextMode(){
  const res = await api('/api/agent/op',{method:'POST',body:JSON.stringify({operation:'admin_inject',payload:injectPayload('text')})});
  document.getElementById('injectOutput').textContent = JSON.stringify(res,null,2);
  await refresh();
}
async function injectJsonBundle(){
  const res = await api('/api/agent/op',{method:'POST',body:JSON.stringify({operation:'admin_inject',payload:injectPayload('json_bundle')})});
  document.getElementById('injectOutput').textContent = JSON.stringify(res,null,2);
  await refresh();
}
function fillSampleInjection(){
  const sample = {
    memories:[
      {kind:'user_preference', text:'پاسخ‌ها فارسی باشند مگر برای کد یا اصطلاح فنی.'},
      {kind:'workflow_rule', text:'قبل از تغییر فایل‌ها git_status بگیر و diff را برای approval نشان بده.'}
    ],
    intents:[
      {id:'browser.refresh', description:'Refresh active browser page', aliases:['refresh','رفرش','صفحه را تازه کن','ctrl+r'], risk:'low', ambiguous:false, status:'approved'}
    ],
    shortcuts:[
      {name:'refresh', description:'Refresh active page/window', keys:['Ctrl','R'], app:'global', risk:'low', requires_approval:false}
    ],
    skills:[
      {id:'shortcut.refresh', intent:'browser.refresh', description:'Refresh active page using Ctrl+R', executor:'execute_shortcut', args:{name:'refresh'}, safety_level:'fast', risk:'low', status:'approved', confidence:0.85, requires_approval:false}
    ]
  };
  document.getElementById('injectText').value = JSON.stringify(sample,null,2);
}
async function agentOp(operation, payload){ 
  const res = await api('/api/agent/op',{method:'POST',body:JSON.stringify({operation,payload})});
  document.getElementById('opsOutput').textContent = JSON.stringify(res,null,2);
  if(operation === 'observe_desktop_logs' || operation === 'get_desktop_state') renderDesktopState(res);
  return res;
}
async function vectorSearch(){
  await agentOp('search_vector_memory', {query:document.getElementById('vecQuery').value, namespace:document.getElementById('vecNamespace').value, limit:8});
}
async function monthlyInject(){
  await agentOp('monthly_inject_memory', {namespace:document.getElementById('vecNamespace').value || 'monthly_experience'});
}
async function registerDesktopLog(){
  await agentOp('register_desktop_log', {path:document.getElementById('desktopLogPath').value});
}
async function observeDesktopLogs(){
  await agentOp('observe_desktop_logs', {});
}
async function getDesktopState(){
  await agentOp('get_desktop_state', {limit:30});
}
async function registerShortcut(){
  await agentOp('register_shortcut', {
    name:document.getElementById('shortcutName').value,
    description:document.getElementById('shortcutDescription').value,
    keys:(document.getElementById('shortcutKeys').value || '').split('+').map(x=>x.trim()).filter(Boolean),
    app:'global', risk:'low', requires_approval:false
  });
}
async function suggestShortcut(){
  await agentOp('suggest_shortcut', {intent:document.getElementById('shortcutIntent').value});
}
async function executeShortcut(dryRun){
  const name = document.getElementById('shortcutName').value;
  if(!name){ alert('Shortcut name را وارد کن یا اول shortcut ثبت کن.'); return; }
  if(!dryRun && !confirm(`Execute shortcut ${name}?`)) return;
  await agentOp('execute_shortcut', {name, dry_run:dryRun});
}
async function reflexOp(operation, payload){
  const res = await api('/api/agent/op',{method:'POST',body:JSON.stringify({operation,payload})});
  document.getElementById('reflexOutput').textContent = JSON.stringify(res,null,2);
  return res;
}
async function reflexResolve(){
  await reflexOp('reflex_resolve', {command:document.getElementById('reflexCommand').value});
}
async function reflexExecute(dryRun){
  const command = document.getElementById('reflexCommand').value;
  if(!command){ alert('دستور reflex خالی است'); return; }
  if(!dryRun && !confirm(`Execute reflex command: ${command}?`)) return;
  await reflexOp('reflex_execute', {command, dry_run:dryRun});
  await refresh();
}
async function skillList(){
  await reflexOp('skill_list', {});
}
async function promoteSkill(status){
  const skill_id = document.getElementById('promoteSkillId').value;
  if(!skill_id){ alert('skill id را وارد کن'); return; }
  await reflexOp('skill_promote', {skill_id, status});
}
async function eventCounts(){
  await reflexOp('event_counts', {});
}
async function dailyDistill(apply){
  if(apply && !confirm('Distill + Apply می‌تواند بعضی skillهای کم‌ریسک را trusted کند. ادامه؟')) return;
  await reflexOp('daily_distill', {apply, inject_vector:true});
  await refresh();
}
function scaffoldPayload(dryRun){
  return {
    template:document.getElementById('scaffoldTemplate').value,
    project_name:document.getElementById('scaffoldProjectName').value,
    description:document.getElementById('scaffoldDescription').value,
    overwrite:document.getElementById('scaffoldOverwrite').checked,
    dry_run:dryRun
  };
}
async function scaffoldProject(dryRun){
  const payload = scaffoldPayload(dryRun);
  if(!payload.project_name){ alert('Project folder name خالی است'); return; }
  if(!dryRun && !confirm(`Create project ${payload.project_name}?`)) return;
  const res = await api('/api/agent/op',{method:'POST',body:JSON.stringify({operation:'create_project',payload})});
  document.getElementById('scaffoldOutput').textContent = JSON.stringify(res,null,2);
  await refresh();
}
async function submitScaffoldAsTask(){
  const p = scaffoldPayload(false);
  const task = `یک پروژه جدید با این مشخصات بساز و در صورت نیاز آن را سفارشی کن. قبل از اعمال فایل‌ها approval بگیر.\ntemplate=${p.template}\nproject_name=${p.project_name}\ndescription=${p.description}`;
  const res = await api('/api/task',{method:'POST',body:JSON.stringify({task,source:'project_factory'})});
  if(!res.ok) alert('Task submit error: '+(res.error||JSON.stringify(res)));
  await refresh();
}
async function submitTask(){ 
  const el = document.getElementById('newTask');
  const task = (el.value || '').trim();
  if(!task){ alert('Task خالی است'); return; }
  const res = await api('/api/task',{method:'POST',body:JSON.stringify({task,source:'dashboard'})});
  if(!res.ok) alert('Task submit error: '+(res.error||JSON.stringify(res)));
  else el.value = '';
  await refresh();
}
async function controlTask(action,id=null){
  if(action==='emergency_stop' && !confirm('Emergency Stop فعال شود؟ همه approvalهای pending رد می‌شوند و policy به read-only می‌رود.')) return;
  const res = await api('/api/task/control',{method:'POST',body:JSON.stringify({action,id})});
  if(!res.ok) alert('Task control error: '+(res.error||JSON.stringify(res)));
  await refresh();
}
async function applyTemplate(merge){
  const id = document.getElementById('policyTemplate').value;
  const res = await api('/api/policy/template',{method:'POST',body:JSON.stringify({id,merge})});
  if(!res.ok) alert('Template error: '+(res.error||JSON.stringify(res)));
  configLoadedOnce=false;
  await refresh();
}
async function savePolicy(){
  const res = await api('/api/policy/save',{method:'POST',body:JSON.stringify({})});
  if(!res.ok) alert('Save policy error: '+(res.error||JSON.stringify(res)));
  await refresh();
}
async function loadPolicy(){
  const res = await api('/api/policy/load',{method:'POST',body:JSON.stringify({})});
  if(!res.ok) alert('Load policy error: '+(res.error||JSON.stringify(res)));
  configLoadedOnce=false;
  await refresh();
}
async function resetPolicy(deleteFile=false){
  const res = await api('/api/policy/reset',{method:'POST',body:JSON.stringify({delete_file:deleteFile})});
  if(!res.ok) alert('Reset policy error: '+(res.error||JSON.stringify(res)));
  configLoadedOnce=false;
  await refresh();
}
async function savePermissions(){
  await api('/api/permissions',{method:'POST',body:JSON.stringify({
    read_only_mode:document.getElementById('readOnly').checked,
    auto_approve_writes:document.getElementById('autoWrites').checked,
    auto_approve_commands:document.getElementById('autoCommands').checked,
    auto_answer_questions:document.getElementById('autoQuestions').checked,
    auto_question_answer:document.getElementById('autoQuestionAnswer').value,
    allowed_write_globs:textToList('allowedWriteGlobs'),
    denied_write_globs:textToList('deniedWriteGlobs'),
    reject_unmatched_writes:document.getElementById('rejectUnmatchedWrites').checked,
    allowed_command_globs:textToList('allowedCommandGlobs'),
    denied_command_fragments:textToList('deniedCommandFragments'),
    reject_unmatched_commands:document.getElementById('rejectUnmatchedCommands').checked
  })});
  configLoadedOnce=false;
  await refresh();
}
async function saveConfig(){
  const body = {
    llm_provider:document.getElementById('cfg_llm_provider').value,
    model:document.getElementById('cfg_model').value,
    ollama_url:document.getElementById('cfg_ollama_url').value,
    openai_base_url:document.getElementById('cfg_openai_base_url').value,
    openai_api_key_env:document.getElementById('cfg_openai_api_key_env').value,
    openai_max_tokens:Number(document.getElementById('cfg_openai_max_tokens').value),
    openai_timeout_sec:Number(document.getElementById('cfg_openai_timeout_sec').value),
    brain_routing_enabled:document.getElementById('cfg_brain_routing_enabled').checked,
    brain_routing_simple_provider:document.getElementById('cfg_brain_routing_simple_provider').value,
    brain_routing_complex_provider:document.getElementById('cfg_brain_routing_complex_provider').value,
    brain_routing_sensitive_provider:document.getElementById('cfg_brain_routing_sensitive_provider').value,
    brain_routing_allow_api_for_sensitive:document.getElementById('cfg_brain_routing_allow_api_for_sensitive').checked,
    enable_shortcut_execution:document.getElementById('cfg_enable_shortcut_execution').checked,
    require_approval_for_shortcuts:document.getElementById('cfg_require_approval_for_shortcuts').checked,
    shortcut_execution_dry_run:document.getElementById('cfg_shortcut_execution_dry_run').checked,
    allow_shortcut_without_desktop_state:document.getElementById('cfg_allow_shortcut_without_desktop_state').checked,
    min_desktop_confidence_for_shortcut:Number(document.getElementById('cfg_min_desktop_confidence_for_shortcut').value),
    shortcut_execution_delay_ms:Number(document.getElementById('cfg_shortcut_execution_delay_ms').value),
    temperature:Number(document.getElementById('cfg_temperature').value),
    num_ctx:Number(document.getElementById('cfg_num_ctx').value),
    max_steps:Number(document.getElementById('cfg_max_steps').value),
    command_timeout_sec:Number(document.getElementById('cfg_command_timeout_sec').value),
    max_file_read_chars:Number(document.getElementById('cfg_max_file_read_chars').value),
    require_approval_for_writes:document.getElementById('cfg_require_approval_for_writes').checked,
    require_approval_for_commands:document.getElementById('cfg_require_approval_for_commands').checked,
    mask_secrets:document.getElementById('cfg_mask_secrets').checked,
    mask_secrets_in_memory:document.getElementById('cfg_mask_secrets_in_memory').checked,
    block_sensitive_file_reads:document.getElementById('cfg_block_sensitive_file_reads').checked
  };
  const res = await api('/api/config',{method:'POST',body:JSON.stringify(body)});
  if(!res.ok) alert('Config error: '+(res.error||JSON.stringify(res)));
  configLoadedOnce=false;
  await refresh();
}
loadExternalApiSettings();
refresh(); setInterval(refresh,1500);
</script>
</body>
</html>
"""