# K.I.N.E.T.I.C. Architecture

## Overview

K.I.N.E.T.I.C. is an autonomous agentic framework built on a **Dispatcher-Registry** model with **stage-based LLM routing**. Agents are hot-swappable modules orchestrated by the `KinetiCDispatcher`. The system supports multiple interaction interfaces (Telegram bot, Web UI, CLI) and features a unified provider system, persistent memory, knowledge base with semantic search, and a tool registry.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       Entrypoint                        │
│                     src/main.ts                         │
│                                                         │
│  Loads config → Creates Dispatcher → Starts services    │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────┐     ┌──────────────────┐
│      KinetiCDispatcher       │────▶│   AgentRegistry   │
│    src/agents/orchestrator   │     │   (in-memory Map) │
│                              │     │                    │
│  • Agent lifecycle           │     │  AgentCard[]       │
│  • Sub-agent spawning        │     │                    │
│  • Session management        │◀────│                    │
│  • Idle eviction             │     └──────────────────┘
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│       AgentInstance          │
│     src/agents/agent.ts      │
│                              │
│  • Stage-based LLM routing   │
│  • Tool registry             │
│  • Memory layer              │
│  • Message processing loop   │
└──────────────┬───────────────┘
               │
     ┌─────────┼──────────┐
     │         │          │
     ▼         ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│ Tools  │ │Memory  │ │Providers│
│registry│ │ layer  │ │ (LLM)  │
└────────┘ └────────┘ └────────┘
```

---

## Core Components

### 1. Entrypoint (`src/main.ts`)

Boot sequence:
1. Load `.env` via `dotenv`
2. Load `src/config/models.json` via `loadModelConfig()` — resolves providers, extracts embedding config
3. Initialize embedding client if embedding config is present
4. Validate provider connectivity (non-blocking)
5. Instantiate `KinetiCDispatcher` with model config + endpoints
6. Load agents from `src/config/agents.json`
7. Start three services in parallel:
   - **Telegram bot** — polls for messages, dispatches to agent
   - **Web API server** — HTTP server on port 18789
   - **Scheduler daemon** — background task execution

### 2. Dispatcher (`src/agents/orchestrator.ts`)

The `KinetiCDispatcher` is the central orchestrator:

- **Agent Registry** — in-memory `Map<string, AgentCard>` of all registered agents
- **Agent Lifecycle** — `getOrInitializeAgent()` lazy-loads agents; `scheduleEviction()` evicts after 5 min idle
- **Sub-agent Spawning** — library agents with `can_delegate: true` can spawn ephemeral specialists (max 3 children, max depth 3)
- **Inter-agent Messaging** — any agent can `send_message` to another registered agent
- **Session Management** — `setSession()` switches conversation contexts; each session has its own history
- **Stage Overrides** — runtime provider/model overrides per stage via `/models` Telegram command
- **Provider Fallback** — `resolveThinkStage()` resolves agent provider; if missing from models.json, falls back to first available

### 3. Agent Instance (`src/agents/agent.ts`)

Each agent is an `AgentInstance` with:

**Processing Modes:**
- **Single mode** — one provider/model handles everything (think stage only)
- **Multi mode** — classify → think → tool_call → answer (each can use a different provider/model)

**Message Processing Loop (`process()`):**
1. Append user message to memory
2. Classify intent (multi mode only) — chitchat vs tool-needing
3. Main reasoning loop (up to 5 iterations):
   a. Call LLM with conversation + tool definitions
   b. If response contains tool calls → execute tool → append result → loop
   c. If no tool calls → break
4. Format final response (answer stage in multi mode)
5. Append assistant response to memory
6. Fire-and-forget background tasks (deferred via `setImmediate`, never blocks response):
   - Build user profile (every 3 messages)
   - Compress history if too long
7. Return response

**Tool Registry:**
Every agent gets these tools:
| Tool | Description |
|------|-------------|
| `web_search` | Brave Search (requires `BRAVE_API_KEY`) |
| `execute_command` | Sandboxed shell commands |
| `read_file`, `write_file`, `edit_file`, `delete_file`, `list_files`, `undo_file` | File operations in sandbox |
| `query_knowledge_base`, `index_file`, `index_url`, `knowledge_stats` | Knowledge base |
| `index_github`, `scrape_and_index` | Data connectors |
| `spawn_specialist` | Only for library agents with `can_delegate: true` |
| `send_message` | Only when 2+ agents are registered |
| `schedule_task` | Background reminders |
| `get_time`, `get_system_info` | System info |
| `download_url` | Download files from URLs |
| `read_env_var` | Read environment variables |
| `run_pipeline` | Execute predefined pipelines |

### 4. LLM Providers (`src/providers/provider.ts`)

Unified provider system — all LLM calls go through the OpenAI SDK. The only difference between providers is `baseUrl` + `apiKey`. Works with any OpenAI-compatible endpoint (OpenAI, OpenRouter, Ollama, Groq, DeepSeek, NVIDIA, etc.).

**Provider resolution:**
1. Agent card specifies provider + model
2. Dispatcher resolves against `models.json` providers
3. Fallback chain: agent provider → default think provider → first available provider
4. Runtime overrides checked first

**Stage-based model routing** — each stage can use a different provider+model:

| Stage | Purpose | Typical Model |
|-------|---------|---------------|
| `classify` | Intent classification | Cheap/fast (Qwen, Gemma 1B) |
| `think` | Main reasoning | Powerful (Llama 70B, Claude) |
| `tool_call` | Structured tool output | Tool-capable (Llama, GPT) |
| `answer` | Response formatting | Same as think |

**Provider failover** — each stage can specify `fallbacks: [{ provider, model }]`. When the primary fails, fallbacks are tried in order.

### 5. Memory Layer (`src/agents/memory.ts`, `src/agents/memory/compressor.ts`)

- **Persistence** — conversations stored as JSONL in `agents_workspace/<agentId>/history.jsonl`
- **Library agents** — keep history across restarts
- **Ephemeral agents** — cleaned on eviction
- **Capped at 500 messages** — oldest trimmed first (system prompt always kept)
- **Memory compression** — `compress()` rewrites conversation to reduce token usage
- **User profiles** — auto-built every 3 messages (deferred, non-blocking), stored as `profile.json`
- **Stale system prompt detection** — on agent init, `refreshSystemPrompt()` compares the stored system prompt against the current SOUL.md + GLOBAL_PROTOCOLS. If different, replaces it in-place. This means SOUL.md changes take effect immediately without manual history cleanup.
- **All background tasks** (profile extraction, compression, evolution) are wrapped in `setImmediate()` — zero synchronous work before the response is returned.

### 6. Knowledge Base (`src/agents/rag/`)

**Embedding (`embedding.ts`):**
- Singleton `OpenAI` client for embedding generation
- `initEmbedding()` initializes with baseUrl, apiKey, model, options
- `getEmbedding(text)` / `getEmbeddings(texts[])` — returns float vectors
- Auto-detects NVIDIA endpoints and adds `input_type` + `truncate` params
- `ensureEmbedding()` (in `knowledgeTool.ts`) auto-initializes from `models.json` if not already set

**Vector Store (`vectorStore.ts`):**
- Disk-based store at `agents_workspace/<agentId>/knowledge/store.json`
- **Chunking strategies:** recursive (by paragraph), sentence, paragraph
- **Search:** cosine similarity + keyword hybrid + MMR diversification
- **Operations:** `addChunks`, `searchSimilar`, `listDocuments`, `removeDocument`, `getStoreStats`

**Knowledge Tools (in `knowledgeTool.ts`):**
- `query_knowledge_base` — semantic search over indexed docs
- `index_file` — index a sandbox file
- `index_url` — fetch a URL and index its content
- `knowledge_stats` — document/chunk counts

**Data Connectors (in `dataConnectors.ts`):**
- `index_github` — index GitHub repos/files via raw GitHub API
- `scrape_and_index` — scrape web pages and index

### 7. Task System (`src/agents/tasks/`)

**Scheduler (`scheduler.ts`):**
- Background daemon ticks every 10 seconds
- Tasks stored in `agents_workspace/_tasks.json`
- When task is due, delivers reminder via bot or callback
- Supports one-time and recurring tasks

**Pipeline (`pipeline.ts`):**
- Chain multiple agents in sequence with `{{variable}}` template substitution
- Each step: agent ID, prompt (with template vars), output variable
- Stored in `agents_workspace/_pipelines/`
- Executable via Web UI, chat command, or CLI

### 8. API Server (`src/api/server.ts`)

HTTP server on port 18789 with routes:

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/chat` | POST | Send message to agent |
| `/api/chat/stream` | POST | Streaming response |
| `/api/knowledge` | GET | List docs and stats |
| `/api/knowledge/inject` | POST | Inject text/URL/file into knowledge base |
| `/api/knowledge/:docId` | DELETE | Remove a document |
| `/api/config/models` | GET/PUT | Read/write models.json |
| `/api/config/agents` | GET/PUT | Read/write agents.json |
| `/api/config/test-provider` | POST | Test provider connectivity |
| `/api/pipelines` | GET/POST/DELETE | Pipeline CRUD |
| `/api/pipelines/execute` | POST | Execute a pipeline |
| `/api/sessions` | GET | List sessions |
| `/api/sessions` | POST | Switch/create session |
| `/api/status` | GET | System status |
| `/favicon.ico` | GET | Tab icon (serves `src/images/logo-dark.png`) |
| `/logo-white.png` | GET | White logo for chat welcome screen |
| `/*` | GET | Serve static frontend from `public/` |

### 9. CLI (`src/cli/`)

| Command | Purpose |
|---------|---------|
| `pnpm cli onboard` | First-time setup wizard — creates models.json, agents.json, .env |
| `pnpm cli models` | Configure providers, stage routing, embedding model |
| `pnpm cli agents` | Manage agent registry — add, edit, delete, list |
| `pnpm cli knowledge` | Manage knowledge base — inject text/URLs/files, list/delete |
| `pnpm cli pipelines` | Manage pipelines — create, edit, delete, execute |

### 10. Web UI (`src/api/public/index.html`)

Single-page application with tabs:
- **Chat** — send messages to the active agent. Shows a welcome screen with the K.I.N.E.T.I.C. logo on first load.
- **Models** — configure providers, stage routing, embedding. Validates `apiKeyEnv` is an env var name (not a raw API key) before saving.
- **Agents** — manage agent registry. `soulPath` auto-set to `./<agent-id>/SOUL.md` — no manual input needed.
- **Knowledge** — inject documents, browse indexed docs
- **Pipelines** — create/edit/execute pipelines
- **Sessions** — switch conversation contexts
- **Docs** — built-in documentation

### 11. Image Serving (`src/api/server.ts`)

- `/favicon.ico` serves `src/images/logo-dark.png` as the browser tab icon
- `/logo-white.png` serves the white variant for the chat welcome screen
- Images directory is separate from the public static directory

---

### 12. Skill System (`src/skills/`, `src/cli/skills.py`)

The skill system turns **sub-agents into installable plugins**:

**Architecture:**
- A **skill** = a directory with `skill.json` (manifest) + `SOUL.md` (system prompt)
- Installed skills live at `config/skills/<id>/`
- `kinetic-cli skills install <name>` fetches from a community GitHub repo (`github.com/kinetic-skills/skills`) and adds an entry to `config/agents.json`
- Skills auto-register with the `"tools"` whitelist from their manifest

**Tool Whitelist (`AgentCard.tools`):**
- New field on `AgentCard`: `tools: list[str] | None`
- `None` = unrestricted (all 37 tools)
- `[]` = no tools (chat-only)
- `["web_search", "index_url"]` = only those tools
- Filtered at registration time in `AgentInstance._register_tool()` in `src/agents/agent.py`
- The agents.json `"tools"` array is normalized to lowercase on load

**Community repo:** `https://github.com/kinetic-skills/skills` (configurable via `KINETIC_SKILLS_REPO` env var). Each skill is a subdirectory with `skill.json` + `SOUL.md` at the root of the repo.

---

## Configuration Files

### `src/config/models.json`
```json
{
  "mode": "single|multi",
  "embedding": { "provider": "...", "model": "..." },
  "defaults": {
    "classify": { "provider": "...", "model": "..." },
    "think": { "provider": "...", "model": "...", "fallbacks": [...] },
    "tool_call": { "provider": "...", "model": "..." },
    "answer": { "provider": "...", "model": "..." }
  },
  "providers": {
    "name": { "baseUrl": "...", "apiKeyEnv": "ENV_VAR_NAME" }
  }
}
```

### `src/config/agents.json`
```json
{
  "settings": { "defaults": { "type": "library", "can_delegate": true } },
  "registry": [
    {
      "id": "main",
      "name": "Main Agent",
      "soulPath": "./main/SOUL.md",
      "provider": "GROQ",
      "model": "llama-3.1-8b-instant",
      "can_delegate": true
    }
  ]
}
```

### SOUL Personality Layer

Each agent has a `SOUL.md` file in `src/config/<agent-id>/SOUL.md`. Loaded as the system prompt on agent initialization.

**Design principles:**
- **Task-focused, not identity-focused** — instructs the agent what to do and how to communicate, not who to "be". Avoids philosophical framing that makes models introspective.
- **Strong imperatives** — uses "NEVER explain yourself", "If greeted, reply in under 5 words" rather than abstract principles.
- **Auto-created** — when an agent is added via Web UI or CLI, the folder and default `SOUL.md` are created automatically by the server (`PUT /api/config/agents`).
- **Stale detection** — on restart, the memory layer compares the stored system prompt against the current SOUL.md. If changed, the system prompt is refreshed in-place so new instructions take effect immediately.
- **Global rules** — `GLOBAL_PROTOCOLS` in `agent.ts` provides a second layer of hard rules that applies to all agents (greeting handling, no meta-commentary, direct answers).

---

## Data Flow

```
User Input (Telegram/WebUI/CLI)
        │
        ▼
  KinetiCDispatcher.dispatch()
        │
        ▼
  getOrInitializeAgent()
        │
        ▼
  AgentInstance.process(message)
        │
        ├──▶ Classify intent (multi mode)
        │
        ├──▶ LLM call (think stage)
        │       │
        │       ├──▶ Tool execution (if tool call)
        │       │       │
        │       │       ├──▶ Knowledge query
        │       │       ├──▶ File operations
        │       │       ├──▶ Web search
        │       │       ├──▶ Delegate to sub-agent
        │       │       └──▶ ...
        │       │
        │       └──▶ Loop until no tool calls (max 5)
        │
        ├──▶ Format response (answer stage)
        │
        ├──▶ Append to memory
        │
        └──▶ Return response
```

---

## Key Design Decisions

1. **OpenAI SDK as universal provider** — avoids per-provider SDKs; any OpenAI-compatible endpoint works
2. **Stage-based routing** — separates concerns (cheap classification, powerful reasoning, structured output)
3. **Singleton embedding client** — initialized once, reused across all knowledge operations
4. **Disk-based vector store** — no external database dependency; JSON files are portable
5. **Sandboxed command execution** — whitelisted commands only, path traversal blocked, no shell chaining
6. **Idle eviction** — prevents memory leaks from abandoned agents
7. **User profiles** — implicit memory without explicit save commands
8. **Task-focused system prompts** — SOUL.md uses strong imperatives ("NEVER do X") rather than philosophical identity language. Prevents model introspection on simple queries.
9. **Deferred background tasks** — profile extraction, compression, and evolution all run via `setImmediate()` after the response is returned. Zero synchronous overhead.
10. **Stale system prompt detection** — `refreshSystemPrompt()` compares the stored prompt against the current SOUL.md on every init. SOUL changes take effect without manual history cleanup.
11. **Multi-layer API key validation** — the Web UI, CLI, and server-side `PUT /api/config/models` endpoint all detect raw API keys pasted as `apiKeyEnv` values. Prevents keys from leaking into the config file.
