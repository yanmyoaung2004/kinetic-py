from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

from src.agents.rag.embedding import get_embedding, init_embedding
from src.agents.rag.vector_store import (
    add_chunks,
    chunk_text,
    get_store_stats,
    list_documents,
    remove_document,
    search_similar,
    strip_html,
)
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.knowledge")

CONFIG_PATH = Path("config/models.json")
SANDBOX_ROOT = Path("agent_sandbox")


def _resolve_safe_path(requested: str) -> Path:
    norm = requested.replace("\\", "/").lstrip("/")
    resolved = (SANDBOX_ROOT / norm).resolve()
    if not str(resolved).startswith(str(SANDBOX_ROOT.resolve())):
        raise ValueError(f"Path escapes sandbox: '{requested}'")
    if ".." in requested:
        raise ValueError(f"Path traversal blocked: '{requested}'")
    return resolved


def init_knowledge_base(base_url: str, api_key: str, model: str | None = None, options: dict | None = None) -> None:
    init_embedding(base_url, api_key, model, options)


def ensure_embedding() -> None:
    try:
        if not CONFIG_PATH.exists():
            return
        raw = json.loads(CONFIG_PATH.read_text("utf-8"))
        emb = raw.get("embedding")
        if not emb or not raw.get("providers", {}).get(emb.get("provider", "")):
            return

        ep = raw["providers"][emb["provider"]]
        key_env = ep.get("apiKeyEnv", "")

        is_local = bool(re.search(r"localhost|127\.0\.0\.1", ep.get("baseUrl", ""), re.IGNORECASE))

        import os
        is_raw_key = bool(re.match(
            r"^(sk-|gsk_|gsb_|nvapi-|nvapi|fk|pds-gpt_|skev_|lightning-|lt-)", key_env, re.IGNORECASE,
        ))
        if is_raw_key:
            logger.warning("[RAG] Embedding provider '%s' has a raw API key instead of an env var name", emb["provider"])
            return

        api_key = "" if is_local else os.environ.get(key_env, "")
        if not is_local and not api_key:
            logger.warning("[RAG] Embedding provider '%s': env var '%s' not set", emb["provider"], key_env)
            return

        init_embedding(
            ep["baseUrl"],
            api_key,
            emb.get("model"),
            {
                "extra_body": emb.get("extraBody"),
                "encoding_format": emb.get("encodingFormat"),
            },
        )
    except Exception:
        pass


# ── Tool creators ──


def create_query_knowledge_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "query_knowledge_base",
                "description": "Search your indexed knowledge base using semantic similarity. Use this to retrieve information from documents, code, and web pages you've previously indexed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query (natural language)"},
                        "top_k": {"type": "number", "description": "Number of results (1-10, default 5)"},
                    },
                    "required": ["query"],
                },
            },
        ),
        execute=lambda args, ctx: _query_knowledge(agent_id, args),
    )


async def _query_knowledge(agent_id: str, args: dict) -> str:
    try:
        ensure_embedding()
        query = args["query"]
        query_emb = await get_embedding(query)
        results = await search_similar(
            agent_id,
            query_emb,
            query,
            type("Options", (), {"top_k": args.get("top_k", 5), "keyword_weight": 0.15, "diversify": True, "diversity_lambda": 0.7, "doc_ids": None})(),
        )
        if not results:
            return "No relevant information found in the knowledge base."
        return "\n\n---\n\n".join(
            f"[{i + 1}] {r.chunk.title} (relevance: {r.score * 100:.0f}%)\nSource: {r.chunk.source}\n{r.chunk.text[:600]}"
            for i, r in enumerate(results)
        )
    except Exception as e:
        return f"ERROR: {e}"


def create_index_file_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "index_file",
                "description": "Index a file from the sandbox into the knowledge base.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path within the sandbox"},
                        "title": {"type": "string", "description": "Optional title for the document (defaults to filename)"},
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=lambda args, ctx: _index_file(agent_id, args),
    )


async def _index_file(agent_id: str, args: dict) -> str:
    try:
        ensure_embedding()
        safe = _resolve_safe_path(args["path"])
        if not safe.exists():
            return f"File not found: {args['path']}"
        content = safe.read_text("utf-8", errors="replace")
        if len(content) > 500_000:
            return f"File too large ({len(content) / 1024:.0f} KB). Max: 500 KB"

        text_chunks = await chunk_text(content, "sentence", 500, 60)
        embeddings = await asyncio_gather([get_embedding(t) for t in text_chunks])

        title = args.get("title", safe.name)
        doc_id = f"doc_{int(__import__('time').time() * 1000)}"

        chunks_data = [
            {"doc_id": doc_id, "title": title, "source": f"file://{args['path']}", "text": text, "embedding": embeddings[i], "metadata": {"filename": args["path"]}}
            for i, text in enumerate(text_chunks)
        ]
        count = await add_chunks(agent_id, chunks_data)
        return f"✓ Indexed {args['path']} ({count} chunks, {len(content) / 1024:.0f} KB)"
    except Exception as e:
        return f"ERROR: {e}"


def create_index_url_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "index_url",
                "description": "Fetch a URL and index its content into the knowledge base.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The full URL to fetch and index"},
                        "title": {"type": "string", "description": "Optional title (defaults to URL)"},
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=lambda args, ctx: _index_url(agent_id, args),
    )


async def _index_url(agent_id: str, args: dict) -> str:
    try:
        url = args["url"]
        if not url.startswith("http"):
            return "URL must start with http:// or https://"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        content = strip_html(html)
        if len(content) < 50:
            return "Page has no readable content."
        if len(content) > 500_000:
            return f"Page too large ({len(content) / 1024:.0f} KB). Max: 500 KB"

        ensure_embedding()
        text_chunks = await chunk_text(content, "recursive", 500, 80)
        embeddings = await asyncio_gather([get_embedding(t) for t in text_chunks])

        title = args.get("title", url)
        doc_id = f"doc_{int(__import__('time').time() * 1000)}"

        chunks_data = [
            {"doc_id": doc_id, "title": title, "source": url, "text": text, "embedding": embeddings[i], "metadata": {"url": url}}
            for i, text in enumerate(text_chunks)
        ]
        count = await add_chunks(agent_id, chunks_data)
        return f"✓ Indexed {url} ({count} chunks, {len(content) / 1024:.0f} KB)"
    except Exception as e:
        return f"ERROR: {e}"


def create_knowledge_stats_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "knowledge_stats",
                "description": "Get statistics about the indexed knowledge base: number of documents and chunks.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        ),
        execute=lambda args, ctx: _stats(agent_id),
    )


async def _stats(agent_id: str) -> str:
    stats = await get_store_stats(agent_id)
    return f"Knowledge base: {stats['doc_count']} documents, {stats['chunk_count']} chunks"


async def asyncio_gather(coros: list) -> list:
    import asyncio
    return await asyncio.gather(*coros)
