from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    timestamp: str = ""  # ISO format, auto-set on creation

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChatMessage:
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            name=d.get("name"),
            tool_call_id=d.get("tool_call_id"),
            tool_calls=d.get("tool_calls"),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    role: str = "assistant"


class LLMProvider(Protocol):
    model: str

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse: ...

    async def generate_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...
