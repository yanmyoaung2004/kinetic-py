"""Web image search — find and download images for presentations without API keys."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from src.agents.tools.presentation_tool import SANDBOX
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def _search_images(args: dict[str, Any], ctx: ToolContext | None) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "ERROR: 'query' is required."

    count = min(args.get("count", 5), 10)
    download_best = args.get("download", False)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}+image&iax=images&ia=images"
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            # Extract image URLs from DuckDuckGo HTML results
            urls = re.findall(r'<img[^>]+src="(https?://[^"]+)"', resp.text)

            # Filter valid image extensions
            images = []
            seen = set()
            for u in urls:
                if u in seen:
                    continue
                seen.add(u)
                if any(u.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    images.append(u)
                elif "thumbnail" in u.lower() or "img" in u.lower():
                    images.append(u)
                if len(images) >= count:
                    break

        if not images:
            return "No images found for that query."

        result_lines = [f"Found {len(images)} images for '{query}':"]

        downloaded = []
        for i, img_url in enumerate(images, 1):
            result_lines.append(f"  {i}. {img_url}")

        if download_best and images:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                for img_url in images[:3]:
                    try:
                        resp = await client.get(img_url, headers=headers)
                        resp.raise_for_status()
                        ext = ".jpg"
                        ct = resp.headers.get("content-type", "")
                        if "png" in ct:
                            ext = ".png"
                        elif "gif" in ct:
                            ext = ".gif"
                        elif "webp" in ct:
                            ext = ".webp"
                        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", query.lower())[:30]
                        filename = f"{safe_name}_{i}{ext}"
                        filepath = SANDBOX / filename
                        filepath.write_bytes(resp.content)
                        downloaded.append(filename)
                    except Exception:
                        continue

        if downloaded:
            result_lines.append(f"\nDownloaded to sandbox: {', '.join(downloaded)}")

        return "\n".join(result_lines)

    except Exception as e:
        return f"ERROR searching images: {e}"


def create_image_search_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "search_images",
                "description": (
                    "Search the web for images related to a topic and optionally"
                    " download the best ones to the sandbox."
                    " Use this for finding presentation images."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for images"},
                        "count": {"type": "number", "description": "Number of results (max 10, default 5)"},
                        "download": {
                            "type": "boolean",
                            "description": "Set to true to download the best images to agent_sandbox/",
                        },
                    },
                    "required": ["query"],
                },
            },
        ),
        execute=_search_images,
    )
