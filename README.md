<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/logo-white.png">
    <img src="images/logo-white.png" alt="K.I.N.E.T.I.C." width="150">
  </picture>
  <br>
  <b>Autonomous AI agent framework — Telegram, voice, RAG, 80+ tools, multi-agent pipelines.</b>
  <br><br>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT">
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?style=for-the-badge&logo=windows" alt="Windows">
  <img src="https://img.shields.io/badge/tests-89%20passed-3fb950?style=for-the-badge" alt="89 tests">
  <br><br>
  <b>K.I.N.E.T.I.C.</b> is a modular AI agent framework that runs entirely on your machine.<br>
  Chat via Telegram, speak via push-to-talk voice, or use the web dashboard.<br>
  It can scan your system for vulnerabilities, manage your Obsidian vault,<br>
  track habits and pomodoro sessions, look up CVEs, check IPs against threat feeds,<br>
  run code, search the web, send emails, schedule tasks — all through a unified<br>
  multi-agent system with persistent memory, RAG, and auto-learning.
  <br><br>
  No cloud dependency. No data leaves your machine. Open source (MIT).
</p>

---

## Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         ENTRY POINTS                                     │
│                                                                            │
│  Telegram Bot         FastAPI              CLI              Voice Chat     │
│  (python-telegram-    port 18789          kinetic-cli       push-to-talk  │
│   bot)                Web dashboard       onboard/models/    STT + TTS    │
│                       OpenAPI /docs        skills/knowledge               │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      KinetiCDispatcher                                    │
│  Routes messages to agents, lazy-loads & caches, max depth 3            │
│                                                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐         │
│  │   main     │  │   coding   │  │  security  │  │ productivity│         │
│  │ orchestrat │→│  assistant  │→│   agent    │→│   agent    │ ...       │
│  │ 15 tools   │  │ 21 tools   │  │ 35 tools   │  │ 11 tools   │         │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘         │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    AgentInstance.process()                                │
│                                                                            │
│  1. Classify ──► chitchat? ──► quick reply (no LLM needed)              │
│       │                                                                    │
│  2. Recall memories (vector store + shared headroom memory)               │
│       │                                                                    │
│  3. Recall Obsidian notes (if vault configured)                           │
│       │                                                                    │
│  4. Inject learned skills                                                 │
│       │                                                                    │
│  5. Think loop (up to N iterations)                                       │
│       │  ┌─────────────────────────────────────────────┐                  │
│       │  │ Build msgs → [HEADROOM COMPRESSION] → LLM   │                  │
│       │  │ → Tool call → execute → append result → repeat                │
│       │  └─────────────────────────────────────────────┘                  │
│       │                                                                    │
│  6. Polish answer (multi-mode only)                                       │
│       │                                                                    │
│  7. Background tasks (deferred, never block):                             │
│     ┌─────────────────────────────────────────────────────┐               │
│     │ Profile extraction (3 msgs) │ Obsidian inject (10)  │               │
│     │ Memory snapshot (5)         │ History compression   │               │
│     │ Skill auto-learning         │ SOUL evolution (50)   │               │
│     │ Memory compaction (5)       │ Failure learning (20) │               │
│     └─────────────────────────────────────────────────────┘               │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       LLM PROVIDERS                                       │
│                                                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │ classify │  │   think  │  │tool_call │  │  answer  │                 │
│  │ Groq     │  │Cloudflare│  │ Lightning│  │ Lightning│                 │
│  │ ~100 tok │  │ → Groq → │  │ → Groq   │  │ → Groq   │                 │
│  │          │  │ Lightning│  │          │  │          │                 │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                 │
│                                                                            │
│  HEADROOM COMPRESSION (optional):                                         │
│  SmartCrusher → JSON tool outputs (30-90% fewer tokens)                   │
│  CacheAligner → KV prefix cache hits                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Voice Pipeline

```
  Telegram Voice Msg     Push-to-Talk (Alt+V)
         │                       │
         ▼                       ▼
  ┌─────────────────────────────────────────┐
  │  handle_voice() / main.py:791           │
  │  Download .ogg → agent_sandbox/         │
  └────────────────┬────────────────────────┘
                   │
                   ▼
  ┌─────────────────────────────────────────┐
  │  Online STT (default)  │  Offline STT   │
  │  Groq Whisper API      │  faster-whisper│
  │  whisper-large-v3-turbo│  tiny, cpu, i8 │
  │  GROQ_API_KEY required │  STT_BACKEND=  │
  │                       │  offline        │
  └────────────────┬────────────────────────┘
                   │
                   ▼
         "[Voice transcribed]: <text>"
                   │
                   ▼
            Dispatcher → Agent → Response
                   │
                   ▼
  ┌─────────────────────────────────────────┐
  │  TTS Delivery                            │
  │                                          │
  │  Agent tool: tts_speak(text, voice)      │
  │  Auto TTS:   /tts_on → every response   │
  │  Engine:     edge-tts (Microsoft Neural) │
  │  Voices:     en-GB-RyanNeural (default)  │
  │              configurable via TTS_VOICE  │
  │  Speed:      configurable via TTS_SPEED  │
  └─────────────────────────────────────────┘
```

Each stage uses a different provider. If the primary fails, it falls through the chain automatically:

| Stage         | Primary    | Fallback 1 | Fallback 2 | Context                               |
| ------------- | ---------- | ---------- | ---------- | ------------------------------------- |
| **Classify**  | Groq       | Lightning  | —          | Message only (~100 tokens)            |
| **Think**     | Cloudflare | Groq       | Lightning  | System + message + tools (~4K tokens) |
| **Tool call** | Lightning  | Groq       | —          | Same as think                         |
| **Answer**    | Lightning  | Groq       | —          | Full history (~4-20K tokens)          |

Providers are OpenAI-compatible — any endpoint with `/chat/completions` works (OpenAI, Anthropic, Groq, OpenRouter, Ollama, vLLM, etc.). Configured in `config/models.json`.

---

## Agent System

### Multi-Agent Delegation

The main agent is a **thin orchestrator** with ~15 core tools. Specialized work is delegated via `send_message`:

```
main (orchestrator, 15 core tools)
  ├── obsidian-assistant    [15 tools] — vault: create, link, search, tags
  ├── coding-assistant      [21 tools] — code: write, debug, git, opencode
  ├── security-agent        [35 tools] — system: scan, firewall, CVE, IP
  ├── productivity-agent    [11 tools] — habits, pomodoro
  └── system-agent          [ 4 tools] — temp cleanup, disk, startup
```

Agents are lazy-loaded, cached, and auto-evicted after 5 minutes idle.

### Tool Whitelist

Each agent can restrict its tool set via the `"tools"` field in `agents.json`:

```json
{ "id": "web-agent", "tools": ["web_search", "scrape_and_index"] }
```

- **`null` / omitted** — all tools
- **`[]`** — no tools (chat-only)
- **`["a", "b"]`** — only these tools

Tools are progressively loaded — only tools matching the user's message keywords are offered, reducing token waste.

---

## Memory & Persistence

K.I.N.E.T.I.C. has a layered memory system:

```
┌──────────────────────────────────────────────────────────────────┐
│                       MEMORY LAYERS                               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  1. Conversation History (JSONL, 500 msg cap)        │        │
│  │     agents_workspace/<id>/history.jsonl               │        │
│  │     → Oldest messages auto-trimmed, FIFO              │        │
│  │     → LLM-summarized into [COMPRESSED HISTORY] at 60+│        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                    │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  2. User Profile (JSON, per-agent + global merge)    │        │
│  │     agents_workspace/<id>/profile.json                │        │
│  │     agents_workspace/<id>/global_profile.json          │        │
│  │     → LLM extracts permanent facts every 3 messages   │        │
│  │     → Sensitive info (email, phone, URLs) filtered    │        │
│  │     → `/forget_fact <keyword>` to remove              │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                    │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  3. Vector RAG (SQLite + numpy cosine similarity)    │        │
│  │     agents_workspace/<id>/knowledge/store.db          │        │
│  │     → Memories archived with metadata.type=memory    │        │
│  │     → Top-3 recalled before each response             │        │
│  │     → FTS5 full-text search as fallback               │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                    │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  4. Shared Memory (SQLite, opt-in HEADROOM_MEMORY=1) │        │
│  │     agents_workspace/shared/memory.db                 │        │
│  │     → Cross-agent: any agent stores, any recalls     │        │
│  │     → Uses same embedding model as RAG                │        │
│  │     → Semantic search across all agents' memories    │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                    │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  5. Shared Context (JSON files with TTL, always on)  │        │
│  │     agents_workspace/shared/context/<key>.json         │        │
│  │     → Agent A shares, Agent B reads                   │        │
│  │     → TTL auto-purge, list all active entries        │        │
│  │     → Tools: share_context / get_context / list_context       │
│  └──────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

---

## Learning System

K.I.N.E.T.I.C. learns from you in three ways:

### Skill Auto-Learning

After every successful multi-step response (2+ tool calls), the sequence is automatically saved as a reusable skill document at `config/skills/learned/<topic>.md`. On future matching queries, the skill is injected as system prompt context for zero-shot expertise.

### Failure Learning (opt-in, `HEADROOM_LEARN=1`)

Scans agent logs for failed tool calls, correlates errors with what worked on retry, and writes structured corrections to `AGENTS.md` under managed markers:

```
<!-- headroom:learn:start -->
### Tool Failures
- **Tool 'system_disk_usage' frequently fails** (x4) — Command timed out
### Retry Patterns
- **Retry with adjusted params on failure**
<!-- headroom:learn:end -->
```

Also available via `kinetic-cli learn scan [--apply]`.

### SOUL Evolution

Every 50 messages, the system analyzes recent conversations and appends auto-evolution notes to the agent's `SOUL.md`, gradually improving behavior over time.

---

## Tool System (80+ tools)

| Category          | Tools                                                                                                                                                                                                                                                                                                 |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **File**          | read, write, edit, delete, list, undo, download_url                                                                                                                                                                                                                                                   |
| **Code**          | run_code, execute_command, git                                                                                                                                                                                                                                                                        |
| **Browser**       | navigate, click, fill, extract, screenshot, html, close                                                                                                                                                                                                                                               |
| **Knowledge**     | query, index_file, index_url, index_github, scrape, stats                                                                                                                                                                                                                                             |
| **Email**         | read, read_body, send, reply                                                                                                                                                                                                                                                                          |
| **Web**           | web_search (Brave), news, weather                                                                                                                                                                                                                                                                     |
| **Security**      | scan_system, scan_network, process_info, kill_process, block_ip, check_logs, audit_startup, audit_tasks, audit_usb, ping_sweep, scan_ports, audit_wifi, lookup_cve, check_ip, audit_users, firewall, drive_health, persistence, defender, hosts, browser_audit, set_watch, list_watches, remove_watch |
| **Productivity**  | pomodoro, habits, obsidian (create, edit, search, graph, daily, canvas, template, tags, spaced repetition), daily_briefing                                                                                                                                                                            |
| **Communication** | send_message, send_file, spawn_specialist, spawn_swarm, generate_image, tts_speak, create_presentation                                                                                                                                                                                                |
| **Scheduling**    | schedule_task, list_tasks, remove_task, create_monitor, list_monitors, get_current_time                                                                                                                                                                                                               |
| **System**        | get_system_info, read_env_var, system_temp_cleanup, disk_usage, startup_optimize                                                                                                                                                                                                                      |
| **Context**       | share_context, get_context, list_context                                                                                                                                                                                                                                                              |
| **Other**         | zip, unzip, youtube_info, image_search, list_skills, call_opencode, apply_opencode, run_pipeline                                                                                                                                                                                                      |

See [`docs/capabilities.md`](docs/capabilities.md) for details.

---

## Context Compression (opt-in, `HEADROOM_COMPRESSION=1`)

Uses [headroom-ai](https://github.com/headroomlabs-ai/headroom) to compress JSON tool outputs before they reach the LLM:

| Compressor       | What                                             | Savings             |
| ---------------- | ------------------------------------------------ | ------------------- |
| **SmartCrusher** | JSON arrays (tool outputs, search results, logs) | 30–90%              |
| **CacheAligner** | Stabilizes prefixes for provider KV cache        | 0% (cache hit rate) |

Compression happens inline in the think loop, right before the LLM call. If it fails or inflates tokens, original messages pass through unchanged.

---

## Voice Chat

| Feature          | Detail                                                    |
| ---------------- | --------------------------------------------------------- |
| **Push-to-talk** | Press Alt+V, speak, release, hear response                |
| **System tray**  | Colored status icon (idle/recording/processing/speaking)  |
| **STT**          | Google Web Speech (default) or faster-whisper (offline)   |
| **TTS**          | Edge TTS with Microsoft Neural voices, configurable speed |
| **Interrupt**    | Press hotkey during playback to stop and re-record        |

---

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
kinetic-cli onboard
kinetic-cli models

# 3. Run
kinetic
```

Opens Telegram bot + FastAPI dashboard at `http://localhost:18789`.

### Optional features

```bash
# Compress tool outputs (30-90% fewer tokens)
export HEADROOM_COMPRESSION=1
export HEADROOM_COMPRESSION_RATIO=0.3

# Shared cross-agent memory
export HEADROOM_MEMORY=1

# Auto failure learning
export HEADROOM_LEARN=1

kinetic
```

See [`docs/setup.md`](docs/setup.md) for full installation and configuration.

---

## CLI Reference

| Command                                       | Description                          |
| --------------------------------------------- | ------------------------------------ |
| `kinetic`                                     | Run bot + API + scheduler            |
| `kinetic-cli onboard`                         | First-time setup wizard              |
| `kinetic-cli models`                          | Configure providers / stage routing  |
| `kinetic-cli agents`                          | Manage agent registry                |
| `kinetic-cli knowledge`                       | Manage knowledge base                |
| `kinetic-cli skills list/install/remove/info` | Manage skill packs                   |
| `kinetic-cli pipelines`                       | Manage pipelines                     |
| `kinetic-cli learn scan [--apply]`            | Analyze logs and learn from failures |

---

## Environment Variables

| Variable                     | Default            | Description                               |
| ---------------------------- | ------------------ | ----------------------------------------- |
| **Required**                 |                    |                                           |
| `TELEGRAM_BOT_TOKEN`         | —                  | Telegram bot token                        |
| **API**                      |                    |                                           |
| `API_PORT`                   | `18789`            | FastAPI server port                       |
| `AGENT_MEMORY_MAX`           | `200`              | Max history messages for answer stage     |
| **Voice**                    |                    |                                           |
| `HIDE_CONSOLE`               | `true`             | Hide terminal windows                     |
| `PTT_KEY`                    | `alt+v`            | Push-to-talk hotkey                       |
| `TTS_VOICE`                  | `en-GB-RyanNeural` | Edge TTS voice                            |
| `TTS_SPEED`                  | `+20%`             | TTS speaking rate                         |
| `STT_BACKEND`                | `google`           | `google` or `offline`                     |
| **headroom-ai**              |                    |                                           |
| `HEADROOM_COMPRESSION`       | —                  | Context compression (`1` to enable)       |
| `HEADROOM_COMPRESSION_RATIO` | —                  | Target keep ratio (e.g. `0.3`)            |
| `HEADROOM_MEMORY`            | —                  | Shared cross-agent memory (`1` to enable) |
| `HEADROOM_LEARN`             | —                  | Auto failure learning (`1` to enable)     |
| `HEADROOM_MODEL`             | `gpt-4o`           | Model for token counting                  |
| **LLM Providers**            |                    |                                           |
| `LIGHTNING_API_KEY`          | —                  | Lightning provider key                    |
| `GROQ_API_KEY`               | —                  | Groq provider key                         |
| `CLOUD_FLARE_API_KEY`        | —                  | Cloudflare Workers AI key                 |
| `CLOUD_FLARE_USER_ID`        | —                  | Cloudflare account ID                     |

---

## Documentation

| Document                                                   | Description                             |
| ---------------------------------------------------------- | --------------------------------------- |
| [`docs/architecture.md`](docs/architecture.md)             | System architecture and processing flow |
| [`docs/capabilities.md`](docs/capabilities.md)             | Full tool list and feature details      |
| [`docs/setup.md`](docs/setup.md)                           | Installation and configuration guide    |
| [`docs/learning-loop-idea.md`](docs/learning-loop-idea.md) | Auto-learning skill system design       |

---

## License

MIT
