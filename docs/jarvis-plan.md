# JARVIS — Ambient AI Assistant Plan

## Vision

K.I.N.E.T.I.C. evolves from "agentic framework you type commands to" into **JARVIS** — an ambient presence that knows what you're doing, talks to you naturally, and acts before you ask.

---

## Voice Input (Speech-to-Text) — ✅ DONE

Send a voice message via Telegram → transcribed via Groq Whisper → agent processes text.

| Feature | Status |
|---------|--------|
| Groq Whisper integration | ✅ Done |
| Voice message handler in Telegram | ✅ Done |
| Auto-transcription with `whisper-large-v3-turbo` | ✅ Done |

---

## Voice Output (Text-to-Speech) — 🚧 NEXT

Agent should speak back — not just show text on screen.

| Option | What | Cost | Quality |
|--------|------|------|---------|
| **ElevenLabs** | Best quality, natural voice | Paid (free tier: 10k chars/mo) | 🥇 Best |
| **Groq Whisper + edge-tts** | Free, local TTS | Free | 🥈 Good |
| **OpenAI TTS** | Via Groq-compatible endpoint | Per-token | 🥉 Decent |

**Telegram integration:**
- Agent response text → TTS → `.ogg` file → send as voice message
- Works seamlessly — you hear JARVIS talk back in the same chat
- Voice messages are native Telegram, no extra app needed

**What we'd build:**
```
Agent responds → _tts_speak("text") → ElevenLabs/edge-tts API
  → save .ogg to sandbox → send as Telegram voice reply
```

---

## Proactive Agent — Scheduled Awareness

JARVIS doesn't wait for you to ask. It tells you what you need to know.

| Trigger | What it does |
|---------|-------------|
| Morning (7 AM) | Runs daily briefing automatically — weather, news, schedule |
| Meeting 5 min before | Sends reminder + agenda if available |
| Task overdue | "Hey, your 3:30 meeting is starting" |
| Daily digest at end of day | "Here's what you did today" |

**Already have:**
- ✅ Scheduler loop runs every 10 seconds
- ✅ `daily_briefing` tool combines weather + news + schedule
- ✅ `obsidian_daily_digest` records daily notes
- ✅ `list_scheduled_tasks` shows active tasks

**What we'd build:**
- `_auto_proactive_reminder()` — check if any task is due within 5 min
- Scheduled morning briefing (7 AM auto-trigger)
- Idle detection — if user hasn't messaged in 2 hours, check in

---

## Always-On Voice (Desktop App)

| Approach | What | Complexity |
|----------|------|-----------|
| **Push-to-talk** | Press a hotkey, speak, get voice response | Medium |
| **Wake word** | Say "Hey JARVIS" -> triggers listening | Hard (needs wake-word engine) |
| **Always listening** | Continuous mic → transcribe → respond | Very hard (battery, privacy) |

**Recommendation:** Start with **push-to-talk** via the desktop app (Tauri/Electron wrapper). Wake word can come later.

---

## Smart Home Integration

| Device/Platform | How | API Key Needed? |
|----------------|-----|----------------|
| **Spotify** | `spotipy` library — play/pause/skip/volume | Spotify Dev API |
| **Philips Hue** | HTTP API — lights on/off/brightness/color | No (local network) |
| **MQTT / Home Assistant** | MQTT publish — any smart device | No (local) |
| **Windows OS** | `subprocess` — volume, sleep, lock, apps | No |

**What we'd build:**
- `smart_home` tool — `{device: "light", action: "on", value: "50%"}`
- Agent calls this when you say "turn on the lights" or "play some music"

---

## Ambient Display (Desktop Widget)

A small always-on-top window showing:
```
☀️ 10:32 AM  Yangon  +30°C
📅 Meeting at 3:30 PM
📧 2 new emails
⚡ 3 active tasks
```

**Options:**
| Approach | Tech | Time |
|----------|------|------|
| **PWA** | Web page served by FastAPI | ~2 hours |
| **Tauri desktop** | Rust + HTML widget | ~1 week |
| **Rainmeter / Widget** | Windows desktop gadget | ~1 day |

**Recommendation:** PWA first — accessible from phone browser, no install.

---

## Personality & Memory — ✅ MOSTLY DONE

| Feature | Status |
|---------|--------|
| SOUL.md personality system | ✅ Done |
| User profile (permanent facts) | ✅ Done (cleaned) |
| Conversation history with timestamps | ✅ Done |
| Memory recall (vector store) | ✅ Done |
| Profile filtering (transient = skip) | ✅ Done |
| Current time injection | ✅ Done |
| **Long-term personality evolution** | 🟡 Rate-limited, works |

---

## Multi-Platform Presence

| Platform | Status | Priority |
|----------|--------|----------|
| **Telegram** | ✅ Fully working | High |
| **Web UI** | ✅ FastAPI dashboard | High |
| **CLI** | ✅ kinetic-cli | Medium |
| **WhatsApp** | ❌ Not built | High (most used app) |
| **Discord** | ❌ Not built | Medium |
| **Desktop app** | ❌ Not built | Low |

---

## Summary: Build Order

| Phase | What | Time | Impact |
|-------|------|------|--------|
| **1** | Voice output (TTS → Telegram voice) | ~1 session | 🔥 JARVIS talks back |
| **2** | Proactive morning briefing (scheduled) | ~1 session | 🔥 No more asking |
| **3** | WhatsApp gateway | ~2 sessions | 📱 Where you already chat |
| **4** | Smart home tools (lights, music) | ~1 session | 🏠 Control your space |
| **5** | Ambient display PWA | ~1 session | 👁️ At a glance |
| **6** | Desktop app with push-to-talk | ~1 week | 🎙️ Always-on voice |

## Already Have (No Build Needed)

- Voice input (Groq Whisper) ✅
- Weather, news, schedule tools ✅
- Scheduler loop ✅
- Memory & profile system ✅
- Personality (SOUL.md) ✅
- Web UI dashboard ✅
- Telegram bot ✅
- Containerized code execution (Docker) ✅
