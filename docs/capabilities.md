# K.I.N.E.T.I.C. — Capabilities

## Agent framework

- **Dispatcher-registry architecture** — lazy-loads agents, evicts after 5 min idle
- **Sub-agent spawning** — library agents with `can_delegate: true` spawn ephemeral specialists (max 3, depth 3)
- **Inter-agent messaging** — `send_message` to any registered agent by ID. Depth-limited
- **SOUL personality layer** — per-agent `SOUL.md` loaded as system prompt. Task-focused with strong imperatives. Auto-created when agents are added via Web UI or CLI.
- **Stale system prompt detection** — `refreshSystemPrompt()` replaces the stored prompt if SOUL.md changed since the last session. No manual history cleanup needed.
- **ReAct-style reasoning** — visible `[THINK]` prefix before tool calls
- **Session management** — `/session new`, `/session list`, `/session <id>` — each session has independent history and profile

## Memory & user profile

- **Persistent history** — JSONL at `agents_workspace/<agentId>/sessions/<sessionId>/history.jsonl`
- **Capped at 500 messages** (configurable via `AGENT_MEMORY_MAX`), oldest trimmed
- **Automatic context compression** — when history exceeds ~60 messages, older exchanges are summarized into a `[COMPRESSED HISTORY]` system message. Triggered fire-and-forget after every response. Saves ~70% of context on long conversations
- **User profile extraction** — every 3 user messages, background LLM call extracts facts. Profile injected as system prompt on every init, survives restarts
- **All background tasks deferred** — profile extraction, compression, and evolution run via `setImmediate()` after the response is returned. Never blocks the user-facing reply.

## Tool system — 20 tools

All tool definitions passed to the LLM each iteration; LLM decides which to call.

| Tool | Condition | Description |
|---|---|---|
| `get_current_time` | Always | Current date/time |
| `get_system_info` | Always | OS, hostname, CPU, RAM, disk |
| `read_env_var` | Always | Env var value (sensitive keys masked) |
| `read_file` | Always | Read file from sandbox |
| `write_file` | Always | Write file to sandbox (backup before overwrite) |
| `edit_file` | Always | Find+replace in file (backup before edit) |
| `delete_file` | Always | Delete file from sandbox (backup before delete) |
| `undo_file` | Always | Restore most recent backup |
| `list_files` | Always | List sandbox directory contents |
| `download_url` | Always | Download URL to sandbox (5MB, 30s) |
| `execute_command` | Always | Whitelisted system commands |
| `web_search` | `BRAVE_API_KEY` | Brave Search API |
| `get_current_time` | Always | Current date/time |
| `schedule_task` | Always | One-time and recurring reminders |
| `query_knowledge_base` | Embedding configured | Semantic search over indexed content |
| `index_file` | Embedding configured | Index a sandbox file into knowledge base |
| `index_url` | Embedding configured | Fetch URL and index into knowledge base |
| `index_github` | Embedding configured | Fetch GitHub file/repo and index |
| `scrape_and_index` | Embedding configured | Scrape web page and index |
| `knowledge_stats` | Embedding configured | Show knowledge base stats |
| `run_pipeline` | Always | Execute a multi-agent pipeline |
| `spawn_specialist` | `can_delegate: true` | Ephemeral sub-agent |
| `send_message` | 2+ agents | Inter-agent message |

## Knowledge base (RAG)

- **Embedding** via any OpenAI-compatible provider (configured in `models.json` under `"embedding"`)
- **Vector store** — JSON-based with cosine similarity. Documents chunked (500 char chunks, 50 char overlap)
- **Index sources**: sandbox files, web URLs, GitHub repos/files, any scraped web page
- **Query**: `query_knowledge_base` tool returns top-5 chunks with relevance scores
- **Commands**: `/knowledge` (stats), `/knowledge list` (documents), `/knowledge remove <id>`

## Multi-agent pipelines

- **Definition**: JSON format with sequential steps, each step specifies agent + prompt template + output variable
- **Template variables**: `{{variable_name}}` — replaced with outputs from previous steps
- **Execution**: `run_pipeline` tool or POST `/api/pipelines/execute`
- **Web UI**: Create and manage pipelines through the dashboard
- **Storage**: JSON files at `agents_workspace/.pipelines/`

## Task scheduler

- `schedule_task` with `time` ("2:00 PM") or `delay_minutes` (10)
- Recurring tasks via `interval_minutes`
- Persisted to `agents_workspace/<id>/tasks.json`
- Daemon ticks every 10s, dispatches to agent, sends response to Telegram chat
- Commands: `/task list`, `/task remove <id>`

## LLM provider system

- **Unified client** — OpenAI SDK with configurable `baseUrl` + `apiKey`. Works with any OpenAI-compatible endpoint
- **Stage-based routing** — `think` stage is the active processing stage (classify/answer removed for cost)
- **Provider failover** — `fallbacks: [{ provider, model }]` per stage. Tried in order on failure
- **Tool-unsupported model fallback** — if model rejects tool calls, auto-retries with plain `generate()`
- **Runtime override** — `/models set think <provider> [model]` switches at runtime without restart

## Web UI dashboard

- **Auto-starts** on port `18789` (configurable via `API_PORT` env var)
- **Chat interface** — send messages, see agent responses with tool calls
- **Session manager** — create, switch, and list sessions
- **Knowledge viewer** — see indexed documents and knowledge base stats
- **Pipeline viewer** — see defined pipelines
- **Status display** — uptime, active session, agent info

### REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/chat` | POST | `{ message, session_id }` → `{ response }` |
| `/api/sessions` | GET | List sessions |
| `/api/sessions` | POST | `{ name }` → create/switch |
| `/api/status` | GET | Uptime, agents, session |
| `/api/knowledge` | GET | Stats + document list |
| `/api/pipelines` | GET | List pipelines |
| `/api/pipelines` | POST | Create pipeline |
| `/api/pipelines/execute` | POST | Execute pipeline |

## Telegram bot

- Auto-reconnect on polling errors
- MarkdownV2 with plain-text fallback on parse errors
- Allowlist auth from `TELEGRAM_ALLOWLIST` (empty = open)
- Typing indicator, error messages, graceful shutdown

### Commands

| Command | Description |
|---|---|
| `/help` | All commands |
| `/models` | Show stage config |
| `/models set think <provider> [model]` | Runtime provider switch |
| `/models reset think` | Revert to default |
| `/providers` | List endpoints |
| `/status` | Uptime, agents, target |
| `/profile` | Extracted user profile |
| `/reset` | Clear current session |
| `/session` | Show active session |
| `/session new <name>` | New session |
| `/session <name>` | Switch session |
| `/session list` | All sessions |
| `/task list` | Scheduled tasks |
| `/task remove <id>` | Remove task |
| `/knowledge` | Knowledge base stats |
| `/knowledge list` | Indexed documents |
| `/knowledge remove <id>` | Remove document |

## CLI tools

- `pnpm cli onboard` — setup wizard
- `pnpm cli models` — configure stages, providers, test connectivity. Validates `apiKeyEnv` is an env var name, not a raw key.
- `pnpm cli agents` — CRUD for agents and SOUL files. Auto-creates agent folder and `SOUL.md`.

## Security boundaries

- All file operations restricted to `agent_sandbox/`
- Path traversal blocked (`..`)
- Command whitelist only (ipconfig, systeminfo, netstat, whoami, ping, curl, etc.)
- Shell chaining (`&&`, `|`, `;`) rejected
- 15s command timeout, 100KB output limit
- Backups before destructive file operations
- Env var reader masks `key`, `token`, `secret` values

## Architecture

```
Telegram ─┐    Web UI ───┐
           ▼             ▼
    ┌──────────────────────────┐
    │      Dispatcher          │──── ToolRegistry (20 tools)
    │  (orchestrator.ts)       │
    └──────────┬───────────────┘
               │
    ┌──────────┴───────────────┐
    │    Agent (agent.ts)      │
    │  • think loop (5 iter)   │
    │  • profile extraction    │
    │  • context compression   │
    │  • SOUL personality      │
    └──────────┬───────────────┘
               │
    ┌──────────┴───────────────┐
    │    UnifiedProvider       │──→ OpenAI-compatible LLM
    │    (with failover chain) │
    └──────────────────────────┘
               │
    ┌──────────┴─────────────────────────────────────┐
    │  Storage (agents_workspace/<id>/)                │
    │  ├── sessions/<id>/history.jsonl                 │
    │  ├── sessions/<id>/profile.json                  │
    │  ├── tasks.json                                  │
    │  └── knowledge/store.json                        │
    └──────────────────────────────────────────────────┘
```

Processing flow per message:
1. Message arrives (Telegram or Web UI) → `dispatcher.dispatch(id, query, 0, chatId)`
2. Agent loads SOUL + history + profile from disk. If the stored system prompt is stale (SOUL.md changed since last session), `refreshSystemPrompt()` replaces it immediately.
3. **Think** loop (up to 5 iterations):
   - LLM receives full history + all tool definitions
   - Tool call → execute, push result, loop
   - Text response → push to history, exit
4. **Response is returned** to sender immediately
5. **Fire-and-forget** (deferred via `setImmediate`, never blocks): profile extraction (every 3rd msg) + context compression (history > 60 msgs)
6. Agent eviction timer resets to 5 min

## Known gaps

| Feature | Notes |
|---|---|
| Multi-platform (Slack, Discord) | Telegram + Web UI only |
| Streaming responses | Would require changing `process()` → `string` contract |
| Tests | `pnpm test` returns placeholder |
| Monitoring | No structured logging or metrics |
| Docker deployment | Not yet — planned next |
| SOUL auto-evolution | Disabled temporarily — the core system prompt quality was unstable. Will be re-enabled after fundamentals are hardened. |
