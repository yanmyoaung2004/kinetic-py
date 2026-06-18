# Daily Life Briefing — Plan

## Goal

A morning briefing and on-demand daily assistant that tells you the weather, today's news, your schedule, and any reminders — all in one natural message.

## Architecture

```
User: "good morning" or "daily briefing"
         │
         ▼
  _auto_morning_briefing()  ← intercepts "good morning" etc.
         │
         ├── get_weather(location)      → wttr.in (no API key)
         ├── get_news_headlines()        → Brave Search or RSS
         ├── list_scheduled_tasks()      → existing scheduler
         └── obsidian_daily_note()       → read/create daily note
         │
         ▼
  Composed response with all info
```

## Phase 1 — Tools (3 new tools)

### 1. `get_weather`
- Uses `wttr.in` (free, no API key, curl-based)
- Returns: temperature, conditions, humidity, wind, forecast
- Parameter: `location` (default: from env or auto-detect)

### 2. `get_news`
- Uses existing Brave Search with news query
- Or: RSS feed scraper for top headlines
- Returns: 5-7 headlines with brief summaries

### 3. `daily_briefing`
- Combines weather + news + tasks + daily note status
- One-call convenience tool
- Parameters: none (auto-detects everything)

## Phase 2 — Auto-detection

Intercept "good morning", "daily briefing", "morning", "what's my day like" etc.
→ Call `daily_briefing` → compose natural response.

## Phase 3 — Scheduling

Auto-trigger daily briefing at a configurable time (e.g., 7:00 AM)
→ Creates a scheduled task that runs the briefing
→ Sends result to Telegram

## Files to create

```
src/agents/tools/weather_tool.py     — get_weather
src/agents/tools/news_tool.py        — get_news_headlines
src/agents/tools/briefing_tool.py    — daily_briefing (combiner)
```

## Config

```env
# Optional overrides
WEATHER_LOCATION=Yangon, Myanmar
NEWS_TOPICS=technology,ai,programming
DAILY_BRIEF_TIME=07:00
```

## No API keys needed

- Weather → wttr.in (free)
- News → Brave Search (already configured) or RSS
- Schedule → existing scheduler
- Notes → existing Obsidian tools
