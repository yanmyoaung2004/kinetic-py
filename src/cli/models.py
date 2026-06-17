from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import click
import httpx

logger = logging.getLogger("kinetic.cli.models")

MODELS_PATH = Path("config/models.json")

STAGE_LABELS = {
    "think": "think     (main reasoning, tool calls)",
    "classify": "classify  (legacy — not used)",
    "tool_call": "tool_call (legacy — not used)",
    "answer": "answer    (legacy — not used)",
}


def _read_config() -> dict:
    if not MODELS_PATH.exists():
        raise click.ClickException("models.json not found. Run 'kinetic-cli onboard' first.")
    return json.loads(MODELS_PATH.read_text("utf-8"))


def _write_config(config: dict) -> None:
    MODELS_PATH.write_text(json.dumps(config, indent=2))
    click.echo("  ✓ Saved to models.json")


@click.group()
def models() -> None:
    """Configure provider endpoints and stage routing."""
    pass


@models.command()
def show() -> None:
    """Show current configuration"""
    config = _read_config()
    click.echo("\n  Providers:")
    for name, ep in config.get("providers", {}).items():
        key_env = ep.get("apiKeyEnv", "")
        key_set = "✓ key set" if os.environ.get(key_env) else "⚠ no key"
        click.echo(f"    {name:<14} {ep.get('baseUrl', ''):<42} {key_set}")

    click.echo("\n  Stages:")
    for stage, sc in config.get("defaults", {}).items():
        label = STAGE_LABELS.get(stage, stage)
        fallbacks = sc.get("fallbacks", [])
        fb_info = f" | fallback: {', '.join(f['provider'] for f in fallbacks)}" if fallbacks else ""
        click.echo(f"    {label}  {sc.get('provider', '?')}/{sc.get('model', '?')}{fb_info}")


@models.command()
@click.argument("stage")
@click.option("--provider", "-p", help="Provider name")
@click.option("--model", "-m", help="Model name")
def edit(stage: str, provider: str | None, model: str | None) -> None:
    """Edit a stage (think, classify, tool_call, answer)"""
    config = _read_config()
    defaults = config.get("defaults", {})
    if stage not in defaults:
        raise click.ClickException(f"Unknown stage '{stage}'. Available: {', '.join(defaults.keys())}")

    sc = defaults[stage]
    providers = list(config.get("providers", {}).keys())

    if not provider:
        provider = click.prompt(f"  Provider [{sc.get('provider', '')}]", default="").strip() or sc.get("provider", "")
    if provider and provider not in providers:
        click.echo(f"  ⚠ '{provider}' not in models.json. Add it first.")
        return

    if not model:
        model = click.prompt(f"  Model [{sc.get('model', '')}]", default="").strip() or sc.get("model", "")

    sc["provider"] = provider
    sc["model"] = model

    # Fallbacks
    if click.confirm("  Add fallback provider?", default=False):
        fallbacks = sc.get("fallbacks", [])
        fb_provider = click.prompt("    Fallback provider").strip()
        if fb_provider in providers:
            fb_model = click.prompt("    Fallback model").strip()
            fallbacks.append({"provider": fb_provider, "model": fb_model})
            sc["fallbacks"] = fallbacks
            click.echo(f"    ✓ Fallback added: {fb_provider}/{fb_model}")

    _write_config(config)
    click.echo(f"  ✓ {stage} → {provider}/{model}")


@models.command()
@click.argument("name")
@click.option("--base-url", "-u", help="Base URL")
@click.option("--api-key-env", "-e", help="Env var name for API key")
def add_provider(name: str, base_url: str | None, api_key_env: str | None) -> None:
    """Add a provider endpoint"""
    config = _read_config()
    if name in config.get("providers", {}):
        raise click.ClickException(f"Provider '{name}' already exists.")

    if not base_url:
        base_url = click.prompt("  Base URL").strip()
    if not api_key_env:
        default_env = f"{name.upper()}_API_KEY"
        api_key_env = click.prompt("  Env var name", default=default_env).strip()

    config.setdefault("providers", {})[name] = {"baseUrl": base_url, "apiKeyEnv": api_key_env}
    _write_config(config)
    click.echo(f"  ✓ Added '{name}' → {base_url}")


@models.command()
@click.argument("name")
def remove_provider(name: str) -> None:
    """Remove a provider endpoint"""
    config = _read_config()
    if name not in config.get("providers", {}):
        raise click.ClickException(f"Provider '{name}' not found.")

    # Check usage
    for stage, sc in config.get("defaults", {}).items():
        if sc.get("provider") == name or any(f.get("provider") == name for f in sc.get("fallbacks", [])):
            raise click.ClickException(f"In use by stage '{stage}'. Reassign first.")

    del config["providers"][name]
    _write_config(config)
    click.echo(f"  ✓ Removed '{name}'.")


@models.command()
def test() -> None:
    """Test connectivity to all providers"""
    config = _read_config()

    async def _test_all():
        async with httpx.AsyncClient(timeout=5.0) as client:
            for name, ep in config.get("providers", {}).items():
                api_key = os.environ.get(ep.get("apiKeyEnv", ""), "")
                if not api_key:
                    click.echo(f"  {name:<14} ⏭ no key")
                    continue
                try:
                    url = ep["baseUrl"].rstrip("/") + "/models"
                    resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                    status = f"✓ {resp.status_code}" if resp.is_success else f"⚠ {resp.status_code}"
                    click.echo(f"  {name:<14} {status}")
                except Exception as e:
                    click.echo(f"  {name:<14} ✗ {e}")

    import asyncio

    asyncio.run(_test_all())
