# K.I.N.E.T.I.C. v2 — Python

## Commands

```bash
pip install -e ".[dev]"        # editable install + dev deps (ruff, mypy, pytest)
kinetic                          # run bot + API + scheduler (requires TELEGRAM_BOT_TOKEN)
kinetic-cli models               # configure providers / stage routing
kinetic-cli onboard              # first-time setup wizard (uses kinetic.cmd wrapper)
pytest                          # all tests (asyncio_mode = auto)
ruff check .                    # lint (line-length 120, select E/F/I/N/W/UP)
mypy src/                       # typecheck (non-strict, ignore_missing_imports)
```

Run focused tests:
```bash
pytest tests/test_dispatcher.py -xvs
pytest tests/test_provider.py::test_fallback_all_fail -xvs
```

## Architecture

- **Entrypoints**: `kinetic` → `src.main:main` (Telegram bot + FastAPI + scheduler in one event loop); `kinetic-cli` → `src.cli:main` (click CLI)
- **Config**: `config/models.json` (providers, stage routing), `config/agents.json` (agent registry). Copy from `.example.json` files.
- **SOUL files**: `config/<agent-id>/SOUL.md` — system prompt per agent
- **Workspace**: `agents_workspace/` — created at runtime for memory, knowledge base, task data
- **Knowledge base**: disk-based vector store at `agents_workspace/<agentId>/knowledge/store.json`
- **Memory**: JSONL at `agents_workspace/<agentId>/history.jsonl`, capped at 500 messages
- **API**: FastAPI on port 18789 (env `API_PORT`)
- **Providers**: all OpenAI-compatible; `SDK_COMPATIBLE_DOMAINS` is empty → uses raw HTTP fetch path by default

## Key conventions

- `apiKeyEnv` in models.json references an env var name, never a raw key
- Tests use `MockProvider` (from `tests/conftest.py`) and `unittest.mock.AsyncMock` for HTTP mocking
- `tmp_path` fixture is commonly used for workspace isolation in tests
- No `@pytest.mark.asyncio` needed for most tests (`asyncio_mode = auto`)
- `docs/architecture.md` references `.ts` files (stale from v1) — Python architecture is the same

## Config structure

```json
{
  "mode": "single|multi",
  "embedding": { "provider": "...", "model": "..." },
  "defaults": { "classify": {...}, "think": {...}, "tool_call": {...}, "answer": {...} },
  "providers": { "name": { "baseUrl": "...", "apiKeyEnv": "ENV_VAR" } }
}
```
