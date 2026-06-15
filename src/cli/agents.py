from __future__ import annotations

import json
import logging
from pathlib import Path

import click

logger = logging.getLogger("kinetic.cli.agents")

AGENTS_PATH = Path("config/agents.json")
CONFIG_DIR = Path("config")

SOUL_TEMPLATE = """# SOUL.md — Who You Are

You are a specialized K.I.N.E.T.I.C. agent. Your core identity is defined here.

## Core Directives
- Be helpful, precise, and technically accurate
- Stay in character as your assigned role
- Use Markdown for structured responses
- Never state "As an AI language model"

## Boundaries
- Keep private information confidential
- Ask before taking external actions
- Be concise when possible, thorough when needed
"""


def _read_agents() -> dict:
    if not AGENTS_PATH.exists():
        return {"settings": {"defaults": {"type": "library", "provider": "", "can_delegate": True}}, "registry": []}
    return json.loads(AGENTS_PATH.read_text("utf-8"))


def _write_agents(config: dict) -> None:
    AGENTS_PATH.write_text(json.dumps(config, indent=2))


def _read_providers() -> list[str]:
    models_path = Path("config/models.json")
    try:
        if models_path.exists():
            return list(json.loads(models_path.read_text("utf-8")).get("providers", {}).keys())
    except Exception:
        pass
    return []


@click.group()
def agents() -> None:
    """Create, edit, delete agents and their SOUL files."""
    pass


def _display(config: dict) -> None:
    registry = config.get("registry", [])
    if not registry:
        click.echo("  ⚠ No agents registered.")
        return
    click.echo("\n  ── Registered agents ──")
    for i, a in enumerate(registry):
        name = a.get("name", "")
        click.echo(f"  [{i + 1}] {a['id']:<20} {name:<28} provider: {a.get('provider', '(default)')}")


@agents.command()
def list_cmd() -> None:
    """List registered agents"""
    _display(_read_agents())


@agents.command()
@click.argument("agent_id")
@click.option("--name", help="Display name")
@click.option("--provider", help="Provider name")
@click.option("--model", help="Model name")
@click.option("--delegate/--no-delegate", default=None, help="Allow sub-agent delegation")
@click.option("--soul-path", help="Path to SOUL.md")
def create(agent_id: str, name: str | None, provider: str | None, model: str | None, delegate: bool | None, soul_path: str | None) -> None:
    """Create a new agent"""
    config = _read_agents()
    if any(a["id"] == agent_id for a in config.get("registry", [])):
        raise click.ClickException(f"Agent '{agent_id}' already exists.")

    providers = _read_providers()
    if not provider:
        provider = click.prompt("  Provider", default=providers[0] if providers else "").strip()
    if not name:
        name = click.prompt("  Display name", default=agent_id).strip()
    if delegate is None:
        delegate = click.confirm("  Allow sub-agent delegation?", default=False)
    if not soul_path:
        soul_path = f"./{agent_id}/SOUL.md"
    soul_path = soul_path.strip()

    if click.confirm("  Create default SOUL.md?", default=True):
        abs_path = (CONFIG_DIR / soul_path).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if not abs_path.exists():
            abs_path.write_text(SOUL_TEMPLATE)
            click.echo(f"  ✓ Created {soul_path}")

    entry = {"id": agent_id, "name": name, "soulPath": soul_path, "provider": provider, "can_delegate": delegate}
    if model:
        entry["model"] = model
    config.setdefault("registry", []).append(entry)
    _write_agents(config)
    click.echo(f"  ✓ Agent '{agent_id}' created.")


@agents.command()
@click.argument("agent_id")
def edit(agent_id: str) -> None:
    """Edit an existing agent"""
    config = _read_agents()
    registry = config.get("registry", [])
    idx = next((i for i, a in enumerate(registry) if a["id"] == agent_id), None)
    if idx is None:
        raise click.ClickException(f"Agent '{agent_id}' not found.")

    agent = registry[idx]
    providers = _read_providers()

    agent["name"] = click.prompt("  Name", default=agent.get("name", agent_id)).strip()
    new_provider = click.prompt("  Provider", default=agent.get("provider", "")).strip()
    if new_provider:
        agent["provider"] = new_provider
    new_model = click.prompt("  Model (enter to keep)", default=agent.get("model", "")).strip()
    if new_model:
        agent["model"] = new_model
    elif "model" in agent:
        del agent["model"]

    agent["can_delegate"] = click.confirm("  Allow delegation?", default=agent.get("can_delegate", False))
    new_soul = click.prompt("  SOUL path", default=agent.get("soulPath", "")).strip()
    if new_soul:
        agent["soulPath"] = new_soul

    _write_agents(config)
    click.echo(f"  ✓ Agent '{agent_id}' updated.")


@agents.command()
@click.argument("agent_id")
@click.confirmation_option(prompt="Delete this agent? This cannot be undone.")
def delete(agent_id: str) -> None:
    """Delete an agent"""
    config = _read_agents()
    registry = config.get("registry", [])
    idx = next((i for i, a in enumerate(registry) if a["id"] == agent_id), None)
    if idx is None:
        raise click.ClickException(f"Agent '{agent_id}' not found.")
    config["registry"].pop(idx)
    _write_agents(config)
    click.echo(f"  ✓ Agent '{agent_id}' deleted.")


@agents.command()
@click.argument("agent_id")
def create_soul(agent_id: str) -> None:
    """Create a SOUL.md file for an agent"""
    soul_path = CONFIG_DIR / agent_id / "SOUL.md"
    if soul_path.exists():
        raise click.ClickException(f"{soul_path} already exists.")
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(SOUL_TEMPLATE)
    click.echo(f"  ✓ Created {agent_id}/SOUL.md")
    click.echo("  Register this agent with 'kinetic-cli agents create'")
