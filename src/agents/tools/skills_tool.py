"""Tool to list installed skills."""

from __future__ import annotations

from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.skills import discover_skills
from src.types.agent import ToolDefinition


def create_list_skills_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "list_skills",
                "description": (
                    "List all installed skill packs with their names, descriptions,"
                    " and tool counts. Use this when the user asks what skills are"
                    " available or what you can do."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ),
        execute=_list_skills,
    )


async def _list_skills(args: dict[str, Any], ctx: ToolContext | None) -> str:
    skills = discover_skills()
    if not skills:
        return "No skills are currently installed. Use `kinetic-cli skills install <name>` to add one."

    lines = [f"Installed skills ({len(skills)}):"]
    for s in skills:
        tool_list = ", ".join(s.tools) if s.tools else "(no tools)"
        lines.append("")
        lines.append(f"  {s.name} (v{s.version})")
        if s.description:
            lines.append(f"    {s.description}")
        lines.append(f"    Tools: {tool_list}")
    return "\n".join(lines)
