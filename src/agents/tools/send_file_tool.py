"""Send file tool — lets the agent send files to the user via Telegram."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

# Pending files for each chat_id — populated by the tool, consumed by main.py
_pending: dict[int, list[dict[str, Any]]] = {}


def get_pending_files(chat_id: int) -> list[dict[str, Any]]:
    return _pending.pop(chat_id, [])


async def _send_file(args: dict[str, Any], ctx: ToolContext | None) -> str:
    path_str = args.get("path", "").strip()
    if not path_str:
        return "ERROR: 'path' parameter is required."

    file_path = Path(path_str)
    if not file_path.exists():
        return f"ERROR: File not found: {path_str}"

    if not file_path.is_file():
        return f"ERROR: Not a file: {path_str}"

    chat_id = ctx.chat_id if ctx else 0
    if not chat_id:
        return "ERROR: No chat_id available to send file."

    content = file_path.read_bytes()
    _pending.setdefault(chat_id, []).append({
        "filename": file_path.name,
        "content": content,
    })

    return f"File '{file_path.name}' will be sent to you."


def create_send_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "send_file",
                "description": "Send a file from the sandbox to the user via Telegram. Call this after creating a file with write_file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file in the sandbox (e.g., 'agent_sandbox/output.txt')"},
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_send_file,
    )
