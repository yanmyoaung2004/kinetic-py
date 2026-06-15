from __future__ import annotations

import logging

import httpx

from src.agents.rag.embedding import get_embedding
from src.agents.rag.vector_store import add_chunks, chunk_text
from src.agents.tools.knowledge_tool import ensure_embedding
from src.agents.tools.registry import ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.dataconnectors")


# ── GitHub connector ──


def create_github_index_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "index_github",
                "description": "Index a GitHub repository or file into the knowledge base.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full URL to a GitHub file or repo"},
                        "title": {"type": "string", "description": "Optional title (defaults to repo name)"},
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=lambda args, ctx: _index_github(agent_id, args),
    )


async def _index_github(agent_id: str, args: dict) -> str:
    try:
        url = args["url"]
        if "github.com" not in url:
            return "Not a GitHub URL"

        raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        if "raw.githubusercontent.com" not in raw_url:
            raw_url = raw_url.rstrip("/") + "/main/README.md"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(raw_url)
            resp.raise_for_status()
            content = resp.text

        if len(content) < 50:
            return "File is empty or binary."
        if len(content) > 500_000:
            return f"File too large ({len(content) / 1024:.0f} KB). Max: 500 KB"

        ensure_embedding()
        text_chunks = await chunk_text(content, "recursive", 600, 80)
        embeddings = await _gather([get_embedding(t) for t in text_chunks])

        title = args.get("title", f"GitHub: {url.split('/')[-2]}/{url.split('/')[-1]}")
        doc_id = f"github_{int(__import__('time').time() * 1000)}"

        chunks_data = [
            {"doc_id": doc_id, "title": title, "source": url, "text": text, "embedding": embeddings[i], "metadata": {"source": "github", "url": url}}
            for i, text in enumerate(text_chunks)
        ]
        count = await add_chunks(agent_id, chunks_data)
        return f"✓ Indexed {url} ({count} chunks, {len(content) / 1024:.0f} KB)"
    except Exception as e:
        return f"ERROR: {e}"


# ── Web scraper connector ──


def create_web_scraper_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "scrape_and_index",
                "description": "Scrape a web page and index its content into the knowledge base.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to scrape"},
                        "title": {"type": "string", "description": "Optional title (defaults to URL)"},
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=lambda args, ctx: _scrape_and_index(agent_id, args),
    )


async def _scrape_and_index(agent_id: str, args: dict) -> str:
    try:
        url = args["url"]
        if not url.startswith("http"):
            return "URL must start with http:// or https://"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"User-Agent": "K.I.N.E.T.I.C./2.0"})
            resp.raise_for_status()
            html = resp.text

        # Basic HTML stripping (regex-based like v1)
        import re
        content = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"&[a-z]+;", " ", content)
        content = re.sub(r"https?://\S+", "", content)
        content = re.sub(r"\s+", " ", content).strip()

        if len(content) < 100:
            return "Page has insufficient readable content."
        if len(content) > 500_000:
            return f"Page too large ({len(content) / 1024:.0f} KB). Max: 500 KB"

        ensure_embedding()
        text_chunks = await chunk_text(content, "recursive", 600, 80)
        embeddings = await _gather([get_embedding(t) for t in text_chunks])

        title = args.get("title", url)
        doc_id = f"scrape_{int(__import__('time').time() * 1000)}"

        chunks_data = [
            {"doc_id": doc_id, "title": title, "source": url, "text": text, "embedding": embeddings[i], "metadata": {"source": "web", "url": url}}
            for i, text in enumerate(text_chunks)
        ]
        count = await add_chunks(agent_id, chunks_data)
        return f"✓ Indexed {url} ({count} chunks, {len(content) / 1024:.0f} KB)"
    except Exception as e:
        return f"ERROR: {e}"


async def _gather(coros: list) -> list:
    import asyncio
    return await asyncio.gather(*coros)
