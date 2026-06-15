from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools")


@dataclass
class ToolContext:
    depth: int = 0
    chat_id: int | None = None


@dataclass
class ToolHandler:
    definition: ToolDefinition
    execute: Callable[[Any, ToolContext | None], Any] = field(default=lambda args, ctx=None: "")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        name = handler.definition.function["name"]
        self._tools[name] = handler

    def get_definitions(self) -> list[ToolDefinition]:
        return [h.definition for h in self._tools.values()]

    async def execute(self, name: str, args: Any, ctx: ToolContext | None = None) -> str:
        handler = self._tools.get(name)
        if not handler:
            available = ", ".join(self._tools.keys())
            return f"ERROR: Unknown tool '{name}'. Available: {available}"
        try:
            result = await handler.execute(args, ctx)
            return result if isinstance(result, str) else str(result)
        except Exception as err:
            return f"ERROR: Tool '{name}' failed: {err}"

    def has(self, name: str) -> bool:
        return name in self._tools


async def _noop_dispatch(target_id: str, message: str, depth: int = 0) -> str:
    return f"[No dispatcher available] Cannot send to {target_id}: {message[:100]}"


# ── Built-in tool factories ──


def create_send_message_tool(
    dispatch_fn: Callable[[str, str, int], Any] | None = None,
) -> ToolHandler:
    fn = dispatch_fn or _noop_dispatch

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "send_message",
                "description": "Sends a message to another registered agent. Use this to delegate work to a specific agent by ID (e.g., 'main'). The recipient will process the task and return a response.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "The agent ID to send the message to"},
                        "message": {"type": "string", "description": "The task or question for the target agent"},
                    },
                    "required": ["target", "message"],
                },
            },
        ),
        execute=lambda args, ctx: _do_send_message(fn, args, ctx),
    )


async def _do_send_message(
    dispatch_fn: Callable[[str, str, int], Any],
    args: Any,
    ctx: ToolContext | None,
) -> str:
    depth = (ctx.depth if ctx else 0) + 1
    result = await dispatch_fn(args["target"], args["message"], depth)
    return f"Response from {args['target']}:\n{result}"


def create_web_search_tool() -> ToolHandler:
    from src.agents.tools.web_search import web_search

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "web_search",
                "description": "Searches the web using Brave Search. Use this when you need current information, news, or facts that may not be in your training data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                        "count": {"type": "number", "description": "Number of results (1-20, default 5)"},
                    },
                    "required": ["query"],
                },
            },
        ),
        execute=lambda args, ctx: web_search(args["query"], args.get("count", 5)),
    )
