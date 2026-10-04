"""
Safe Shell Command Executor ('Hands' System Operator).
Executes system shell commands with security policies, approval enforcement, timeouts, and output truncation.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.approval_guard import ApprovalGuard

logger = logging.getLogger("qwen_hands_eyes.command_executor")


class SafeCommandExecutor:
    """Executes bash/powershell/cmd commands within workspace boundaries and security guidelines."""

    def __init__(
        self,
        workspace_root: str = ".",
        timeout_sec: int = 30,
        approval_guard: Optional[ApprovalGuard] = None,
        max_output_chars: int = 8000,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_sec = timeout_sec
        self.approval_guard = approval_guard
        self.max_output_chars = max_output_chars

    def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        skip_approval: bool = False,
    ) -> Dict[str, Any]:
        """Execute a shell command safely."""
        cmd_str = (command or "").strip()
        if not cmd_str:
            return {"ok": False, "error": "Command cannot be empty"}

        work_dir = (self.workspace_root / cwd).resolve() if cwd else self.workspace_root
        timeout_val = timeout or self.timeout_sec

        # Security & Approval Evaluation
        if self.approval_guard and not skip_approval:
            risk = self.approval_guard.evaluate_command_risk(cmd_str)
            if not risk["allowed"]:
                return {
                    "ok": False,
                    "error": f"Command blocked by security policy: {risk['reason']}",
                    "command": cmd_str,
                }

            if risk["risk_level"] in {"medium", "high", "critical"}:
                approved = self.approval_guard.request_approval(
                    category="shell_execution",
                    title=f"Execute: {cmd_str[:60]}...",
                    details={"command": cmd_str, "cwd": str(work_dir), "risk": risk},
                    risk_level=risk["risk_level"],
                )
                if not approved:
                    return {
                        "ok": False,
                        "error": "Execution rejected by user or approval timeout",
                        "command": cmd_str,
                    }

        start_time = time.time()
        try:
            proc = subprocess.run(
                cmd_str,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=timeout_val,
                errors="replace",
            )
            elapsed = round(time.time() - start_time, 3)

            stdout = proc.stdout[: self.max_output_chars] if proc.stdout else ""
            stderr = proc.stderr[: self.max_output_chars] if proc.stderr else ""

            return {
                "ok": proc.returncode == 0,
                "command": cmd_str,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "elapsed_sec": elapsed,
                "cwd": str(work_dir),
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "command": cmd_str,
                "error": f"Command timed out after {timeout_val} seconds",
                "elapsed_sec": timeout_val,
            }
        except Exception as e:
            return {
                "ok": False,
                "command": cmd_str,
                "error": str(e),
                "elapsed_sec": round(time.time() - start_time, 3),
            }
