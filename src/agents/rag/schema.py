from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger("kinetic.rag.schema")

STORAGE_DIR = Path("agents_workspace")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS docs (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL DEFAULT 'Untitled',
    source    TEXT NOT NULL DEFAULT '',
    added     TEXT NOT NULL DEFAULT (datetime('now')),
    metadata  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunks (
    id         TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT '',
    text       TEXT NOT NULL,
    embedding  BLOB,
    added      TEXT NOT NULL DEFAULT (datetime('now')),
    metadata   TEXT NOT NULL DEFAULT '{}',
    keywords   TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

FTS_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


def _sanitize(id_str: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "_", id_str)


def _db_path(agent_id: str) -> Path:
    dir_path = STORAGE_DIR / _sanitize(agent_id) / "knowledge"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "store.db"


def _json_path(agent_id: str) -> Path:
    return STORAGE_DIR / _sanitize(agent_id) / "knowledge" / "store.json"


async def open_db(agent_id: str) -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(_db_path(agent_id)))
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    await _run_schema(db)
    await _migrate_from_json(db, agent_id)
    db.row_factory = aiosqlite.Row
    return db


async def _run_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_SQL)
    await db.executescript(FTS_TRIGGERS_SQL)
    await db.commit()


async def _migrate_from_json(db: aiosqlite.Connection, agent_id: str) -> None:
    old_path = _json_path(agent_id)
    if not old_path.exists():
        return

    rows = list(await db.execute_fetchall("SELECT COUNT(*) as c FROM chunks"))
    if rows and rows[0][0] > 0:
        return

    logger.info("[RAG] Migrating store.json to SQLite for %s...", agent_id)
    try:
        chunks: list[dict[str, Any]] = json.loads(old_path.read_text("utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        old_path.rename(old_path.with_suffix(".json.corrupted"))
        return

    if not chunks:
        old_path.rename(old_path.with_suffix(".json.bak"))
        return

    for c in chunks:
        emb = c.get("embedding")
        emb_buf: bytes | None = None
        if emb:
            emb_buf = struct.pack(f"{len(emb)}f", *emb)
        await db.execute(
            "INSERT OR IGNORE INTO docs (id, title, source, added, metadata) VALUES (?, ?, ?, ?, ?)",
            (
                c.get("docId"),
                c.get("title", "Untitled"),
                c.get("source", ""),
                c.get("added", ""),
                json.dumps(c.get("metadata", {})),
            ),
        )
        await db.execute(
            "INSERT OR IGNORE INTO chunks "
            "(id, doc_id, title, source, text, embedding, added, metadata, keywords) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c.get("id"),
                c.get("docId"),
                c.get("title", ""),
                c.get("source", ""),
                c.get("text", ""),
                emb_buf,
                c.get("added", ""),
                json.dumps(c.get("metadata", {})),
                json.dumps(c.get("keywords", [])),
            ),
        )
    await db.commit()
    old_path.rename(old_path.with_suffix(".json.bak"))
    logger.info("[RAG] Migrated %d chunks from store.json", len(chunks))
