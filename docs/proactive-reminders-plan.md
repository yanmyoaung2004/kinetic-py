# Proactive Reminders — Plan

## Goal

K.I.N.E.T.I.C. proactively notifies you about upcoming tasks and delivers a morning briefing without being asked.

## Already Have

- Scheduler loop runs every 10 seconds ✅
- `get_overdue_tasks()` — checks `tasks.json` for past-due tasks ✅
- Telegram bot can send messages proactively ✅
- `daily_briefing` tool combines weather + news + schedule ✅
- `list_scheduled_tasks` shows active tasks ✅

## What to Build

### 1. Upcoming Reminders (5 min warning)

In the scheduler loop, check for tasks due within the next 5 minutes:

```
Task: "Meeting at 3:30 PM"   now: 3:25 PM → "5 min warning" → send reminder
```

Add a `get_upcoming_tasks(minutes=5)` function to `scheduler.py`.

### 2. Morning Briefing (7 AM auto-trigger)

When the scheduler detects it's 7 AM and the briefing hasn't been sent today, auto-send the daily briefing.

### 3. Idle Check-in (Optional)

If user hasn't sent a message in 2+ hours, send a casual check-in:
```
"Hey, been a while. Anything on your mind?"
```

## Implementation

### scheduler.py changes
- Add `get_upcoming_tasks(window_minutes: int)` — returns tasks where `0 < next_run - now < window_minutes`
- Add `_last_briefing_date` tracking to avoid duplicate daily briefings

### main.py changes
- In `_scheduler_loop`, after processing overdue tasks:
  1. Check for upcoming tasks → send reminder via Telegram
  2. Check if briefing is due (7 AM, not sent today) → send briefing
