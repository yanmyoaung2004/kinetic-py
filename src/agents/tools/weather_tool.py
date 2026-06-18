"""Weather tool — fetches current weather + forecast via wttr.in (no API key)."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

DEFAULT_LOCATION = os.environ.get("WEATHER_LOCATION", "")


async def _get_weather(args: dict[str, Any], ctx: ToolContext | None) -> str:
    location = (args.get("location") or DEFAULT_LOCATION or "").strip()
    if not location:
        return "ERROR: Set WEATHER_LOCATION env var or pass 'location' param."

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                f"https://wttr.in/{quote(location)}?format=%C|%t|%h|%w|%p|%P"
            )
            resp.raise_for_status()
            parts = resp.text.strip().split("|")
            condition = parts[0] if len(parts) > 0 else "?"
            temp = parts[1] if len(parts) > 1 else "?"
            humidity = parts[2] if len(parts) > 2 else "?"
            wind = parts[3] if len(parts) > 3 else "?"
            precip = parts[4] if len(parts) > 4 else "?"
            pressure = parts[5] if len(parts) > 5 else "?"

            # Forecast
            forecast_text = ""
            try:
                fcast = await client.get(
                    f"https://wttr.in/{quote(location)}?0pq&lang=en",
                    headers={"Accept": "text/plain"},
                )
                if fcast.status_code == 200:
                    lines = fcast.text.split("\n")
                    forecast_text = "\n".join(lines[2:7])
            except Exception:
                pass

            lines = [
                f"Weather in {location}:",
                f"  {condition}, {temp}",
                f"  Humidity: {humidity}",
                f"  Wind: {wind}",
            ]
            if precip and precip != "?":
                lines.append(f"  Precipitation: {precip}")
            if pressure and pressure != "?":
                lines.append(f"  Pressure: {pressure}")

            if forecast_text:
                lines.append(f"\nForecast:\n{forecast_text.strip()}")

            return "\n".join(lines)

    except Exception as e:
        return f"ERROR fetching weather: {e}"


def create_weather_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_weather",
                "description": "Get current weather and forecast for any location. No API key needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City name (e.g., 'Yangon, Myanmar'). Defaults to WEATHER_LOCATION env var.",
                        },
                    },
                },
            },
        ),
        execute=_get_weather,
    )
