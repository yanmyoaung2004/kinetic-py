"""Guardrails — human-in-the-loop approval for destructive actions."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("kinetic.guardrails")

# Tools that require user approval before execution
GUARDED_TOOLS: dict[str, dict[str, str]] = {
    "security_kill_process": {
        "level": "destructive",
        "reason": "Terminates a running process — may cause data loss.",
    },
    "security_block_ip": {
        "level": "destructive",
        "reason": "Blocks an IP address via firewall — affects network connectivity.",
    },
    "security_unblock_ip": {
        "level": "moderate",
        "reason": "Removes a firewall rule — unblocks an IP address.",
    },
    "security_remove_firewall_rule": {
        "level": "destructive",
        "reason": "Deletes a firewall rule — changes security posture.",
    },
    "security_defender_set": {
        "level": "destructive",
        "reason": "Enables or disables Windows Defender — affects system security.",
    },
    "sandbox_delete_file": {
        "level": "destructive",
        "reason": "Permanently deletes a file — cannot be undone.",
    },
    "system_temp_cleanup": {
        "level": "moderate",
        "reason": "Deletes temporary files — may remove files in use.",
    },
    "system_startup_optimize": {
        "level": "moderate",
        "reason": "Modifies startup registry entries — affects boot behavior.",
    },
    "send_email": {
        "level": "moderate",
        "reason": "Sends an email on your behalf — verify content before sending.",
    },
}

_pending: dict[str, dict[str, Any]] = {}


def request_approval(tool_name: str, args: dict[str, Any], chat_id: int = 0) -> str:
    """Register a pending approval. Returns a task_id string like 'guard_12345'."""
    task_id = f"guard_{int(time.time() * 1000)}"
    info = GUARDED_TOOLS.get(tool_name, {"level": "unknown", "reason": "This action requires confirmation."})
    _pending[task_id] = {
        "tool": tool_name,
        "args": args,
        "chat_id": chat_id,
        "level": info["level"],
        "reason": info["reason"],
        "created": time.time(),
    }
    logger.info("[GUARD] Pending approval: %s (%s) [%s]", tool_name, task_id, info["level"])
    return task_id


def get_pending(task_id: str) -> dict[str, Any] | None:
    """Get pending approval info without consuming it."""
    return _pending.get(task_id)


def consume(task_id: str) -> dict[str, Any] | None:
    """Consume and remove a pending approval. Returns the action or None."""
    return _pending.pop(task_id, None)


def list_pending(chat_id: int) -> list[dict[str, Any]]:
    """List all pending approvals for a chat."""
    return [
        {"task_id": tid, **info}
        for tid, info in _pending.items()
        if info["chat_id"] == chat_id
    ]
