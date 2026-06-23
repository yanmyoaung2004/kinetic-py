# K.I.N.E.T.I.C. v2 — Python

Autonomous AI assistant with Telegram bot, voice chat, 35+ security/network/maintenance tools, RAG knowledge base, multi-agent pipelines, and a web dashboard.

## Docker Deployment

```bash
# Build and run
docker compose up -d

# Check logs
docker compose logs -f

# Stop
docker compose down
```

Or build manually:

```bash
docker build -t kinetic .
docker run -d --name kinetic --env-file .env -p 18789:18789 -v ./config:/app/config -v ./agents_workspace:/app/agents_workspace -v ./agent_sandbox:/app/agent_sandbox kinetic
```

Note: Voice chat features are Windows-only (PyAudio, keyboard hooks) and don't run in Docker. The Docker image runs the bot server (Telegram + API + scheduler).

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
- **Cross-session memory** — facts learned in one session persist across all sessions via global profile. `/forget_fact <keyword>` to remove specific facts.

### Voice Chat
- **Push-to-talk** — press Alt+V, speak, release, hear response
- **System tray** — icon shows status (idle/recording/processing/speaking)
- **Google STT** — accurate speech-to-text via Google Web Speech API
- **Offline STT** — set `STT_BACKEND=offline` for faster-whisper (fully offline, ~75MB model)
- **Edge TTS** — natural voice output with Microsoft Neural TTS
- **Interrupt** — press hotkey during playback to stop and re-record
- **Toggle mode** — `/tts_on` for automatic voice responses in Telegram

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
/forget_fact   — Remove a fact from my memory (e.g., /forget_fact my location)
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
- `STT_BACKEND` — `google` (default, online) or `offline` (faster-whisper)

## Desktop UI (Tauri)

A native desktop app is available in `src-tauri/` (requires Visual Studio 2022 Build Tools):

```bash
cd src-tauri
cargo tauri build
```

Or run the web dashboard at `http://localhost:18789` while kinetic is running.

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
