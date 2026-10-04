"""
Safe File Operations & Workspace Manager ('Hands' File Manipulator).
Features atomic writes, automated timestamped backups, fuzzy/exact text replacements, and unified diff generation.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.approval_guard import ApprovalGuard

logger = logging.getLogger("qwen_hands_eyes.file_manager")


class SafeFileManager:
    """Safely manages files and directories within allowed workspace boundaries."""

    def __init__(
        self,
        workspace_root: str = ".",
        max_read_chars: int = 25000,
        create_backups: bool = True,
        backup_dir: str = ".qwen_hands_eyes/backups",
        approval_guard: Optional[ApprovalGuard] = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.max_read_chars = max_read_chars
        self.create_backups = create_backups
        self.backup_dir = (self.workspace_root / backup_dir).resolve()
        self.approval_guard = approval_guard

    def _resolve_safe_path(self, rel_path: str) -> Path:
        p = (self.workspace_root / (rel_path or ".")).resolve()
        try:
            p.relative_to(self.workspace_root)
        except ValueError:
            raise ValueError(f"Security Alert: Path '{rel_path}' escapes workspace boundary '{self.workspace_root}'")
        return p

    def _create_backup(self, file_path: Path) -> Optional[str]:
        if not self.create_backups or not file_path.exists() or not file_path.is_file():
            return None
        rel = file_path.relative_to(self.workspace_root)
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_backup = self.backup_dir / timestamp / rel
        target_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target_backup)
        return str(target_backup.relative_to(self.workspace_root))

    def read_file(self, rel_path: str, max_chars: Optional[int] = None) -> Dict[str, Any]:
        """Read content of a file with size limits."""
        try:
            target = self._resolve_safe_path(rel_path)
            if not target.exists():
                return {"ok": False, "error": f"File not found: {rel_path}"}
            if not target.is_file():
                return {"ok": False, "error": f"Path is a directory: {rel_path}"}

            limit = max_chars or self.max_read_chars
            text = target.read_text(encoding="utf-8", errors="replace")
            truncated = len(text) > limit

            return {
                "ok": True,
                "path": rel_path,
                "content": text[:limit],
                "total_chars": len(text),
                "truncated": truncated,
            }
        except Exception as e:
            return {"ok": False, "path": rel_path, "error": str(e)}

    def write_file(self, rel_path: str, content: str, require_approval: bool = True) -> Dict[str, Any]:
        """Write full content to a file atomically, creating backups if existing."""
        try:
            target = self._resolve_safe_path(rel_path)
            old_content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
            diff = self.approval_guard.render_diff(old_content, content, rel_path) if self.approval_guard else ""

            if self.approval_guard and require_approval and target.exists():
                approved = self.approval_guard.request_approval(
                    category="file_overwrite",
                    title=f"Overwrite file: {rel_path}",
                    details={"path": rel_path, "diff": diff},
                    risk_level="medium",
                )
                if not approved:
                    return {"ok": False, "error": "User rejected file modification", "path": rel_path}

            backup_path = self._create_backup(target)
            target.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write via temp file
            with tempfile.NamedTemporaryFile("w", dir=str(target.parent), delete=False, encoding="utf-8") as tf:
                tf.write(content)
                temp_name = tf.name

            shutil.move(temp_name, str(target))
            return {
                "ok": True,
                "path": rel_path,
                "bytes_written": len(content.encode("utf-8")),
                "backup_path": backup_path,
                "diff": diff,
            }
        except Exception as e:
            return {"ok": False, "path": rel_path, "error": str(e)}

    def edit_file(self, rel_path: str, old_text: str, new_text: str) -> Dict[str, Any]:
        """Search and replace text within a file."""
        try:
            target = self._resolve_safe_path(rel_path)
            if not target.exists():
                return {"ok": False, "error": f"File not found: {rel_path}"}

            current_content = target.read_text(encoding="utf-8", errors="replace")
            if old_text not in current_content:
                return {
                    "ok": False,
                    "error": "Target text not found in file. Please verify exact indentation and wording.",
                    "path": rel_path,
                }

            updated_content = current_content.replace(old_text, new_text, 1)
            return self.write_file(rel_path, updated_content)
        except Exception as e:
            return {"ok": False, "path": rel_path, "error": str(e)}

    def list_files(self, rel_dir: str = ".", pattern: str = "*", recursive: bool = False) -> Dict[str, Any]:
        """List files in workspace."""
        try:
            target_dir = self._resolve_safe_path(rel_dir)
            if not target_dir.exists():
                return {"ok": False, "error": f"Directory not found: {rel_dir}"}

            items = []
            iterator = target_dir.rglob(pattern) if recursive else target_dir.glob(pattern)
            for p in sorted(iterator)[:200]:
                if ".git" in p.parts or "__pycache__" in p.parts:
                    continue
                rel = p.relative_to(self.workspace_root).as_posix()
                items.append({
                    "path": rel,
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else 0,
                })

            return {"ok": True, "dir": rel_dir, "files": items, "count": len(items)}
        except Exception as e:
            return {"ok": False, "dir": rel_dir, "error": str(e)}
