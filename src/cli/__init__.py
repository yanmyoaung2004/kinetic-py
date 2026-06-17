from __future__ import annotations

import click

from src.cli.agents import agents
from src.cli.knowledge import knowledge
from src.cli.models import models
from src.cli.onboard import onboard
from src.cli.pipelines import pipelines
from src.cli.skills import skills as skills_group


@click.group()
def main() -> None:
    """K.I.N.E.T.I.C. CLI — Manage your agent system"""
    pass


main.add_command(onboard)
main.add_command(models)
main.add_command(agents)
main.add_command(knowledge)
main.add_command(pipelines)
main.add_command(skills_group)

if __name__ == "__main__":
    main()
