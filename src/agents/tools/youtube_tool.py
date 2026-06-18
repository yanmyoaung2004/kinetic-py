"""YouTube tool — video info, transcript, and summarization."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _extract_vid(url: str) -> str | None:
    patterns = [
        r"youtube\.com/watch\?v=([\w-]+)",
        r"youtu\.be/([\w-]+)",
        r"youtube\.com/embed/([\w-]+)",
        r"youtube\.com/shorts/([\w-]+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


async def _get_youtube_info(args: dict[str, Any], ctx: ToolContext | None) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "ERROR: 'url' parameter is required."

    vid = _extract_vid(url)
    if not vid:
        return "ERROR: Could not extract video ID from that URL."

    summarize = args.get("summarize", False)

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                f"https://www.youtube.com/watch?v={vid}",
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            html = resp.text

        # Metadata extraction
        title = ""
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if m:
            title = m.group(1)

        description = ""
        m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html)
        if m:
            description = m.group(1)
        if not description:
            m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
            if m:
                description = m.group(1)

        channel = ""
        m = re.search(r'<link\s+itemprop="name"\s+content="([^"]+)"', html)
        if m:
            channel = m.group(1)
        if not channel:
            m = re.search(r'"author"[^}]*"name"\s*:\s*"([^"]+)"', html)
            if m:
                channel = m.group(1)

        duration = ""
        m = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
        if m:
            secs = int(m.group(1))
            h, r = divmod(secs, 3600)
            m2, s = divmod(r, 60)
            duration = f"{h}h {m2}m {s}s" if h else f"{m2}m {s}s"

        views = ""
        m = re.search(r'"viewCount"\s*:\s*"(\d+)"', html)
        if m:
            views = f"{int(m.group(1)):,}"

        upload_date = ""
        m = re.search(r'"uploadDate"\s*:\s*"([^"]+)"', html)
        if m:
            upload_date = m.group(1)

        full_desc = description
        m = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                ld = json.loads(m.group(1))
                if isinstance(ld, dict):
                    full_desc = ld.get("description", description)
                    if not channel:
                        channel = ld.get("author", {}).get("name", "")
            except json.JSONDecodeError:
                pass

        lines = [f"Title: {title or '(unknown)'}"]
        if channel:
            lines.append(f"Channel: {channel}")
        if duration:
            lines.append(f"Duration: {duration}")
        if upload_date:
            lines.append(f"Uploaded: {upload_date}")
        if views:
            lines.append(f"Views: {views}")
        if full_desc:
            lines.append(f"\nDescription:\n{full_desc[:500]}")

        # ── Transcript ──
        if summarize:
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(vid)  # type: ignore[attr-defined]
                transcript_text = " ".join(t["text"] for t in transcript_list)

                # Truncate if very long (LLM context window)
                if len(transcript_text) > 10000:
                    transcript_text = transcript_text[:10000] + "\n\n...[truncated]"

                lines.append(f"\n── Transcript ({len(transcript_list)} segments) ──\n")
                lines.append(transcript_text)
                lines.append("\n── End transcript ──")
            except Exception as e:
                lines.append(f"\n(Transcript unavailable: {e})")

        lines.append(f"\nURL: https://youtu.be/{vid}")
        return "\n".join(lines)

    except Exception as e:
        return f"ERROR: Could not fetch video info: {e}"


def create_youtube_info_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_youtube_info",
                "description": (
                    "Get video info + transcript. Set summarize=true to fetch"
                    " the full transcript text so you can summarize the video content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "YouTube video URL"},
                        "summarize": {
                            "type": "boolean",
                            "description": (
                                "Set to true to fetch the full transcript for summarization."
                                " The transcript text will be included in the response."
                            ),
                        },
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=_get_youtube_info,
    )
