# K.I.N.E.T.I.C. v2 — Python

Autonomous agentic framework with stage-based LLM routing, RAG, multi-agent pipelines, sandboxed tools, persistent memory, and a web dashboard.

## Quick Start

```bash
cd python-code

# Install dependencies
pip install -e ".[dev]"

# Setup
kinetic-cli onboard       # copies example configs, prompts for keys
kinetic-cli models        # configure providers and stage routing

# Run (bot + UI)
kinetic

# Or run components separately:
kinetic-cli knowledge     # Manage knowledge base
kinetic-cli pipelines     # Manage pipelines
kinetic-cli skills        # Manage installable skill packs
```

## Skills (Plugin System)

K.I.N.E.T.I.C. has a skill system — installable sub-agents with focused tool sets:

```bash
# Install from community repo
kinetic-cli skills install web-research
kinetic-cli skills install email-assistant
kinetic-cli skills install code-runner

# Install from any GitHub repo
kinetic-cli skills install my-skill --url https://github.com/user/awesome-skills

# List installed skills
kinetic-cli skills list

# Show skill details
kinetic-cli skills info web-research

# Remove a skill
kinetic-cli skills remove web-research
```

Skills are sub-agents with their own `SOUL.md` (system prompt) and a tool whitelist — each only gets the tools it needs. They auto-register in `config/agents.json` on install. See `docs/setup.md` for details.

## Architecture

See `docs/plan-python.md` for the full migration plan and architecture.

Key improvements over v1 (TypeScript):
- **numpy** for vector operations (20-50x faster)
- **aiosqlite** for async SQLite access
- **FastAPI** for the REST API (auto-docs, OpenAPI)
- **httpx** connection pooling for provider calls
- **psutil** for system info (cross-platform, instant)
- **beautifulsoup4** for HTML stripping (robust)
- **structlog** for structured logging
- **click** for CLI (declarative, less boilerplate)
- **pydantic** for validation (where feasible)
- **pytest** for comprehensive testing

## Dependencies

- Python 3.12+
- See `pyproject.toml` for full list
