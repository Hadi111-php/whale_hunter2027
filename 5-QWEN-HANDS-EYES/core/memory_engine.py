"""
Memory Engine with SQLite Persistence and DSA 'Fade-Not-Forget' Dynamics.
Implements DSA v4 memory retention constants: lambda=0.15, gamma=0.4, min_weight=0.15.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)


class MemoryEngine:
    """Manages conversations, episodic experiences, and learned patterns with DSA retention decay."""

    def __init__(
        self,
        db_path: str = ".qwen_hands_eyes/memory.sqlite",
        dsa_enabled: bool = True,
        dsa_lambda: float = 0.15,
        dsa_gamma: float = 0.4,
        dsa_min: float = 0.15,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dsa_enabled = dsa_enabled
        self.dsa_lambda = dsa_lambda
        self.dsa_gamma = dsa_gamma
        self.dsa_min = dsa_min
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT,
                    success_rate REAL DEFAULT 1.0,
                    access_count INTEGER DEFAULT 1,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT,
                    results_json TEXT,
                    error_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def calculate_dsa_weight(self, created_at_str: str, access_count: int = 1) -> float:
        """Calculate DSA Fade-Not-Forget retention weight."""
        if not self.dsa_enabled:
            return 1.0
        try:
            # Parse ISO or SQLite datetime
            clean_str = created_at_str.replace("Z", "+00:00")
            if "T" in clean_str:
                created_dt = dt.datetime.fromisoformat(clean_str)
            else:
                created_dt = dt.datetime.strptime(clean_str[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.dsa_min

        now = dt.datetime.now(dt.timezone.utc) if created_dt.tzinfo else dt.datetime.now()
        age_days = max(0.0, (now - created_dt).total_seconds() / 86400.0)

        # Base exponential decay modulated by gamma and access frequency reinforcement
        access_boost = min(1.5, 1.0 + math.log1p(access_count) * 0.1)
        decayed = self.dsa_gamma * math.exp(-self.dsa_lambda * age_days) * access_boost

        # Floor constraint: Never forget below min_weight (0.15)
        return round(max(self.dsa_min, min(1.0, decayed)), 4)

    def save_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO conversations (session_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.commit()
            return cur.lastrowid or 0

    def get_conversation_history(self, session_id: str = "default", limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT role, content, metadata_json, created_at FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            )
            rows = cur.fetchall()
            history = []
            for r in reversed(rows):
                history.append({
                    "role": r[0],
                    "content": r[1],
                    "metadata": json.loads(r[2]) if r[2] else {},
                    "created_at": r[3],
                })
            return history

    def add_experience(self, category: str, title: str, content: str, tags: str = "", success_rate: float = 1.0) -> int:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO experiences (category, title, content, tags, success_rate, access_count, last_accessed, created_at)
                VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (category, title, content, tags, success_rate),
            )
            conn.commit()
            return cur.lastrowid or 0

    def search_experiences(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_tokens = set(TOKEN_RE.findall(query.lower()))
        if not query_tokens:
            return []

        with self._lock, sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT id, category, title, content, tags, success_rate, access_count, created_at FROM experiences")
            rows = cur.fetchall()

            scored: List[Tuple[float, Dict[str, Any]]] = []
            for r in rows:
                doc_id, category, title, content, tags, success_rate, access_count, created_at = r
                doc_text = f"{title} {content} {tags} {category}".lower()
                doc_tokens = set(TOKEN_RE.findall(doc_text))
                intersection = query_tokens.intersection(doc_tokens)
                if not intersection:
                    continue

                token_overlap = len(intersection) / float(len(query_tokens))
                dsa_weight = self.calculate_dsa_weight(created_at, access_count)
                final_score = token_overlap * 0.6 + dsa_weight * 0.3 + (success_rate or 1.0) * 0.1

                scored.append((
                    final_score,
                    {
                        "id": doc_id,
                        "category": category,
                        "title": title,
                        "content": content,
                        "tags": tags,
                        "success_rate": success_rate,
                        "dsa_weight": dsa_weight,
                        "created_at": created_at,
                    },
                ))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [item[1] for item in scored[:limit]]

    def record_task(self, task_id: str, description: str, status: str = "started", plan: Optional[Dict] = None) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO task_history (task_id, description, status, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    plan_json = coalesce(excluded.plan_json, task_history.plan_json),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (task_id, description, status, json.dumps(plan or {}, ensure_ascii=False)),
            )
            conn.commit()

    def update_task_results(self, task_id: str, status: str, results: List[Any], error: Optional[Dict] = None) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE task_history
                SET status = ?, results_json = ?, error_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
                """,
                (status, json.dumps(results, ensure_ascii=False), json.dumps(error or {}, ensure_ascii=False), task_id),
            )
            conn.commit()
