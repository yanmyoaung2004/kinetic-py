from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.shared_context")

CONTEXT_DIR = Path("agents_workspace") / "shared" / "context"
DEFAULT_TTL_HOURS = 24


def _ensure_dir() -> Path:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    return CONTEXT_DIR


def _path(key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", key)
    return _ensure_dir() / f"{safe}.json"


def put(key: str, value: Any, creator: str = "", ttl_hours: int = DEFAULT_TTL_HOURS) -> str:
    path = _path(key)
    data = {
        "key": key,
        "value": value,
        "creator": creator,
        "created_at": time.time(),
        "expires_at": time.time() + ttl_hours * 3600,
        "ttl_hours": ttl_hours,
    }
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
    logger.debug("[SHARED_CTX] %s set by %s (ttl=%dh)", key, creator, ttl_hours)
    return f"Context '{key}' stored (expires in {ttl_hours}h)"


def get(key: str) -> dict[str, Any] | None:
    path = _path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        expires = data.get("expires_at", 0)
        if expires > 0 and time.time() > expires:
            path.unlink(missing_ok=True)
            logger.debug("[SHARED_CTX] %s expired, purged", key)
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def delete(key: str) -> bool:
    path = _path(key)
    if path.exists():
        path.unlink()
        return True
    return False


def list_keys() -> list[dict[str, Any]]:
    _ensure_dir()
    results = []
    now = time.time()
    for p in sorted(CONTEXT_DIR.iterdir()):
        if p.suffix != ".json":
            continue
        try:
            data = json.loads(p.read_text("utf-8"))
            expires = data.get("expires_at", 0)
            if expires > 0 and now > expires:
                p.unlink(missing_ok=True)
                continue
            remaining = max(0, int((expires - now) / 3600)) if expires else -1
            results.append({
                "key": data.get("key", p.stem),
                "creator": data.get("creator", ""),
                "age_hours": round((now - data.get("created_at", now)) / 3600, 1),
                "ttl_remaining_hours": remaining,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return results


def purge_expired() -> int:
    count = 0
    _ensure_dir()
    now = time.time()
    for p in CONTEXT_DIR.iterdir():
        if p.suffix != ".json":
            continue
        try:
            data = json.loads(p.read_text("utf-8"))
            if data.get("expires_at", 0) > 0 and now > data["expires_at"]:
                p.unlink(missing_ok=True)
                count += 1
        except (json.JSONDecodeError, OSError):
            continue
    if count:
        logger.info("[SHARED_CTX] Purged %d expired entries", count)
    return count


def make_share_context_tool(agent_id: str = "unknown") -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "share_context",
                "description": (
                    "Store a value in shared context so other agents can read it. "
                    "Use this to pass structured data (config, results, references) "
                    "between agents instead of embedding everything in a text message."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Unique key name (e.g. 'project_config', 'user_preferences')",
                        },
                        "value": {
                            "type": "string",
                            "description": "The value to share (JSON string recommended for structured data)",
                        },
                        "ttl_hours": {
                            "type": "number",
                            "description": "Hours until auto-expiry (default 24, max 168)",
                            "default": 24,
                        },
                    },
                    "required": ["key", "value"],
                },
            },
        ),
        execute=lambda args, ctx: put(
            args["key"], args["value"],
            creator=agent_id,
            ttl_hours=min(int(args.get("ttl_hours", DEFAULT_TTL_HOURS)), 168),
        ),
    )


def make_get_context_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_context",
                "description": (
                    "Read a value previously stored in shared context by any agent. "
                    "Returns the value, creator, and remaining TTL. "
                    "Use this to retrieve data shared by another agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "The key to retrieve",
                        },
                    },
                    "required": ["key"],
                },
            },
        ),
        execute=lambda args, ctx: _format_get(args["key"]),
    )


def make_list_context_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "list_context",
                "description": "List all active shared context entries with their keys, creators, and TTL.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ),
        execute=lambda args, ctx: _format_list(),
    )


def _format_get(key: str) -> str:
    data = get(key)
    if data is None:
        return f"Context '{key}' not found or expired."
    remaining = ""
    expires = data.get("expires_at", 0)
    if expires:
        rem_h = max(0, int((expires - time.time()) / 3600))
        remaining = f" (TTL: {rem_h}h remaining)"
    return (
        f"Key: {key}{remaining}\n"
        f"Creator: {data.get('creator', 'unknown')}\n"
        f"Value:\n{data.get('value', '')}"
    )


def _format_list() -> str:
    entries = list_keys()
    if not entries:
        return "No active shared context entries."
    lines = [f"Shared context ({len(entries)} entries):"]
    for e in entries:
        lines.append(
            f"  - {e['key']} (by {e['creator']}, {e['age_hours']}h old, {e['ttl_remaining_hours']}h left)"
        )
    return "\n".join(lines)
