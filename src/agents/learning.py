"""Workflow learning system — stores successful tool sequences in SQLite."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import aiosqlite

logger = logging.getLogger("kinetic.learning")

DB_PATH = Path("agents_workspace") / "learning.db"


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                tool_sequence TEXT NOT NULL,
                user_message TEXT,
                timestamp TEXT NOT NULL,
                success_count INTEGER DEFAULT 1
            )
        """)
        await db.commit()


async def save_workflow(trigger: str, tool_sequence: list[str], user_message: str = "") -> None:
    """Save a successful workflow."""
    await init_db()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Check if similar trigger already exists
        cursor = await db.execute(
            "SELECT id, tool_sequence, success_count FROM workflows WHERE trigger = ?",
            (trigger,),
        )
        row = await cursor.fetchone()
        if row:
            # Update existing — keep the tool sequence, increment count
            await db.execute(
                "UPDATE workflows SET tool_sequence = ?, success_count = ?, user_message = ? WHERE id = ?",
                (json.dumps(tool_sequence), row[2] + 1, user_message, row[0]),
            )
        else:
            await db.execute(
                "INSERT INTO workflows (trigger, tool_sequence, user_message, timestamp) VALUES (?, ?, ?, ?)",
                (trigger, json.dumps(tool_sequence), user_message,
                 __import__("datetime").datetime.now().isoformat()),
            )
        await db.commit()
    logger.info("[LEARN] Saved workflow for '%s': %s", trigger, tool_sequence)


async def find_workflows(message: str) -> list[dict]:
    """Find matching workflows by keyword overlap."""
    await init_db()
    words = set(re.findall(r"[a-z]{4,}", message.lower()))
    if not words:
        return []

    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM workflows ORDER BY success_count DESC")
        rows = await cursor.fetchall()

    matches = []
    for row in rows:
        trigger_words = set(re.findall(r"[a-z]{4,}", row["trigger"].lower()))
        overlap = words & trigger_words
        if overlap:
            matches.append({
                "id": row["id"],
                "trigger": row["trigger"],
                "tool_sequence": json.loads(row["tool_sequence"]),
                "user_message": row["user_message"],
                "timestamp": row["timestamp"],
                "success_count": row["success_count"],
            })
    return matches


async def forget_workflow(trigger: str) -> bool:
    """Delete a workflow by trigger word."""
    await init_db()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        cursor = await db.execute("DELETE FROM workflows WHERE trigger = ?", (trigger,))
        await db.commit()
        return cursor.rowcount > 0


async def list_workflows() -> list[dict]:
    """List all learned workflows."""
    await init_db()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM workflows ORDER BY success_count DESC")
        rows = await cursor.fetchall()
    return [{
        "id": row["id"],
        "trigger": row["trigger"],
        "tool_sequence": json.loads(row["tool_sequence"]),
        "user_message": row["user_message"][:100] if row["user_message"] else "",
        "timestamp": row["timestamp"],
        "success_count": row["success_count"],
    } for row in rows]


async def get_last_workflow() -> dict | None:
    """Get the most recently saved workflow."""
    await init_db()
    async with aiosqlite.connect(str(DB_PATH)) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM workflows ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        if row:
            return {
                "id": row["id"],
                "trigger": row["trigger"],
                "tool_sequence": json.loads(row["tool_sequence"]),
                "user_message": row["user_message"],
                "timestamp": row["timestamp"],
                "success_count": row["success_count"],
            }
    return None
