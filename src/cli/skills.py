from __future__ import annotations

import click

from src.skills import discover_skills, install_skill, load_skill, remove_skill


@click.group()
def skills() -> None:
    """Install and manage skill packs."""
    pass


@skills.command("list")
def list_skills() -> None:
    """Show installed skills."""
    found = discover_skills()
    if not found:
        click.echo("No skills installed. Use 'kinetic skill install <name>' to add one.")
        return

    click.echo(f"Installed skills ({len(found)}):")
    for s in found:
        tool_count = len(s.tools)
        click.echo(f"  {s.id:<20} v{s.version:<8} {tool_count} tools  {s.name}")
        if s.description:
            click.echo(f"  {'':20} {s.description}")


@skills.command()
@click.argument("name")
@click.option("--no-activate", is_flag=True, help="Install but don't add to agents.json")
@click.option("--url", default=None, help="Custom URL to a skill directory (e.g., https://github.com/user/repo/tree/main/my-skill)")
def install(name: str, no_activate: bool, url: str | None) -> None:
    """Install a skill from the community repo or a custom URL.

    Examples:

      kinetic skill install web-research

      kinetic skill install my-skill --url https://github.com/user/repo

      kinetic skill install custom-skill --url https://raw.githubusercontent.com/user/repo/main/skills/my-folder
    """
    result = install_skill(name.lower(), activate=not no_activate, url=url)
    click.echo(result)


@skills.command()
@click.argument("name")
def remove(name: str) -> None:
    """Uninstall a skill."""
    ok = remove_skill(name.lower())
    if ok:
        click.echo(f"Removed skill '{name}'.")
    else:
        click.echo(f"Skill '{name}' not found.")


@skills.command()
@click.argument("name")
def info(name: str) -> None:
    """Show skill details."""
    manifest = load_skill(name.lower())
    if not manifest:
        click.echo(f"Skill '{name}' not found.")
        return

    click.echo(f"Name:        {manifest.name}")
    click.echo(f"ID:          {manifest.id}")
    click.echo(f"Version:     {manifest.version}")
    click.echo(f"Description: {manifest.description}")
    click.echo(f"Provider:    {manifest.provider or '(default)'}")
    click.echo(f"Model:       {manifest.model or '(default)'}")
    if manifest.tools:
        click.echo(f"Tools ({len(manifest.tools)}):")
        for t in manifest.tools:
            click.echo(f"  - {t}")
    if manifest.soul:
        click.echo(f"SOUL: {len(manifest.soul)} chars")
