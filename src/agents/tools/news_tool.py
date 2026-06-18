"""News headlines tool — fetches top headlines via RSS feeds (no API key)."""

from __future__ import annotations

import re
from typing import Any

import httpx

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# RSS feeds by category
FEEDS: dict[str, list[str]] = {
    "tech": [
        "https://hnrss.org/frontpage?count=5",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    ],
    "ai": [
        "https://www.reddit.com/r/MachineLearning/hot/.rss",
    ],
    "world": [
        "https://feeds.bbci.co.uk/news/rss.xml",
    ],
    "business": [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ],
}


async def _get_news(args: dict[str, Any], ctx: ToolContext | None) -> str:
    topic = (args.get("topic") or "tech").strip().lower()
    count = min(args.get("count", 7), 15)

    feed_urls = FEEDS.get(topic, FEEDS["tech"])

    headlines: list[tuple[str, str]] = []
    headers = {"User-Agent": USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for feed_url in feed_urls:
                if len(headlines) >= count:
                    break
                try:
                    resp = await client.get(feed_url, headers=headers)
                    resp.raise_for_status()
                    # Simple RSS/XML headline extraction
                    items = re.findall(
                        r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>",
                        resp.text,
                        re.DOTALL,
                    )
                    if not items:
                        items = re.findall(
                            r"<entry>.*?<title>(.*?)</title>.*?<link.*?href=\"(.*?)\"",
                            resp.text,
                            re.DOTALL,
                        )
                    for title, link in items:
                        clean_title = re.sub(r"<[^>]+>", "", title).strip()
                        if clean_title and (clean_title.lower(), link) not in headlines:
                            headlines.append((clean_title, link))
                            if len(headlines) >= count:
                                break
                except Exception:
                    continue

        if not headlines:
            return f"No headlines found for topic '{topic}'."

        lines = [f"Top {topic} headlines:"]
        for i, (title, link) in enumerate(headlines, 1):
            lines.append(f"  {i}. {title}")
        return "\n".join(lines)

    except Exception as e:
        return f"ERROR fetching news: {e}"


def create_news_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_news",
                "description": (
                    "Get latest news headlines by topic."
                    " Topics: tech, ai, world, business (default: tech)."
                    " No API key needed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Topic: 'tech', 'ai', 'world', 'business' (default: tech)",
                        },
                        "count": {
                            "type": "number",
                            "description": "Number of headlines (max 15, default 7)",
                        },
                    },
                },
            },
        ),
        execute=_get_news,
    )
