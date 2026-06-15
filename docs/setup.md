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

### 3.3 Direct Python

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

**Tool categories (17 total):**
- **File ops:** read, write, edit, delete, undo, list
- **Knowledge:** query, index file, index URL, stats
- **System:** execute command, system info, download, env vars
- **Web:** web search (Brave), GitHub index, web scraper
- **Delegation:** send message, spawn specialist, run pipeline
- **Scheduling:** schedule task, get current time
