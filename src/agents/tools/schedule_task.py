from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from src.agents.tasks.scheduler import add_task
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


def _parse_time_to_delay(time_str: str) -> int | None:
    now = datetime.now(UTC)
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
                        "delay_minutes": {
                            "type": "number",
                            "description": "Delay in minutes from now (alternative to 'time')",
                        },
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
            return (
                f"Could not understand time '{args['time']}'. "
                f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        if delay_ms < 0:
            return f"Time '{args['time']}' has already passed."
    else:
        delay_ms = (args.get("delay_minutes", 0) or 0) * 60_000

    interval_minutes = args.get("interval_minutes") or 0
    interval_ms = interval_minutes * 60_000 if interval_minutes else None
    next_run = (datetime.now(UTC) + timedelta(milliseconds=delay_ms)).isoformat()

    task = add_task(
        agent_id,
        {
            "description": args["description"],
            "type": "interval" if interval_ms else "once",
            "interval_ms": interval_ms,
            "next_run": next_run,
            "dispatch_to": agent_id,
            "query": args["description"],
            "chat_id": ctx.chat_id if ctx else None,
        },
    )

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


def create_list_tasks_tool() -> ToolHandler:
    from src.agents.tasks.scheduler import list_tasks

    async def _list_tasks(args: dict, ctx: ToolContext | None) -> str:
        agent_id = args.get("agent_id", "").strip() or "main"
        tasks = list_tasks(agent_id)
        if not tasks:
            return "No scheduled tasks."
        lines = []
        now = datetime.now()
        for t in tasks:
            due = ""
            if t.next_run:
                try:
                    due_dt = datetime.fromisoformat(t.next_run)
                    due = due_dt.strftime("%a %H:%M")
                    if due_dt.date() == now.date():
                        due = f"Today {due_dt.strftime('%H:%M')}"
                    elif due_dt.date() == (now + timedelta(days=1)).date():
                        due = f"Tomorrow {due_dt.strftime('%H:%M')}"
                except Exception:
                    due = t.next_run[:16]
            type_str = "🔄" if t.interval_ms else "🔔"
            lines.append(f"  {type_str} {t.description} ({due})")
        return "Scheduled tasks:\n" + "\n".join(lines)

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "list_scheduled_tasks",
                "description": "List all scheduled reminders and recurring tasks with their next run time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string", "description": "Agent ID (default: main)"},
                    },
                },
            },
        ),
        execute=_list_tasks,
    )


def create_remove_task_tool() -> ToolHandler:
    from src.agents.tasks.scheduler import list_tasks, remove_task

    async def _remove_task(args: dict, ctx: ToolContext | None) -> str:
        query = args.get("query", "").strip().lower()
        remove_all = args.get("all", False)
        agent_id = args.get("agent_id", "").strip() or "main"

        tasks = list_tasks(agent_id)
        if not tasks:
            return "No scheduled tasks to remove."

        if remove_all:
            count = len(tasks)
            for t in tasks:
                remove_task(agent_id, t.id)
            return f"Removed all {count} scheduled tasks."

        if not query:
            lines = ["Specify a task description or use all=true to clear everything. Tasks:"]
            for t in tasks:
                lines.append(f"  • {t.description} (id: {t.id[:8]}…)")
            return "\n".join(lines)

        # Find matching tasks by description
        to_remove = [t for t in tasks if query in t.description.lower()]
        if not to_remove:
            lines = [f"No tasks matching '{query}'. Tasks:"]
            for t in tasks:
                lines.append(f"  • {t.description} (id: {t.id[:8]}…)")
            return "\n".join(lines)

        for t in to_remove:
            remove_task(agent_id, t.id)
        return f"Removed {len(to_remove)} task(s) matching '{query}'."

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "remove_scheduled_task",
                "description": (
                    "Remove scheduled tasks by keyword or clear all."
                    " Use 'all' to remove everything."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword to match task descriptions (e.g., 'reminder')",
                        },
                        "all": {"type": "boolean", "description": "Set to true to remove ALL scheduled tasks"},
                        "agent_id": {"type": "string", "description": "Agent ID (default: main)"},
                    },
                },
            },
        ),
        execute=_remove_task,
    )
