# K.I.N.E.T.I.C. v2 — Python Setup Guide

## Prerequisites

- **Python 3.12+** (tested on 3.14)
- **pip** (Python package installer)
- **Git** (optional, for cloning)
- **Ollama** (optional, for local LLM inference at `http://127.0.0.1:11434`)

---

## 1. Install Dependencies

From the `python-code/` directory:

```bash
# Install in editable mode with dev extras
pip install -e ".[dev]"

# Or minimal install (no dev tools)
pip install -e .
```

This installs:
- `openai` — LLM provider SDK
- `httpx` — async HTTP client
- `python-telegram-bot` — Telegram integration
- `aiosqlite` — async SQLite for knowledge base
- `numpy` — vector operations (20-50x faster than pure Python)
- `psutil` — cross-platform system info
- `beautifulsoup4` — HTML parsing
- `fastapi` + `uvicorn` — REST API server
- `click` — CLI framework
- `structlog` — structured logging
- `pydantic` — data validation

---

## 2. Configuration

### 2.1 Copy Example Configs

```bash
cp config/models.example.json config/models.json
cp config/agents.example.json config/agents.json
```

### 2.2 Configure Providers

Edit `config/models.json` to add your LLM provider endpoints:

```json
{
  "defaults": {
    "think": {
      "provider": "openrouter",
      "model": "anthropic/claude-3.5-sonnet",
      "fallbacks": [
        { "provider": "groq", "model": "llama-3.1-8b-instant" }
      ]
    }
  },
  "providers": {
    "openrouter": {
      "baseUrl": "https://openrouter.ai/api/v1",
      "apiKeyEnv": "OPENROUTER_API_KEY"
    },
    "groq": {
      "baseUrl": "https://api.groq.com/openai/v1",
      "apiKeyEnv": "GROQ_API_KEY"
    }
  }
}
```

**Supported providers** (any OpenAI-compatible endpoint):
- OpenAI, OpenRouter, Groq, DeepSeek, Together AI
- Ollama (local), vLLM, LiteLLM
- NVIDIA AI, Google AI Studio
- Any custom endpoint with `/chat/completions` and `/embeddings`

### 2.3 Configure Agents

Edit `config/agents.json` to register your agents:

```json
{
  "registry": [
    {
      "id": "main",
      "name": "Main Agent",
      "soulPath": "./main/SOUL.md",
      "provider": "openrouter",
      "can_delegate": true
    }
  ]
}
```

Each agent has a `SOUL.md` file (`config/<agent-id>/SOUL.md`) that defines its personality and behavior directives. Edit these to customize how each agent responds.

### 2.3a Tool Whitelist (per-agent)

You can restrict which tools an agent has access to using the optional `"tools"` field:

```json
{
  "registry": [
    {
      "id": "web-agent",
      "name": "Web Research Agent",
      "soulPath": "./web-agent/SOUL.md",
      "provider": "openrouter",
      "can_delegate": false,
      "tools": ["web_search", "scrape_and_index", "index_url"]
    },
    {
      "id": "full-agent",
      "name": "Full Access Agent",
      "soulPath": "./full-agent/SOUL.md",
      "provider": "openrouter"
    }
  ]
}
```

- If `"tools"` is **omitted or null**: agent gets all 37 tools (existing behavior)
- If `"tools"` is **an empty list `[]`**: agent gets no tools (chat-only agent)
- If `"tools"` lists specific tool names: agent only gets those

**Available tool names:**

| Category | Tools |
|----------|-------|
| **File** | `read_file`, `write_file`, `edit_file`, `delete_file`, `list_files`, `undo_file` |
| **Knowledge** | `query_knowledge_base`, `index_file`, `index_url`, `knowledge_stats` |
| **Web** | `web_search`, `scrape_and_index`, `index_github`, `download_url` |
| **Browser** | `browser_navigate`, `browser_click`, `browser_fill`, `browser_extract`, `browser_screenshot`, `browser_html`, `browser_close` |
| **Email** | `read_emails`, `read_email_body`, `send_email`, `reply_to_email` |
| **Code** | `execute_command`, `run_code` |
| **System** | `get_system_info`, `read_env_var`, `get_current_time` |
| **Schedule** | `schedule_task`, `create_monitor`, `list_monitors` |
| **Communication** | `send_message`, `send_file`, `generate_image` |
| **Pipeline** | `run_pipeline` |

### 2.4 Environment Variables

Create a `.env` file in the `python-code/` directory:

```bash
# Required for Telegram bot
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather

# Optional: restrict access to specific Telegram user IDs
# TELEGRAM_ALLOWLIST=123456789,987654321

# API keys (set at least one)
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=...
GROQ_API_KEY=gsk_...
DEEPSEEK_API_KEY=sk-...

# Required for web search tool
BRAVE_API_KEY=...

# Optional overrides
AGENT_TARGET=main
API_PORT=18789
AGENT_MEMORY_MAX=500
```

Or use the setup wizard:

```bash
kinetic-cli onboard
```

---

## 3. Running

### 3.1 Full System (Bot + API + Scheduler)

```bash
kinetic
```

This starts:
- **Telegram bot** — listens for commands and messages
- **REST API** — Web UI at `http://localhost:18789`
- **Scheduler** — background task execution

### 3.2 CLI Only

```bash
kinetic-cli --help

# Setup wizard
kinetic-cli onboard

# Configure models
kinetic-cli models

# Manage agents
kinetic-cli agents

# Manage knowledge base
kinetic-cli knowledge

# Manage pipelines
kinetic-cli pipelines
```

### 3.3 Skill Management

The skill system lets you install focused sub-agents from a community repository:

```bash
# List installed skills
kinetic-cli skills list

# Install a skill (downloads + activates in agents.json)
kinetic-cli skills install web-research
kinetic-cli skills install file-organizer
kinetic-cli skills install email-assistant
kinetic-cli skills install code-runner
kinetic-cli skills install scheduler

# Install without auto-activating
kinetic-cli skills install web-research --no-activate

# Show skill details
kinetic-cli skills info web-research

# Remove a skill
kinetic-cli skills remove web-research
```

You can also install from **any GitHub repo** using `--url`:

```bash
# Install from a GitHub repo (expects <repo>/<name>/skill.json)
kinetic-cli skills install my-agent --url https://github.com/some-user/awesome-skills

# Install from a direct raw URL
kinetic-cli skills install custom --url https://raw.githubusercontent.com/user/repo/main/skills/my-folder
```

When you install a skill:
1. It downloads the `skill.json` manifest + `SOUL.md` to `config/skills/<name>/`
2. It adds an entry to `config/agents.json` registry (unless `--no-activate`)
3. The entry includes the `"tools"` whitelist from the skill manifest

**How skills work:** A skill is a sub-agent with its own system prompt (SOUL.md) and a restricted tool set. The `main` agent delegates to skill agents via the `spawn_specialist` tool. Skills are defined locally at `config/skills/<id>/` and fetched remotely from `github.com/kinetic-skills/skills` (configurable via `KINETIC_SKILLS_REPO` env var) or any URL via `--url`.

**Starter skills shipped with the project:**

| Skill | Tools | Purpose |
|-------|-------|---------|
| web-research | `web_search`, `scrape_and_index`, `index_url`, `query_knowledge_base`, `knowledge_stats` | Search the web, scrape pages, index results |
| file-organizer | `read_file`, `write_file`, `edit_file`, `delete_file`, `list_files`, `undo_file`, `download_url` | Read, write, organize files in sandbox |
| email-assistant | `read_emails`, `read_email_body`, `send_email`, `reply_to_email` | Read, send, reply to emails |
| code-runner | `execute_command`, `run_code` | Run Python code and shell commands |
| scheduler | `schedule_task`, `get_current_time`, `create_monitor`, `list_monitors` | Reminders, recurring tasks, monitors |

### 3.4 Direct Python

```bash
python -m src.main
python -m src.cli --help
```

---

## 4. Telegram Bot Commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/models` | Show current stage config |
| `/models set think <provider> [model]` | Switch provider at runtime |
| `/models reset think` | Reset to config default |
| `/providers` | List available provider endpoints |
| `/status` | Bot uptime, active agents |
| `/profile` | Show what I know about you |
| `/reset` | Clear current conversation history |
| `/session` | Show current session |
| `/session new <name>` | Start a new conversation session |
| `/session list` | List all sessions |
| `/task list` | Show scheduled tasks |
| `/task remove <id>` | Remove a scheduled task |
| `/knowledge` | Show knowledge base stats |
| `/knowledge list` | List indexed documents |
| `/knowledge remove <id>` | Remove a document |

---

## 5. API Server

The REST API runs at `http://localhost:18789` by default.

### Key Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send message to agent |
| `GET` | `/api/status` | System status |
| `GET` | `/api/sessions` | List sessions |
| `POST` | `/api/sessions` | Create/switch session |
| `GET` | `/api/knowledge` | KB stats + documents |
| `POST` | `/api/knowledge/inject` | Index text/URL/file |
| `POST` | `/api/knowledge/search` | Semantic search |
| `DELETE` | `/api/knowledge/{id}` | Remove document |
| `GET/POST/PUT/DELETE` | `/api/pipelines` | Pipeline CRUD |
| `POST` | `/api/pipelines/execute` | Execute pipeline |
| `GET/PUT` | `/api/config/models` | Read/write models.json |
| `GET/PUT` | `/api/config/agents` | Read/write agents.json |

OpenAPI docs available at `http://localhost:18789/docs`.

---

## 6. Development

### Running Tests

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src

# Specific test file
pytest tests/test_memory.py -v
```

### Code Quality

```bash
# Lint
ruff check src/

# Type check
mypy src/

# Format
ruff format src/
```

---

## 7. Architecture Overview

```
User Input (Telegram / Web UI / CLI)
        │
        ▼
  KinetiCDispatcher.dispatch()
        │
        ▼
  AgentInstance.process()
        │
        ├── Classify intent (multi mode)
        ├── Think loop (up to 5 iterations)
        │       └── LLM call → Tool execution → repeat
        ├── Polish response (multi mode)
        └── Background tasks (profile, compression)
```

**Data flow:** User → Dispatcher → Agent → LLM Provider (with failover) → Tools → Memory → Response

**Tool categories (37 tools):**
- **File ops:** read, write, edit, delete, undo, list
- **Knowledge:** query, index file, index URL, stats
- **System:** execute command, system info, download, env vars
- **Web:** web search (Brave), GitHub index, web scraper
- **Delegation:** send message, spawn specialist, run pipeline
- **Scheduling:** schedule task, get current time
