from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.agents.tasks.pipeline import execute_pipeline, get_pipeline
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


def create_run_pipeline_tool(dispatch_fn: Callable[[str, str, int | None], Any]) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "run_pipeline",
                "description": "Execute a predefined multi-agent pipeline. A pipeline is a sequence of steps where each step delegates to a different agent and passes results to the next step.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "string", "description": "The pipeline ID to execute"},
                        "variables": {
                            "type": "object",
                            "description": "Optional input variables for the pipeline",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["pipeline_id"],
                },
            },
        ),
        execute=lambda args, ctx: _run_pipeline(dispatch_fn, args),
    )


async def _run_pipeline(dispatch_fn: Callable, args: dict) -> str:
    pipeline = get_pipeline(args["pipeline_id"])
    if not pipeline:
        return f"Pipeline '{args['pipeline_id']}' not found."

    variables = args.get("variables", {})

    async def _dispatch(agent_id: str, message: str) -> str:
        return await dispatch_fn(agent_id, message, None)

    outputs = await execute_pipeline(pipeline, variables, _dispatch)

    summary = "\n\n".join(f"{key}: {val[:200]}..." for key, val in outputs.items())
    return f"Pipeline '{pipeline.name}' completed.\n\nOutputs:\n{summary}"
