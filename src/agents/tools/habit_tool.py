"""Habit tracker — add, log, and track daily/weekly habits with streaks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

DATA_DIR = Path("agents_workspace") / "habits"


def _data() -> dict[str, Any]:
    p = DATA_DIR / "habits.json"
    if p.exists():
        return json.loads(p.read_text("utf-8"))
    return {"habits": []}


def _save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "habits.json").write_text(json.dumps(data, indent=2))


def _next_id(data: dict[str, Any]) -> int:
    ids = [h.get("id", 0) for h in data.get("habits", [])]
    return max(ids) + 1 if ids else 1


def _calc_streak(logs: list[str], freq: str) -> int:
    today = datetime.now(UTC)
    streak = 0
    if freq == "daily":
        check = today
        while True:
            if check.strftime("%Y-%m-%d") in logs:
                streak += 1
                check -= timedelta(days=1)
            else:
                break
    elif freq == "weekly":
        check = today - timedelta(days=today.weekday())
        for _ in range(52):
            if check.strftime("%Y-W%W") in logs:
                streak += 1
                check -= timedelta(days=7)
            else:
                break
    return streak


async def _habit_add(args: dict[str, Any], ctx: ToolContext | None) -> str:
    name = args.get("name", "").strip()
    if not name:
        return "ERROR: 'name' is required."
    frequency = args.get("frequency", "daily").strip().lower()
    if frequency not in ("daily", "weekly"):
        return "ERROR: 'frequency' must be 'daily' or 'weekly'."
    category = args.get("category", "").strip()

    data = _data()
    hid = _next_id(data)
    data["habits"].append({
        "id": hid,
        "name": name,
        "frequency": frequency,
        "category": category or None,
        "created": datetime.now(UTC).strftime("%Y-%m-%d"),
        "logs": [],
    })
    _save(data)
    return f"Habit added: {name} ({frequency}, #{hid})"


async def _habit_log(args: dict[str, Any], ctx: ToolContext | None) -> str:
    habit_id = args.get("id")
    if not habit_id:
        return "ERROR: 'id' is required. Use habit_list to find IDs."

    data = _data()
    for h in data["habits"]:
        if h["id"] == habit_id:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            if h["frequency"] == "weekly":
                today = (datetime.now(UTC) - timedelta(days=datetime.now(UTC).weekday())).strftime("%Y-W%W")
            if today in h["logs"]:
                return f"Habit '{h['name']}' already logged today."
            h["logs"].append(today)
            _save(data)
            streak = _calc_streak(h["logs"], h["frequency"])
            return f"Logged '{h['name']}' for {today}. Streak: {streak}"
    return f"ERROR: Habit #{habit_id} not found."


async def _habit_unlog(args: dict[str, Any], ctx: ToolContext | None) -> str:
    habit_id = args.get("id")
    if not habit_id:
        return "ERROR: 'id' is required."

    data = _data()
    for h in data["habits"]:
        if h["id"] == habit_id:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            if h["frequency"] == "weekly":
                today = (datetime.now(UTC) - timedelta(days=datetime.now(UTC).weekday())).strftime("%Y-W%W")
            if today in h["logs"]:
                h["logs"].remove(today)
                _save(data)
                return f"Unlogged '{h['name']}' for {today}."
            return f"No log found for today on '{h['name']}'."
    return f"ERROR: Habit #{habit_id} not found."


async def _habit_list(args: dict[str, Any], ctx: ToolContext | None) -> str:
    category = args.get("category", "").strip().lower()
    data = _data()
    habits = data.get("habits", [])
    if category:
        habits = [h for h in habits if (h.get("category") or "").lower() == category]

    if not habits:
        return "No habits found." + (f" in category '{category}'" if category else "")

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [f"Habits ({len(habits)}):", ""]
    for h in habits:
        logged_today = today in h["logs"]
        streak = _calc_streak(h["logs"], h["frequency"])
        cat = f" [{h['category']}]" if h.get("category") else ""
        status = "✓" if logged_today else "○"
        lines.append(f"  #{h['id']} {status} {h['name']} ({h['frequency']}){cat} — streak: {streak}")
    return "\n".join(lines)


async def _habit_stats(args: dict[str, Any], ctx: ToolContext | None) -> str:
    data = _data()
    habits = data.get("habits", [])
    if not habits:
        return "No habits yet. Add one with habit_add."

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    week_ago = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    lines = ["Habit Stats", "=" * 30, ""]
    for h in habits:
        logs = h["logs"]
        week_count = sum(1 for log in logs if log >= week_ago)
        month_count = sum(1 for log in logs if log >= month_ago)
        logged_today = today in logs
        streak = _calc_streak(logs, h["frequency"])
        status = "✓ today" if logged_today else "○ today"
        lines.append(f"  #{h['id']} {h['name']} — {status}")
        lines.append(f"       streak: {streak} | week: {week_count} | month: {month_count}")
        lines.append("")
    return "\n".join(lines)


async def _habit_remove(args: dict[str, Any], ctx: ToolContext | None) -> str:
    habit_id = args.get("id")
    if not habit_id:
        return "ERROR: 'id' is required."

    data = _data()
    for i, h in enumerate(data["habits"]):
        if h["id"] == habit_id:
            name = h["name"]
            data["habits"].pop(i)
            _save(data)
            return f"Removed habit: {name} (#{habit_id})"
    return f"ERROR: Habit #{habit_id} not found."


def _make_handler(fn, name: str, description: str, parameters: dict) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={"name": name, "description": description, "parameters": parameters},
        ),
        execute=fn,
    )


def create_habit_tools() -> list[ToolHandler]:
    return [
        _make_handler(
            _habit_add,
            "habit_add",
            "Add a new habit to track. Set frequency: daily or weekly.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Habit name (e.g., 'Read 30min')"},
                    "frequency": {"type": "string", "description": "'daily' (default) or 'weekly'"},
                    "category": {"type": "string", "description": "Optional category (e.g., 'health', 'learning')"},
                },
                "required": ["name"],
            },
        ),
        _make_handler(
            _habit_log,
            "habit_log",
            "Mark a habit as completed for today/this week. Use habit_list to find the ID.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "number", "description": "Habit ID from habit_list"},
                },
                "required": ["id"],
            },
        ),
        _make_handler(
            _habit_unlog,
            "habit_unlog",
            "Remove today's completion from a habit.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "number", "description": "Habit ID"},
                },
                "required": ["id"],
            },
        ),
        _make_handler(
            _habit_list,
            "habit_list",
            "List all habits with today's status and current streaks.",
            {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Optional filter by category"},
                },
            },
        ),
        _make_handler(
            _habit_stats,
            "habit_stats",
            "View habit completion stats: streaks, weekly and monthly counts.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _habit_remove,
            "habit_remove",
            "Remove a habit and all its history. Use habit_list to find the ID.",
            {
                "type": "object",
                "properties": {
                    "id": {"type": "number", "description": "Habit ID to remove"},
                },
                "required": ["id"],
            },
        ),
    ]
