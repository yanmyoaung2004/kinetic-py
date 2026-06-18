"""OpenCode integration — delegates complex coding tasks to OpenCode CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

DEFAULT_DIR = os.environ.get("OPENCODE_PROJECT_DIR", ".")
DEFAULT_MODEL = os.environ.get("OPENCODE_DEFAULT_MODEL", "")  # empty = let OpenCode decide


async def _call_opencode(args: dict[str, Any], ctx: ToolContext | None) -> str:
    task = args.get("task", "").strip()
    if not task:
        return "ERROR: 'task' parameter is required."

    project_dir = (args.get("dir") or DEFAULT_DIR).strip()
    model = args.get("model") or DEFAULT_MODEL

    project_path = Path(project_dir).resolve()
    if not project_path.is_dir():
        return f"ERROR: Project directory not found: {project_dir}"

    # Build opencode command
    cmd = ["opencode", "run", "--dangerously-skip-permissions", "--format", "json"]
    if model:
        cmd += ["--model", model]
    cmd.append(task)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=300,  # 5 min timeout
            cwd=project_path,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: OpenCode task timed out after 5 minutes."
    except FileNotFoundError:
        return "ERROR: 'opencode' not found in PATH. Install OpenCode first."

    stdout = proc.stdout or ""

    # Parse JSON events
    files_changed: list[dict[str, str]] = []
    total_cost = 0.0
    final_text = ""

    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        typ = event.get("type", "")
        part = event.get("part", {})

        # Track file writes
        if typ == "tool_use" and isinstance(part, dict):
            tool = part.get("tool", "")
            state = part.get("state", {})
            inp = state.get("input", {})
            if tool == "write" and inp.get("filePath"):
                files_changed.append({
                    "path": str(inp["filePath"]),
                    "content": str(inp.get("content", "")),
                })

        # Track cost
        if typ == "step_finish" and isinstance(part, dict):
            cost = part.get("cost", 0)
            if isinstance(cost, (int, float)):
                total_cost += cost

        # Track text output
        if typ == "text" and isinstance(part, dict):
            text = part.get("text", "")
            if text:
                final_text += text + "\n"

    # Get git diff after changes
    diff_after = ""
    try:
        diff_result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, timeout=10, cwd=project_path,
        )
        diff_after = diff_result.stdout.strip()
    except Exception:
        pass

    # Build summary
    summary_parts = [f"OpenCode completed task: {task[:80]}"]

    if files_changed:
        summary_parts.append(f"\nFiles modified ({len(files_changed)}):")
        for f in files_changed:
            rel = Path(f["path"])
            try:
                rel_path = rel.relative_to(project_path)
            except ValueError:
                rel_path = rel
            summary_parts.append(f"  • {rel_path}")
    else:
        summary_parts.append("\nNo files were modified.")

    if total_cost > 0:
        summary_parts.append(f"\nToken cost: ${total_cost:.5f}")

    if diff_after:
        # Truncate diff if very long
        if len(diff_after) > 2000:
            diff_after = diff_after[:2000] + "\n... (diff truncated)"
        summary_parts.append(f"\nDiff:\n{diff_after}")

    if final_text:
        summary_parts.append(f"\nOpenCode says: {final_text[:500].strip()}")

    # Store files_changed in a temp marker so apply/reject can use it
    _pending_opencode[task] = {
        "files": files_changed,
        "project": str(project_path),
        "diff": diff_after,
    }

    return "\n".join(summary_parts)


# Store last opencode result so apply/reject can access it
_pending_opencode: dict[str, dict[str, Any]] = {}


async def _apply_opencode_changes(args: dict[str, Any], ctx: ToolContext | None) -> str:
    action = args.get("action", "apply").strip().lower()
    task = args.get("task", "")

    # Find the pending result
    pending = None
    if task and task in _pending_opencode:
        pending = _pending_opencode.pop(task, None)
    elif _pending_opencode:
        # Use most recent
        last_key = list(_pending_opencode.keys())[-1]
        pending = _pending_opencode.pop(last_key, None)

    if not pending:
        return "No pending OpenCode changes. Run call_opencode first."

    project = Path(pending["project"])

    if action in ("apply", "yes", "approve", "commit"):
        try:
            result = subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, text=True, timeout=10, cwd=project,
            )
            commit_msg = f"opencode: {task[:60]}" if task else "opencode: automated changes"
            result = subprocess.run(
                ["git", "commit", "-m", commit_msg],
                capture_output=True, text=True, timeout=10, cwd=project,
            )
            if result.returncode == 0:
                return f"✓ Changes committed.\n{result.stdout.strip()}"
            else:
                return f"Commit result: {result.stdout.strip()}\n{result.stderr.strip()}"
        except Exception as e:
            return f"ERROR: Failed to commit: {e}"

    elif action in ("reject", "no", "discard", "reset"):
        try:
            result = subprocess.run(
                ["git", "checkout", "--", "."],
                capture_output=True, text=True, timeout=10, cwd=project,
            )
            return "✗ Changes discarded. Working tree cleaned."
        except Exception as e:
            return f"ERROR: Failed to discard: {e}"

    elif action in ("diff", "show"):
        if pending.get("diff"):
            d = pending["diff"]
            if len(d) > 3000:
                d = d[:3000] + "\n... (truncated)"
            return f"Pending diff:\n{d}"
        return "No diff available."

    return f"Unknown action: {action}. Use apply, reject, or diff."


def create_call_opencode_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "call_opencode",
                "description": (
                    "Delegate a complex coding task to OpenCode (Go)."
                    " Use for multi-file features, refactoring, architecture changes."
                    " For simple scripts/functions, use run_code instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "The coding task to perform"},
                        "dir": {
                            "type": "string",
                            "description": "Project directory (default: OPENCODE_PROJECT_DIR env)",
                        },
                        "model": {
                            "type": "string",
                            "description": "OpenCode model (e.g., 'go/sonnet'). Default: OPENCODE_DEFAULT_MODEL env",
                        },
                    },
                    "required": ["task"],
                },
            },
        ),
        execute=_call_opencode,
    )


def create_apply_opencode_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "apply_opencode",
                "description": (
                    "Apply, reject, or show diff of the last OpenCode changes."
                    " Call this after call_opencode to approve or discard changes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "apply (default), reject, diff, or show",
                        },
                    },
                },
            },
        ),
        execute=_apply_opencode_changes,
    )
