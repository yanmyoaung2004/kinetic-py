# K.I.N.E.T.I.C. Architecture

## Overview

K.I.N.E.T.I.C. is an autonomous AI agent framework built on Python. It features multi-agent orchestration with a thin orchestrator and specialized sub-agents, stage-based LLM routing with failover, 80+ tools distributed across agents, persistent memory with RAG, Docker sandboxed code execution, multi-platform interfaces (Telegram + Web + Voice Chat), and an installable skill system.

---

## High-Level Architecture

```
Telegram Bot / Web UI / Voice Chat
         │
         ▼
  KinetiCDispatcher (orchestrator.py)
         │
         ├── Agent Registry (AgentCard[])
         ├── Session management
         ├── Sub-agent spawning
         ├── Idle eviction (5 min)
         └── Stage override resolution
         │
         ▼
  AgentInstance — MAIN (agent.py) [~12 core tools]
         │
         ├── Orchestrator — routes tasks via send_message
         │
         ├── ▶ obsidian-assistant  [10 obsidian tools]
         ├── ▶ coding-assistant    [18 coding tools]
         ├── ▶ security-agent      [33 security + network tools]
         ├── ▶ productivity-agent  [10 habit + pomodoro tools]
         └── ▶ system-agent        [3 maintenance tools]
         │
         └── Background tasks:
              ├── Profile extraction (every 3 msgs)
              ├── Knowledge injection (every 10 msgs)
              ├── Context compression
               └── SOUL evolution
          └── Workflow learning (SQLite)
```

---

## Agent Architecture

The main agent is a thin **orchestrator** with ~12 core tools. Specialized tasks are delegated via `send_message` to sub-agents.

| Agent | Tools | Purpose |
|-------|-------|---------|
| **main** | read/write files, web search, send file, schedule, spawn | Orchestrator — routes tasks, handles simple requests |
| **obsidian-assistant** | obsidian_create/edit/search, template, recent, tags, daily, flashcards | Second brain — manages Obsidian vault |
| **coding-assistant** | file ops, git, run code, opencode, execute commands | Software development tasks |
| **security-agent** | security_scan/block/audit, network_dns/whois/traceroute, CVE lookup, IP check | System security scanning and threat intel |
| **productivity-agent** | habit_add/log/list, pomodoro_start/status/stats | Habit tracking and focus sessions |
| **system-agent** | system_temp_cleanup, disk_usage, startup_optimize | System maintenance |

### Communication Flow

```
User: "scan my system for vulnerabilities"
  → main agent receives message
  → main recognizes security task
  → main calls send_message(target="security-agent", message="scan my system...")
  → security-agent processes with its 33 security tools
  → security-agent returns result
  → main agent formats and delivers response
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.13 | Runtime |
| **LLM Provider** | OpenAI SDK / httpx | Unified API for any OpenAI-compatible endpoint |
| **Telegram Bot** | python-telegram-bot v22 | Chat interface |
| **Web API** | FastAPI + uvicorn | REST API + Web UI |
| **CLI** | click | Command-line interface |
| **Config** | dotenv + JSON | .env for secrets, JSON for structure |
| **Vector Store** | SQLite + numpy | Knowledge base with cosine similarity + MMR |
| **Embedding** | OpenAI SDK / httpx | Any OpenAI-compatible embedding endpoint |
| **Code Execution** | Docker (or subprocess fallback) | Sandboxed Python execution |
| **Image Analysis** | Groq Vision API (httpx) | Image understanding via Telegram |
| **Voice** | Groq Whisper API (httpx) | Speech-to-text via Telegram |
| **Transcripts** | youtube-transcript-api | YouTube video summarization |
| **PowerPoint** | python-pptx | .pptx generation with charts + styles |
| **SLT** | aiosqlite | async SQLite for learning workflows |
| **Linting** | ruff | Code quality |
| **Type Checking** | mypy | Type safety |
| **Testing** | pytest | 89 tests |

---

## Storage Layer

| Data | Format | Location | Why this format |
|------|--------|----------|----------------|
| Conversation history | JSONL | `agents_workspace/<agentId>/history.jsonl` | Append-only log, sequential reads |
| User profile | JSON | `agents_workspace/<agentId>/profile.json` | Small, human-readable, atomic writes |
| Scheduled tasks | JSON | `agents_workspace/<agentId>/tasks.json` | Small (<100 items), simple CRUD |
| Knowledge base | SQLite + numpy | `agents_workspace/<agentId>/knowledge/store.db` | Vector search with cosine similarity |
| Learning workflows | SQLite | `agents_workspace/learning.db` | Queryable by trigger, increment counters |
| Scheduler meta | JSON | `agents_workspace/_scheduler_meta.json` | Warned task IDs, briefing date (persisted state) |

---

## Core Components

### 1. Entrypoint (`src/main.py`)

Boot sequence:
1. Import all modules
2. Load `.env` via `dotenv`
3. Load `config/models.json` via `load_model_config()` — resolves providers, extracts embedding config
4. Initialize embedding client if configured
5. Validate provider connectivity (non-blocking background task)
6. Instantiate `KinetiCDispatcher` with model config + endpoints
7. Load agents from `config/agents.json`
8. Start three services in parallel:
   - **Telegram bot** — polls for messages, dispatches to main agent
   - **Web API server** — FastAPI on port 18789
   - **Scheduler daemon** — checks every 10s for overdue/upcoming tasks

### 2. Dispatcher (`src/agents/orchestrator.py`)

The `KinetiCDispatcher` is the central orchestrator:
- **Agent Registry** — in-memory `dict[str, AgentCard]` of registered agents
- **Agent Lifecycle** — lazy-loads agents on first dispatch; evicts after 5 min idle
- **Sub-agent Spawning** — library agents with `can_delegate: true` can spawn ephemeral specialists (max 3 children, depth 3)
- **Inter-agent Messaging** — `send_message` tool to delegate to other agents
- **Session Management** — switches conversation contexts; each session has independent history
- **Stage Overrides** — runtime provider/model overrides per stage via `/models` Telegram command
- **Provider Fallback** — agent provider → default think provider → first available provider
- **Streaming** — `on_token` callback threaded through dispatch → process → think loop

### 3. Agent Instance (`src/agents/agent.py`)

Each agent has:
- **SOUL.md** — system prompt (personality + behavior rules)
- **Tool whitelist** — only registered tools available
- **Memory** — JSONL conversation history with auto-compression
- **Profile** — extracted user facts (filtered for permanence)

**Processing modes:**
- **Single mode** — one provider/model handles everything (think stage only)
- **Multi mode** — classify → think → tool_call → answer

**Message processing loop:**
1. Append user message to memory, reset tool sequence tracking
2. Inject current time as system message
3. Recall relevant past memories from vector store (timestamped)
4. Recall learned workflows from SQLite (if matching trigger found)
5. Main think loop (max 3 iterations):
   a. Build messages with context (time + recall + learned workflow)
   b. Call LLM with tool definitions
   c. If streaming enabled on final iteration, stream tokens via callback
   d. Execute tool calls, track sequence, append results
   e. If no tool calls → break
6. Append feedback prompt if tools were used ("Are you satisfied?")
7. Fire-and-forget background tasks: profile extraction, memory snapshot, compression, soul evolution

### 4. LLM Providers (`src/providers/provider.py`)

Unified provider class that works with any OpenAI-compatible endpoint:
- **OpenAI SDK path** — used when `SDK_COMPATIBLE_DOMAINS` matches base URL
- **HTTP fetch path** — used for all other endpoints (httpx direct)
- **Streaming** — both SDK and HTTP paths support token streaming
- **Temperature** — configurable per provider instance (default: 0.3)
- **Failover** — `call_with_fallback()` tries providers in order until one succeeds

**Stage-based model routing:**
| Stage | Purpose | Strategy |
|-------|---------|----------|
| classify | Intent classification | Cheap/fast model |
| think | Main reasoning | Powerful model |
| tool_call | Structured tool output | Tool-capable model |
| answer | Response formatting | Same as think or polished |

### 5. Memory Layer (`src/agents/memory.py`)

- **Persistence** — conversations stored as JSONL per session
- **Library agents** — keep history across restarts
- **Ephemeral agents** — history cleaned on eviction
- **Capped at 500 messages** — oldest trimmed, system prompt always kept
- **Compression** — when history >60 messages, older exchanges summarized into a `[COMPRESSED HISTORY]` system message
- **User profiles** — auto-built every 3 messages, stores permanent facts (filters transient data)
- **Timestamps** — every message has creation timestamp, injected as `[Thu 10:32]` prefix in LLM calls

### 6. Knowledge Base (`src/agents/rag/`)

- **Embedding** — any OpenAI-compatible embedding endpoint, configured in `models.json`
- **Vector store** — SQLite + numpy with cosine similarity + MMR diversification
- **Chunking** — recursive paragraph splitting
- **Search** — hybrid semantic + keyword (BM25) with configurable weighting
- **Memory archiving** — compressed conversation summaries stored as `type: memory` chunks
- **Recall** — on every message, top 3 relevant memories injected with timestamps

### 7. Tool System — 60+ tools

| Category | Tools | Files |
|----------|-------|-------|
| **File (sandbox)** | `sandbox_read_file`, `sandbox_write_file`, `sandbox_edit_file`, `sandbox_delete_file`, `sandbox_list_files`, `sandbox_undo_file` | `file_tools.py` |
| **Knowledge** | `query_knowledge_base`, `index_file`, `index_url`, `knowledge_stats` | `knowledge_tool.py` |
| **Data** | `index_github`, `scrape_and_index` | `data_connectors.py` |
| **Web** | `web_search` (Brave), `search_images` (DuckDuckGo) | `web_search.py`, `image_search.py` |
| **Browser** | navigate, click, fill, extract, screenshot, html, close | `browser.py` |
| **Email** | read_emails, read_email_body, send_email, reply_to_email | `email_tool.py` |
| **Code** | `run_code` (Docker sandbox), `execute_command` (whitelisted) | `code_tool.py`, `execute_command.py` |
| **System** | `get_current_time`, `get_system_info`, `read_env_var`, `download_url` | `system_tools.py`, `schedule_task.py` |
| **Schedule** | `schedule_task`, `list_scheduled_tasks`, `remove_scheduled_task`, `create_monitor`, `list_monitors` | `schedule_task.py`, `monitor_tool.py` |
| **Communication** | `send_message`, `send_file` | `registry.py`, `send_file_tool.py` |
| **Obsidian** | create_note, edit_note, search, graph_query, daily_note, suggest_links, daily_digest, canvas_add, spaced_repetition | `obsidian_tools.py` |
| **Presentation** | `create_presentation` (with POWERPOINT_MODEL support) | `presentation_tool.py` |
| **Agent** | `spawn_specialist`, `spawn_swarm`, `send_message`, `run_pipeline` | `agent.py`, `registry.py`, `pipeline_tool.py` |
| **Image** | `generate_image`, `search_images`, `get_youtube_info` | `image_tool.py`, `image_search.py`, `youtube_tool.py` |
| **OpenCode** | `call_opencode`, `apply_opencode` | `opencode_tool.py` |
| **Zip/Git** | `zip_project`, `unzip`, `git` | `zip_tool.py`, `git_tool.py` |
| **Weather/News** | `get_weather`, `get_news`, `daily_briefing` | `weather_tool.py`, `news_tool.py`, `briefing_tool.py` |

### 8. Multi-Agent System

Three agents registered by default:

| Agent | Role | Tools | When used |
|-------|------|-------|-----------|
| **main** | Primary assistant | All 60+ tools | Every user message |
| **coding-assistant** | Code specialist | run_code, execute_command, sandbox file ops | Delegated via send_message |
| **obsidian-assistant** | Vault manager | obsidian_create_note, obsidian_edit_note, obsidian_search, etc. | Delegated via send_message |

Sub-agent spawning: `spawn_specialist` creates ephemeral agents with custom SOUL. `spawn_swarm` runs 2-5 in parallel and merges results.

### 9. OpenCode Integration

OpenCode (Go) is used for project-level coding tasks:
- Runs `opencode run` asynchronously via subprocess
- Creates projects in `OPENCODE_WORKSPACE` directory
- Writes `PROJECT.md` for duplicate detection
- Supports apply (git commit) / reject (git checkout) workflow
- Configurable model via `OPENCODE_DEFAULT_MODEL`

### 10. Docker Sandbox

- Persistent container (`kinetic-sandbox`) with 24h sleep loop
- Resource limits: 128MB RAM, 0.5 CPU, no network
- Falls back to subprocess if Docker unavailable
- Marked with `[Docker]` or `[Subprocess]` prefix in output

### 11. Learning System

- SQLite-based workflow learning
- Tracks tool call sequence during think loop
- `/perfect` saves current workflow
- `/forget <trigger>` removes a workflow
- Before think loop, matching workflows are injected as system context
- Auto-feedback prompts "Are you satisfied?" after tool calls

### 12. Skill System

- Skills = sub-agents with tool whitelists
- Defined in `config/skills/<id>/skill.json` + `SOUL.md`
- `kinetic-cli skills list/install/remove/info`
- Community repo support via `--url` flag
- 6 bundled skills: web-research, file-organizer, email-assistant, code-runner, scheduler, obsidian-assistant

---

## Data Flow

```
User sends message (Telegram/WebUI)
         │
         ▼
  Bot handler (main.py)
         ├── Track user activity for idle check-in
         ├── If file → Groq Vision analysis
         ├── If voice → Groq Whisper transcription
         └── Dispatch to main agent
         │
         ▼
  KinetiCDispatcher.dispatch()
         ├── Clear eviction timeout
         ├── Get or initialize agent
         └── agent.process(message)
         │
         ▼
  AgentInstance.process()
         ├── Append user message to memory
         ├── Inject current time as context
         ├── Recall past memories (vector store)
         ├── Recall learned workflows (SQLite)
         │
         ├── Think loop (max 3 iterations):
         │   ├── LLM call (with tools)
         │   ├── Execute tool → append result
         │   │   ├── Docker sandbox (run_code)
         │   │   ├── API call (web_search, Groq, etc.)
         │   │   ├── File operation (sandbox)
         │   │   └── OpenCode (async subprocess)
         │   └── If streaming → update message progressively
         │
         ├── Append feedback prompt ("Satisfied?")
         ├── Background tasks (fire-and-forget)
         └── Return response
         │
         ▼
  Bot handler sends response (streamed or full)
         ├── Send pending files (auto-queued)
         └── Check for pending background tasks
```
