from __future__ import annotations

import asyncio
import logging

import click

logger = logging.getLogger("kinetic.cli.learn")


@click.group()
def learn() -> None:
    """Analyze agent logs and learn from failures — writes corrections to AGENTS.md"""
    pass


@learn.command()
@click.option("--apply", is_flag=True, help="Write learnings to AGENTS.md (default: dry-run)")
@click.option("--workspace", default="agents_workspace", help="Path to agents workspace directory")
@click.option("--target", default="AGENTS.md", help="Target file for learnings")
def scan(apply: bool, workspace: str, target: str) -> None:
    """Scan agent history and extract failure patterns"""
    from src.learn.learner import run_learn

    async def _run():
        result = await run_learn(
            workspace_dir=workspace,
            target_file=target,
            dry_run=not apply,
        )

        if "error" in result:
            click.echo(f"  ✗ {result['error']}")
            return

        if "enabled" in result and not result.get("enabled", True):
            click.echo("  ⚠ HEADROOM_LEARN=1 not set. Set it to enable learning in background mode.")
            click.echo("    Dry-run analysis still works for preview.")

        click.echo(f"  Scanned agents in: {workspace}")
        click.echo(f"  Failures found: {result.get('failures', 0)}")
        click.echo(f"  Patterns extracted: {result.get('patterns', 0)}")

        if "preview" in result:
            click.echo("\n-- Preview ----")
            click.echo(result["preview"])
            click.echo("----------------")
            click.echo("  Run with --apply to write these to AGENTS.md")

        if result.get("written"):
            click.echo(f"  ✓ Written to {result['target']}")

    asyncio.run(_run())


@learn.command()
def stats() -> None:
    """Show learning stats from AGENTS.md"""
    from src.learn.learner import read_learnings

    current = read_learnings("AGENTS.md")
    if current:
        line_count = len(current.splitlines())
        click.echo(f"  Current learnings: {line_count} lines in AGENTS.md")
    else:
        click.echo("  No learnings found in AGENTS.md. Run `kinetic-cli learn scan` first.")
