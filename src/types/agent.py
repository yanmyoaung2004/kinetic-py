from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentCard:
    id: str
    system_prompt: str
    provider: str
    model: str
    type: str = "library"  # "library" | "ephemeral"
    parent_id: str | None = None
    api_key: str = ""
    can_delegate: bool = False
    soul_path: str | None = None
    tools: list[str] | None = None  # None = all tools, [] = no tools, [...] = only these
    # Thin specialist flags
    soul_trimmed: bool = False       # use minimal one-liner instead of full SOUL.md
    skip_recall: bool = False        # skip vector store query for memories
    skip_auto_learn: bool = False    # skip skill extraction from tool sequences
    ephemeral: bool = False          # keep memory in-memory, no disk I/O
    max_iterations: int = 3          # cap think loop iterations (3 = existing default)


class IAgent(Protocol):
    id: str
    config: AgentCard

    async def process(self, message: str, current_depth: int = 0, chat_id: int | None = None,
                      on_token: Callable[[str], None] | None = None,
                      on_status: Callable[[str], None] | None = None) -> str: ...

    async def execute_tool_directly(self, tool_name: str, tool_args: dict) -> str: ...

    def dispose(self) -> None: ...


@dataclass
class ToolDefinition:
    type: str = "function"
    function: dict[str, Any] = field(
        default_factory=lambda: {
            "name": "",
            "description": "",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "function": self.function}
