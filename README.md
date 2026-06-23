# K.I.N.E.T.I.C. v2

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

**Autonomous AI assistant with Telegram bot, voice chat, 80+ tools, RAG knowledge base, and multi-agent pipelines.**

K.I.N.E.T.I.C. is a modular AI agent framework that runs on your own machine. Chat via Telegram, speak via push-to-talk voice chat, or use the web dashboard. It can scan your system for vulnerabilities, manage your Obsidian vault, track habits and pomodoro sessions, look up CVEs, check IPs against threat feeds, and more — all through a unified agent with persistent memory.

---

## Architecture

K.I.N.E.T.I.C. separates orchestration from execution through three layers:

### 1. The Dispatcher (Orchestrator)

The central coordinator manages agent lifecycle:

- **Agent Registry** — lazy-loads agents from `config/agents.json`, evicts after 5 min idle
- **Session Management** — independent conversation sessions with per-session history and profiles
- **Sub-agent Spawning** — library agents can spawn ephemeral specialists (max 3, depth 3)

### 2. The Agent (Execution)

Each agent runs a think loop with tool access:

- **SOUL personality layer** — per-agent `SOUL.md` loaded as system prompt
- **ReAct loop** — up to 3 iterations of tool call → execute → observe
- **80+ tools** — all registered globally, restricted per-agent via tool whitelist
- **Background processing** — profile extraction and context compression run deferred, never block the response

### 3. Storage & Memory

- **Persistent history** — JSONL at `agents_workspace/<agentId>/history.jsonl`
- **User profile** — LLM extracts permanent facts every 3 messages; cross-session via global profile
- **Knowledge base** — SQLite vector store with cosine similarity for RAG
- **Task scheduler** — one-time and recurring tasks persisted to disk

See [`docs/architecture.md`](docs/architecture.md) for full architecture details.

---

## Capabilities

K.I.N.E.T.I.C. ships with **80+ tools** across all categories. Full details in [`docs/capabilities.md`](docs/capabilities.md).

### Security (28 tools)
System vulnerability scanning, network monitoring, process management, firewall control, port scanning, WiFi audit, user audit, USB tracking, CVE lookup, IP threat check, Defender scan, persistence analysis, and more.

### Voice Chat
- **Push-to-talk** — press Alt+V, speak, release, hear response
- **System tray** — colored status icon (idle/recording/processing/speaking)
- **Dual STT** — Google Web Speech (online) or faster-whisper (offline, ~75MB)
- **Edge TTS** — Microsoft Neural voices with configurable speed
- **Interrupt** — press hotkey during playback to stop and re-record

### Productivity (13 tools)
Pomodoro timer, habit tracker with streaks, Obsidian vault templates, recent notes, tag cloud.

### System Maintenance (3 tools)
Temp file cleanup, disk usage analysis, startup program management.

### Network (4 tools)
DNS lookup (all record types), traceroute, domain WHOIS, bandwidth stats.

### Telegram Bot
- Chat with AI, file uploads, voice message transcription
- `/tts_on` / `/tts_off` — toggle automatic voice responses
- Session management, task scheduler, knowledge base queries

### Web Dashboard
FastAPI at `localhost:18789` with chat UI, status, sessions, knowledge base, pipeline viewer, and provider config.

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

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/tts_on` | Enable voice responses |
| `/tts_off` | Disable voice responses |
| `/models` | Show/switch provider config |
| `/status` | Bot uptime and agent info |
| `/profile` | Show what I know about you |
| `/forget_fact <keyword>` | Remove a fact from memory |
| `/reset` | Clear current conversation |
| `/session` | Manage conversation sessions |
| `/task list` | Show scheduled tasks |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token (required) |
| `API_PORT` | `18789` | FastAPI server port |
| `HIDE_CONSOLE` | `true` | Hide terminal windows |
| `PTT_KEY` | `alt+v` | Push-to-talk hotkey |
| `TTS_VOICE` | `en-GB-RyanNeural` | Edge TTS voice |
| `TTS_SPEED` | `+20%` | TTS speaking rate |
| `STT_BACKEND` | `google` | `google` or `offline` |
| `RATE_LIMIT_RETRY_SECONDS` | `3` | LLM 429 retry delay |
| `AGENT_MEMORY_MAX` | `500` | Max history messages |

---

## Deployment

### Docker

```bash
docker compose up -d --build
```

Mounts `config/`, `agents_workspace/`, `agent_sandbox/` as volumes. Reads `.env` for secrets.

---

## Testing

```bash
# Regression test (36 checks)
.venv\Scripts\python.exe regression_test.py

# Lint
ruff check .

# Type check
mypy src/
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | System architecture and processing flow |
| [`docs/capabilities.md`](docs/capabilities.md) | Full tool list and feature details |
| [`docs/setup.md`](docs/setup.md) | Installation and configuration guide |

---

## License

MIT
