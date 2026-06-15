from __future__ import annotations

import json
import logging
import re
import struct
from dataclasses import dataclass, field
from typing import Any

import aiosqlite
import numpy as np
from bs4 import BeautifulSoup

from src.agents.rag.schema import open_db

logger = logging.getLogger("kinetic.rag.vectorstore")


@dataclass
class Chunk:
    id: str
    doc_id: str
    title: str
    source: str
    text: str
    embedding: list[float] = field(default_factory=list)
    added: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)


@dataclass
class KnowledgeDoc:
    id: str
    title: str
    source: str
    added: str
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchOptions:
    top_k: int = 5
    keyword_weight: float = 0.15
    diversify: bool = False
    diversity_lambda: float = 0.7
    doc_ids: list[str] | None = None
    metadata_filter: dict[str, str] | None = None


@dataclass
class SearchResult:
    chunk: Chunk
    score: float = 0.0


# ── DB cache ──

_db_cache: dict[str, aiosqlite.Connection] = {}


async def _get_db(agent_id: str) -> aiosqlite.Connection:
    if agent_id not in _db_cache:
        _db_cache[agent_id] = await open_db(agent_id)
    return _db_cache[agent_id]


# ── Similarity ──


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


# ── Keyword extraction ──

STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "can", "could", "shall", "should", "may", "might", "must",
    "it", "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "not", "no", "nor", "so", "if", "then", "than",
    "too", "very", "just", "about", "above", "after", "again", "all", "also",
    "any", "because", "before", "between", "both", "each", "few", "more",
    "most", "into", "over", "such", "only", "own", "same", "some", "still",
}


def extract_keywords(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    words = [w for w in cleaned.split() if len(w) > 2 and w not in STOP_WORDS]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: -x[1])
    return [w for w, _ in sorted_words[:30]]


# ── MMR ──


def _mmr_diversify(results: list[SearchResult], emb_matrix: np.ndarray, lambda_: float) -> list[SearchResult]:
    n = len(results)
    if n <= 1:
        return results
    selected = [results[0]]
    selected_embs = [emb_matrix[0]]
    remaining_indices = list(range(1, n))

    while len(selected) < n and remaining_indices:
        best_idx = -1
        best_score = -float("inf")
        for i in remaining_indices:
            rel = results[i].score
            sim_to_sel = max(np.dot(emb_matrix[i], se) / (np.linalg.norm(emb_matrix[i]) * np.linalg.norm(se) + 1e-10) for se in selected_embs)
            mmr = lambda_ * rel - (1 - lambda_) * sim_to_sel
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        if best_idx == -1:
            break
        remaining_indices.remove(best_idx)
        selected.append(results[best_idx])
        selected_embs.append(emb_matrix[best_idx])

    return selected


# ── Public API ──


async def add_chunks(agent_id: str, chunks: list[dict[str, Any]]) -> int:
    db = await _get_db(agent_id)
    now = __import__("datetime").datetime.now().isoformat()
    count = 0
    for c in chunks:
        chunk_id = f"chunk_{int(__import__('time').time() * 1000)}_{count}"
        keywords = json.dumps(extract_keywords(c["text"]))
        emb = c.get("embedding")
        emb_buf: bytes | None = None
        if emb:
            emb_buf = struct.pack(f"{len(emb)}f", *emb)

        await db.execute(
            "INSERT OR IGNORE INTO docs (id, title, source, added, metadata) VALUES (?, ?, ?, ?, ?)",
            (c["doc_id"], c.get("title", "Untitled"), c.get("source", ""), now, json.dumps(c.get("metadata", {}))),
        )
        await db.execute(
            "INSERT INTO chunks (id, doc_id, title, source, text, embedding, added, metadata, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk_id, c["doc_id"], c.get("title", ""), c.get("source", ""), c["text"], emb_buf, now, json.dumps(c.get("metadata", {})), keywords),
        )
        count += 1
    await db.commit()
    return count


async def search_similar(
    agent_id: str,
    query_embedding: list[float],
    query_text: str | None = None,
    options: SearchOptions | None = None,
) -> list[SearchResult]:
    db = await _get_db(agent_id)
    opts = options or SearchOptions()
    top_k = opts.top_k
    kw_weight = opts.keyword_weight
    limit = max(top_k * 3, 30)

    query_vec = np.array(query_embedding, dtype=np.float64)

    # Build SQL
    sql = "SELECT rowid, id, doc_id, title, source, text, embedding, added, metadata, keywords FROM chunks"
    params: list[Any] = []
    conditions: list[str] = []

    if opts.doc_ids:
        placeholders = ",".join("?" for _ in opts.doc_ids)
        conditions.append(f"doc_id IN ({placeholders})")
        params.extend(opts.doc_ids)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " LIMIT ?"
    params.append(limit)

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()

    chunks: list[Chunk] = []
    for r in rows:
        emb_raw = r["embedding"]
        emb: list[float] = []
        if emb_raw:
            n_floats = len(emb_raw) // 4
            emb = list(struct.unpack(f"{n_floats}f", emb_raw))
        chunks.append(Chunk(
            id=r["id"],
            doc_id=r["doc_id"],
            title=r["title"],
            source=r["source"],
            text=r["text"],
            embedding=emb,
            added=r["added"],
            metadata=_safe_json(r["metadata"]),
            keywords=_safe_json(r["keywords"]),
        ))

    # Apply metadata filter in Python (avoids SQLite json_extract quirks)
    if opts.metadata_filter:
        filtered = []
        for ch in chunks:
            if all(ch.metadata.get(k) == v for k, v in opts.metadata_filter.items()):
                filtered.append(ch)
        chunks = filtered

    # Semantic scores
    scored: list[SearchResult] = []
    vecs: list[np.ndarray] = []
    for ch in chunks:
        if ch.embedding:
            vec = np.array(ch.embedding, dtype=np.float64)
            vecs.append(vec)
            scored.append(SearchResult(chunk=ch, score=cosine_similarity(query_vec, vec)))
        else:
            scored.append(SearchResult(chunk=ch, score=0.0))

    # BM25 keyword scores
    bm25_scores: dict[str, float] = {}
    if query_text and len(query_text.strip()) > 2:
        try:
            tokens = re.sub(r"[^a-z0-9\s-]", " ", query_text.lower()).split()
            tokens = [f'"{w}"' for w in tokens if len(w) > 2 and w not in STOP_WORDS]
            if tokens:
                fts_query = " OR ".join(tokens)
                fts_cursor = await db.execute(
                    "SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                )
                fts_rows = await fts_cursor.fetchall()
                if fts_rows:
                    ranks = [abs(r["rank"]) for r in fts_rows]
                    min_rank = min(ranks)
                    max_rank = max(ranks)
                    range_ = max(max_rank - min_rank, 0.001)
                    for r in fts_rows:
                        normalized = 1 - (abs(r["rank"]) - min_rank) / range_
                        bm25_scores[str(r["rowid"])] = normalized
        except aiosqlite.OperationalError:
            pass

    # Combine scores
    for i, s in enumerate(scored):
        rowid = str(rows[i]["rowid"])
        bm25 = bm25_scores.get(rowid, 0.0)
        s.score = (1 - kw_weight) * s.score + kw_weight * bm25

    scored.sort(key=lambda x: -x.score)
    top_results = scored[:limit]

    if opts.diversify and len(top_results) > 1:
        emb_matrix = np.array([np.array(r.chunk.embedding, dtype=np.float64) for r in top_results])
        top_results = _mmr_diversify(top_results, emb_matrix, opts.diversity_lambda)

    return top_results[:top_k]


async def list_documents(agent_id: str) -> list[KnowledgeDoc]:
    db = await _get_db(agent_id)
    cursor = await db.execute(
        """SELECT d.id, d.title, d.source, d.added, d.metadata,
                  COUNT(c.id) as chunkCount
           FROM docs d
           LEFT JOIN chunks c ON c.doc_id = d.id
           GROUP BY d.id
           ORDER BY d.added DESC"""
    )
    rows = await cursor.fetchall()
    return [
        KnowledgeDoc(
            id=r["id"],
            title=r["title"],
            source=r["source"],
            added=r["added"],
            chunk_count=r["chunkCount"],
            metadata=_safe_json(r["metadata"]),
        )
        for r in rows
    ]


async def remove_document(agent_id: str, doc_id: str) -> bool:
    db = await _get_db(agent_id)
    cursor = await db.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    await db.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
    await db.commit()
    return cursor.rowcount > 0


async def get_store_stats(agent_id: str) -> dict[str, int]:
    db = await _get_db(agent_id)
    docs = await db.execute_fetchall("SELECT COUNT(*) as c FROM docs")
    chunks = await db.execute_fetchall("SELECT COUNT(*) as c FROM chunks")
    return {"doc_count": docs[0][0] if docs else 0, "chunk_count": chunks[0][0] if chunks else 0}


async def get_document(agent_id: str, doc_id: str) -> list[Chunk]:
    db = await _get_db(agent_id)
    cursor = await db.execute(
        "SELECT id, doc_id, title, source, text, embedding, added, metadata, keywords FROM chunks WHERE doc_id = ?",
        (doc_id,),
    )
    rows = await cursor.fetchall()
    return [
        Chunk(
            id=r["id"],
            doc_id=r["doc_id"],
            title=r["title"],
            source=r["source"],
            text=r["text"],
            embedding=list(struct.unpack(f"{len(r['embedding']) // 4}f", r["embedding"])) if r["embedding"] else [],
            added=r["added"],
            metadata=_safe_json(r["metadata"]),
            keywords=_safe_json(r["keywords"]),
        )
        for r in rows
    ]


def _safe_json(val: str) -> Any:
    if not val:
        return {}
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return {}


# ── Chunking ──

ChunkStrategy = str  # "recursive" | "sentence" | "paragraph"


async def chunk_text(
    text: str,
    strategy: ChunkStrategy = "recursive",
    max_len: int = 600,
    overlap: int = 80,
) -> list[str]:
    if strategy == "paragraph":
        return _chunk_by_paragraph(text, max_len)
    elif strategy == "sentence":
        return _chunk_by_sentence(text, max_len, overlap)
    return _chunk_recursive(text, max_len, overlap)


def _chunk_recursive(text: str, max_len: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    current = ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip()
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(para) > max_len:
                chunks.extend(_chunk_by_sentence(para, max_len, overlap))
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) > 20]


def _chunk_by_sentence(text: str, max_len: int, overlap: int) -> list[str]:
    sentences = re.findall(r"[^.!?\n]+[.!?]*", text) or [text]
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        trimmed = sent.strip()
        if not trimmed:
            continue
        candidate = (current + " " + trimmed).strip()
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = trimmed
    if current:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = []
        for i in range(len(chunks)):
            overlapped.append(chunks[i])
            if i < len(chunks) - 1:
                prev_sents = re.findall(r"[^.!?\n]+[.!?]*", chunks[i]) or []
                overlap_sents = " ".join(prev_sents[-2:]).strip()
                combined = (overlap_sents + " " + chunks[i + 1]).strip()
                if len(combined) < max_len + overlap:
                    overlapped.append(combined)
        return [c for c in overlapped if len(c) > 20]
    return [c for c in chunks if len(c) > 20]


def _chunk_by_paragraph(text: str, max_len: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip()
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) > 20]


def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_document_meta(text: str, source: str | None = None) -> dict[str, Any]:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    first_line = lines[0] if lines else ""
    title = re.sub(r"^#\s*", "", first_line).strip() or source or "Untitled"
    headings = len([l for l in lines if re.match(r"^#{1,6}\s", l)])
    word_count = len(text.split())
    has_non_ascii = bool(re.search(r"[^\x00-\x7F]", text))
    return {"title": title, "source": source or "unknown", "headings": headings, "word_count": word_count, "has_non_ascii": has_non_ascii}
