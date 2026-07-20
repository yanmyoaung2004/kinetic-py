from __future__ import annotations

import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
import numpy as np

logger = logging.getLogger("kinetic.headroom_memory")

SHARED_DB_PATH = Path("agents_workspace") / "shared" / "memory.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    agent_id   TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL DEFAULT 'fact',
    content    TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    embedding  BLOB,
    created    TEXT NOT NULL DEFAULT (datetime('now')),
    metadata   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created);
"""

_HEADROOM_MEMORY_AVAILABLE: bool | None = None


def _check_available() -> bool:
    global _HEADROOM_MEMORY_AVAILABLE
    if _HEADROOM_MEMORY_AVAILABLE is not None:
        return _HEADROOM_MEMORY_AVAILABLE
    try:
        import headroom  # noqa: F401
        _HEADROOM_MEMORY_AVAILABLE = True
    except ImportError:
        _HEADROOM_MEMORY_AVAILABLE = False
    return _HEADROOM_MEMORY_AVAILABLE


def is_enabled() -> bool:
    return os.environ.get("HEADROOM_MEMORY", "0") == "1"


def is_available() -> bool:
    return is_enabled() and _check_available()


@dataclass
class MemoryRecord:
    id: str
    user_id: str
    agent_id: str
    category: str
    content: str
    importance: float
    created: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


async def _get_db() -> aiosqlite.Connection:
    SHARED_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(SHARED_DB_PATH))
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.executescript(SCHEMA_SQL)
    await db.commit()
    db.row_factory = aiosqlite.Row
    return db


async def _get_embedding(text: str) -> list[float]:
    try:
        from src.agents.rag.embedding import get_embedding
        return await get_embedding(text)
    except Exception:
        return []


def _pack_embedding(emb: list[float]) -> bytes:
    return struct.pack(f"{len(emb)}f", *emb)


def _unpack_embedding(data: bytes) -> list[float]:
    return list(struct.unpack(f"{len(data) // 4}f", data))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    arr_a = np.array(a, dtype=np.float64)
    arr_b = np.array(b, dtype=np.float64)
    norm_a = np.linalg.norm(arr_a)
    norm_b = np.linalg.norm(arr_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))


async def store_memory(
    content: str,
    user_id: str,
    agent_id: str = "",
    category: str = "fact",
    importance: float = 0.5,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    if not is_available():
        return None
    try:
        mem_id = f"mem_{int(time.time() * 1000)}_{user_id[:8]}"
        emb = await _get_embedding(content)
        emb_bytes = _pack_embedding(emb) if emb else None
        db = await _get_db()
        try:
            await db.execute(
                "INSERT OR REPLACE INTO memories "
                "(id, user_id, agent_id, category, content, importance, embedding, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mem_id,
                    user_id,
                    agent_id,
                    category,
                    content,
                    importance,
                    emb_bytes,
                    json.dumps(metadata or {}),
                ),
            )
            await db.commit()
            logger.debug("[HEADROOM_MEMORY] Stored: %s (%s)", mem_id, category)
            return mem_id
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("[HEADROOM_MEMORY] Store failed: %s", exc)
        return None


async def recall_memories(
    query: str,
    user_id: str | None = None,
    top_k: int = 5,
    min_score: float = 0.2,
) -> list[MemoryRecord]:
    if not is_available():
        return []
    try:
        query_emb = await _get_embedding(query)
        if not query_emb:
            return []

        db = await _get_db()
        try:
            if user_id:
                cursor = await db.execute(
                    "SELECT id, user_id, agent_id, category, content, importance, created, metadata, embedding "
                    "FROM memories WHERE user_id = ? ORDER BY created DESC",
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    "SELECT id, user_id, agent_id, category, content, importance, created, metadata, embedding "
                    "FROM memories ORDER BY created DESC LIMIT 200",
                )

            rows = await cursor.fetchall()
            scored: list[tuple[float, dict]] = []
            for row in rows:
                emb_bytes = row["embedding"]
                if not emb_bytes:
                    continue
                mem_emb = _unpack_embedding(emb_bytes)
                score = _cosine_similarity(query_emb, mem_emb)
                if score >= min_score:
                    scored.append((
                        score,
                        {
                            "id": row["id"],
                            "user_id": row["user_id"],
                            "agent_id": row["agent_id"],
                            "category": row["category"],
                            "content": row["content"],
                            "importance": row["importance"],
                            "created": row["created"],
                            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        },
                    ))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                MemoryRecord(score=s, **data)
                for s, data in scored[:top_k]
            ]
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("[HEADROOM_MEMORY] Recall failed: %s", exc)
        return []


async def get_stats() -> dict[str, Any]:
    if not is_available():
        return {"enabled": False}
    try:
        db = await _get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) as c FROM memories")
            total = (await cursor.fetchone())["c"]
            cursor = await db.execute(
                "SELECT category, COUNT(*) as c FROM memories GROUP BY category"
            )
            by_category = {row["category"]: row["c"] for row in await cursor.fetchall()}
            cursor = await db.execute("SELECT COUNT(DISTINCT user_id) as c FROM memories")
            users = (await cursor.fetchone())["c"]
            return {
                "enabled": True,
                "total": total,
                "by_category": by_category,
                "users": users,
            }
        finally:
            await db.close()
    except Exception as exc:
        return {"enabled": True, "error": str(exc)}


async def clear_user(user_id: str) -> int:
    if not is_available():
        return 0
    try:
        db = await _get_db()
        try:
            cursor = await db.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            await db.commit()
            return cursor.rowcount
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("[HEADROOM_MEMORY] Clear failed: %s", exc)
        return 0
