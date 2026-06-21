"""Pomodoro timer — focus sessions with break reminders via the scheduler."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.agents.tasks.scheduler import add_task, remove_task
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

DATA_DIR = Path("agents_workspace") / "pomodoro"


def _load() -> dict[str, Any]:
    p = DATA_DIR / "state.json"
    if p.exists():
        return json.loads(p.read_text("utf-8"))
    return {}


def _save(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "state.json").write_text(json.dumps(state, indent=2))


def _load_stats() -> dict[str, Any]:
    p = DATA_DIR / "stats.json"
    if p.exists():
        return json.loads(p.read_text("utf-8"))
    return {"sessions": {}, "total_focus_minutes": 0}


def _save_stats(stats: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "stats.json").write_text(json.dumps(stats, indent=2))


async def _pomodoro_start(args: dict[str, Any], ctx: ToolContext | None) -> str:
    focus_min = max(int(args.get("focus_minutes", 25)), 1)
    break_min = max(int(args.get("break_minutes", 5)), 1)

    state = _load()
    if state and state.get("status") in ("focus", "break"):
        remaining = state["end_time"] - datetime.now(UTC).timestamp()
        if remaining > 0:
            return (
                f"Already in a {state['status']} session "
                f"({int(remaining / 60)}min remaining). "
                "Use pomodoro_stop first."
            )

    now = datetime.now(UTC)
    focus_end = now + timedelta(minutes=focus_min)

    for task_id in list(state.get("task_ids", [])):
        remove_task("main", task_id)

    task_focus = add_task("main", {
        "description": f"Pomodoro focus ({focus_min}min)",
        "type": "once",
        "next_run": focus_end.isoformat(),
        "dispatch_to": "main",
        "query": f"Pomodoro focus session of {focus_min}min just ended. "
                 f"Tell the user focus is done and ask if they want to start the {break_min}min break.",
        "chat_id": ctx.chat_id if ctx else None,
    })

    state = {
        "status": "focus",
        "start_time": now.timestamp(),
        "end_time": focus_end.timestamp(),
        "focus_minutes": focus_min,
        "break_minutes": break_min,
        "task_ids": [task_focus.id],
    }
    _save(state)

    return (
        f"Pomodoro started: {focus_min}min focus.\n"
        f"Started at: {now.strftime('%H:%M')}\n"
        f"Focus ends at: {focus_end.strftime('%H:%M')}\n"
        f"Break will be: {break_min}min\n"
        "I'll notify you when focus is up!"
    )


async def _pomodoro_status(args: dict[str, Any], ctx: ToolContext | None) -> str:
    state = _load()
    if not state or state.get("status") not in ("focus", "break"):
        return "No active pomodoro session."

    now = datetime.now(UTC).timestamp()
    remaining = state["end_time"] - now
    elapsed = now - state["start_time"]

    if remaining <= 0:
        return f"{state['status'].title()} session has ended. Start a new one with pomodoro_start."

    mins_left = int(remaining / 60)
    mins_elapsed = int(elapsed / 60)
    return (
        f"Status: {state['status'].title()}\n"
        f"Elapsed: {mins_elapsed}min\n"
        f"Remaining: {mins_left}min\n"
        f"Ends at: {datetime.fromtimestamp(state['end_time'], UTC).strftime('%H:%M')}"
    )


async def _pomodoro_stats(args: dict[str, Any], ctx: ToolContext | None) -> str:
    stats = _load_stats()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    today_sessions = stats.get("sessions", {}).get(today, 0)

    week_ago = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    week_sessions = sum(
        v for k, v in stats.get("sessions", {}).items() if k >= week_ago
    )

    return (
        f"Pomodoro Stats\n"
        f"{'=' * 30}\n"
        f"Today:     {today_sessions} sessions\n"
        f"This week: {week_sessions} sessions\n"
        f"Total:     {stats.get('total_focus_minutes', 0)} focus minutes"
    )


async def _pomodoro_stop(args: dict[str, Any], ctx: ToolContext | None) -> str:
    state = _load()
    if not state or state.get("status") not in ("focus", "break"):
        return "No active pomodoro session."

    for task_id in list(state.get("task_ids", [])):
        remove_task("main", task_id)

    elapsed = datetime.now(UTC).timestamp() - state["start_time"]
    elapsed_min = int(elapsed / 60)

    # Record stats
    stats = _load_stats()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    stats.setdefault("sessions", {})
    stats["sessions"][today] = stats["sessions"].get(today, 0) + 1
    stats["total_focus_minutes"] = stats.get("total_focus_minutes", 0) + elapsed_min
    _save_stats(stats)

    _save({})
    return f"Pomodoro stopped after {elapsed_min}min. Session recorded."


def _make_handler(fn, name: str, description: str, parameters: dict) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={"name": name, "description": description, "parameters": parameters},
        ),
        execute=fn,
    )


def create_pomodoro_tools() -> list[ToolHandler]:
    return [
        _make_handler(
            _pomodoro_start,
            "pomodoro_start",
            "Start a Pomodoro focus session with a timer. Notifies you when focus ends and break begins.",
            {
                "type": "object",
                "properties": {
                    "focus_minutes": {"type": "number", "description": "Focus duration in minutes", "default": 25},
                    "break_minutes": {"type": "number", "description": "Break duration in minutes", "default": 5},
                },
            },
        ),
        _make_handler(
            _pomodoro_status,
            "pomodoro_status",
            "Check the current Pomodoro session status and remaining time.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _pomodoro_stats,
            "pomodoro_stats",
            "View your Pomodoro history: sessions today, this week, and total focus minutes.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _pomodoro_stop,
            "pomodoro_stop",
            "Stop the current Pomodoro session early and record it.",
            {"type": "object", "properties": {}},
        ),
    ]
