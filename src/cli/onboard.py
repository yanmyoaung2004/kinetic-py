from __future__ import annotations

import json
import logging
from pathlib import Path

import click

CONFIG_DIR = Path("config")
PROJECT_ROOT = Path.cwd()
MODELS_PATH = CONFIG_DIR / "models.json"
AGENTS_PATH = CONFIG_DIR / "agents.json"
ENV_PATH = PROJECT_ROOT / ".env"

logger = logging.getLogger("kinetic.cli.onboard")


@click.command()
@click.pass_context
def onboard(ctx: click.Context) -> None:
    """First-time setup wizard — creates models.json, agents.json, .env"""
    click.echo(click.style("\n╔══════════════════════════════════════════╗", bold=True))
    click.echo(click.style("║     K.I.N.E.T.I.C. — Setup Wizard       ║", bold=True))
    click.echo(click.style("╚══════════════════════════════════════════╝", bold=True))

    # Step 1: Provider endpoints
    click.echo("\n" + click.style("STEP 1: Provider endpoints", fg="cyan"))
    _ensure_config_dir()
    _setup_models()

    # Step 2: Agent config
    click.echo("\n" + click.style("STEP 2: Agent registry", fg="cyan"))
    _setup_agents()

    # Step 3: Environment variables
    click.echo("\n" + click.style("STEP 3: Environment variables (.env)", fg="cyan"))
    providers = _read_providers_from_models()
    _ensure_env(providers)

    if click.confirm("\nSet up Telegram bot?", default=False):
        _setup_telegram()

    click.echo(click.style("\n✓ Setup complete!", fg="green"))
    click.echo("  Next steps:")
    click.echo("    1. Edit .env to fill in your API keys")
    click.echo("    2. Run:  kinetic-cli models   — to configure stages")
    click.echo("    3. Run:  kinetic               — to launch the bot")


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _setup_models() -> None:
    if MODELS_PATH.exists():
        click.echo(f"  ✓ {MODELS_PATH.name} already exists.")
        if not click.confirm("  Overwrite existing config?", default=False):
            return

    providers: list[dict[str, str]] = []
    click.echo("  Add provider endpoints (leave name empty to finish):")

    while True:
        name = click.prompt("    Provider name", default="").strip()
        if not name:
            break
        base_url = click.prompt("    Base URL", default=f"https://api.{name}.com/v1").strip()
        default_env = f"{name.upper()}_API_KEY"
        env_key = click.prompt("    Env var for API key", default=default_env).strip()
        providers.append({"name": name, "baseUrl": base_url, "apiKeyEnv": env_key})
        click.echo(f"    ✓ Added provider '{name}'")

    if not providers:
        click.echo("  ⚠ No providers configured. Creating placeholder config.")
        MODELS_PATH.write_text(
            json.dumps(
                {
                    "defaults": {
                        "classify": {"provider": "", "model": ""},
                        "think": {"provider": "", "model": ""},
                        "tool_call": {"provider": "", "model": ""},
                        "answer": {"provider": "", "model": ""},
                    },
                    "providers": {},
                },
                indent=2,
            )
        )
        click.echo("  ✓ Created placeholder models.json")
        return

    first = providers[0]["name"]
    default_model = "gemma3:1b" if "ollama" in first.lower() else "gpt-4o-mini"
    provider_entries = {p["name"]: {"baseUrl": p["baseUrl"], "apiKeyEnv": p["apiKeyEnv"]} for p in providers}

    MODELS_PATH.write_text(
        json.dumps(
            {
                "defaults": {
                    "classify": {"provider": first, "model": default_model},
                    "think": {"provider": first, "model": default_model},
                    "tool_call": {"provider": first, "model": default_model},
                    "answer": {"provider": first, "model": default_model},
                },
                "providers": provider_entries,
            },
            indent=2,
        )
    )
    click.echo(f"  ✓ Created models.json with {len(providers)} provider(s).")


def _setup_agents() -> None:
    if AGENTS_PATH.exists():
        click.echo(f"  ✓ {AGENTS_PATH.name} already exists.")
        if not click.confirm("  Overwrite existing config?", default=False):
            return

    agent_id = click.prompt("  Agent ID", default="main").strip()
    if not agent_id:
        agent_id = "main"

    agent_name = click.prompt("  Display name", default=agent_id).strip()
    provider = click.prompt("  Default provider", default="ollama").strip()

    AGENTS_PATH.write_text(
        json.dumps(
            {
                "settings": {"defaults": {"type": "library", "provider": provider, "can_delegate": False}},
                "registry": [
                    {
                        "id": agent_id,
                        "name": agent_name,
                        "soulPath": f"./{agent_id}/SOUL.md",
                        "provider": provider,
                        "can_delegate": False,
                    }
                ],
            },
            indent=2,
        )
    )
    click.echo(f"  ✓ Created agents.json with agent '{agent_id}'.")


def _read_providers_from_models() -> list[str]:
    try:
        if MODELS_PATH.exists():
            data = json.loads(MODELS_PATH.read_text("utf-8"))
            return [p.get("apiKeyEnv", "") for p in data.get("providers", {}).values()]
    except Exception:
        pass
    return []


def _ensure_env(required_vars: list[str]) -> None:
    existing_vars: set[str] = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text("utf-8").splitlines():
            key = line.strip().split("=")[0]
            if key:
                existing_vars.add(key)
        click.echo(f"  ✓ {ENV_PATH.name} already exists.")

    missing = [v for v in required_vars if v not in existing_vars]
    if not missing:
        click.echo("  ✓ All required env vars present.")
        return

    click.echo(f"  ⚠ Missing env vars: {', '.join(missing)}")
    if not click.confirm("  Add them to .env now?", default=True):
        return

    with ENV_PATH.open("a", encoding="utf-8") as f:
        if ENV_PATH.exists() and ENV_PATH.stat().st_size > 0:
            f.write("\n")
        f.write("\n# K.I.N.E.T.I.C. — Added by onboard wizard\n")
        for v in missing:
            if v in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWLIST"):
                val = click.prompt(f"  {v}", default="")
                f.write(f"{v}={val}\n")
            else:
                f.write(f"# {v}=your_api_key_here\n")
    click.echo("  ✓ .env updated.")


def _setup_telegram() -> None:
    content = ENV_PATH.read_text("utf-8") if ENV_PATH.exists() else ""
    if not content.endswith("\n"):
        content += "\n"

    if "TELEGRAM_BOT_TOKEN" not in content:
        token = click.prompt("  TELEGRAM_BOT_TOKEN", default="")
        content += f"\nTELEGRAM_BOT_TOKEN={token}\n"
    if "TELEGRAM_ALLOWLIST" not in content:
        allowlist = click.prompt("  TELEGRAM_ALLOWLIST (comma-separated user IDs, empty = open)", default="")
        content += f"TELEGRAM_ALLOWLIST={allowlist}\n"
    ENV_PATH.write_text(content)
    click.echo("  ✓ Telegram env vars added.")
