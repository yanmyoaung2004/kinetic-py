from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("kinetic.scheduler")

TASKS_DIR = Path("agents_workspace")


@dataclass
class TaskEntry:
    id: str
    description: str
    type: str  # "once" | "interval"
    interval_ms: int | None = None
    next_run: str = ""
    created: str = ""
    last_run: str | None = None
    dispatch_to: str = ""
    query: str = ""
    chat_id: int | None = None


def _sanitize(id_str: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", id_str)


def _tasks_path(agent_id: str) -> Path:
    dir_path = TASKS_DIR / _sanitize(agent_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "tasks.json"


def _read_tasks(agent_id: str) -> list[dict[str, Any]]:
    p = _tasks_path(agent_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _write_tasks(agent_id: str, tasks: list[dict[str, Any]]) -> None:
    _tasks_path(agent_id).write_text(json.dumps(tasks, indent=2))


def add_task(agent_id: str, task: dict[str, Any]) -> TaskEntry:
    tasks = _read_tasks(agent_id)
    entry = TaskEntry(
        id=f"task_{int(__import__('time').time() * 1000)}",
        description=task.get("description", ""),
        type=task.get("type", "once"),
        interval_ms=task.get("interval_ms"),
        next_run=task.get("next_run", ""),
        created=datetime.now().isoformat(),
        last_run=None,
        dispatch_to=task.get("dispatch_to", agent_id),
        query=task.get("query", ""),
        chat_id=task.get("chat_id"),
    )
    tasks.append(entry.__dict__)
    _write_tasks(agent_id, tasks)
    return entry


def remove_task(agent_id: str, task_id: str) -> bool:
    tasks = _read_tasks(agent_id)
    for i, t in enumerate(tasks):
        if t.get("id") == task_id:
            tasks.pop(i)
            _write_tasks(agent_id, tasks)
            return True
    return False


def list_tasks(agent_id: str) -> list[TaskEntry]:
    return [TaskEntry(**t) for t in _read_tasks(agent_id)]


def get_overdue_tasks() -> list[dict[str, Any]]:
    now = datetime.now().timestamp() * 1000
    overdue: list[dict[str, Any]] = []

    if not TASKS_DIR.exists():
        return overdue

    for agent_dir in TASKS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        tasks = _read_tasks(agent_dir.name)
        for t in tasks:
            next_run = t.get("next_run", "")
            if next_run:
                try:
                    if datetime.fromisoformat(next_run).timestamp() * 1000 <= now:
                        overdue.append({"agent_id": agent_dir.name, "task": t})
                except (ValueError, TypeError):
                    continue

    return overdue


def get_upcoming_tasks(window_minutes: int = 5) -> list[dict[str, Any]]:
    """Return tasks due within the next N minutes (but not overdue)."""
    now = datetime.now()
    now_ts = now.timestamp() * 1000
    window_end = (now + timedelta(minutes=window_minutes)).timestamp() * 1000
    upcoming: list[dict[str, Any]] = []

    if not TASKS_DIR.exists():
        return upcoming

    for agent_dir in TASKS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        tasks = _read_tasks(agent_dir.name)
        for t in tasks:
            next_run = t.get("next_run", "")
            if next_run:
                try:
                    ts = datetime.fromisoformat(next_run).timestamp() * 1000
                    if now_ts < ts <= window_end:
                        upcoming.append({"agent_id": agent_dir.name, "task": t})
                except (ValueError, TypeError):
                    continue
    return upcoming


def mark_task_run(agent_id: str, task_id: str) -> None:
    tasks = _read_tasks(agent_id)
    for t in tasks:
        if t.get("id") == task_id:
            t["last_run"] = datetime.now().isoformat()
            if t.get("type") == "once":
                tasks.remove(t)
            elif t.get("type") == "interval" and t.get("interval_ms"):
                t["next_run"] = (datetime.now() + timedelta(milliseconds=t["interval_ms"])).isoformat()
            _write_tasks(agent_id, tasks)
            return
