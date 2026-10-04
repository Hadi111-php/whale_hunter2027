"""
Approval and Safety Guard for SkyGround Autonomous Agent.
Enforces human-in-the-loop validation, risk scoring, diff review, and command sandboxing.
"""

from __future__ import annotations

import difflib
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("qwen_hands_eyes.approval_guard")


class PendingApprovalRequest:
    def __init__(
        self,
        request_id: str,
        category: str,
        title: str,
        details: Dict[str, Any],
        risk_level: str = "medium",  # low | medium | high | critical
    ):
        self.request_id = request_id
        self.category = category
        self.title = title
        self.details = details
        self.risk_level = risk_level
        self.created_at = time.time()
        self.status = "pending"  # pending | approved | rejected
        self.decision_by = ""
        self.event = threading.Event()


class ApprovalGuard:
    """Protects system integrity by evaluating risks and asking for user permission."""

    def __init__(
        self,
        safe_mode: bool = True,
        require_approval: bool = True,
        auto_approve_low_risk: bool = False,
        blocked_commands: Optional[List[str]] = None,
    ):
        self.safe_mode = safe_mode
        self.require_approval = require_approval
        self.auto_approve_low_risk = auto_approve_low_risk
        self.blocked_commands = blocked_commands or [
            "rm -rf /", "rmdir /s /q c:\\", "mkfs", "dd if=", ":(){ :|:& };:",
            "format c:", "del /f /s /q c:\\windows", "shutdown", "reboot"
        ]
        self.pending_requests: Dict[str, PendingApprovalRequest] = {}
        self._lock = threading.Lock()

    def evaluate_command_risk(self, command: str) -> Dict[str, Any]:
        cmd_lower = command.lower().strip()

        # Check critical blocked commands
        for blocked in self.blocked_commands:
            if blocked.lower() in cmd_lower:
                return {
                    "allowed": False,
                    "risk_level": "critical",
                    "reason": f"Command contains forbidden pattern: '{blocked}'",
                }

        # Check high risk indicators
        high_risk_patterns = ["rm ", "del ", "drop table", "truncate", "iptables", "netsh", "curl | bash", "wget | bash"]
        if any(p in cmd_lower for p in high_risk_patterns):
            return {
                "allowed": True,
                "risk_level": "high",
                "reason": "Potentially destructive or system-modifying operation",
            }

        # Check medium risk indicators
        medium_risk = ["git push", "npm install", "pip install", "docker run", "systemctl"]
        if any(p in cmd_lower for p in medium_risk):
            return {"allowed": True, "risk_level": "medium", "reason": "Environment modification"}

        # Low risk
        return {"allowed": True, "risk_level": "low", "reason": "Read-only or safe command"}

    def render_diff(self, old_content: str, new_content: str, filename: str = "file") -> str:
        """Render unified diff between old and new text."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}")
        return "".join(diff)

    def request_approval(
        self,
        category: str,
        title: str,
        details: Dict[str, Any],
        risk_level: str = "medium",
        cli_fallback: Optional[Callable[[], bool]] = None,
        timeout_sec: float = 60.0,
    ) -> bool:
        """Request permission to execute an action."""
        if not self.require_approval:
            return True

        if risk_level == "low" and self.auto_approve_low_risk:
            logger.info(f"Auto-approved low risk action: {title}")
            return True

        req_id = str(uuid.uuid4())[:8]
        req = PendingApprovalRequest(
            request_id=req_id,
            category=category,
            title=title,
            details=details,
            risk_level=risk_level,
        )

        with self._lock:
            self.pending_requests[req_id] = req

        logger.info(f"🛡️ Action requires approval [ID: {req_id} | Risk: {risk_level}]: {title}")

        # If CLI fallback provided and no remote resolver active
        if cli_fallback:
            print(f"\n⚠️  [APPROVAL NEEDED - Risk: {risk_level.upper()}]")
            print(f"Action: {title}")
            if "command" in details:
                print(f"Command: {details['command']}")
            if "diff" in details:
                print(f"Diff Preview:\n{details['diff']}")
            print("Approve execution? [y/N]: ", end="", flush=True)

            decision = cli_fallback()
            self.resolve_request(req_id, approved=decision, decision_by="cli_user")
            return decision

        # Wait on event for web/dashboard approval
        signaled = req.event.wait(timeout=timeout_sec)
        with self._lock:
            if req_id in self.pending_requests:
                del self.pending_requests[req_id]

        if not signaled:
            logger.warning(f"Approval request {req_id} timed out. Defaulting to REJECT.")
            return False

        return req.status == "approved"

    def resolve_request(self, req_id: str, approved: bool, decision_by: str = "web_user") -> bool:
        with self._lock:
            req = self.pending_requests.get(req_id)
            if not req:
                return False
            req.status = "approved" if approved else "rejected"
            req.decision_by = decision_by
            req.event.set()
            return True

    def list_pending_requests(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "request_id": r.request_id,
                    "category": r.category,
                    "title": r.title,
                    "details": r.details,
                    "risk_level": r.risk_level,
                    "created_at": r.created_at,
                }
                for r in self.pending_requests.values()
                if r.status == "pending"
            ]
