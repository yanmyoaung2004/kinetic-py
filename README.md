# K.I.N.E.T.I.C. v2

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

**Autonomous AI assistant with Telegram bot, voice chat, 80+ tools, RAG knowledge base, multi-agent pipelines, and multi-stage LLM routing.**

K.I.N.E.T.I.C. is a modular AI agent framework that runs on your own machine. Chat via Telegram, speak via push-to-talk voice chat, or use the web dashboard. It can scan your system for vulnerabilities, manage your Obsidian vault, track habits and pomodoro sessions, look up CVEs, check IPs against threat feeds, and more — all through a unified multi-agent system with persistent memory and auto-learning.

---

## Architecture

### Multi-Stage LLM Routing

K.I.N.E.T.I.C. uses a **multi-stage pipeline** where each stage is handled by a different provider optimized for its job:

```
User message
  │
  ├── 1. Classify (Groq) — determines intent: question / command / chitchat / task
  │     No history, just the message. ~100 tokens.
  │
  ├── 2. Think (Cloudflare → Groq → Lightning) — decides what tools to call
  │     Lean context: system prompt + current message only. No history. ~4K tokens.
  │     Falls back through providers if tool calling isn't supported.
  │
  ├── 3. Answer (Lightning → Groq) — formats the final response
  │     Full history + tool results for context-aware formatting.
  │     History length controlled by AGENT_MEMORY_MAX env var (default 200).
  │
  └── Background tasks (deferred, never block response):
        ├── User profile extraction (every 3 msgs)
        ├── Knowledge injection to Obsidian vault (every 10 msgs)
        ├── Context compression
        ├── Skill learning (auto after multi-step success)
        └── SOUL evolution
```

See [`docs/architecture.md`](docs/architecture.md) for full architecture details.

---

### Multi-Agent Delegation

The main agent is a **thin orchestrator** with ~15 core tools. Specialized tasks are delegated via `send_message` to sub-agents.

```
main agent (orchestrator, 15 tools)
  ├── obsidian-assistant    [15 tools] — vault: create, search, link, template, tags
  ├── coding-assistant      [21 tools] — code: write, debug, git, opencode
  ├── security-agent        [35 tools] — system: scan, firewall, CVE, IP check, network
  ├── productivity-agent    [11 tools] — habits, pomodoro
  └── system-agent          [ 4 tools] — temp cleanup, disk, startup
```

Each specialist has only the tools it needs. The main agent delegates rather than doing specialist work itself.

---

### Self-Improving Learning Loop

After every successful multi-step response (2+ tool calls), the system automatically generates a reusable skill document:

- **Trigger** — background task after multi-step success
- **Extract** — the user's request, tool sequence, and agent used
- **Generate** — a SOUL.md skill document at `config/skills/learned/<topic>.md`
- **Reuse** — on future matching queries, the skill is injected as system prompt context

Commands: `/skills` (list), `/forget_skill <name>` (remove)

---

### Memory & Learning

| Layer | What | How | Cost |
|-------|------|-----|------|
| **Conversation history** | Last 500 messages | JSONL file, trimmed oldest-first | ~20-50K tokens (dominant cost) |
| **User profile** | Your facts & preferences | Extracted by LLM every 3 msgs, persists across sessions | ~200 tokens |
| **Vector RAG** | Past memories as embeddings | Cosine similarity search, recalled before each response | ~300 tokens |
| **Obsidian auto-indexing** | Your vault notes | Auto-searched on relevant queries | ~500 tokens (conditional) |
| **Learned skills** | Successful tool sequences | Auto-saved as SOUL.md, injected on matching queries | ~300 tokens (conditional) |

See [`docs/capabilities.md`](docs/capabilities.md) for the full tool list (80+ tools).

---

### Provider Configuration

Configured in `config/models.json`. Each stage has its own provider with fallback chain:

```
classify:  Groq → Lightning
think:     Cloudflare → Groq → Lightning
tool_call: Lightning → Groq
answer:    Lightning → Groq
```

See [`docs/setup.md`](docs/setup.md) for installation and configuration.

---

## Quick Start

### Prerequisites

- Python 3.12+
- Windows (for voice chat with PyAudio + keyboard hooks)
- Telegram API token

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Configure

```bash
kinetic-cli onboard       # First-time setup wizard
kinetic-cli models        # Configure LLM providers
```

Copy `.env.example` to `.env` and set at minimum:

```
TELEGRAM_BOT_TOKEN=your_token_here
```

### 3. Run

```bash
kinetic
```

Opens Telegram bot + FastAPI dashboard at `http://localhost:18789`.

### 4. Voice Chat (optional)

```bash
voice.bat           # Launches kinetic + voice chat, no console windows
```

Requires admin for global hotkey.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (required) |
| `API_PORT` | `18789` | FastAPI server port |
| `AGENT_MEMORY_MAX` | `200` | Max history messages for answer stage |
| `HIDE_CONSOLE` | `true` | Hide terminal windows |
| `PTT_KEY` | `alt+v` | Push-to-talk hotkey |
| `TTS_VOICE` | `en-GB-RyanNeural` | Edge TTS voice |
| `TTS_SPEED` | `+20%` | TTS speaking rate |
| `STT_BACKEND` | `google` | `google` or `offline` |
| `RATE_LIMIT_RETRY_SECONDS` | `3` | LLM 429 retry delay |
| `LIGHTNING_API_KEY` | — | Lightning provider key |
| `GROQ_API_KEY` | — | Groq provider key |
| `CLOUD_FLARE_API_KEY` | — | Cloudflare Workers AI key |
| `CLOUD_FLARE_USER_ID` | — | Cloudflare account ID |

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | System architecture and processing flow |
| [`docs/capabilities.md`](docs/capabilities.md) | Full tool list and feature details |
| [`docs/setup.md`](docs/setup.md) | Installation and configuration guide |
| [`docs/learning-loop-idea.md`](docs/learning-loop-idea.md) | Auto-learning skill system design |

---

## License

MIT
