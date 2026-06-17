"""Code execution tool — run Python in a Docker container, falls back to subprocess."""

from __future__ import annotations

from typing import Any

from src.agents.tools.docker_sandbox import run_in_docker
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


async def _run_code(args: dict[str, Any], ctx: ToolContext | None) -> str:
    code = args.get("code", "")
    language = args.get("language", "python").lower()
    if not code:
        return "ERROR: 'code' parameter is required."

    if language not in ("python", "py", "python3"):
        return f"ERROR: Unsupported language '{language}'. Only 'python' is supported."

    return await run_in_docker(code)


def create_run_code_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "run_code",
                "description": (
                    "Execute Python code inside a Docker container with resource limits. "
                    "Use for calculations, data analysis, automation scripts. "
                    "Falls back to subprocess if Docker is not available. "
                    "Configurable via KINETIC_SANDBOX_IMAGE, KINETIC_SANDBOX_MEMORY, KINETIC_SANDBOX_CPU env vars."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                        "language": {"type": "string", "description": "Language (only 'python' supported)"},
                    },
                    "required": ["code"],
                },
            },
        ),
        execute=_run_code,
    )
