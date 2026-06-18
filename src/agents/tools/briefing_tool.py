"""Daily briefing — combines weather, news, schedule, and daily note into one."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.agents.tasks.scheduler import list_tasks
from src.agents.tools.news_tool import _get_news
from src.agents.tools.registry import ToolContext, ToolHandler
from src.agents.tools.weather_tool import _get_weather
from src.types.agent import ToolDefinition

DEFAULT_LOCATION = os.environ.get("WEATHER_LOCATION", "Yangon, Myanmar")


async def _daily_briefing(args: dict[str, Any], ctx: ToolContext | None) -> str:
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    location = args.get("location") or DEFAULT_LOCATION

    lines = [f"☀️ Good morning! Here's your briefing for {date_str}\n"]

    # Weather
    weather = await _get_weather({"location": location}, ctx)
    if weather and not weather.startswith("ERROR"):
        lines.append("🌤 Weather")
        lines.append(weather)
        lines.append("")

    # News
    news = await _get_news({"topic": "tech", "count": 5}, ctx)
    if news and not news.startswith("ERROR"):
        lines.append("📰 Tech News")
        lines.append(news)
        lines.append("")

    # AI News
    ai_news = await _get_news({"topic": "ai", "count": 3}, ctx)
    if ai_news and not ai_news.startswith("ERROR"):
        lines.append("🤖 AI")
        lines.append(ai_news)
        lines.append("")

    # Scheduled tasks
    tasks = list_tasks("main")
    if tasks:
        lines.append("⏰ Today's Schedule")
        for t in tasks:
            desc = t.description
            time_str = ""
            if t.next_run:
                try:
                    dt = datetime.fromisoformat(t.next_run)
                    time_str = dt.strftime(" (%H:%M)")
                except Exception:
                    pass
            recurring = " 🔄" if t.interval_ms else ""
            lines.append(f"  • {desc}{time_str}{recurring}")
        lines.append("")

    return "\n".join(lines)


async def _execute_briefing(args: dict[str, Any], ctx: ToolContext | None) -> str:
    result = await _daily_briefing(args, ctx)
    return result


def create_daily_briefing_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "daily_briefing",
                "description": (
                    "Get a complete daily briefing: weather, news, AI headlines,"
                    " and your scheduled tasks. One call covers everything."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City for weather (default: WEATHER_LOCATION env var)",
                        },
                    },
                },
            },
        ),
        execute=_execute_briefing,
    )
