# K.I.N.E.T.I.C. Architecture

## Overview

K.I.N.E.T.I.C. is an autonomous AI agent framework built on Python. It features multi-agent orchestration with a thin orchestrator and specialized sub-agents, stage-based LLM routing with failover, 80+ tools distributed across agents, persistent memory with RAG, a self-improving learning loop, multi-platform interfaces (Telegram + Web + Voice Chat), and an installable skill system.

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
  AgentInstance — MAIN (agent.py) [~15 core tools]
         │
         ├── Orchestrator — routes tasks via send_message
         │
         ├── ▶ obsidian-assistant  [15 obsidian tools]
         ├── ▶ coding-assistant    [21 coding tools]
         ├── ▶ security-agent      [33 security + network tools]
         ├── ▶ productivity-agent  [10 habit + pomodoro tools]
         └── ▶ system-agent        [3 maintenance tools]
         │
         ├── Self-improving learning loop
         │    └── Auto-generates skill SOUL.md from multi-step sequences
         │
         └── Background tasks:
              ├── Profile extraction (every 3 msgs)
              ├── Knowledge injection (every 10 msgs)
              ├── Context compression
              └── SOUL evolution
          └── Skill learning (auto after multi-step success)
```

---

## Agent Architecture

The main agent is a **thin orchestrator** with ~15 core tools (file ops, scheduling, delegation). Specialized tasks are delegated via `send_message` to sub-agents. The main agent does NOT have web_search, execute_command, or specialist tools — it is forced to delegate.

| Agent | Tools | Purpose |
|-------|-------|---------|
| **main** | File ops, send_message, schedule, spawn_specialist, tts_speak | Orchestrator — routes tasks, handles simple file/ schedule requests |
| **obsidian-assistant** | obsidian_create/edit/search, template, recent, tags, daily, flashcards | Second brain — manages Obsidian vault |
| **coding-assistant** | File ops, git, run code, opencode, execute commands | Software development tasks |
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

## Self-Improving Learning Loop

When the agent solves a multi-step task (2+ tool calls), it automatically generates a reusable skill document:

1. **Trigger** — after every successful multi-step response
2. **Extract** — the user's request, tool sequence, and agent used
3. **Generate** — a SOUL.md skill document at `config/skills/learned/<topic>.md`
4. **Index** — stores trigger keywords for matching
5. **Reuse** — on future matching queries, the skill is injected as system prompt context

This replaces the old manual `/perfect` workflow system with automatic, persistent skill learning.

**Commands:**
- `/skills` — list all learned skills
- `/forget_skill <name>` — remove a learned skill

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
| **Voice** | edge-tts + pyaudio | Text-to-speech + audio playback |
| **STT** | Google Web Speech / faster-whisper | Speech-to-text (online or offline) |

---

## Multi-Stage LLM Routing

K.I.N.E.T.I.C. uses a multi-stage pipeline where each stage uses a different provider optimized for its job:

| Stage | Provider (chain) | Context | Purpose |
|-------|-----------------|---------|---------|
| **Classify** | Groq → Lightning | Message only (~100 tokens) | Determine intent (question/command/chitchat/task) |
| **Think** | Cloudflare → Groq → Lightning | Lean: system + message + tools (~4K tokens) | Decide what tools to call, execute tools |
| **Answer** | Lightning → Groq | Full: AGENT_MEMORY_MAX messages (~4-20K tokens) | Format final response with full context |

The **think stage is lean** — it receives only the system prompt, tool definitions, and the current user message. No conversation history. This keeps token usage low (~4K) and allows Cloudflare's 32K context window to work comfortably.

The **answer stage** receives the full conversation history (controlled by `AGENT_MEMORY_MAX`, default 200 messages) plus the raw response from the think stage, and produces a polished, context-aware final response.

### Processing Flow

```
1. Message arrives (Telegram / Web UI / Voice Chat)
2. Background context: memory recall + Obsidian auto-indexing + matching learned skills
3. Stage 1 — Classify: "question" / "command" / "chitchat" / "task"
   → If chitchat: responds directly without tools
4. Stage 2 — Think loop (up to 3 iterations):
   - LLM receives lean context (no history) + tool definitions
   - Tool call → execute → loop
   - Text response → proceed to answer stage
5. Stage 3 — Answer: formats final response with full history + tool results
6. Response sent to user (text + optional TTS)
7. Background tasks (deferred): profile extraction, context compression, knowledge injection, skill learning
```

In **single mode** (`"mode"` not set), all stages collapse into one think loop with full history — same behavior as before.

---

## Thin Specialist Agents

Specialists (`security-agent`, `coding-assistant`, etc.) can be configured as lightweight executors rather than full agents using config flags in `agents.json`:

| Flag | Default | Effect |
|------|---------|--------|
| `soul_trimmed` | `false` | Replaces full SOUL.md with `"You are {id}. Execute what's requested. Output concisely."` |
| `skip_recall` | `false` | Skips vector store query for past memories |
| `skip_auto_learn` | `false` | Skips skill extraction from tool sequences |
| `ephemeral` | `false` | In-memory only — no disk I/O for history or profiles |
| `max_iterations` | `3` | Caps the think loop iterations |

The **main agent** always runs as a full agent (all flags default to `false`). Specialists become thin executors: no SOUL overhead, no memory persistence, no background tasks, no recall queries.

```
main agent        → full agent (SOUL, memory, recall, evolution, auto-learn)
specialists       → thin executors (trimmed SOUL, ephemeral memory, no recall, no auto-learn)
```
