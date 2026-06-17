"""Monitor tool — create recurring checks that notify when conditions are met."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.agents.tasks.scheduler import add_task
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


def create_create_monitor_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "create_monitor",
                "description": (
                    "Create a recurring monitor that checks a condition periodically "
                    "and notifies you when it's met. "
                    "Example: 'Check if Apple stock is below $200 every 6 hours'"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "Human-readable name for this monitor"},
                        "check_prompt": {
                            "type": "string",
                            "description": (
                                "The prompt/question to check each time. Be specific about what to look for."
                            ),
                        },
                        "interval_minutes": {
                            "type": "number",
                            "description": "How often to check (in minutes). Minimum: 15.",
                        },
                    },
                    "required": ["description", "check_prompt", "interval_minutes"],
                },
            },
        ),
        execute=lambda args, ctx: _do_create_monitor(agent_id, args, ctx),
    )


async def _do_create_monitor(agent_id: str, args: dict, ctx: ToolContext | None) -> str:
    interval = max(int(args.get("interval_minutes", 60)), 15)
    next_run = (datetime.now(UTC) + timedelta(minutes=interval)).isoformat()

    task = add_task(
        agent_id,
        {
            "description": args["description"],
            "type": "monitor",
            "interval_ms": interval * 60_000,
            "next_run": next_run,
            "dispatch_to": agent_id,
            "query": args["check_prompt"],
            "chat_id": ctx.chat_id if ctx else None,
        },
    )
    return (
        f'✓ Monitor created: "{args["description"]}"\n'
        f"  Check prompt: {args['check_prompt']}\n"
        f"  Interval: {interval} minutes\n"
        f"  First check at: {next_run[:19]}\n"
        f"  Task ID: {task.id}\n"
        f"  You will be notified when the condition is met."
    )


def create_list_monitors_tool(agent_id: str) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "list_monitors",
                "description": "List all active monitors.",
                "parameters": {"type": "object", "properties": {}},
            },
        ),
        execute=lambda args, ctx: _do_list_monitors(agent_id),
    )


async def _do_list_monitors(agent_id: str) -> str:
    from src.agents.tasks.scheduler import list_tasks

    tasks = list_tasks(agent_id)
    monitors = [t for t in tasks if t.type == "monitor"]
    if not monitors:
        return "No active monitors."
    lines = ["Active monitors:"]
    for m in monitors:
        next_str = m.next_run[:19] if m.next_run else "?"
        lines.append(f"  • {m.description} — next check: {next_str} — `{m.id}`")
    return "\n".join(lines)
