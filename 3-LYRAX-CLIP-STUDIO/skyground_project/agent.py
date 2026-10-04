#!/usr/bin/env python3
"""
SkyGround Local Cursor-like Coding Agent v3

- Offline/local LLM via Ollama
- Project file read/write tools
- Terminal command tool with approval
- SQLite long-term memory
- Project index/search with symbol extraction
- Git status/diff tools
- Safer atomic edits with backups and diff preview
- No external Python dependencies

Run:
  python agent.py --config config.json --root "C:\\path\\to\\project"
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import difflib
import fnmatch
import hashlib
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import traceback
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dashboard import AdminControlCenter, DashboardServer
except ImportError:  # pragma: no cover - dashboard.py should exist in normal use
    AdminControlCenter = None  # type: ignore
    DashboardServer = None  # type: ignore

from security import find_secrets, looks_sensitive_path, mask_secrets, sanitize_for_display
from text_intelligence import detect_text_profile
from vector_memory import VectorMemoryStore
from desktop_io import DesktopIORegistry, ShortcutAction
from event_journal import EventJournal
from intent_registry import IntentRegistry
from skill_registry import SkillDefinition, SkillRegistry
from reflex_engine import ReflexEngine
from daily_distiller import DailyDistiller
from project_scaffolds import create_scaffold, list_templates


# -----------------------------
# Config
# -----------------------------


@dataclasses.dataclass(frozen=True)
class AgentConfig:
    # Brain / LLM
    # llm_provider: "ollama" for local offline brain, or "openai_compatible" for APIs like GapGPT.
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    openai_base_url: str = "https://api.gapgpt.app/v1"
    openai_api_key_env: str = "GAPGPT_API_KEY"
    openai_api_key: str = ""  # Prefer env var; direct key is supported but not recommended.
    openai_timeout_sec: int = 600
    openai_max_tokens: int = 0  # 0 means provider default.

    # Smart brain routing. If llm_provider="auto" or this is true, the agent can route
    # each task between local Ollama and OpenAI-compatible API.
    brain_routing_enabled: bool = False
    brain_routing_simple_provider: str = "ollama"
    brain_routing_complex_provider: str = "openai_compatible"
    brain_routing_sensitive_provider: str = "ollama"
    brain_routing_allow_api_for_sensitive: bool = False

    model: str = "qwen2.5-coder:7b-instruct"
    temperature: float = 0.2
    num_ctx: int = 8192
    max_steps: int = 8
    workspace_root: str = "."
    memory_dir: str = ".sg_agent"

    # Context / reading limits
    max_file_read_chars: int = 20_000
    max_tree_entries: int = 250

    # Project index
    auto_index_on_start: bool = False
    max_index_files: int = 5_000
    max_index_file_bytes: int = 250_000
    index_preview_chars: int = 1_500

    # Safety
    command_timeout_sec: int = 60
    require_approval_for_writes: bool = True
    require_approval_for_commands: bool = True
    create_backups: bool = True
    backup_dir: str = ".sg_agent/backups"
    enable_shortcut_execution: bool = False
    require_approval_for_shortcuts: bool = True
    shortcut_execution_dry_run: bool = False
    shortcut_execution_method: str = "powershell_sendkeys"
    shortcut_execution_delay_ms: int = 120
    min_desktop_confidence_for_shortcut: float = 0.0
    allow_shortcut_without_desktop_state: bool = True
    mask_secrets: bool = True
    mask_secrets_in_memory: bool = True
    block_sensitive_file_reads: bool = False
    sensitive_file_globs: Tuple[str, ...] = (
        ".env",
        ".env.*",
        "**/.env",
        "**/.env.*",
        "*.pem",
        "*.key",
        "id_rsa",
        "id_ed25519",
        "**/secrets/**",
        "**/credentials/**",
        "**/.ssh/**",
    )

    # Admin dashboard / supervision
    enable_dashboard: bool = False
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    dashboard_token: str = ""  # if non-empty, dashboard requires this token
    approval_timeout_sec: int = 0  # 0 means wait forever
    policy_file: str = ".sg_agent/policy.json"
    auto_load_policy: bool = True

    # Learning / vector memory / desktop log eye
    vector_memory_file: str = ".sg_agent/vector_memory.sqlite"
    vector_dimensions: int = 384
    desktop_state_file: str = ".sg_agent/desktop_state.json"

    # Reflex / skill learning layer
    reflex_enabled: bool = True
    reflex_auto_execute_trusted: bool = True
    reflex_trust_threshold: float = 0.85
    reflex_require_approval_for_confirm: bool = True
    skills_file: str = ".sg_agent/skills.json"
    intents_file: str = ".sg_agent/intents.json"
    event_journal_dir: str = ".sg_agent/events"
    distillation_dir: str = ".sg_agent/distillations"

    ignored_dirs: Tuple[str, ...] = (
        ".git",
        ".sg_agent",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "target",
        "out",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    )
    ignored_file_globs: Tuple[str, ...] = (
        "*.pyc",
        "*.pyo",
        "*.exe",
        "*.dll",
        "*.so",
        "*.dylib",
        "*.bin",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.gif",
        "*.ico",
        "*.pdf",
        "*.zip",
        "*.tar",
        "*.gz",
        "*.7z",
        "*.rar",
        "*.mp4",
        "*.mp3",
        "*.wav",
        "*.lock",
    )
    blocked_command_fragments: Tuple[str, ...] = (
        "rm -rf /",
        "sudo rm",
        "mkfs",
        "format ",
        "del /s",
        "rmdir /s",
        "shutdown",
        "reboot",
        "reg delete",
        "Remove-Item -Recurse -Force C:\\",
        "Remove-Item -Recurse -Force /",
    )

    @staticmethod
    def load(path: str, root_override: Optional[str] = None) -> "AgentConfig":
        raw: Dict[str, Any] = {}
        p = Path(path)
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
        if root_override:
            raw["workspace_root"] = root_override

        tuple_keys = (
            "blocked_command_fragments",
            "ignored_dirs",
            "ignored_file_globs",
            "sensitive_file_globs",
        )
        for key in tuple_keys:
            if key in raw and isinstance(raw[key], list):
                raw[key] = tuple(raw[key])

        cfg = AgentConfig(**raw)
        allowed_providers = {"ollama", "openai_compatible", "auto"}
        if cfg.llm_provider not in allowed_providers:
            raise ValueError("llm_provider must be 'ollama', 'openai_compatible', or 'auto'")
        for provider_field in (cfg.brain_routing_simple_provider, cfg.brain_routing_complex_provider, cfg.brain_routing_sensitive_provider):
            if provider_field not in {"ollama", "openai_compatible"}:
                raise ValueError("brain routing providers must be 'ollama' or 'openai_compatible'")
        if not (0 <= cfg.temperature <= 2):
            raise ValueError("temperature must be between 0 and 2")
        if cfg.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if cfg.command_timeout_sec <= 0:
            raise ValueError("command_timeout_sec must be positive")
        if cfg.shortcut_execution_delay_ms < 0:
            raise ValueError("shortcut_execution_delay_ms cannot be negative")
        if not (0 <= cfg.min_desktop_confidence_for_shortcut <= 1):
            raise ValueError("min_desktop_confidence_for_shortcut must be between 0 and 1")
        if cfg.openai_timeout_sec <= 0:
            raise ValueError("openai_timeout_sec must be positive")
        if cfg.openai_max_tokens < 0:
            raise ValueError("openai_max_tokens cannot be negative")
        if cfg.dashboard_port <= 0 or cfg.dashboard_port > 65535:
            raise ValueError("dashboard_port must be between 1 and 65535")
        if cfg.approval_timeout_sec < 0:
            raise ValueError("approval_timeout_sec cannot be negative")
        if cfg.max_file_read_chars <= 100:
            raise ValueError("max_file_read_chars is too small")
        if cfg.max_index_files <= 0:
            raise ValueError("max_index_files must be positive")
        if cfg.max_index_file_bytes <= 1024:
            raise ValueError("max_index_file_bytes must be greater than 1024")
        if cfg.vector_dimensions <= 0:
            raise ValueError("vector_dimensions must be positive")
        if not (0 <= cfg.reflex_trust_threshold <= 1):
            raise ValueError("reflex_trust_threshold must be between 0 and 1")
        return cfg


# -----------------------------
# Memory
# -----------------------------


class MemoryStore:
    def __init__(self, db_path: Path, mask_secrets_enabled: bool = True):
        self.db_path = db_path
        self.mask_secrets_enabled = mask_secrets_enabled
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self.conn.commit()

    def add(self, kind: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()
        safe_text = mask_secrets(text) if self.mask_secrets_enabled else text
        safe_metadata = sanitize_for_display(metadata or {}) if self.mask_secrets_enabled else (metadata or {})
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO memories(created_at, kind, text, metadata_json) VALUES (?, ?, ?, ?)",
                (created_at, kind, safe_text, json.dumps(safe_metadata, ensure_ascii=False)),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        q = f"%{query}%"
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT id, created_at, kind, text, metadata_json
                FROM memories
                WHERE text LIKE ? OR kind LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (q, q, limit),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def recent(self, limit: int = 8) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT id, created_at, kind, text, metadata_json
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def export_rows(self, limit: int = 5000) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT id, created_at, kind, text, metadata_json
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    @staticmethod
    def _row_to_memory(r: Tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "id": r[0],
            "created_at": r[1],
            "kind": r[2],
            "text": r[3],
            "metadata": json.loads(r[4] or "{}"),
        }


# -----------------------------
# Project Index
# -----------------------------


LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".php": "php",
    ".rb": "ruby",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c-header",
    ".hpp": "cpp-header",
    ".sh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
}


class ProjectIndex:
    """SQLite-backed lightweight project index for paths, previews, and symbols."""

    def __init__(self, root: Path, cfg: AgentConfig, conn: sqlite3.Connection, db_lock: Optional[threading.RLock] = None):
        self.root = root.resolve()
        self.cfg = cfg
        self.conn = conn
        self.db_lock = db_lock or threading.RLock()
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_index (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                sha256 TEXT NOT NULL,
                ext TEXT NOT NULL,
                language TEXT NOT NULL,
                symbols_json TEXT NOT NULL,
                preview TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def count(self) -> int:
        with self.db_lock:
            row = self.conn.execute("SELECT COUNT(*) FROM file_index").fetchone()
        return int(row[0] or 0)

    def should_ignore_rel(self, rel: Path) -> bool:
        parts = set(rel.parts)
        if any(part in parts for part in self.cfg.ignored_dirs):
            return True
        rel_posix = rel.as_posix()
        name = rel.name
        return any(fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(name, pat) for pat in self.cfg.ignored_file_globs)

    def iter_candidate_files(self) -> List[Path]:
        files: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            current = Path(dirpath).resolve()
            rel_dir = current.relative_to(self.root)
            dirnames[:] = [d for d in dirnames if not self.should_ignore_rel(rel_dir / d)]
            for filename in filenames:
                p = current / filename
                rel = p.relative_to(self.root)
                if self.should_ignore_rel(rel):
                    continue
                files.append(p)
                if len(files) >= self.cfg.max_index_files:
                    return files
        return files

    def rebuild(self) -> Dict[str, Any]:
        started = time.time()
        files = self.iter_candidate_files()
        rows = []
        skipped = 0
        for p in files:
            row = self._make_row(p)
            if row is None:
                skipped += 1
                continue
            rows.append(row)

        with self.db_lock:
            self.conn.execute("DELETE FROM file_index")
            self.conn.executemany(
                """
                INSERT OR REPLACE INTO file_index
                (path, size, mtime, sha256, ext, language, symbols_json, preview, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self.conn.commit()
        elapsed = round(time.time() - started, 3)
        return {
            "ok": True,
            "indexed_files": len(rows),
            "skipped_files": skipped,
            "elapsed_sec": elapsed,
            "summary": self.summary(),
        }

    def upsert_path(self, path: Path) -> None:
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            return
        rel_posix = rel.as_posix()
        if not path.exists() or not path.is_file() or self.should_ignore_rel(rel):
            with self.db_lock:
                self.conn.execute("DELETE FROM file_index WHERE path = ?", (rel_posix,))
                self.conn.commit()
            return
        row = self._make_row(path)
        if row is None:
            return
        with self.db_lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO file_index
                (path, size, mtime, sha256, ext, language, symbols_json, preview, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            self.conn.commit()

    def _make_row(self, p: Path) -> Optional[Tuple[Any, ...]]:
        try:
            stat = p.stat()
            rel = p.resolve().relative_to(self.root)
            rel_posix = rel.as_posix()
            ext = p.suffix.lower()
            language = LANG_BY_EXT.get(ext, "text" if ext else "unknown")

            preview = ""
            symbols: List[Dict[str, Any]] = []
            sha = ""

            if stat.st_size <= self.cfg.max_index_file_bytes:
                data = p.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                if b"\x00" not in data:
                    text = data.decode("utf-8", errors="replace")
                    preview_text = mask_secrets(text) if self.cfg.mask_secrets else text
                    preview = truncate(preview_text, self.cfg.index_preview_chars)
                    symbols = self.extract_symbols(text, ext)
            else:
                sha = f"size:{stat.st_size}:mtime:{stat.st_mtime}"

            indexed_at = dt.datetime.now(dt.timezone.utc).isoformat()
            return (
                rel_posix,
                int(stat.st_size),
                float(stat.st_mtime),
                sha,
                ext,
                language,
                json.dumps(symbols, ensure_ascii=False),
                preview,
                indexed_at,
            )
        except OSError:
            return None

    def extract_symbols(self, text: str, ext: str) -> List[Dict[str, Any]]:
        symbols: List[Dict[str, Any]] = []
        lines = text.splitlines()

        def add(kind: str, name: str, line_no: int) -> None:
            if len(symbols) < 80:
                symbols.append({"kind": kind, "name": name, "line": line_no})

        for i, line in enumerate(lines, start=1):
            if ext == ".py":
                m = re.match(r"^\s*class\s+([A-Za-z_]\w*)", line)
                if m:
                    add("class", m.group(1), i)
                    continue
                m = re.match(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", line)
                if m:
                    add("function", m.group(1), i)
                    continue
            elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
                patterns = [
                    ("class", r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
                    ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
                    ("function", r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?"),
                ]
                for kind, pat in patterns:
                    m = re.match(pat, line)
                    if m:
                        add(kind, m.group(1), i)
                        break
            elif ext in {".go"}:
                m = re.match(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", line)
                if m:
                    add("function", m.group(1), i)
            elif ext in {".rs"}:
                m = re.match(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*\(", line)
                if m:
                    add("function", m.group(1), i)
                m = re.match(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", line)
                if m:
                    add("type", m.group(1), i)
        return symbols

    def summary(self) -> Dict[str, Any]:
        total = self.count()
        with self.db_lock:
            rows = self.conn.execute(
                "SELECT ext, COUNT(*) FROM file_index GROUP BY ext ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
            last = self.conn.execute("SELECT MAX(indexed_at) FROM file_index").fetchone()[0]
        return {
            "total_files": total,
            "top_extensions": [{"ext": r[0] or "[none]", "count": r[1]} for r in rows],
            "last_indexed_at": last,
        }

    def search(self, query: str, limit: int = 12) -> Dict[str, Any]:
        query = query.strip()
        if not query:
            return {"ok": False, "error": "query cannot be empty"}
        if self.count() == 0:
            # Search should work out of the box; build the index on first use.
            self.rebuild()

        like = f"%{query.lower()}%"
        with self.db_lock:
            rows = self.conn.execute(
                """
                SELECT path, size, ext, language, symbols_json, preview
                FROM file_index
                WHERE lower(path) LIKE ? OR lower(preview) LIKE ? OR lower(symbols_json) LIKE ?
                ORDER BY path ASC
                LIMIT ?
                """,
                (like, like, like, max(limit * 4, limit)),
            ).fetchall()

        results: List[Dict[str, Any]] = []
        q_lower = query.lower()
        for row in rows:
            rel_path, size, ext, language, symbols_json, preview = row
            snippets = self._line_snippets(rel_path, q_lower, max_snippets=3)
            symbols = json.loads(symbols_json or "[]")
            matching_symbols = [s for s in symbols if q_lower in str(s.get("name", "")).lower()][:5]
            results.append(
                {
                    "path": rel_path,
                    "size": size,
                    "ext": ext,
                    "language": language,
                    "symbols": matching_symbols,
                    "snippets": snippets,
                    "preview": "" if snippets else truncate(preview, 500),
                }
            )
            if len(results) >= limit:
                break
        return {"ok": True, "query": query, "results": results, "index_summary": self.summary()}

    def _line_snippets(self, rel_path: str, q_lower: str, max_snippets: int = 3) -> List[Dict[str, Any]]:
        p = (self.root / rel_path).resolve()
        try:
            if not p.exists() or p.stat().st_size > self.cfg.max_index_file_bytes:
                return []
            data = p.read_bytes()
            if b"\x00" in data:
                return []
            text = data.decode("utf-8", errors="replace")
        except OSError:
            return []
        snippets: List[Dict[str, Any]] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if q_lower in line.lower():
                safe_line = mask_secrets(line.strip()) if self.cfg.mask_secrets else line.strip()
                snippets.append({"line": i, "text": truncate(safe_line, 300)})
                if len(snippets) >= max_snippets:
                    break
        return snippets


# -----------------------------
# Ollama Client
# -----------------------------


class OllamaClient:
    def __init__(self, base_url: str, model: str, temperature: float, num_ctx: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx

    def chat(self, messages: List[Dict[str, str]]) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
                return obj.get("message", {}).get("content", "")
        except urllib.error.URLError as e:
            raise RuntimeError(
                "Could not connect to Ollama. Make sure Ollama is running and the model is pulled. "
                f"URL={url}. Error={e}"
            ) from e


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat/completions client without external dependencies.

    Works with providers exposing:
      POST {base_url}/chat/completions
    such as GapGPT base URL: https://api.gapgpt.app/v1
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float,
        timeout_sec: int = 600,
        max_tokens: int = 0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_sec = timeout_sec
        self.max_tokens = max_tokens

    def _chat_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if not self.api_key:
            raise RuntimeError(
                "OpenAI-compatible provider selected, but API key is missing. "
                "Set openai_api_key_env in config and define that environment variable, "
                "or set openai_api_key directly (not recommended)."
            )
        url = self._chat_url()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.max_tokens > 0:
            payload["max_tokens"] = self.max_tokens
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                obj = json.loads(raw)
                choices = obj.get("choices") or []
                if not choices:
                    raise RuntimeError(f"OpenAI-compatible API returned no choices. Response={truncate(mask_secrets(raw), 2000)}")
                message = choices[0].get("message") or {}
                content = message.get("content")
                if content is None:
                    # Some compatible APIs may return text.
                    content = choices[0].get("text", "")
                return str(content or "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError(f"OpenAI-compatible API HTTP {e.code}: {e.reason}. Body={truncate(mask_secrets(body), 2000)}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not connect to OpenAI-compatible API. URL={url}. Error={e}") from e


# -----------------------------
# Utilities
# -----------------------------


def now_local() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n\n... [truncated: {len(s) - max_chars} chars omitted]"


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    ans = input(f"{prompt} {suffix} ").strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes", "بله", "آره", "اره"}


def extract_json_object(text: str) -> Dict[str, Any]:
    """Try to extract one JSON object from model output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text.strip()).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        return json.loads(candidate)
    raise ValueError("Model did not return valid JSON object")


def render_diff(old: str, new: str, fromfile: str = "old", tofile: str = "new") -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{int(time.time() * 1000)}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


# -----------------------------
# Tools
# -----------------------------


class ToolExecutor:
    def __init__(
        self,
        root: Path,
        cfg: AgentConfig,
        memory: MemoryStore,
        indexer: ProjectIndex,
        admin: Optional[Any] = None,
        vector_store: Optional[VectorMemoryStore] = None,
        desktop_io: Optional[DesktopIORegistry] = None,
    ):
        self.root = root.resolve()
        self.cfg = cfg
        self.memory = memory
        self.indexer = indexer
        self.admin = admin
        self.vector_store = vector_store
        self.desktop_io = desktop_io

    def _safe_path(self, rel_path: str) -> Path:
        rel_path = rel_path or "."
        p = (self.root / rel_path).resolve()
        try:
            p.relative_to(self.root)
        except ValueError:
            raise ValueError(f"Path escapes workspace root: {rel_path}")
        return p

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _backup_file(self, path: Path) -> Optional[str]:
        if not self.cfg.create_backups or not path.exists() or not path.is_file():
            return None
        rel = path.resolve().relative_to(self.root)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.root / self.cfg.backup_dir / stamp / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(path.read_bytes())
        return backup_path.relative_to(self.root).as_posix()

    def _request_approval(self, kind: str, title: str, details: Dict[str, Any], console_prompt: str) -> bool:
        if self.admin is not None:
            return bool(
                self.admin.request_approval(
                    kind=kind,
                    title=title,
                    details=details,
                    console_fallback=lambda: yes_no(console_prompt),
                )
            )
        return yes_no(console_prompt)

    def _sanitize(self, value: Any, max_string: Optional[int] = None) -> Any:
        if not self.cfg.mask_secrets:
            return value
        return sanitize_for_display(value, max_string=max_string)

    def _mask_text(self, text: str) -> str:
        return mask_secrets(text) if self.cfg.mask_secrets else text

    def _emit(self, event_type: str, message: str, data: Optional[Dict[str, Any]] = None, level: str = "info") -> None:
        if self.admin is not None:
            self.admin.emit(event_type, self._mask_text(message), self._sanitize(data or {}, max_string=4000), level=level)

    def project_tree(self) -> str:
        entries: List[str] = []
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            current = Path(dirpath).resolve()
            rel_dir = current.relative_to(self.root)
            dirnames[:] = [d for d in dirnames if not self.indexer.should_ignore_rel(rel_dir / d)]
            depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
            if depth > 3:
                dirnames[:] = []
                continue
            indent = "  " * depth
            if str(rel_dir) != ".":
                entries.append(f"{indent}{rel_dir.name}/")
                count += 1
            for f in sorted(filenames)[:40]:
                rel_file = rel_dir / f
                if self.indexer.should_ignore_rel(rel_file):
                    continue
                entries.append(f"{indent}  {f}")
                count += 1
                if count >= self.cfg.max_tree_entries:
                    entries.append("... [tree truncated]")
                    return "\n".join(entries)
        return "\n".join(entries) if entries else "[empty project]"

    def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        tool = action.get("tool")
        args = action.get("args") or {}
        self._emit("tool.start", f"Tool started: {tool}", {"tool": tool, "args": args})
        try:
            if tool == "list_dir":
                result = self.list_dir(str(args.get("path", ".")))
            elif tool == "read_file":
                result = self.read_file(str(args.get("path", "")), int(args.get("max_chars") or self.cfg.max_file_read_chars))
            elif tool == "write_file":
                result = self.write_file(str(args.get("path", "")), str(args.get("content", "")))
            elif tool == "edit_file":
                result = self.edit_file(str(args.get("path", "")), str(args.get("old_text", "")), str(args.get("new_text", "")))
            elif tool == "edit_file_multi":
                result = self.edit_file_multi(str(args.get("path", "")), args.get("replacements") or [])
            elif tool == "apply_patch":
                result = self.apply_patch(str(args.get("patch", "")))
            elif tool == "run_command":
                result = self.run_command(str(args.get("command", "")), str(args.get("cwd", ".")), int(args.get("timeout_sec") or self.cfg.command_timeout_sec))
            elif tool == "index_project":
                result = self.index_project()
            elif tool == "list_project_templates":
                result = self.list_project_templates()
            elif tool == "create_project":
                result = self.create_project(
                    template=str(args.get("template", "")),
                    project_name=str(args.get("project_name", "")),
                    description=str(args.get("description", "")),
                    overwrite=bool(args.get("overwrite", False)),
                    dry_run=bool(args.get("dry_run", False)),
                )
            elif tool == "search_project":
                result = self.search_project(str(args.get("query", "")), int(args.get("limit") or 12))
            elif tool == "add_vector_memory":
                result = self.add_vector_memory(str(args.get("text", "")), str(args.get("namespace", "general")), str(args.get("source", "agent_tool")))
            elif tool == "search_vector_memory":
                result = self.search_vector_memory(str(args.get("query", "")), str(args.get("namespace", "") or ""), int(args.get("limit") or 8))
            elif tool == "register_desktop_log":
                result = self.register_desktop_log(str(args.get("path", "")))
            elif tool == "observe_desktop_logs":
                result = self.observe_desktop_logs()
            elif tool == "register_shortcut":
                result = self.register_shortcut(args)
            elif tool == "suggest_shortcut":
                result = self.suggest_shortcut(str(args.get("intent", "")), str(args.get("app", "") or ""))
            elif tool == "execute_shortcut":
                result = self.execute_shortcut(str(args.get("name", "")), bool(args.get("dry_run", self.cfg.shortcut_execution_dry_run)))
            elif tool == "git_status":
                result = self.git_status(int(args.get("max_chars") or 12_000))
            elif tool == "git_diff":
                result = self.git_diff(str(args.get("path", "")), bool(args.get("staged", False)), int(args.get("max_chars") or 20_000))
            elif tool == "git_log":
                result = self.git_log(int(args.get("limit") or 8))
            elif tool == "ask_admin":
                result = self.ask_admin(
                    str(args.get("question", "")),
                    args.get("options") or [],
                    int(args.get("timeout_sec") or 0),
                )
            elif tool == "remember":
                result = self.remember(str(args.get("text", "")), str(args.get("kind", "experience")))
            elif tool == "search_memory":
                result = self.search_memory(str(args.get("query", "")), int(args.get("limit") or 8))
            elif tool == "finish":
                result = {"ok": True, "finished": True, "final": str(args.get("answer", ""))}
            else:
                result = {"ok": False, "error": f"Unknown tool: {tool}"}
            self._emit("tool.finish", f"Tool finished: {tool}", {"tool": tool, "ok": result.get("ok"), "result": result}, level="info" if result.get("ok") else "warning")
            return result
        except Exception as e:
            result = {"ok": False, "error": str(e), "traceback": traceback.format_exc(limit=2)}
            self._emit("tool.error", f"Tool error: {tool}", result, level="error")
            return result

    def list_dir(self, path: str) -> Dict[str, Any]:
        p = self._safe_path(path)
        if not p.exists():
            return {"ok": False, "error": "path does not exist"}
        if not p.is_dir():
            return {"ok": False, "error": "path is not a directory"}
        items = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            rel = child.resolve().relative_to(self.root)
            if self.indexer.should_ignore_rel(rel):
                continue
            try:
                stat = child.stat()
                items.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": stat.st_size,
                    }
                )
            except OSError:
                items.append({"name": child.name, "type": "unknown", "size": None})
        return {"ok": True, "path": self._rel(p), "items": items[:300]}

    def read_file(self, path: str, max_chars: int) -> Dict[str, Any]:
        p = self._safe_path(path)
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "file does not exist"}
        rel_path = self._rel(p)
        sensitive_path = looks_sensitive_path(rel_path, self.cfg.sensitive_file_globs)
        if sensitive_path and self.cfg.block_sensitive_file_reads:
            self._emit("security.sensitive_read_blocked", "Blocked sensitive file read", {"path": rel_path}, level="warning")
            return {"ok": False, "error": "sensitive file read is blocked by config", "path": rel_path, "sensitive_path": True}
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="utf-8", errors="replace")
        findings = find_secrets(content) if self.cfg.mask_secrets else []
        safe_content = mask_secrets(content) if self.cfg.mask_secrets else content
        if findings or sensitive_path:
            self._emit(
                "security.secrets_masked",
                "Secrets/sensitive content masked during read_file",
                {"path": rel_path, "sensitive_path": sensitive_path, "finding_count": len(findings), "findings": findings[:10]},
                level="warning",
            )
        limit = min(max_chars, self.cfg.max_file_read_chars)
        return {
            "ok": True,
            "path": rel_path,
            "content": truncate(safe_content, limit),
            "truncated": len(safe_content) > limit,
            "secrets_masked": bool(findings),
            "sensitive_path": sensitive_path,
            "secret_finding_count": len(findings),
        }

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        p = self._safe_path(path)
        old = ""
        existed = p.exists()
        if existed and p.is_file():
            old = p.read_text(encoding="utf-8", errors="replace")
        diff = render_diff(old, content, self._rel(p) + " (old)", self._rel(p) + " (new)")
        display_diff = self._mask_text(diff or "[new file/no textual diff]")
        findings = find_secrets(diff) if self.cfg.mask_secrets else []
        print("\n--- Proposed write diff ---")
        print(truncate(display_diff, 16_000))
        print("--- End diff ---\n")
        if (self.cfg.require_approval_for_writes or (self.admin is not None and self.admin.permissions.get("read_only_mode"))) and not self._request_approval(
            kind="write",
            title=f"write_file: {self._rel(p)}",
            details={
                "path": self._rel(p),
                "existed": existed,
                "bytes": len(content.encode("utf-8")),
                "diff": truncate(display_diff, 16_000),
                "secrets_masked": bool(findings),
                "secret_finding_count": len(findings),
            },
            console_prompt=f"Apply write_file to {self._rel(p)}?",
        ):
            return {"ok": False, "cancelled": True, "error": "User rejected write_file"}
        backup = self._backup_file(p)
        atomic_write_text(p, content)
        self.indexer.upsert_path(p)
        self.memory.add("file_changed", f"write_file {self._rel(p)}", {"backup": backup, "existed": existed})
        return {
            "ok": True,
            "path": self._rel(p),
            "bytes": len(content.encode("utf-8")),
            "existed": existed,
            "backup": backup,
        }

    def edit_file(self, path: str, old_text: str, new_text: str) -> Dict[str, Any]:
        return self.edit_file_multi(path, [{"old_text": old_text, "new_text": new_text}])

    def edit_file_multi(self, path: str, replacements: Any) -> Dict[str, Any]:
        if not isinstance(replacements, list) or not replacements:
            return {"ok": False, "error": "replacements must be a non-empty list"}
        p = self._safe_path(path)
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "file does not exist"}
        original = p.read_text(encoding="utf-8", errors="replace")
        updated = original
        applied: List[Dict[str, Any]] = []

        for idx, rep in enumerate(replacements, start=1):
            if not isinstance(rep, dict):
                return {"ok": False, "error": f"replacement #{idx} must be an object"}
            old_text = str(rep.get("old_text", rep.get("old", "")))
            new_text = str(rep.get("new_text", rep.get("new", "")))
            replace_all = bool(rep.get("replace_all", False))
            if not old_text:
                return {"ok": False, "error": f"replacement #{idx}: old_text cannot be empty"}
            occurrences = updated.count(old_text)
            if occurrences == 0:
                return {
                    "ok": False,
                    "error": f"replacement #{idx}: old_text not found exactly in file",
                    "path": self._rel(p),
                    "old_text_preview": truncate(self._mask_text(old_text), 500),
                }
            if replace_all:
                updated = updated.replace(old_text, new_text)
                count = occurrences
            else:
                updated = updated.replace(old_text, new_text, 1)
                count = 1
            applied.append({"index": idx, "occurrences_before": occurrences, "applied": count})

        if updated == original:
            return {"ok": True, "path": self._rel(p), "changed": False, "message": "No changes produced"}

        diff = render_diff(original, updated, self._rel(p) + " (old)", self._rel(p) + " (new)")
        display_diff = self._mask_text(diff)
        findings = find_secrets(diff) if self.cfg.mask_secrets else []
        print("\n--- Proposed edit diff ---")
        print(truncate(display_diff, 16_000))
        print("--- End diff ---\n")
        if (self.cfg.require_approval_for_writes or (self.admin is not None and self.admin.permissions.get("read_only_mode"))) and not self._request_approval(
            kind="edit",
            title=f"edit_file_multi: {self._rel(p)}",
            details={
                "path": self._rel(p),
                "applied_preview": applied,
                "diff": truncate(display_diff, 16_000),
                "secrets_masked": bool(findings),
                "secret_finding_count": len(findings),
            },
            console_prompt=f"Apply edit_file_multi to {self._rel(p)}?",
        ):
            return {"ok": False, "cancelled": True, "error": "User rejected edit_file_multi"}
        backup = self._backup_file(p)
        atomic_write_text(p, updated)
        self.indexer.upsert_path(p)
        self.memory.add("file_changed", f"edit_file_multi {self._rel(p)}", {"backup": backup, "applied": applied})
        return {"ok": True, "path": self._rel(p), "changed": True, "applied": applied, "backup": backup}

    def _paths_from_unified_patch(self, patch: str) -> List[str]:
        paths: List[str] = []
        for line in patch.splitlines():
            if not (line.startswith("--- ") or line.startswith("+++ ")):
                continue
            raw = line[4:].split("\t", 1)[0].strip()
            if raw == "/dev/null":
                continue
            if raw.startswith("a/") or raw.startswith("b/"):
                raw = raw[2:]
            if raw and raw not in paths:
                # Validate path is inside workspace.
                self._safe_path(raw)
                paths.append(raw)
        return paths

    def apply_patch(self, patch: str) -> Dict[str, Any]:
        """Apply a multi-file unified diff using git apply after approval.

        This is closer to a Cursor-style patch engine than old_text replacement.
        It requires git executable, but does not require committing/staging changes.
        """
        patch = patch.strip("\n") + "\n"
        if not patch.strip():
            return {"ok": False, "error": "patch cannot be empty"}
        paths = self._paths_from_unified_patch(patch)
        if not paths:
            return {"ok": False, "error": "could not detect file paths in unified patch"}

        try:
            check = subprocess.run(
                ["git", "apply", "--check", "--whitespace=nowarn", "-"],
                cwd=str(self.root),
                input=patch,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "git executable not found; apply_patch requires git"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "git apply --check timed out"}

        if check.returncode != 0:
            return {
                "ok": False,
                "error": "patch check failed",
                "stdout": truncate(self._mask_text(check.stdout), 4000),
                "stderr": truncate(self._mask_text(check.stderr), 4000),
                "paths": paths,
            }

        display_patch = self._mask_text(patch)
        findings = find_secrets(patch) if self.cfg.mask_secrets else []
        print("\n--- Proposed unified patch ---")
        print(truncate(display_patch, 20_000))
        print("--- End patch ---\n")
        if (self.cfg.require_approval_for_writes or (self.admin is not None and self.admin.permissions.get("read_only_mode"))) and not self._request_approval(
            kind="edit",
            title=f"apply_patch: {len(paths)} file(s)",
            details={"paths": paths, "patch": truncate(display_patch, 20_000), "secrets_masked": bool(findings), "secret_finding_count": len(findings)},
            console_prompt=f"Apply unified patch to {len(paths)} file(s)?",
        ):
            return {"ok": False, "cancelled": True, "error": "User rejected apply_patch"}

        backups: Dict[str, Optional[str]] = {}
        for rel_path in paths:
            p = self._safe_path(rel_path)
            backups[rel_path] = self._backup_file(p)

        apply = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=str(self.root),
            input=patch,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if apply.returncode != 0:
            return {
                "ok": False,
                "error": "patch apply failed after successful check",
                "stdout": truncate(self._mask_text(apply.stdout), 4000),
                "stderr": truncate(self._mask_text(apply.stderr), 4000),
                "paths": paths,
                "backups": backups,
            }

        for rel_path in paths:
            self.indexer.upsert_path(self._safe_path(rel_path))
        self.memory.add("file_changed", f"apply_patch {len(paths)} files", {"paths": paths, "backups": backups})
        return {"ok": True, "paths": paths, "backups": backups, "stdout": truncate(self._mask_text(apply.stdout), 4000), "stderr": truncate(self._mask_text(apply.stderr), 4000), "secrets_masked": bool(findings), "secret_finding_count": len(findings)}

    def run_command(self, command: str, cwd: str, timeout_sec: int) -> Dict[str, Any]:
        command = command.strip()
        if not command:
            return {"ok": False, "error": "command cannot be empty"}
        lowered = command.lower()
        for frag in self.cfg.blocked_command_fragments:
            if frag.lower() in lowered:
                return {"ok": False, "error": f"blocked dangerous command fragment: {frag}"}
        workdir = self._safe_path(cwd)
        if not workdir.exists() or not workdir.is_dir():
            return {"ok": False, "error": "cwd does not exist or is not directory"}
        display_command = self._mask_text(command)
        print("\n--- Proposed command ---")
        print(f"cwd: {workdir}")
        print(display_command)
        print("--- End command ---\n")
        if (self.cfg.require_approval_for_commands or (self.admin is not None and self.admin.permissions.get("read_only_mode"))) and not self._request_approval(
            kind="command",
            title=f"run_command: {display_command[:120]}",
            details={
                "command": display_command,
                "cwd": self._rel(workdir),
                "timeout_sec": min(timeout_sec, self.cfg.command_timeout_sec),
            },
            console_prompt="Run this command?",
        ):
            return {"ok": False, "cancelled": True, "error": "User rejected run_command"}
        started = time.time()
        proc = subprocess.run(
            command,
            cwd=str(workdir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=min(timeout_sec, self.cfg.command_timeout_sec),
        )
        elapsed = time.time() - started
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_sec": round(elapsed, 3),
            "stdout": truncate(self._mask_text(proc.stdout), 12_000),
            "stderr": truncate(self._mask_text(proc.stderr), 12_000),
        }

    def index_project(self) -> Dict[str, Any]:
        return self.indexer.rebuild()

    def list_project_templates(self) -> Dict[str, Any]:
        return {"ok": True, "templates": list_templates()}

    def create_project(
        self,
        template: str,
        project_name: str,
        description: str = "",
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        try:
            scaffold = create_scaffold(template, project_name, description)
        except Exception as e:
            return {"ok": False, "error": str(e), "available_templates": list_templates()}

        base = self._safe_path(scaffold.project_name)
        if base.exists() and not base.is_dir():
            return {"ok": False, "error": "project path exists and is not a directory", "path": self._rel(base)}

        file_plan: List[Dict[str, Any]] = []
        conflicts: List[str] = []
        combined_diff_parts: List[str] = []
        for rel_file, content in scaffold.files.items():
            dest = (base / rel_file).resolve()
            try:
                dest.relative_to(base.resolve())
                dest.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": f"scaffold file escapes project/root: {rel_file}"}
            existed = dest.exists()
            if existed and not overwrite:
                conflicts.append(dest.relative_to(self.root).as_posix())
            old = dest.read_text(encoding="utf-8", errors="replace") if existed and dest.is_file() else ""
            diff = render_diff(old, content, dest.relative_to(self.root).as_posix() + " (old)", dest.relative_to(self.root).as_posix() + " (new)")
            combined_diff_parts.append(diff or f"--- {dest.relative_to(self.root).as_posix()} (new file)\n+++ {dest.relative_to(self.root).as_posix()}\n[content length: {len(content)} chars]\n")
            file_plan.append({"path": dest.relative_to(self.root).as_posix(), "bytes": len(content.encode("utf-8")), "existed": existed})

        preview = self._mask_text("\n".join(combined_diff_parts))
        if conflicts and not dry_run:
            return {
                "ok": False,
                "error": "target files already exist; set overwrite=true or choose a different project_name",
                "conflicts": conflicts,
                "template": scaffold.template,
                "project_name": scaffold.project_name,
                "files": file_plan,
                "preview": truncate(preview, 20_000),
            }

        print("\n--- Proposed project scaffold ---")
        print(f"template: {scaffold.template}")
        print(f"project: {scaffold.project_name}")
        print(truncate(preview, 20_000))
        print("--- End scaffold preview ---\n")

        result_base = {
            "ok": True,
            "dry_run": dry_run,
            "template": scaffold.template,
            "project_name": scaffold.project_name,
            "description": scaffold.description,
            "project_path": base.relative_to(self.root).as_posix(),
            "files": file_plan,
            "run_commands": scaffold.run_commands,
            "next_steps": scaffold.next_steps,
            "preview": truncate(preview, 20_000),
            "overwrite": overwrite,
            "conflicts": conflicts,
        }
        if dry_run:
            return result_base

        if self.cfg.require_approval_for_writes and not self._request_approval(
            kind="write",
            title=f"create_project: {scaffold.project_name} ({scaffold.template})",
            details={k: v for k, v in result_base.items() if k != "preview"} | {"preview": truncate(preview, 20_000)},
            console_prompt=f"Create project {scaffold.project_name} from template {scaffold.template}?",
        ):
            return {"ok": False, "cancelled": True, "error": "User rejected create_project", **result_base}

        backups: Dict[str, Optional[str]] = {}
        for rel_file, content in scaffold.files.items():
            dest = (base / rel_file).resolve()
            backups[dest.relative_to(self.root).as_posix()] = self._backup_file(dest)
            atomic_write_text(dest, content)
            self.indexer.upsert_path(dest)
        self.memory.add(
            "project_created",
            f"Created project {scaffold.project_name} using template {scaffold.template}",
            {"template": scaffold.template, "project_path": base.relative_to(self.root).as_posix(), "files": file_plan, "run_commands": scaffold.run_commands},
        )
        result_base["backups"] = backups
        result_base["created"] = True
        return result_base

    def search_project(self, query: str, limit: int) -> Dict[str, Any]:
        return self.indexer.search(query, limit=limit)

    def add_vector_memory(self, text: str, namespace: str = "general", source: str = "agent_tool") -> Dict[str, Any]:
        if self.vector_store is None:
            return {"ok": False, "error": "vector memory is not configured"}
        if not text.strip():
            return {"ok": False, "error": "text cannot be empty"}
        mid = self.vector_store.add(text=text, namespace=namespace or "general", source=source or "agent_tool")
        return {"ok": True, "id": mid, "namespace": namespace or "general"}

    def search_vector_memory(self, query: str, namespace: str = "", limit: int = 8) -> Dict[str, Any]:
        if self.vector_store is None:
            return {"ok": False, "error": "vector memory is not configured"}
        if not query.strip():
            return {"ok": False, "error": "query cannot be empty"}
        results = self.vector_store.search(query=query, namespace=namespace or None, limit=limit)
        return {"ok": True, "query": query, "namespace": namespace or None, "results": [dataclasses.asdict(r) for r in results]}

    def register_desktop_log(self, path: str) -> Dict[str, Any]:
        if self.desktop_io is None:
            return {"ok": False, "error": "desktop I/O registry is not configured"}
        if not path.strip():
            return {"ok": False, "error": "path cannot be empty"}
        return self.desktop_io.register_log_path(path)

    def observe_desktop_logs(self) -> Dict[str, Any]:
        if self.desktop_io is None:
            return {"ok": False, "error": "desktop I/O registry is not configured"}
        result = self.desktop_io.observe_from_logs()
        if self.vector_store is not None and result.get("ok"):
            for obs in result.get("observations", []):
                text = f"Desktop observation app={obs.get('app')} location={obs.get('location')} summary={obs.get('summary')}"
                self.vector_store.add(text, namespace="desktop_observation", source="desktop_logs", metadata=obs)
        return result

    def register_shortcut(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.desktop_io is None:
            return {"ok": False, "error": "desktop I/O registry is not configured"}
        name = str(args.get("name", "")).strip()
        description = str(args.get("description", "")).strip()
        keys_raw = args.get("keys", [])
        if isinstance(keys_raw, str):
            keys = [x.strip() for x in keys_raw.split("+") if x.strip()]
        elif isinstance(keys_raw, list):
            keys = [str(x).strip() for x in keys_raw if str(x).strip()]
        else:
            keys = []
        if not name or not keys:
            return {"ok": False, "error": "shortcut name and keys are required"}
        action = ShortcutAction(
            name=name,
            description=description or name,
            keys=keys,
            app=str(args.get("app", "global") or "global"),
            risk=str(args.get("risk", "low") or "low"),
            requires_approval=bool(args.get("requires_approval", False)),
        )
        return self.desktop_io.register_shortcut(action)

    def suggest_shortcut(self, intent: str, app: str = "") -> Dict[str, Any]:
        if self.desktop_io is None:
            return {"ok": False, "error": "desktop I/O registry is not configured"}
        return self.desktop_io.suggest_shortcut(intent, app or None)

    def _desktop_confidence_ok(self) -> Tuple[bool, float, str]:
        threshold = self.cfg.min_desktop_confidence_for_shortcut
        if threshold <= 0:
            return True, 0.0, "confidence check disabled"
        if self.desktop_io is None:
            return False, 0.0, "desktop I/O registry is not configured"
        snapshot = self.desktop_io.get_state_snapshot(limit=5)
        current = snapshot.get("current_by_app", {}) or {}
        if not current:
            return (True, 0.0, "no desktop state; allowed by config") if self.cfg.allow_shortcut_without_desktop_state else (False, 0.0, "no desktop state")
        max_conf = max(float(v.get("confidence") or 0.0) for v in current.values())
        return max_conf >= threshold, max_conf, f"max confidence={max_conf}, threshold={threshold}"

    def execute_shortcut(self, name: str, dry_run: bool = False) -> Dict[str, Any]:
        if self.desktop_io is None:
            return {"ok": False, "error": "desktop I/O registry is not configured"}
        if not name.strip():
            return {"ok": False, "error": "shortcut name cannot be empty"}
        if not self.cfg.enable_shortcut_execution and not dry_run:
            return {"ok": False, "error": "shortcut execution is disabled. Enable it in runtime config or use dry_run=true."}
        ok_conf, confidence, conf_reason = self._desktop_confidence_ok()
        if not ok_conf and not dry_run:
            return {"ok": False, "error": "desktop confidence is too low for shortcut execution", "confidence": confidence, "reason": conf_reason}
        shortcut = self.desktop_io.shortcuts.get(name)
        if not shortcut:
            return {"ok": False, "error": f"shortcut not registered: {name}", "known_shortcuts": list(self.desktop_io.shortcuts.keys())}
        if self.cfg.require_approval_for_shortcuts and not dry_run:
            approved = self._request_approval(
                kind="shortcut",
                title=f"execute_shortcut: {name}",
                details={
                    "name": name,
                    "shortcut": dataclasses.asdict(shortcut),
                    "confidence": confidence,
                    "confidence_reason": conf_reason,
                    "method": self.cfg.shortcut_execution_method,
                },
                console_prompt=f"Execute shortcut {name} ({'+'.join(shortcut.keys)})?",
            )
            if not approved:
                return {"ok": False, "cancelled": True, "error": "User rejected execute_shortcut"}
        return self.desktop_io.execute_shortcut(
            name=name,
            dry_run=dry_run or self.cfg.shortcut_execution_dry_run,
            method=self.cfg.shortcut_execution_method,
            delay_ms=self.cfg.shortcut_execution_delay_ms,
        )

    def _run_git(self, args: List[str], max_chars: int = 12_000) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": truncate(self._mask_text(proc.stdout), max_chars),
                "stderr": truncate(self._mask_text(proc.stderr), max_chars),
                "command": "git " + " ".join(args),
            }
        except FileNotFoundError:
            return {"ok": False, "error": "git executable not found"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "git command timed out"}

    def git_status(self, max_chars: int = 12_000) -> Dict[str, Any]:
        return self._run_git(["status", "--short", "--branch"], max_chars=max_chars)

    def git_diff(self, path: str = "", staged: bool = False, max_chars: int = 20_000) -> Dict[str, Any]:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            p = self._safe_path(path)
            args.extend(["--", self._rel(p)])
        return self._run_git(args, max_chars=max_chars)

    def git_log(self, limit: int = 8) -> Dict[str, Any]:
        limit = max(1, min(limit, 30))
        return self._run_git(["log", f"-{limit}", "--oneline", "--decorate"], max_chars=12_000)

    def git_status_for_context(self) -> str:
        res = self.git_status(max_chars=2_000)
        if not res.get("ok"):
            err = res.get("stderr") or res.get("error") or "not a git repository"
            return f"[git unavailable or not a repo: {truncate(str(err), 300)}]"
        return res.get("stdout", "").strip() or "[git clean]"

    def ask_admin(self, question: str, options: Any, timeout_sec: int = 0) -> Dict[str, Any]:
        if not question.strip():
            return {"ok": False, "error": "question cannot be empty"}
        normalized_options: List[str] = []
        if isinstance(options, list):
            normalized_options = [str(x) for x in options[:6]]
        if self.admin is not None:
            return self.admin.ask_admin(
                question=question.strip(),
                options=normalized_options,
                timeout_sec=timeout_sec,
                console_fallback=lambda: input(question.strip() + "\nAdmin answer> ").strip(),
            )
        answer = input(question.strip() + "\nAdmin answer> ").strip()
        return {"ok": True, "answer": answer}

    def remember(self, text: str, kind: str) -> Dict[str, Any]:
        if not text.strip():
            return {"ok": False, "error": "memory text cannot be empty"}
        mid = self.memory.add(kind=kind or "experience", text=text.strip(), metadata={"source": "agent_tool"})
        return {"ok": True, "id": mid}

    def search_memory(self, query: str, limit: int) -> Dict[str, Any]:
        return {"ok": True, "results": self.memory.search(query, limit=limit)}


# -----------------------------
# Agent
# -----------------------------


SYSTEM_PROMPT = r"""
You are SkyGround Local Coding Agent, a careful Cursor-like coding assistant running on the user's own machine.

You can inspect and modify ONLY the selected workspace. You have tools for project indexing/search, file reading, file editing, git inspection, shell commands, and local memory.

CRITICAL OUTPUT RULE:
Return ONLY one valid JSON object. No markdown. No extra text.

JSON format:
{
  "thought": "brief private planning summary in Persian or English",
  "actions": [
    {"tool": "search_project", "args": {"query": "login", "limit": 10}},
    {"tool": "list_dir", "args": {"path": "."}},
    {"tool": "read_file", "args": {"path": "README.md", "max_chars": 12000}},
    {"tool": "edit_file", "args": {"path": "file.py", "old_text": "exact old text", "new_text": "new text"}},
    {"tool": "edit_file_multi", "args": {"path": "file.py", "replacements": [{"old_text": "exact old", "new_text": "new"}]}},
    {"tool": "apply_patch", "args": {"patch": "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"}},
    {"tool": "write_file", "args": {"path": "new_file.py", "content": "..."}},
    {"tool": "git_status", "args": {}},
    {"tool": "git_diff", "args": {"path": "", "staged": false, "max_chars": 20000}},
    {"tool": "run_command", "args": {"command": "python -m pytest", "cwd": ".", "timeout_sec": 60}},
    {"tool": "index_project", "args": {}},
    {"tool": "list_project_templates", "args": {}},
    {"tool": "create_project", "args": {"template": "python_flask_site", "project_name": "my_site", "description": "A simple Python website", "dry_run": false}}, 
    {"tool": "search_vector_memory", "args": {"query": "login token", "namespace": "monthly_experience", "limit": 5}},
    {"tool": "observe_desktop_logs", "args": {}},
    {"tool": "suggest_shortcut", "args": {"intent": "open search", "app": "vscode"}},
    {"tool": "execute_shortcut", "args": {"name": "open_search", "dry_run": true}},
    {"tool": "ask_admin", "args": {"question": "Do you want me to run the full test suite?", "options": ["yes", "no"], "timeout_sec": 0}},
    {"tool": "remember", "args": {"kind": "project_fact", "text": "..."}},
    {"tool": "search_memory", "args": {"query": "...", "limit": 5}},
    {"tool": "finish", "args": {"answer": "final answer to user"}}
  ]
}

Available tools:
- index_project(): rebuild the local project index. Useful after many changes or if search seems stale.
- search_project(query, limit): search indexed paths, previews, and symbols. Auto-indexes on first use.
- list_project_templates(): list built-in project scaffold templates.
- create_project(template, project_name, description, overwrite, dry_run): create a new project from a built-in template. Use for new-project requests such as "یک وب‌سایت با پایتون بساز". Shows one scaffold preview and requires approval unless dry_run=true.
- list_dir(path): list files/directories under workspace.
- read_file(path, max_chars): read text file.
- write_file(path, content): create/replace a text file. Shows diff, creates backup, requires user approval.
- edit_file(path, old_text, new_text): exact single replacement. Shows diff, creates backup, requires user approval.
- edit_file_multi(path, replacements): multiple exact replacements in one file. Prefer this for several small edits. Shows one diff, creates backup, requires user approval.
- apply_patch(patch): apply a multi-file unified diff using git apply. Prefer this for coordinated multi-file changes. Shows patch, creates backups, requires user/admin approval.
- git_status(): read-only git status. No approval required.
- git_diff(path, staged, max_chars): read-only git diff. No approval required.
- git_log(limit): read-only recent commit log. No approval required.
- run_command(command, cwd, timeout_sec): run shell command. Requires user/admin approval.
- ask_admin(question, options, timeout_sec): ask the human admin through dashboard/CLI and wait for an answer.
- add_vector_memory(text, namespace, source): store an important learned fact in local vector memory.
- search_vector_memory(query, namespace, limit): retrieve semantically related past experiences from vector memory.
- register_desktop_log(path): register an application log file as a safe desktop-eye source.
- observe_desktop_logs(): read registered log tails to infer current app/screen/location without screenshots.
- register_shortcut(name, description, keys, app, risk, requires_approval): register a known shortcut.
- suggest_shortcut(intent, app): suggest registered shortcuts for an intent; does not execute.
- execute_shortcut(name, dry_run): execute a registered shortcut only; no free typing/clicking. Use dry_run first unless the user/admin clearly wants execution.
- remember(kind, text): store long-term experience.
- search_memory(query, limit): retrieve past experiences.
- finish(answer): finish the task.

Behavior rules:
1. For unfamiliar code tasks, start with search_project/list_dir/read_file before editing.
2. For bug fixes, search related names/errors, then inspect the smallest relevant files.
3. Prefer edit_file_multi or edit_file over rewriting whole files.
4. For coordinated multi-file edits, prefer apply_patch with a valid unified diff.
5. For brand-new projects, prefer list_project_templates/create_project before manually writing many files.
6. Use write_file mainly for new files or small complete rewrites.
7. Before meaningful edits in git projects, use git_status if not already available in context.
8. After edits, use git_diff to review and summarize the changes when useful.
9. Never attempt to access files outside workspace.
10. Never run destructive commands.
11. For desktop/app state, prefer observe_desktop_logs and registered shortcuts; do not request screenshots unless absolutely necessary and approved by the user.
12. Before executing a shortcut, verify it is registered and preferably run execute_shortcut with dry_run=true first. Never perform free-form clicking or typing.
13. Use vector memory for learned recurring patterns and search it before repeating old investigations.
14. If you need an operational decision during the task (permission, preference, risky choice), use ask_admin.
15. If you need more information and can stop the task, use finish(answer) with a concise question.
16. After successful changes, remember important project facts or decisions.
17. Final answer should be in Persian unless user asks otherwise.
""".strip()


class LocalCodingAgent:
    def _resolve_openai_api_key(self, cfg: AgentConfig) -> str:
        if cfg.openai_api_key:
            return cfg.openai_api_key
        if cfg.openai_api_key_env:
            return os.environ.get(cfg.openai_api_key_env, "")
        return ""

    def _create_llm_client_for_provider(self, provider: str, cfg: AgentConfig) -> Any:
        if provider == "ollama":
            return OllamaClient(cfg.ollama_url, cfg.model, cfg.temperature, cfg.num_ctx)
        if provider == "openai_compatible":
            return OpenAICompatibleClient(
                base_url=cfg.openai_base_url,
                api_key=self._resolve_openai_api_key(cfg),
                model=cfg.model,
                temperature=cfg.temperature,
                timeout_sec=cfg.openai_timeout_sec,
                max_tokens=cfg.openai_max_tokens,
            )
        raise ValueError(f"Unsupported llm provider: {provider}")

    def _create_llm_client(self, cfg: AgentConfig) -> Any:
        provider = cfg.llm_provider
        if provider == "auto":
            # Default active client for status/fallback. Per-task selection happens in _select_brain.
            if self._provider_available(cfg.brain_routing_complex_provider, cfg):
                provider = cfg.brain_routing_complex_provider
            elif self._provider_available(cfg.brain_routing_simple_provider, cfg):
                provider = cfg.brain_routing_simple_provider
            else:
                provider = "ollama"
        return self._create_llm_client_for_provider(provider, cfg)

    def _provider_available(self, provider: str, cfg: Optional[AgentConfig] = None) -> bool:
        cfg = cfg or self.cfg
        if provider == "ollama":
            return True
        if provider == "openai_compatible":
            return bool(cfg.openai_api_key or (cfg.openai_api_key_env and os.environ.get(cfg.openai_api_key_env)))
        return False

    def _routing_enabled(self) -> bool:
        return self.cfg.llm_provider == "auto" or self.cfg.brain_routing_enabled

    def _task_is_sensitive(self, text: str) -> bool:
        lowered = (text or "").lower()
        sensitive_keywords = [
            ".env", "api key", "apikey", "token", "secret", "password", "passwd", "pwd",
            "private key", "credential", "credentials", "ssh", "pem", "database_url",
            "db_url", "connection string", "authorization", "bearer", "access key",
        ]
        if find_secrets(text):
            return True
        return any(k in lowered for k in sensitive_keywords)

    def _task_is_complex(self, text: str) -> bool:
        lowered = (text or "").lower()
        complex_keywords = [
            "implement", "پیاده", "اعمال", "refactor", "ری‌فکتور", "rewrite", "bug", "fix",
            "debug", "error", "exception", "traceback", "stack", "test", "pytest", "build",
            "architecture", "معماری", "patch", "diff", "multi-file", "security", "review",
            "performance", "optimize", "بهینه", "database", "migration", "api", "login", "auth",
        ]
        return len(text or "") > 900 or any(k in lowered for k in complex_keywords)

    def _select_brain(self, task_text: str) -> Tuple[Any, Dict[str, Any]]:
        cfg = self.cfg
        if not self._routing_enabled():
            provider = cfg.llm_provider if cfg.llm_provider != "auto" else cfg.brain_routing_complex_provider
            if provider == "openai_compatible" and not self._provider_available(provider, cfg):
                provider = "ollama"
            return self._create_llm_client_for_provider(provider, cfg), {
                "routing_enabled": False,
                "provider": provider,
                "reason": "configured_provider",
                "sensitive": self._task_is_sensitive(task_text),
                "complex": self._task_is_complex(task_text),
            }

        sensitive = self._task_is_sensitive(task_text)
        complex_task = self._task_is_complex(task_text)
        reason = "simple_task"
        if sensitive and not cfg.brain_routing_allow_api_for_sensitive:
            provider = cfg.brain_routing_sensitive_provider
            reason = "sensitive_local_policy"
        elif complex_task:
            provider = cfg.brain_routing_complex_provider
            reason = "complex_task"
        else:
            provider = cfg.brain_routing_simple_provider

        fallback = None
        if provider == "openai_compatible" and not self._provider_available(provider, cfg):
            fallback = "openai_api_key_missing"
            provider = "ollama"
        if provider not in {"ollama", "openai_compatible"}:
            fallback = f"invalid_provider_{provider}"
            provider = "ollama"

        return self._create_llm_client_for_provider(provider, cfg), {
            "routing_enabled": True,
            "provider": provider,
            "reason": reason,
            "fallback": fallback,
            "sensitive": sensitive,
            "complex": complex_task,
            "allow_api_for_sensitive": cfg.brain_routing_allow_api_for_sensitive,
        }

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.root = Path(cfg.workspace_root).resolve()
        if not self.root.exists():
            raise FileNotFoundError(f"Workspace root does not exist: {self.root}")
        self.started_at = time.time()
        self.current_task: Optional[str] = None
        self.current_task_id: Optional[str] = None
        self.task_running = False
        self.total_tasks = 0
        self.last_error: Optional[str] = None
        self.last_brain_route: Optional[Dict[str, Any]] = None
        self.dashboard_server: Optional[Any] = None

        # Dashboard task manager state
        self.run_lock = threading.RLock()
        self.task_lock = threading.RLock()
        self.task_queue: "queue.Queue[str]" = queue.Queue()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.task_worker_thread: Optional[threading.Thread] = None
        self.pause_requested = False

        mem_dir = self.root / cfg.memory_dir
        self.memory = MemoryStore(mem_dir / "memory.sqlite", mask_secrets_enabled=cfg.mask_secrets_in_memory)
        self.indexer = ProjectIndex(self.root, cfg, self.memory.conn, db_lock=self.memory.lock)
        vector_path = (self.root / cfg.vector_memory_file).resolve()
        desktop_state_path = (self.root / cfg.desktop_state_file).resolve()
        skills_path = (self.root / cfg.skills_file).resolve()
        intents_path = (self.root / cfg.intents_file).resolve()
        events_dir = (self.root / cfg.event_journal_dir).resolve()
        distillation_dir = (self.root / cfg.distillation_dir).resolve()
        try:
            vector_path.relative_to(self.root)
            desktop_state_path.relative_to(self.root)
            skills_path.relative_to(self.root)
            intents_path.relative_to(self.root)
            events_dir.relative_to(self.root)
            distillation_dir.relative_to(self.root)
        except ValueError:
            raise ValueError("agent state files must stay inside the workspace root")
        self.vector_store = VectorMemoryStore(vector_path, dimensions=cfg.vector_dimensions)
        self.desktop_io = DesktopIORegistry(self.root, state_path=desktop_state_path)
        self.event_journal = EventJournal(events_dir)
        self.intent_registry = IntentRegistry(intents_path)
        self.skill_registry = SkillRegistry(skills_path)
        self.reflex = ReflexEngine(self.intent_registry, self.skill_registry, self.event_journal)
        self.daily_distiller = DailyDistiller(self.event_journal, self.skill_registry, distillation_dir)
        self._seed_foundation_shortcuts()

        self.admin: Optional[Any] = None
        if cfg.enable_dashboard:
            if AdminControlCenter is None or DashboardServer is None:
                raise RuntimeError("dashboard.py is required when enable_dashboard=true")
            policy_path = (self.root / cfg.policy_file).resolve()
            try:
                policy_path.relative_to(self.root)
            except ValueError:
                raise ValueError("policy_file must stay inside the workspace root")
            self.admin = AdminControlCenter(approval_timeout_sec=cfg.approval_timeout_sec)
            self.admin.set_policy_storage(policy_path, auto_load=cfg.auto_load_policy)
            self.admin.set_status_provider(self.status_snapshot)
            self.admin.set_config_callbacks(self.runtime_config_snapshot, self.apply_runtime_config_update)
            self.admin.set_task_callbacks(self.submit_dashboard_task, self.task_manager_snapshot, self.control_dashboard_task)
            self.admin.set_agent_ops_handler(self.handle_dashboard_operation)
            self.dashboard_server = DashboardServer(self.admin, cfg.dashboard_host, cfg.dashboard_port, auth_token=cfg.dashboard_token)
            dashboard_url = self.dashboard_server.start_background()
            print(f"[dashboard] Admin dashboard: {dashboard_url}")

        self.tools = ToolExecutor(self.root, cfg, self.memory, self.indexer, admin=self.admin, vector_store=self.vector_store, desktop_io=self.desktop_io)
        self.llm = self._create_llm_client(cfg)
        if self.admin is not None:
            self.task_worker_thread = threading.Thread(target=self._task_worker_loop, name="SkyGroundTaskWorker", daemon=True)
            self.task_worker_thread.start()
        if cfg.auto_index_on_start and self.indexer.count() == 0:
            print("[index] auto-indexing project on start...")
            print(json.dumps(self.indexer.rebuild(), ensure_ascii=False, indent=2))

    def _seed_foundation_shortcuts(self) -> None:
        """Seed basic low-level shortcuts used by reflex skills."""
        defaults = [
            ShortcutAction("copy", "Copy selection", ["Ctrl", "C"], app="global", risk="low"),
            ShortcutAction("paste", "Paste clipboard", ["Ctrl", "V"], app="global", risk="medium"),
            ShortcutAction("cut", "Cut selection", ["Ctrl", "X"], app="global", risk="medium"),
            ShortcutAction("save", "Save active file/window", ["Ctrl", "S"], app="global", risk="low"),
            ShortcutAction("escape", "Press Escape", ["Esc"], app="global", risk="low"),
            ShortcutAction("open_search", "Open search / quick search", ["Ctrl", "K"], app="global", risk="low"),
            ShortcutAction("command_palette", "Open command palette", ["Ctrl", "Shift", "P"], app="vscode", risk="low"),
        ]
        for action in defaults:
            if action.name not in self.desktop_io.shortcuts:
                self.desktop_io.register_shortcut(action)

    # ---------- Dashboard task manager ----------

    def submit_dashboard_task(self, prompt: str, source: str = "dashboard") -> Dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            return {"ok": False, "error": "task prompt cannot be empty"}
        task_id = str(uuid.uuid4())
        language_profile = detect_text_profile(prompt).to_dict()
        record = {
            "id": task_id,
            "prompt": prompt,
            "language_profile": language_profile,
            "source": source,
            "status": "queued",
            "created_at": now_local(),
            "updated_at": now_local(),
            "started_at": None,
            "finished_at": None,
            "result": "",
            "error": "",
            "cancel_requested": False,
        }
        with self.task_lock:
            self.tasks[task_id] = record
            self.task_queue.put(task_id)
        self.memory.add("task_queued", prompt, {"task_id": task_id, "source": source, "language_profile": language_profile})
        if self.admin is not None:
            self.admin.emit("task.queued", "Task queued", {"task_id": task_id, "prompt": truncate(prompt, 1200), "source": source, "language_profile": language_profile})
        visible_record = sanitize_for_display(dict(record)) if self.cfg.mask_secrets else dict(record)
        return {"ok": True, "task": visible_record}

    def task_manager_snapshot(self) -> Dict[str, Any]:
        with self.task_lock:
            tasks = [dict(v) for v in self.tasks.values()]
            tasks.sort(key=lambda t: t.get("created_at") or "")
            visible_tasks = sanitize_for_display(tasks[-100:]) if self.cfg.mask_secrets else tasks[-100:]
            return {
                "ok": True,
                "paused": self.pause_requested,
                "queue_size": self.task_queue.qsize(),
                "current_task_id": self.current_task_id,
                "tasks": visible_tasks,
            }

    def control_dashboard_task(self, action: str, task_id: Optional[str] = None) -> Dict[str, Any]:
        action = action.strip().lower()
        if action == "pause":
            self.pause_requested = True
            return {"ok": True, "paused": True}
        if action == "resume":
            self.pause_requested = False
            return {"ok": True, "paused": False}
        if action == "clear_emergency_stop":
            self.pause_requested = False
            return {"ok": True, "paused": False}
        if action == "emergency_stop":
            self.pause_requested = True
            with self.task_lock:
                for rec in self.tasks.values():
                    if rec.get("status") in {"queued", "running", "cancelling"}:
                        rec["cancel_requested"] = True
                        if rec.get("status") == "queued":
                            rec["status"] = "cancelled"
                            rec["finished_at"] = now_local()
                            rec["updated_at"] = now_local()
                            rec["error"] = "cancelled by emergency stop"
            return {"ok": True, "emergency_stop": True, "paused": True}
        if action == "cancel":
            if not task_id:
                return {"ok": False, "error": "task_id is required for cancel"}
            with self.task_lock:
                rec = self.tasks.get(task_id)
                if not rec:
                    return {"ok": False, "error": "task not found"}
                rec["cancel_requested"] = True
                rec["updated_at"] = now_local()
                if rec.get("status") == "queued":
                    rec["status"] = "cancelled"
                    rec["finished_at"] = now_local()
                    rec["error"] = "cancelled before start"
                elif rec.get("status") == "running":
                    rec["status"] = "cancelling"
            if self.admin is not None:
                self.admin.emit("task.cancel_requested", "Task cancel requested", {"task_id": task_id}, level="warning")
            return {"ok": True, "task_id": task_id, "cancel_requested": True}
        return {"ok": False, "error": f"unknown task control action: {action}"}

    def _task_worker_loop(self) -> None:
        while True:
            task_id = self.task_queue.get()
            try:
                with self.task_lock:
                    rec = self.tasks.get(task_id)
                    if not rec or rec.get("status") == "cancelled" or rec.get("cancel_requested"):
                        continue
                    prompt = str(rec.get("prompt", ""))
                try:
                    answer = self.run_task(prompt, task_id=task_id)
                    with self.task_lock:
                        rec = self.tasks.get(task_id)
                        if rec and rec.get("status") not in {"cancelled"}:
                            rec["status"] = "completed"
                            rec["result"] = answer
                            rec["finished_at"] = now_local()
                            rec["updated_at"] = now_local()
                    self.memory.add("task_completed", answer, {"task_id": task_id})
                except RuntimeError as e:
                    # Used for cooperative cancellation.
                    with self.task_lock:
                        rec = self.tasks.get(task_id)
                        if rec:
                            rec["status"] = "cancelled" if "cancelled" in str(e).lower() else "failed"
                            rec["error"] = str(e)
                            rec["finished_at"] = now_local()
                            rec["updated_at"] = now_local()
                    if self.admin is not None:
                        self.admin.emit("task.worker_cancelled", "Task cancelled/failed", {"task_id": task_id, "error": str(e)}, level="warning")
                except Exception as e:
                    with self.task_lock:
                        rec = self.tasks.get(task_id)
                        if rec:
                            rec["status"] = "failed"
                            rec["error"] = str(e)
                            rec["finished_at"] = now_local()
                            rec["updated_at"] = now_local()
                    if self.admin is not None:
                        self.admin.emit("task.worker_error", "Task worker error", {"task_id": task_id, "error": str(e), "traceback": traceback.format_exc(limit=3)}, level="error")
            finally:
                self.task_queue.task_done()

    def _is_task_cancelled(self, task_id: Optional[str]) -> bool:
        if not task_id:
            return False
        with self.task_lock:
            rec = self.tasks.get(task_id)
            return bool(rec and rec.get("cancel_requested"))

    def _wait_if_paused_or_cancelled(self, task_id: Optional[str]) -> None:
        while self.pause_requested:
            if self._is_task_cancelled(task_id):
                raise RuntimeError("Task cancelled")
            time.sleep(0.25)
        if self._is_task_cancelled(task_id):
            raise RuntimeError("Task cancelled")

    def _execute_skill_definition(self, skill: SkillDefinition, dry_run: bool, approval_reason: str) -> Dict[str, Any]:
        executor = skill.executor
        args = dict(skill.args or {})
        if executor == "execute_shortcut":
            return self.tools.execute_shortcut(str(args.get("name", "")), dry_run=dry_run)
        if dry_run:
            return {"ok": True, "dry_run": True, "executor": executor, "args": args, "message": "dry run; no tool executed"}
        if executor == "git_status":
            return self.tools.git_status()
        if executor == "git_diff":
            return self.tools.git_diff()
        if executor == "index_project":
            return self.tools.index_project()
        if executor == "observe_desktop_logs":
            return self.tools.observe_desktop_logs()
        if executor == "search_project":
            return self.tools.search_project(str(args.get("query", "")), int(args.get("limit") or 12))
        if executor == "search_memory":
            query = str(args.get("query", ""))
            if args.get("query_from_command"):
                query = str(args.get("_command", query))
            return self.tools.search_memory(query, int(args.get("limit") or 8))
        return {"ok": False, "error": f"unsupported reflex skill executor: {executor}", "args": args}

    def _approve_reflex_skill(self, skill: SkillDefinition, resolved: Dict[str, Any], reason: str) -> bool:
        if self.admin is not None:
            return bool(
                self.admin.request_approval(
                    kind="reflex",
                    title=f"reflex: {skill.id}",
                    details={"skill": dataclasses.asdict(skill), "resolved": resolved, "approval_reason": reason},
                    console_fallback=lambda: yes_no(f"Execute reflex skill {skill.id}?"),
                )
            )
        return yes_no(f"Execute reflex skill {skill.id}?")

    def execute_reflex_command(self, command: str, dry_run: bool = False) -> Dict[str, Any]:
        if not self.cfg.reflex_enabled:
            return {"ok": False, "error": "reflex layer is disabled"}
        result = self.reflex.execute(
            command=command,
            executor=self._execute_skill_definition,
            dry_run=dry_run,
            approval_callback=self._approve_reflex_skill,
            auto_execute_trusted=self.cfg.reflex_auto_execute_trusted,
            trust_threshold=self.cfg.reflex_trust_threshold,
            require_approval_for_confirm=self.cfg.reflex_require_approval_for_confirm,
        )
        if result.get("ok"):
            self.memory.add("reflex_executed", command, {"result": result})
        return result

    def admin_inject(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Admin injection center: text/file/JSON bundle into memory, vector memory, intents, skills, shortcuts."""
        mode = str(payload.get("mode", "text") or "text").lower()
        source = str(payload.get("source", "dashboard_admin") or "dashboard_admin")
        namespace = str(payload.get("namespace", "admin_injection") or "admin_injection")
        kind = str(payload.get("kind", "admin_note") or "admin_note")
        inject_memory = bool(payload.get("memory", True))
        inject_vector = bool(payload.get("vector", True))
        overwrite = bool(payload.get("overwrite", True))
        summary: Dict[str, Any] = {
            "ok": True,
            "mode": mode,
            "source": source,
            "namespace": namespace,
            "memory_added": 0,
            "vector_added": 0,
            "intents_added": 0,
            "skills_added": 0,
            "shortcuts_added": 0,
            "errors": [],
            "results": [],
        }

        def add_text(text: str, item_kind: str = kind, metadata: Optional[Dict[str, Any]] = None) -> None:
            text = (text or "").strip()
            if not text:
                return
            meta = {"source": source, **(metadata or {})}
            if inject_memory:
                self.memory.add(item_kind, text, meta)
                summary["memory_added"] += 1
            if inject_vector:
                self.vector_store.add(text, namespace=namespace, source=source, metadata={"kind": item_kind, **meta})
                summary["vector_added"] += 1

        if mode in {"text", "file_text", "manual"}:
            text = str(payload.get("text", ""))
            if not text.strip():
                return {"ok": False, "error": "text is empty"}
            add_text(text, kind, {"injection_mode": mode, "filename": payload.get("filename")})
        elif mode in {"json", "json_bundle", "bundle"}:
            raw = payload.get("json")
            if raw is None:
                raw = payload.get("text", "")
            try:
                obj = json.loads(raw) if isinstance(raw, str) else raw
            except Exception as e:
                return {"ok": False, "error": f"invalid JSON: {e}"}
            if isinstance(obj, list):
                obj = {"memories": obj}
            if not isinstance(obj, dict):
                return {"ok": False, "error": "JSON bundle must be an object or list"}
            for item in obj.get("memories", []):
                if isinstance(item, str):
                    add_text(item, kind, {"bundle_section": "memories"})
                elif isinstance(item, dict):
                    add_text(str(item.get("text", "")), str(item.get("kind", kind)), {"bundle_section": "memories", "metadata": item.get("metadata", {})})
            for item in obj.get("vector_memories", []):
                if isinstance(item, str):
                    self.vector_store.add(item, namespace=namespace, source=source, metadata={"bundle_section": "vector_memories"})
                    summary["vector_added"] += 1
                elif isinstance(item, dict):
                    self.vector_store.add(str(item.get("text", "")), namespace=str(item.get("namespace", namespace)), source=str(item.get("source", source)), metadata=item.get("metadata", {}))
                    summary["vector_added"] += 1
            for item in obj.get("intents", []):
                if isinstance(item, dict):
                    res = self.intent_registry.register_intent(item, overwrite=overwrite)
                    summary["results"].append(res)
                    if res.get("ok"):
                        summary["intents_added"] += 1
                    else:
                        summary["errors"].append(res)
            for item in obj.get("skills", []):
                if isinstance(item, dict):
                    res = self.skill_registry.register_skill(item, overwrite=overwrite)
                    summary["results"].append(res)
                    if res.get("ok"):
                        summary["skills_added"] += 1
                    else:
                        summary["errors"].append(res)
            for item in obj.get("shortcuts", []):
                if isinstance(item, dict):
                    res = self.tools.register_shortcut(item)
                    summary["results"].append(res)
                    if res.get("ok"):
                        summary["shortcuts_added"] += 1
                    else:
                        summary["errors"].append(res)
        else:
            return {"ok": False, "error": f"unknown injection mode: {mode}"}

        self.event_journal.record("admin.inject", summary)
        self.memory.add("admin_injection_summary", json.dumps(summary, ensure_ascii=False), {"source": source, "mode": mode})
        return summary

    def handle_dashboard_operation(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        operation = operation.strip().lower()
        if operation == "reflex_resolve":
            return self.reflex.resolve(str(payload.get("command", "")))
        if operation == "reflex_execute":
            return self.execute_reflex_command(str(payload.get("command", "")), dry_run=bool(payload.get("dry_run", False)))
        if operation == "skill_list":
            return {"ok": True, "skills": self.skill_registry.list_skills(), "intents": self.intent_registry.list_intents()}
        if operation == "skill_promote":
            return self.skill_registry.promote(str(payload.get("skill_id", "")), str(payload.get("status", "trusted")))
        if operation == "event_recent":
            return {"ok": True, "events": self.event_journal.recent(limit=int(payload.get("limit") or 100))}
        if operation == "event_counts":
            return self.event_journal.summarize_counts()
        if operation == "daily_distill":
            day = str(payload.get("day", "") or "") or None
            apply_changes = bool(payload.get("apply", False))
            inject_vector = bool(payload.get("inject_vector", True))
            report = self.daily_distiller.distill(day=day, apply=apply_changes)
            self.memory.add("daily_distillation", json.dumps(report, ensure_ascii=False), {"day": report.get("day"), "path": report.get("path"), "apply": apply_changes})
            if inject_vector:
                text = "\n".join(report.get("lesson_lines", []))
                self.vector_store.add(text, namespace="daily_distillation", source="daily_distiller", metadata={"day": report.get("day"), "path": report.get("path")})
            return report
        if operation == "admin_inject":
            return self.admin_inject(payload)
        if operation == "list_project_templates":
            return self.tools.list_project_templates()
        if operation == "create_project":
            return self.tools.create_project(
                template=str(payload.get("template", "")),
                project_name=str(payload.get("project_name", "")),
                description=str(payload.get("description", "")),
                overwrite=bool(payload.get("overwrite", False)),
                dry_run=bool(payload.get("dry_run", False)),
            )
        if operation == "search_vector_memory":
            return self.tools.search_vector_memory(
                query=str(payload.get("query", "")),
                namespace=str(payload.get("namespace", "") or ""),
                limit=int(payload.get("limit") or 8),
            )
        if operation == "monthly_inject_memory":
            namespace = str(payload.get("namespace", "monthly_experience") or "monthly_experience")
            month = str(payload.get("month", "") or "") or None
            rows = self.memory.export_rows(limit=int(payload.get("limit") or 5000))
            result = self.vector_store.monthly_inject_from_rows(rows, month=month, namespace=namespace)
            self.memory.add("monthly_vector_injection", json.dumps(result, ensure_ascii=False), {"namespace": namespace, "month": month})
            return result
        if operation == "register_desktop_log":
            return self.tools.register_desktop_log(str(payload.get("path", "")))
        if operation == "observe_desktop_logs":
            return self.tools.observe_desktop_logs()
        if operation == "get_desktop_state":
            return self.desktop_io.get_state_snapshot(limit=int(payload.get("limit") or 30))
        if operation == "register_shortcut":
            return self.tools.register_shortcut(payload)
        if operation == "suggest_shortcut":
            return self.tools.suggest_shortcut(str(payload.get("intent", "")), str(payload.get("app", "") or ""))
        if operation == "execute_shortcut":
            return self.tools.execute_shortcut(str(payload.get("name", "")), bool(payload.get("dry_run", self.cfg.shortcut_execution_dry_run)))
        return {"ok": False, "error": f"unknown dashboard operation: {operation}"}

    def status_snapshot(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "workspace": str(self.root),
            "llm_provider": self.cfg.llm_provider,
            "brain_routing_enabled": self._routing_enabled(),
            "last_brain_route": self.last_brain_route,
            "model": self.cfg.model,
            "task_running": self.task_running,
            "current_task_id": self.current_task_id,
            "current_task": truncate(mask_secrets(self.current_task or "") if self.cfg.mask_secrets else (self.current_task or ""), 1000),
            "task_paused": self.pause_requested,
            "total_tasks": self.total_tasks,
            "uptime_sec": round(time.time() - self.started_at, 1),
            "last_error": mask_secrets(self.last_error or "") if (self.cfg.mask_secrets and self.last_error) else self.last_error,
            "index": self.indexer.summary(),
            "git_status": truncate(self.tools.git_status_for_context() if hasattr(self, "tools") else "", 2000),
            "current_task_language": detect_text_profile(self.current_task or "").to_dict() if self.current_task else None,
            "vector_memory_count": self.vector_store.count() if hasattr(self, "vector_store") else 0,
            "desktop_log_count": len(self.desktop_io.log_paths) if hasattr(self, "desktop_io") else 0,
            "shortcut_count": len(self.desktop_io.shortcuts) if hasattr(self, "desktop_io") else 0,
            "skill_count": len(self.skill_registry.skills) if hasattr(self, "skill_registry") else 0,
            "intent_count": len(self.intent_registry.intents) if hasattr(self, "intent_registry") else 0,
            "event_counts": self.event_journal.summarize_counts() if hasattr(self, "event_journal") else {},
            "policy_file": str(self.root / self.cfg.policy_file),
        }

    def runtime_config_snapshot(self) -> Dict[str, Any]:
        cfg_dict = dataclasses.asdict(self.cfg)
        if cfg_dict.get("dashboard_token"):
            cfg_dict["dashboard_token"] = "***"
        if cfg_dict.get("openai_api_key"):
            cfg_dict["openai_api_key"] = "***"
        cfg_dict["ignored_dirs"] = list(self.cfg.ignored_dirs)
        cfg_dict["ignored_file_globs"] = list(self.cfg.ignored_file_globs)
        cfg_dict["blocked_command_fragments"] = list(self.cfg.blocked_command_fragments)
        editable = [
            "llm_provider",
            "model",
            "ollama_url",
            "openai_base_url",
            "openai_api_key_env",
            "openai_api_key",
            "openai_timeout_sec",
            "openai_max_tokens",
            "brain_routing_enabled",
            "brain_routing_simple_provider",
            "brain_routing_complex_provider",
            "brain_routing_sensitive_provider",
            "brain_routing_allow_api_for_sensitive",
            "enable_shortcut_execution",
            "require_approval_for_shortcuts",
            "shortcut_execution_dry_run",
            "shortcut_execution_method",
            "shortcut_execution_delay_ms",
            "min_desktop_confidence_for_shortcut",
            "allow_shortcut_without_desktop_state",
            "reflex_enabled",
            "reflex_auto_execute_trusted",
            "reflex_trust_threshold",
            "reflex_require_approval_for_confirm",
            "skills_file",
            "intents_file",
            "event_journal_dir",
            "distillation_dir",
            "temperature",
            "num_ctx",
            "max_steps",
            "max_file_read_chars",
            "max_tree_entries",
            "command_timeout_sec",
            "require_approval_for_writes",
            "require_approval_for_commands",
            "create_backups",
            "mask_secrets",
            "mask_secrets_in_memory",
            "block_sensitive_file_reads",
            "approval_timeout_sec",
            "policy_file",
            "auto_load_policy",
            "vector_memory_file",
            "desktop_state_file",
        ]
        return {"ok": True, "config": cfg_dict, "editable_fields": editable}

    def apply_runtime_config_update(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        editable_types: Dict[str, Any] = {
            "llm_provider": str,
            "model": str,
            "ollama_url": str,
            "openai_base_url": str,
            "openai_api_key_env": str,
            "openai_api_key": str,
            "openai_timeout_sec": int,
            "openai_max_tokens": int,
            "brain_routing_enabled": bool,
            "brain_routing_simple_provider": str,
            "brain_routing_complex_provider": str,
            "brain_routing_sensitive_provider": str,
            "brain_routing_allow_api_for_sensitive": bool,
            "enable_shortcut_execution": bool,
            "require_approval_for_shortcuts": bool,
            "shortcut_execution_dry_run": bool,
            "shortcut_execution_method": str,
            "shortcut_execution_delay_ms": int,
            "min_desktop_confidence_for_shortcut": float,
            "allow_shortcut_without_desktop_state": bool,
            "reflex_enabled": bool,
            "reflex_auto_execute_trusted": bool,
            "reflex_trust_threshold": float,
            "reflex_require_approval_for_confirm": bool,
            "skills_file": str,
            "intents_file": str,
            "event_journal_dir": str,
            "distillation_dir": str,
            "temperature": float,
            "num_ctx": int,
            "max_steps": int,
            "max_file_read_chars": int,
            "max_tree_entries": int,
            "command_timeout_sec": int,
            "require_approval_for_writes": bool,
            "require_approval_for_commands": bool,
            "create_backups": bool,
            "mask_secrets": bool,
            "mask_secrets_in_memory": bool,
            "block_sensitive_file_reads": bool,
            "approval_timeout_sec": int,
            "policy_file": str,
            "auto_load_policy": bool,
            "vector_memory_file": str,
            "desktop_state_file": str,
        }
        clean: Dict[str, Any] = {}
        for key, caster in editable_types.items():
            if key not in updates:
                continue
            value = updates[key]
            if caster is bool:
                clean[key] = bool(value)
            elif caster is int:
                clean[key] = int(value)
            elif caster is float:
                clean[key] = float(value)
            else:
                clean[key] = str(value)

        if not clean:
            return {"ok": False, "error": "no editable config fields provided"}

        candidate = dataclasses.replace(self.cfg, **clean)
        # Validate the fields that can affect runtime safety/stability.
        if candidate.llm_provider not in {"ollama", "openai_compatible", "auto"}:
            return {"ok": False, "error": "llm_provider must be 'ollama', 'openai_compatible', or 'auto'"}
        for provider_field in (candidate.brain_routing_simple_provider, candidate.brain_routing_complex_provider, candidate.brain_routing_sensitive_provider):
            if provider_field not in {"ollama", "openai_compatible"}:
                return {"ok": False, "error": "brain routing providers must be 'ollama' or 'openai_compatible'"}
        if not (0 <= candidate.temperature <= 2):
            return {"ok": False, "error": "temperature must be between 0 and 2"}
        if candidate.num_ctx <= 0:
            return {"ok": False, "error": "num_ctx must be positive"}
        if candidate.max_steps <= 0:
            return {"ok": False, "error": "max_steps must be positive"}
        if candidate.command_timeout_sec <= 0:
            return {"ok": False, "error": "command_timeout_sec must be positive"}
        if candidate.shortcut_execution_delay_ms < 0:
            return {"ok": False, "error": "shortcut_execution_delay_ms cannot be negative"}
        if not (0 <= candidate.min_desktop_confidence_for_shortcut <= 1):
            return {"ok": False, "error": "min_desktop_confidence_for_shortcut must be between 0 and 1"}
        if not (0 <= candidate.reflex_trust_threshold <= 1):
            return {"ok": False, "error": "reflex_trust_threshold must be between 0 and 1"}
        if candidate.openai_timeout_sec <= 0:
            return {"ok": False, "error": "openai_timeout_sec must be positive"}
        if candidate.openai_max_tokens < 0:
            return {"ok": False, "error": "openai_max_tokens cannot be negative"}
        if candidate.max_file_read_chars <= 100:
            return {"ok": False, "error": "max_file_read_chars is too small"}
        if candidate.approval_timeout_sec < 0:
            return {"ok": False, "error": "approval_timeout_sec cannot be negative"}
        policy_path: Optional[Path] = None
        vector_path: Optional[Path] = None
        desktop_state_path: Optional[Path] = None
        skills_path: Optional[Path] = None
        intents_path: Optional[Path] = None
        events_dir: Optional[Path] = None
        distillation_dir: Optional[Path] = None
        if self.admin is not None and (candidate.policy_file != self.cfg.policy_file or candidate.auto_load_policy != self.cfg.auto_load_policy):
            policy_path = (self.root / candidate.policy_file).resolve()
            try:
                policy_path.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "policy_file must stay inside the workspace root"}
        if candidate.vector_memory_file != self.cfg.vector_memory_file:
            vector_path = (self.root / candidate.vector_memory_file).resolve()
            try:
                vector_path.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "vector_memory_file must stay inside the workspace root"}
        if candidate.desktop_state_file != self.cfg.desktop_state_file:
            desktop_state_path = (self.root / candidate.desktop_state_file).resolve()
            try:
                desktop_state_path.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "desktop_state_file must stay inside the workspace root"}
        if candidate.skills_file != self.cfg.skills_file:
            skills_path = (self.root / candidate.skills_file).resolve()
            try:
                skills_path.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "skills_file must stay inside the workspace root"}
        if candidate.intents_file != self.cfg.intents_file:
            intents_path = (self.root / candidate.intents_file).resolve()
            try:
                intents_path.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "intents_file must stay inside the workspace root"}
        if candidate.event_journal_dir != self.cfg.event_journal_dir:
            events_dir = (self.root / candidate.event_journal_dir).resolve()
            try:
                events_dir.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "event_journal_dir must stay inside the workspace root"}
        if candidate.distillation_dir != self.cfg.distillation_dir:
            distillation_dir = (self.root / candidate.distillation_dir).resolve()
            try:
                distillation_dir.relative_to(self.root)
            except ValueError:
                return {"ok": False, "error": "distillation_dir must stay inside the workspace root"}

        old = self.cfg
        self.cfg = candidate
        # Recreate the brain client so provider/base_url/API-key/model changes apply immediately.
        self.llm = self._create_llm_client(candidate)
        self.tools.cfg = candidate
        self.indexer.cfg = candidate
        self.memory.mask_secrets_enabled = candidate.mask_secrets_in_memory
        if vector_path is not None:
            self.vector_store = VectorMemoryStore(vector_path, dimensions=candidate.vector_dimensions)
            self.tools.vector_store = self.vector_store
        if desktop_state_path is not None:
            self.desktop_io = DesktopIORegistry(self.root, state_path=desktop_state_path)
            self._seed_foundation_shortcuts()
            self.tools.desktop_io = self.desktop_io
        if skills_path is not None:
            self.skill_registry = SkillRegistry(skills_path)
            self.reflex = ReflexEngine(self.intent_registry, self.skill_registry, self.event_journal)
        if intents_path is not None:
            self.intent_registry = IntentRegistry(intents_path)
            self.reflex = ReflexEngine(self.intent_registry, self.skill_registry, self.event_journal)
        if events_dir is not None:
            self.event_journal = EventJournal(events_dir)
            self.reflex = ReflexEngine(self.intent_registry, self.skill_registry, self.event_journal)
            self.daily_distiller = DailyDistiller(self.event_journal, self.skill_registry, Path(self.root / candidate.distillation_dir).resolve())
        if distillation_dir is not None:
            self.daily_distiller = DailyDistiller(self.event_journal, self.skill_registry, distillation_dir)
        if self.admin is not None:
            self.admin.approval_timeout_sec = candidate.approval_timeout_sec
            if policy_path is not None:
                self.admin.set_policy_storage(policy_path, auto_load=candidate.auto_load_policy)
        return {
            "ok": True,
            "updated": clean,
            "old_model": old.model,
            "new_model": candidate.model,
            "note": "Runtime updated. If you want persistence, mirror these values into config.json.",
        }

    def build_context(self) -> str:
        recent_memories = self.memory.recent(limit=6)
        memories_text = "\n".join(
            f"- [{m['kind']}] {truncate(m['text'], 500)}" for m in recent_memories
        ) or "[no memories yet]"
        index_summary = json.dumps(self.indexer.summary(), ensure_ascii=False)
        git_status = self.tools.git_status_for_context()
        return textwrap.dedent(
            f"""
            Local time: {now_local()}
            Workspace root: {self.root}

            Git status snapshot:
            {git_status}

            Project index summary:
            {index_summary}

            Project tree snapshot:
            {self.tools.project_tree()}

            Recent memories:
            {memories_text}
            """
        ).strip()

    def run_task(self, user_task: str, task_id: Optional[str] = None) -> str:
        with self.run_lock:
            self.total_tasks += 1
            self.current_task = user_task
            self.current_task_id = task_id
            self.task_running = True
            self.last_error = None
            if task_id:
                with self.task_lock:
                    rec = self.tasks.get(task_id)
                    if rec:
                        rec["status"] = "running"
                        rec["started_at"] = now_local()
                        rec["updated_at"] = now_local()
            if self.admin is not None:
                self.admin.emit("task.started", "Task started", {"task": truncate(user_task, 1500), "task_no": self.total_tasks, "task_id": task_id})

            try:
                self._wait_if_paused_or_cancelled(task_id)
                safe_user_task = mask_secrets(user_task) if self.cfg.mask_secrets else user_task
                language_profile = detect_text_profile(safe_user_task).to_dict()
                self.memory.add("user_task", safe_user_task, {"time": now_local(), "task_id": task_id, "language_profile": language_profile})
                messages: List[Dict[str, str]] = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self.build_context() + "\n\nUser task language profile:\n" + json.dumps(language_profile, ensure_ascii=False) + "\n\nUser task:\n" + safe_user_task},
                ]
                selected_llm, brain_route = self._select_brain(safe_user_task)
                self.last_brain_route = brain_route
                if task_id:
                    with self.task_lock:
                        rec = self.tasks.get(task_id)
                        if rec:
                            rec["brain_route"] = brain_route
                            rec["updated_at"] = now_local()
                if self.admin is not None:
                    self.admin.emit("brain.selected", "Brain selected for task", {"task_id": task_id, "brain_route": brain_route})

                final_answer = ""
                step = 1
                while step <= self.cfg.max_steps:
                    self._wait_if_paused_or_cancelled(task_id)
                    print(f"\n[agent] step {step}/{self.cfg.max_steps} - thinking with {selected_llm.model} via {brain_route.get('provider')}...")
                    if self.admin is not None:
                        self.admin.emit("agent.thinking", "LLM call started", {"step": step, "max_steps": self.cfg.max_steps, "model": selected_llm.model, "task_id": task_id, "brain_route": brain_route})
                    raw = selected_llm.chat(messages)
                    self._wait_if_paused_or_cancelled(task_id)
                    print("[agent] raw model output:")
                    safe_raw_for_display = mask_secrets(raw) if self.cfg.mask_secrets else raw
                    print(truncate(safe_raw_for_display, 3000))
                    try:
                        obj = extract_json_object(raw)
                    except Exception as e:
                        err = f"Invalid JSON from model: {e}"
                        print(f"[agent] {err}")
                        if self.admin is not None:
                            self.admin.emit("agent.invalid_json", err, {"raw": truncate(safe_raw_for_display, 2000), "task_id": task_id}, level="warning")
                        messages.append({"role": "assistant", "content": safe_raw_for_display})
                        messages.append({"role": "user", "content": "Your previous output was not valid JSON. Return ONLY the required JSON object."})
                        step += 1
                        continue

                    actions = obj.get("actions") or []
                    if not isinstance(actions, list):
                        messages.append({"role": "user", "content": "actions must be a list. Return valid JSON."})
                        step += 1
                        continue
                    if not actions:
                        safe_obj_for_context = sanitize_for_display(obj, max_string=8000) if self.cfg.mask_secrets else obj
                        messages.append({"role": "assistant", "content": json.dumps(safe_obj_for_context, ensure_ascii=False)})
                        messages.append({"role": "user", "content": "No actions were provided. Use finish(answer) or a tool action."})
                        step += 1
                        continue

                    observations = []
                    for action in actions:
                        self._wait_if_paused_or_cancelled(task_id)
                        if not isinstance(action, dict):
                            observations.append({"ok": False, "error": "action is not object", "action": action})
                            continue
                        tool = action.get("tool")
                        safe_args = sanitize_for_display(action.get('args') or {}, max_string=500) if self.cfg.mask_secrets else (action.get('args') or {})
                        print(f"[tool] {tool} {json.dumps(safe_args, ensure_ascii=False)[:500]}")
                        result = self.tools.execute(action)
                        safe_action_for_obs = sanitize_for_display(action, max_string=4000) if self.cfg.mask_secrets else action
                        safe_result_for_obs = sanitize_for_display(result, max_string=8000) if self.cfg.mask_secrets else result
                        observations.append({"action": safe_action_for_obs, "result": safe_result_for_obs})
                        if tool == "finish" and result.get("ok"):
                            final_answer = result.get("final", "")
                            self.memory.add("assistant_final", final_answer, {"time": now_local(), "task_id": task_id})
                            if self.admin is not None:
                                self.admin.emit("task.finished", "Task finished", {"answer": truncate(final_answer, 2000), "task_id": task_id}, level="info")
                            return final_answer

                    obs_text = json.dumps(observations, ensure_ascii=False, indent=2)
                    print("[agent] observations:")
                    print(truncate(obs_text, 5000))
                    safe_obj_for_context = sanitize_for_display(obj, max_string=8000) if self.cfg.mask_secrets else obj
                    messages.append({"role": "assistant", "content": json.dumps(safe_obj_for_context, ensure_ascii=False)})
                    messages.append({"role": "user", "content": "Tool observations:\n" + truncate(obs_text, 20_000) + "\n\nContinue. Return ONLY JSON."})
                    step += 1

                final_answer = "به سقف مراحل رسیدم. اگر لازم است، دوباره با دستور دقیق‌تر ادامه بده."
                self.memory.add("assistant_final", final_answer, {"time": now_local(), "max_steps_reached": True, "task_id": task_id})
                if self.admin is not None:
                    self.admin.emit("task.max_steps", "Task reached max steps", {"answer": final_answer, "task_id": task_id}, level="warning")
                return final_answer
            except Exception as e:
                self.last_error = str(e)
                if self.admin is not None:
                    level = "warning" if "cancelled" in str(e).lower() else "error"
                    self.admin.emit("task.error", "Task failed", {"error": str(e), "task_id": task_id, "traceback": traceback.format_exc(limit=3)}, level=level)
                raise
            finally:
                self.task_running = False
                self.current_task = None
                self.current_task_id = None


# -----------------------------
# CLI helpers
# -----------------------------


def handle_slash_command(agent: LocalCodingAgent, command: str) -> bool:
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in {"/help", "/?"}:
        print(
            textwrap.dedent(
                """
                Local commands:
                  /help              show this help
                  /index             rebuild project index
                  /status            show git status
                  /diff [path]        show git diff, optionally for one path
                  /search QUERY       search project index without LLM
                  /memory QUERY       search memory without LLM
                  /summary           show project index summary
                  /dashboard         show admin dashboard URL
                  exit                quit
                """
            ).strip()
        )
        return True

    if cmd == "/index":
        print(json.dumps(agent.indexer.rebuild(), ensure_ascii=False, indent=2))
        return True

    if cmd == "/summary":
        print(json.dumps(agent.indexer.summary(), ensure_ascii=False, indent=2))
        return True

    if cmd == "/status":
        print(json.dumps(agent.tools.git_status(), ensure_ascii=False, indent=2))
        return True

    if cmd == "/diff":
        print(json.dumps(agent.tools.git_diff(path=arg), ensure_ascii=False, indent=2))
        return True

    if cmd == "/search":
        if not arg:
            print("Usage: /search QUERY")
        else:
            print(json.dumps(agent.indexer.search(arg), ensure_ascii=False, indent=2))
        return True

    if cmd == "/memory":
        if not arg:
            print("Usage: /memory QUERY")
        else:
            print(json.dumps(agent.memory.search(arg), ensure_ascii=False, indent=2))
        return True

    if cmd == "/dashboard":
        if agent.admin is not None:
            print(agent.admin.server_url or "dashboard enabled but URL is not available")
        else:
            print("dashboard is disabled. Set enable_dashboard=true in config.json")
        return True

    return False


# -----------------------------
# CLI
# -----------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="SkyGround Local Cursor-like Coding Agent with Ollama")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--root", default=None, help="Workspace/project root")
    parser.add_argument("--task", default=None, help="Run one task and exit")
    parser.add_argument("--index", action="store_true", help="Rebuild project index before starting")
    args = parser.parse_args()

    cfg = AgentConfig.load(args.config, root_override=args.root)
    agent = LocalCodingAgent(cfg)

    if args.index:
        print(json.dumps(agent.indexer.rebuild(), ensure_ascii=False, indent=2))

    print("=" * 72)
    print("SkyGround Local Coding Agent v3")
    print(f"Workspace: {agent.root}")
    print(f"Model: {cfg.model}")
    print(f"Ollama: {cfg.ollama_url}")
    if agent.admin is not None:
        print(f"Dashboard: {agent.admin.server_url}")
        if cfg.dashboard_token:
            print("Dashboard auth: enabled (use your dashboard_token to login)")
    print("Type '/help' for local commands, or 'exit' to quit.")
    print("=" * 72)

    if args.task:
        answer = agent.run_task(args.task)
        print("\n--- Final ---")
        print(mask_secrets(answer) if cfg.mask_secrets else answer)
        return 0

    while True:
        try:
            task = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not task:
            continue
        if task.lower() in {"exit", "quit", "خروج"}:
            print("bye")
            return 0
        if task.startswith("/") and handle_slash_command(agent, task):
            continue
        try:
            answer = agent.run_task(task)
            print("\nAgent>")
            print(mask_secrets(answer) if cfg.mask_secrets else answer)
        except Exception as e:
            print("\n[error]", e)
            traceback.print_exc()


if __name__ == "__main__":
    raise SystemExit(main())