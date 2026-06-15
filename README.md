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
```

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
