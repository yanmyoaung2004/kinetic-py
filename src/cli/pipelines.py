from __future__ import annotations

import json
import logging
from pathlib import Path

import click

logger = logging.getLogger("kinetic.cli.pipelines")


@click.group()
def pipelines() -> None:
    """Create, edit, execute, and delete pipelines."""
    pass


@pipelines.command()
def list_cmd() -> None:
    """List all pipelines"""
    from src.agents.tasks.pipeline import list_pipelines

    all_pipelines = list_pipelines()
    if not all_pipelines:
        click.echo("  No pipelines defined.")
        return
    for p in all_pipelines:
        click.echo(f"  • {p.name} ({len(p.steps)} steps) — {p.description or 'no description'} ({p.id})")


@pipelines.command()
@click.option("--name", prompt=True, help="Pipeline name")
@click.option("--description", default="", help="Description")
@click.option("--steps", help="JSON array of steps (or use interactive)")
def create(name: str, description: str, steps: str | None) -> None:
    """Create a new pipeline"""
    from src.agents.tasks.pipeline import save_pipeline

    if steps:
        steps_list = json.loads(steps)
    else:
        steps_list = []
        click.echo("  Define pipeline steps:")
        while True:
            click.echo(f"\n  Step {len(steps_list) + 1}:")
            agent = click.prompt("    Agent ID").strip()
            prompt = click.prompt("    Prompt (use {{variables}})").strip()
            output_var = click.prompt("    Output variable name").strip()
            steps_list.append({"id": f"step_{len(steps_list)}", "agent": agent, "prompt": prompt, "output_var": output_var})
            if not click.confirm("    Add another step?", default=True):
                break

    pipeline = save_pipeline({"name": name, "description": description, "steps": steps_list})
    click.echo(f"  ✓ Created pipeline: {pipeline.name} ({pipeline.id})")


@pipelines.command()
@click.argument("pipeline_id")
def execute(pipeline_id: str) -> None:
    """Execute a pipeline"""
    import asyncio
    from src.agents.tasks.pipeline import execute_pipeline, get_pipeline

    pipeline = get_pipeline(pipeline_id)
    if not pipeline:
        raise click.ClickException(f"Pipeline '{pipeline_id}' not found.")

    # Collect variables
    from re import findall
    var_names = set()
    for step in pipeline.steps:
        for m in findall(r"\{\{(\w+)\}\}", step.prompt):
            var_names.add(m)

    variables: dict[str, str] = {}
    for v in var_names:
        variables[v] = click.prompt(f"  Value for {{{{${v}}}}}", default="")

    async def _dispatch(agent_id: str, msg: str) -> str:
        from src.agents.orchestrator import KinetiCDispatcher
        from src.config.loader import load_model_config

        config, endpoints, _ = load_model_config()
        disp = KinetiCDispatcher(config, endpoints)
        disp.register_agent(type("", (), {"id": agent_id,
            "config": type("", (), {"id": agent_id, "system_prompt": "You are a helpful K.I.N.E.T.I.C. agent.",
                "provider": config.defaults.get("think", type("", (), {"provider": ""})()).provider if config.defaults else "",
                "model": config.defaults.get("think", type("", (), {"model": ""})()).model if config.defaults else "",
                "type": "library", "api_key": "", "can_delegate": False})})(),
        )
        return await disp.dispatch(agent_id, msg, 0)

    click.echo(f"\n  Executing: {pipeline.name}")
    outputs = asyncio.run(execute_pipeline(pipeline, variables, _dispatch))
    click.echo("\n  Outputs:")
    for key, val in outputs.items():
        click.echo(f"    {key}: {val[:200]}{'...' if len(val) > 200 else ''}")


@pipelines.command()
@click.argument("pipeline_id")
def delete(pipeline_id: str) -> None:
    """Delete a pipeline"""
    from src.agents.tasks.pipeline import delete_pipeline

    ok = delete_pipeline(pipeline_id)
    click.echo(f"  {'✓ Deleted' if ok else '✗ Not found'}: {pipeline_id}")
