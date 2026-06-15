from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("kinetic.tools.websearch")


async def web_search(query: str, count: int = 5) -> str:
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return "Error: BRAVE_API_KEY is missing from environment variables."

    url = "https://api.search.brave.com/res/v1/web/search"
    params = {"q": query, "count": str(min(count, 20))}
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return f'No results found for query: "{query}"'

        formatted = []
        for i, r in enumerate(results):
            date = f" [Published: {r['published']}]" if r.get("published") else ""
            formatted.append(
                f"Result {i + 1}:\n"
                f"Title: {r['title']}{date}\n"
                f"URL: {r['url']}\n"
                f"Snippet: {r['description']}\n"
            )
        return f'Search Results for "{query}":\n\n' + "\n---\n".join(formatted)
    except httpx.HTTPError as e:
        return f"Search API Error: {e}"
    except Exception as e:
        return f"Technical Failure during search execution: {e}"
