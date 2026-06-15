from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.agents.tasks.scheduler import add_task
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


def _parse_time_to_delay(time_str: str) -> int | None:
    now = datetime.now(timezone.utc)
    lower = time_str.lower().strip()

    # ISO format
    try:
        parsed = datetime.fromisoformat(lower)
        return int((parsed - now).total_seconds() * 1000)
    except (ValueError, TypeError):
        pass

    # "HH:MM AM/PM" or "HH:MM" (24h)
    m12 = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)$", lower)
    m24 = re.match(r"^(\d{1,2}):(\d{2})$", lower)

    hours: int
    minutes: int

    if m12:
        hours = int(m12.group(1))
        minutes = int(m12.group(2))
        is_pm = m12.group(3) == "pm"
        if is_pm and hours != 12:
            hours += 12
        if not is_pm and hours == 12:
            hours = 0
    elif m24:
        hours = int(m24.group(1))
        minutes = int(m24.group(2))
    else:
        return None

    target = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    return int((target - now).total_seconds() * 1000)


def create_schedule_task_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "schedule_task",
                "description": "Schedule a task or reminder to run at a specific time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Task description / reminder message"},
                        "time": {"type": "string", "description": "Time to run: '12:31 AM', '14:30', or ISO date"},
                        "delay_minutes": {"type": "number", "description": "Delay in minutes from now (alternative to 'time')"},
                        "interval_minutes": {"type": "number", "description": "Recurring interval in minutes"},
                    },
                    "required": ["description"],
                },
            },
        ),
        execute=lambda args, ctx: _do_schedule(agent_id, args, ctx),
    )


async def _do_schedule(agent_id: str, args: dict, ctx: ToolContext | None) -> str:
    if args.get("time"):
        delay_ms = _parse_time_to_delay(args["time"])
        if delay_ms is None:
            return f"Could not understand time '{args['time']}'. Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if delay_ms < 0:
            return f"Time '{args['time']}' has already passed."
    else:
        delay_ms = (args.get("delay_minutes", 0) or 0) * 60_000

    interval_ms = args.get("interval_minutes") * 60_000 if args.get("interval_minutes") else None
    next_run = (datetime.now(timezone.utc) + timedelta(milliseconds=delay_ms)).isoformat()

    task = add_task(agent_id, {
        "description": args["description"],
        "type": "interval" if interval_ms else "once",
        "interval_ms": interval_ms,
        "next_run": next_run,
        "dispatch_to": agent_id,
        "query": args["description"],
        "chat_id": ctx.chat_id if ctx else None,
    })

    time_info = f"at {args['time']}" if args.get("time") else f"in {args.get('delay_minutes', 0)}m"
    recurring = f" (recurring every {args['interval_minutes']}m)" if interval_ms else ""
    return f'✓ Scheduled: "{args["description"]}" {time_info}{recurring}. Task ID: {task.id}'


def create_get_time_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_current_time",
                "description": "Get the current date and time.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        ),
        execute=lambda args, ctx: _get_time(),
    )


async def _get_time() -> str:
    now = datetime.now()
    return f"Current time: {now.strftime('%c')} ({now.isoformat()})"
