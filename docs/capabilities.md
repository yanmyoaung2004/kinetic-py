# K.I.N.E.T.I.C. — Capabilities

## Agent Framework

- **Dispatcher-registry architecture** — lazy-loads agents, evicts after 5 min idle
- **Sub-agent spawning** — library agents with `can_delegate: true` spawn ephemeral specialists (max 3, depth 3)
- **Inter-agent messaging** — `send_message` to any registered agent by ID
- **SOUL personality layer** — per-agent `SOUL.md` loaded as system prompt
- **ReAct-style reasoning** — visible tool call cycles with think/execute loop
- **Session management** — `/session new`, `/session list`, `/session <id>`

## Memory & User Profile

- **Persistent history** — JSONL at `agents_workspace/<agentId>/history.jsonl`
- **Capped at 500 messages** (configurable via `AGENT_MEMORY_MAX`)
- **Context compression** — old exchanges summarized into `[COMPRESSED HISTORY]` when exceeding threshold
- **User profile extraction** — background LLM extracts permanent facts every 3 messages
- **All background tasks deferred** — never blocks the user-facing reply

## Tool System — 80+ Tools

All tools registered globally, restricted per-agent via `"tools"` whitelist in `agents.json`.

### File & Code (9)
`read_file`, `write_file`, `edit_file`, `delete_file`, `list_files`, `undo_file`, `download_url`, `execute_command`, `run_code`

### System & Maintenance (6)
`get_current_time`, `get_system_info`, `read_env_var`, `system_temp_cleanup`, `system_disk_usage`, `system_startup_optimize`

### Browser (7)
`browser_navigate`, `browser_click`, `browser_fill`, `browser_extract`, `browser_screenshot`, `browser_html`, `browser_close`

### Communication (5)
`send_file`, `send_message`, `send_email`, `read_emails`, `read_email_body`, `reply_to_email`

### Knowledge & Search (7)
`query_knowledge_base`, `index_file`, `index_url`, `index_github`, `scrape_and_index`, `knowledge_stats`, `web_search`

### Security (28)
`security_scan_system`, `security_scan_network`, `security_process_info`, `security_kill_process`, `security_block_ip`, `security_unblock_ip`, `security_check_logs`, `security_audit_startup`, `security_audit_scheduled_tasks`, `security_audit_usb`, `security_generate_report`, `security_ping_sweep`, `security_scan_ports`, `security_audit_wifi`, `security_lookup_cve`, `security_check_ip`, `security_audit_users`, `security_firewall_rules`, `security_drive_health`, `security_persistence_check`, `security_defender_scan`, `security_hosts_check`, `security_browser_audit`, `security_remove_firewall_rule`, `security_defender_set`, `security_elevate_bot`, `security_set_watch`, `security_list_watches`, `security_remove_watch`

### Network (4)
`network_dns_lookup`, `network_traceroute`, `network_whois`, `network_bandwidth`

### Productivity (13)
`pomodoro_start`, `pomodoro_status`, `pomodoro_stats`, `pomodoro_stop`, `habit_add`, `habit_log`, `habit_unlog`, `habit_list`, `habit_stats`, `habit_remove`, `obsidian_template`, `obsidian_recent`, `obsidian_tags`

### Other (7)
`generate_image`, `image_search`, `spawn_specialist`, `schedule_task`, `create_monitor`, `list_monitors`, `run_pipeline`, `get_youtube_info`, `zip`, `unzip`, `git`, `weather`, `news`, `daily_briefing`, `list_skills`, `call_opencode`, `apply_opencode`, `create_presentation`

## Voice Chat

- **Push-to-talk** — press Alt+V, speak, release, hear response
- **System tray app** — icon shows idle/recording/processing/speaking states
- **Google Web Speech STT** — accurate, free, no API key
- **Offline STT** — faster-whisper backend via STT_BACKEND=offline (~75MB model, fully offline)
- **Edge TTS** — Microsoft Neural voices, configurable speed and voice
- **Interrupt** — press hotkey during playback to stop and re-record
- **Restart** — tray menu restarts the server
- **Settings UI** — Tkinter dialog to edit env vars (API URL, hotkey, voice, speed)

## Security Tools

| Category | Tools |
|----------|-------|
| **Scanning** | system scan, network scan, process info, check logs, ping sweep, port scan |
| **Threat Intel** | CVE lookup, IP check (AbuseIPDB) |
| **Firewall** | list rules, block IP, unblock IP, remove rule |
| **Audit** | users, startup programs, scheduled tasks, USB devices, WiFi audit, drive health, persistence check, browser policies |
| **Defender** | scan (quick/full), enable/disable real-time protection, enable/disable antivirus |
| **Monitoring** | create watch, list watches, remove watch |
| **Maintenance** | temp cleanup, disk usage, startup optimize |

## Knowledge Base (RAG)

- **Embedding** via any OpenAI-compatible provider
- **Vector store** — JSON-based with cosine similarity
- **Index sources**: files, URLs, GitHub, any scraped page
- **Query**: returns top-5 chunks with relevance scores

## Task Scheduler

- One-time and recurring tasks
- Persisted to `agents_workspace/<id>/tasks.json`
- Daemon ticks every 10s, dispatches to agent, sends to Telegram
- Commands: `/task list`, `/task remove <id>`

## LLM Provider System

- **Unified client** — works with any OpenAI-compatible endpoint
- **Stage-based routing** — think stage with fallback chain
- **Provider failover** — `fallbacks` tried in order on failure
- **429 retry** — configurable via `RATE_LIMIT_RETRY_SECONDS` env var
- **Runtime override** — `/models set think <provider> [model]`

## Web UI Dashboard (FastAPI)

- Auto-starts on port `18789` (configurable via `API_PORT`)
- Chat interface, session manager, knowledge viewer, pipeline viewer

### REST API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/chat` | POST | `{ message, session_id, voice }` → `{ response }` |
| `/api/chat/upload` | POST | File upload + message |
| `/api/sessions` | GET/POST | List/create sessions |
| `/api/status` | GET | Uptime, agents, session |
| `/api/knowledge` | GET | Stats + document list |

## Telegram Bot

- Auto-reconnect on polling errors
- Allowlist auth from `TELEGRAM_ALLOWLIST` (empty = open)
- Typing indicator, file uploads, voice message transcription
- TTS mode: `/tts_on` sends responses as voice messages

### Commands

| Command | Description |
|---|---|
| `/help` | All commands |
| `/tts_on` | Enable voice responses |
| `/tts_off` | Disable voice responses |
| `/models` | Show/switch provider config |
| `/providers` | List endpoints |
| `/status` | Bot uptime, agents |
| `/profile` | Extracted user profile |
| `/reset` | Clear current session |
| `/session` | Manage sessions |
| `/task list` | Scheduled tasks |
| `/task remove` | Remove task |
| `/knowledge` | Knowledge base stats |
| `/search` | Search conversation history |
| `/workflows` | Learned workflows |

## Architecture

```
Telegram ─┐    Web UI ───┐    Voice Chat ──┐
           ▼             ▼                ▼
    ┌──────────────────────────────────────────┐
    │              Dispatcher                  │
    │  (orchestrator.py)                       │
    └────────────────┬─────────────────────────┘
                     │
    ┌────────────────┴─────────────────────────┐
    │              Agent (agent.py)             │
    │  • think loop (3 iter)                   │
    │  • profile extraction                    │
    │  • context compression                   │
    │  • SOUL personality                      │
    │  • 80+ tools                             │
    └────────────────┬─────────────────────────┘
                     │
    ┌────────────────┴─────────────────────────┐
    │          UnifiedProvider                  │
    │  (OpenAI-compatible, failover chain)     │
    └──────────────────────────────────────────┘
```

## Processing Flow

1. Message arrives (Telegram / Web UI / Voice Chat)
2. Agent loads SOUL + history + profile
3. **Think** loop (up to 3 iterations):
   - LLM receives history + tools
   - Tool call → execute → loop
   - Text response → return
4. Background: profile extraction + compression

## CLI Tools

- `kinetic` — run bot + API + scheduler
- `kinetic-cli onboard` — setup wizard
- `kinetic-cli models` — configure providers/stages
- `kinetic-cli skills` — manage skill packs
