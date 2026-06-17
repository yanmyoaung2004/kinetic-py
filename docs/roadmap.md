# K.I.N.E.T.I.C. — Roadmap

## ✅ Done

### Core
- Multi-provider LLM routing with stage-based failover (classify → think → tool_call → answer)
- UnifiedProvider — single class for any OpenAI-compatible endpoint
- Agent registry + lifecycle (lazy-load, 5min idle eviction)
- Sub-agent spawning (depth 3, max 3 children)
- Inter-agent messaging
- Session management with independent history

### Memory
- JSONL conversation history with 500-msg cap
- Auto-compression for long conversations
- User profile extraction every 3 messages
- Vector store (SQLite + numpy) for long-term memory
- Session snapshots every 5 messages → persisted across sessions
- Memory recall on every message (semantic search)

### Tools (37)
- File ops (read/write/edit/delete/list/undo)
- Knowledge base (query/index/index_url/knowledge_stats)
- Web search (Brave), GitHub index, web scraper
- Email (read/send/reply)
- Browser automation (navigate/click/fill/extract/screenshot/html/close)
- Code execution via Docker sandbox (persistent container, falls back to subprocess)
- Schedule tasks + monitors
- System info, env vars, download URL
- Pipeline execution
- Image generation
- Skill listing

### Skill System
- Installable sub-agent skill packs (skill.json + SOUL.md)
- Tool whitelist per agent (agents.json `"tools"` array)
- `kinetic-cli skills list/install/remove/info`
- `--url` flag for any GitHub repo
- 5 starter skills (web-research, file-organizer, email-assistant, code-runner, scheduler)

### Interfaces
- Telegram bot with 15+ commands
- FastAPI web UI with chat, models, agents, knowledge, pipelines, sessions
- CLI (onboard, models, agents, knowledge, pipelines, skills)

### Code Quality
- ruff: 0 errors (186 fixed)
- mypy: 0 errors (64 fixed)
- 89/89 tests passing
- 34 files reformatted

---

## 🚧 Next

### Short-term (1-2 sessions)

| Priority | Feature | Why |
|----------|---------|-----|
| 🔴 | **Auto-fetch fresh emails** — when user asks about email, always call `read_emails` instead of relying on cached profile data | Profile caches stale email content |
| 🟡 | **Streaming responses** — return tokens as they arrive instead of waiting for full response | Feels faster and more responsive |
| 🟡 | **Discord gateway** — add Discord bot alongside Telegram | Broader reach, user requested |
| 🟢 | **`/health` endpoint** — for container orchestration / uptime monitoring | Needed for deployment |

### Medium-term (3-5 sessions)

| Feature | Why |
|---------|-----|
| **Skill builder** — a Web UI page to create/configure skills without editing JSON | Makes skills accessible to non-technical users |
| **Skill store repo** — create `github.com/kinetic-skills/skills` with community CI | `kinetic-cli skills install <name>` works from anywhere |
| **Multi-user** — per-user sessions, auth, allowlist management | Share with family/team |
| **PWA** — progressive web app for mobile, installable on phone | No app store needed |
| **SOUL auto-evolution** — agent reflects on conversations and improves its own SOUL.md | Unique differentiator |

### Long-term

| Feature | Why |
|---------|-----|
| **Plugin API** — third-party developers write tools without modifying core code | Ecosystem growth |
| **Multi-agent swarms** — parallel sub-agent spawning for complex tasks | Speed up multi-step workflows |
| **Function calling gateway** — expose agent as OpenAI-compatible API endpoint | Integrate with any OpenAI-compatible tool |
| **Desktop app** — Tauri/Electron wrapper with system tray | Always-on assistant |
| **Mobile app** — native iOS/Android with push notifications | True daily driver |

---

## Current Architecture

```
Telegram / Web UI / CLI
        │
  KinetiCDispatcher
        │
  AgentInstance.process()
        │
  ├── Classify (multi mode)
  ├── Think loop (up to 5 iterations)
  │     └── LLM call → Tool execution → repeat
  ├── Recall past memories (vector DB)
  ├── Snapshot every 5 messages (vector DB)
  ├── Compress long history (vector DB)
  ├── Polish response (multi mode)
  └── Extract user profile (every 3 msgs)
```

## Config

```
config/
├── models.json          — providers, stages, embedding
├── agents.json          — agent registry + tool whitelists
├── skills/              — installed skill packs
│   ├── web-research/
│   ├── file-organizer/
│   ├── email-assistant/
│   ├── code-runner/
│   └── scheduler/
└── <agent-id>/
    └── SOUL.md           — per-agent personality
```
