"""
Lightweight local vector memory for SkyGround.

This is a dependency-free hashed vector store. It is not as strong as a real embedding
model, but it gives us a stable interface for "monthly injection into vector brain".
Later it can be replaced with Ollama embeddings, sentence-transformers, bge, etc.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from security import sanitize_for_display
from text_intelligence import detect_text_profile


TOKEN_RE = re.compile(r"[\w\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", re.UNICODE)


@dataclasses.dataclass(frozen=True)
class VectorSearchResult:
    id: int
    score: float
    created_at: str
    namespace: str
    source: str
    text: str
    metadata: Dict[str, Any]


class HashingVectorizer:
    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def tokenize(self, text: str) -> List[str]:
        return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t.strip()) >= 2]

    def embed_sparse(self, text: str) -> Dict[int, float]:
        vec: Dict[int, float] = {}
        for token in self.tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            n = int.from_bytes(digest, "big")
            idx = n % self.dimensions
            sign = 1.0 if (n >> 63) == 0 else -1.0
            vec[idx] = vec.get(idx, 0.0) + sign
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}
        return vec

    @staticmethod
    def cosine_sparse(a: Dict[int, float], b: Dict[int, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        return float(sum(v * b.get(k, 0.0) for k, v in a.items()))


def _encode_vec(vec: Dict[int, float]) -> str:
    return json.dumps({str(k): round(v, 6) for k, v in vec.items()}, separators=(",", ":"))


def _decode_vec(raw: str) -> Dict[int, float]:
    obj = json.loads(raw or "{}")
    return {int(k): float(v) for k, v in obj.items()}


class VectorMemoryStore:
    def __init__(self, db_path: Path, dimensions: int = 384):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.vectorizer = HashingVectorizer(dimensions=dimensions)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                namespace TEXT NOT NULL,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                vector_json TEXT NOT NULL
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_vector_memories_namespace ON vector_memories(namespace)")
        self.conn.commit()

    def add(self, text: str, namespace: str = "general", source: str = "manual", metadata: Optional[Dict[str, Any]] = None) -> int:
        safe_text = sanitize_for_display(text or "")
        safe_metadata = sanitize_for_display(metadata or {})
        profile = detect_text_profile(safe_text).to_dict()
        merged_metadata = {**safe_metadata, "text_profile": profile}
        vector = self.vectorizer.embed_sparse(safe_text)
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT INTO vector_memories(created_at, namespace, source, text, metadata_json, vector_json) VALUES (?, ?, ?, ?, ?, ?)",
            (created_at, namespace, source, safe_text, json.dumps(merged_metadata, ensure_ascii=False), _encode_vec(vector)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def search(self, query: str, namespace: Optional[str] = None, limit: int = 8) -> List[VectorSearchResult]:
        query_vec = self.vectorizer.embed_sparse(query)
        if namespace:
            rows = self.conn.execute(
                "SELECT id, created_at, namespace, source, text, metadata_json, vector_json FROM vector_memories WHERE namespace = ? ORDER BY id DESC LIMIT 2000",
                (namespace,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, created_at, namespace, source, text, metadata_json, vector_json FROM vector_memories ORDER BY id DESC LIMIT 2000"
            ).fetchall()
        scored: List[VectorSearchResult] = []
        for r in rows:
            score = self.vectorizer.cosine_sparse(query_vec, _decode_vec(r[6]))
            if score <= 0:
                continue
            scored.append(
                VectorSearchResult(
                    id=int(r[0]),
                    score=round(score, 4),
                    created_at=str(r[1]),
                    namespace=str(r[2]),
                    source=str(r[3]),
                    text=str(r[4]),
                    metadata=json.loads(r[5] or "{}"),
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def count(self, namespace: Optional[str] = None) -> int:
        if namespace:
            row = self.conn.execute("SELECT COUNT(*) FROM vector_memories WHERE namespace = ?", (namespace,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM vector_memories").fetchone()
        return int(row[0] or 0)

    def monthly_inject_from_rows(self, rows: Iterable[Dict[str, Any]], month: Optional[str] = None, namespace: str = "monthly_experience") -> Dict[str, Any]:
        """Inject memory rows into vector brain. month format: YYYY-MM; defaults current UTC month."""
        month = month or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
        injected = 0
        skipped = 0
        for row in rows:
            created = str(row.get("created_at", ""))
            if month and not created.startswith(month):
                # Also accept local memory timestamps that may include date only; skip otherwise.
                skipped += 1
                continue
            text = str(row.get("text", "")).strip()
            if not text:
                skipped += 1
                continue
            metadata = {"memory_id": row.get("id"), "kind": row.get("kind"), "created_at": created, "month": month, "metadata": row.get("metadata", {})}
            self.add(text=text, namespace=namespace, source="monthly_injection", metadata=metadata)
            injected += 1
        return {"ok": True, "month": month, "namespace": namespace, "injected": injected, "skipped": skipped, "total_vectors": self.count(namespace)}