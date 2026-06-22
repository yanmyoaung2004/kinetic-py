# K.I.N.E.T.I.C. v2 — Python

Autonomous AI assistant with Telegram bot, voice chat, 35+ security/network/maintenance tools, RAG knowledge base, multi-agent pipelines, and a web dashboard.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# First-time setup
kinetic-cli onboard       # copies example configs, prompts for keys
kinetic-cli models        # configure providers and stage routing

# Run (Telegram bot + API + scheduler)
kinetic
```

## Features

### Core
- **Telegram bot** — chat with AI via Telegram, file uploads, voice messages
- **FastAPI** — REST API at `localhost:18789` with auto-docs
- **Multi-agent** — route tasks to specialized sub-agents (coding, security, obsidian)
- **RAG knowledge base** — vector store with embeddings for long-term memory
- **Scheduler** — recurring tasks, monitors, alerts
- **Tool system** — 80+ tools across all categories

### Security (28 tools)
Scan system for vulnerabilities, monitor network, check processes, manage firewall rules, scan ports, audit users, check logs, track USB devices, lookup CVEs, check IPs against threat feeds, run Defender scans, and more.

### Voice Chat
- **Push-to-talk** — press Alt+V, speak, release, hear response
- **System tray** — icon shows status (idle/recording/processing/speaking)
- **Google STT** — accurate speech-to-text via Google Web Speech API
- **Edge TTS** — natural voice output with Microsoft Neural TTS
- **Interrupt** — press hotkey during playback to stop and re-record
- **Toggle mode** — `/tts_on` for automatic voice responses in Telegram

### Productivity
- **Pomodoro timer** — focus sessions with break reminders
- **Habit tracker** — daily/weekly habits with streak tracking
- **Obsidian vault** — create/edit/search notes, templates, tag cloud

### System Maintenance
- Temp file cleanup, disk usage analysis, startup program management

### Dev Tools
- Code execution (sandboxed), git operations, OpenCode integration

## Commands

```
/help          — Show all commands
/tts_on        — Enable voice responses (TTS mode)
/tts_off       — Disable voice responses
/models        — Show/switch provider config
/session       — Manage conversation sessions
/reset         — Clear current conversation
/profile       — View learned profile
/task list     — Show scheduled tasks
```

## Voice Chat (standalone)

```bash
voice.bat       # Launches kinetic + voice chat, no console windows
# Or:
py voice_chat.py
```

Requires admin (for global hotkey). Configure via env vars:
- `PTT_KEY` — hotkey (default: `alt+v`)
- `TTS_VOICE` — voice (default: `en-GB-RyanNeural`)
- `TTS_SPEED` — speaking rate (default: `+20%`)

## Architecture

See `docs/architecture.md` for full details.

Key stack:
- **Python 3.13+** — core language
- **python-telegram-bot** — Telegram integration
- **FastAPI** — REST API + Swagger docs
- **edge-tts** — text-to-speech (Microsoft Neural voices)
- **PyAudio** — microphone input / speaker output
- **httpx** — async HTTP for LLM providers
- **click** — CLI framework
- **pytest** — test suite

## Skills (Plugin System)

```bash
kinetic-cli skills list
kinetic-cli skills install web-research
kinetic-cli skills remove web-research
```

## Dependencies

- Python 3.12+
- See `pyproject.toml` for full list
- Windows required for voice chat (PyAudio + keyboard hooks)
