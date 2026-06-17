from __future__ import annotations

import logging
from pathlib import Path

import click
import httpx

logger = logging.getLogger("kinetic.cli.knowledge")

AGENT_ID = "main"


@click.group()
def knowledge() -> None:
    """Manage the knowledge base — inject text, URLs, files, list/delete docs."""
    pass


@knowledge.command()
@click.option("--agent", default=AGENT_ID, help="Agent ID")
def list_cmd(agent: str) -> None:
    """List indexed documents"""
    import asyncio

    from src.agents.rag.vector_store import list_documents

    async def _run():
        docs = await list_documents(agent)
        if not docs:
            click.echo("  No documents indexed.")
            return
        for d in docs:
            click.echo(f"  • {d.title} ({d.chunk_count} chunks) — {d.source}")

    asyncio.run(_run())


@knowledge.command()
@click.option("--text", "-t", help="Text content to index")
@click.option("--url", "-u", help="URL to fetch and index")
@click.option("--file", "-f", "file_path", type=click.Path(exists=True), help="File path to index")
@click.option("--title", help="Document title")
@click.option("--agent", default=AGENT_ID, help="Agent ID")
def inject(text: str | None, url: str | None, file_path: str | None, title: str | None, agent: str) -> None:
    """Index text, URL, or file into the knowledge base"""
    import asyncio

    from src.agents.rag.embedding import get_embedding
    from src.agents.rag.vector_store import add_chunks, chunk_text, strip_html
    from src.agents.tools.knowledge_tool import ensure_embedding

    async def _run():
        content = ""
        src = "manual"
        doc_title = title or "Untitled"

        if url:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    html = resp.text
                content = strip_html(html)[:50000]
                src = url
                doc_title = title or url.split("/")[-1] or "Untitled"
            except Exception as e:
                click.echo(f"  ✗ Failed to fetch URL: {e}")
                return
        elif file_path:
            content = Path(file_path).read_text("utf-8", errors="replace")[:50000]
            src = file_path
            doc_title = title or Path(file_path).name
        elif text:
            content = text
        else:
            click.echo("  ✗ Provide --text, --url, or --file")
            return

        segments = await chunk_text(content, "sentence", 500, 60)
        if not segments:
            click.echo("  ✗ No content to index.")
            return

        ensure_embedding()
        chunks_data = []
        for seg in segments:
            emb = await get_embedding(seg)
            chunks_data.append(
                {
                    "doc_id": f"doc_{int(__import__('time').time() * 1000)}",
                    "title": doc_title,
                    "source": src,
                    "text": seg,
                    "embedding": emb,
                    "metadata": {},
                }
            )
        count = await add_chunks(agent, chunks_data)
        click.echo(f'  ✓ Indexed "{doc_title}" ({count} chunks)')

    asyncio.run(_run())


@knowledge.command()
@click.argument("doc_id")
@click.option("--agent", default=AGENT_ID, help="Agent ID")
def remove(doc_id: str, agent: str) -> None:
    """Remove a document from the knowledge base"""
    import asyncio

    from src.agents.rag.vector_store import remove_document

    async def _run():
        ok = await remove_document(agent, doc_id)
        click.echo(f"  {'✓ Deleted' if ok else '✗ Not found'}: {doc_id}")

    asyncio.run(_run())


@knowledge.command()
@click.option("--agent", default=AGENT_ID, help="Agent ID")
def stats(agent: str) -> None:
    """Show knowledge base statistics"""
    import asyncio

    from src.agents.rag.vector_store import get_store_stats

    async def _run():
        s = await get_store_stats(agent)
        click.echo(f"  Knowledge Base: {s['doc_count']} documents, {s['chunk_count']} chunks")

    asyncio.run(_run())
