# K.I.N.E.T.I.C. v2 — Python

## Commands

```bash
pip install -e ".[dev]"        # editable install + dev deps
playwright install chromium     # install headless browser (once)
kinetic                          # run bot + API + scheduler (requires TELEGRAM_BOT_TOKEN)
kinetic-cli models               # configure providers / stage routing
kinetic-cli onboard              # first-time setup wizard
kinetic-cli skills list          # show installed skills
kinetic-cli skills install <n>   # install skill from community repo
kinetic-cli skills remove <n>    # uninstall a skill
kinetic-cli skills info <n>      # show skill manifest details
pytest                          # all tests (asyncio_mode = auto) — 89 tests
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
- **Skills**: `config/skills/<id>/skill.json` (manifest) + `SOUL.md` — installable sub-agent packs with tool whitelists
- **Tool whitelist**: agents can restrict tools via `"tools"` array in `agents.json` — `null` = all tools, `[]` = no tools, `["a","b"]` = only those
- **Workspace**: `agents_workspace/` — created at runtime for memory, knowledge base, task data
- **Knowledge base**: disk-based vector store at `agents_workspace/<agentId>/knowledge/store.json`
- **Memory**: JSONL at `agents_workspace/<agentId>/history.jsonl`, capped at 500 messages
- **API**: FastAPI on port 18789 (env `API_PORT`)
- **Providers**: all OpenAI-compatible; `SDK_COMPATIBLE_DOMAINS` is empty → uses raw HTTP fetch path by default

## Tool set (31 tools)

| Category | Tools |
|----------|-------|
| **File** | read_file, write_file, edit_file, delete_file, list_files, undo_file, download_url |
| **Browser** | browser_navigate, browser_click, browser_fill, browser_extract, browser_screenshot, browser_html, browser_close |
| **Knowledge** | query_knowledge_base, index_file, index_url, knowledge_stats |
| **Email** | read_emails, send_email |
| **Code** | run_code, execute_command |
| **Image** | generate_image |
| **Automation** | schedule_task, get_current_time, create_monitor, list_monitors |
| **System** | get_system_info, read_env_var, web_search |
| **Agent** | spawn_specialist, send_message, run_pipeline |
| **Skills** | kinetic-cli skills list/install/remove/info |
| **Data** | index_github, scrape_and_index |

## Key conventions

- `apiKeyEnv` in models.json references an env var name, never a raw key
- Tests use `MockProvider` (from `tests/conftest.py`) and `unittest.mock.AsyncMock` for HTTP mocking
- `tmp_path` fixture is commonly used for workspace isolation in tests
- No `@pytest.mark.asyncio` needed for most tests (`asyncio_mode = auto`)
- `docs/architecture.md` references `.ts` files (stale from v1) — Python architecture is the same
- Long-term memory: compressed summaries are auto-archived to the vector store with `metadata.type=memory` and recalled before each response
- Browser tools require `playwright install chromium` after pip install
- File upload endpoint uses multipart form data (`python-multipart` dependency)
- Email tools require `EMAIL_IMAP_SERVER`, `EMAIL_SMTP_SERVER`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD` in `.env`
- Image generation requires an `"image"` section in models.json pointing to an OpenAI-compatible image endpoint

## Config structure

```json
{
  "mode": "single|multi",
  "embedding": { "provider": "...", "model": "..." },
  "defaults": { "classify": {...}, "think": {...}, "tool_call": {...}, "answer": {...} },
  "providers": { "name": { "baseUrl": "...", "apiKeyEnv": "ENV_VAR" } }
}
```
