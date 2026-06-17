from __future__ import annotations

import shutil
from pathlib import Path

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

SANDBOX_NAME = "agent_sandbox"
MAX_FILE_SIZE = 100_000


def _sandbox_root() -> Path:
    return (Path.cwd() / SANDBOX_NAME).resolve()


def _resolve_safe_path(requested: str) -> Path:
    norm = requested.replace("\\", "/").lstrip("/")
    sandbox = _sandbox_root()
    resolved = (sandbox / norm).resolve()
    if not str(resolved).upper().startswith(str(sandbox).upper()):
        raise ValueError(f"Path escapes sandbox: '{requested}' (resolved: {resolved}, sandbox: {sandbox})")
    if ".." in requested:
        raise ValueError(f"Path traversal blocked: '{requested}'")
    return resolved


def _ensure_sandbox() -> None:
    _sandbox_root().mkdir(parents=True, exist_ok=True)


def _backup_dir() -> Path:
    d = _sandbox_root() / ".backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _create_backup(safe_path: Path) -> None:
    if not safe_path.exists():
        return
    rel = str(safe_path.relative_to(_sandbox_root())).replace("\\", "_").replace("/", "_")
    backup_file = _backup_dir() / rel / f"{int(__import__('time').time() * 1000)}.bak"
    backup_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(safe_path, backup_file)


def _find_latest_backup(safe_path: Path) -> Path | None:
    rel = str(safe_path.relative_to(_sandbox_root())).replace("\\", "_").replace("/", "_")
    backup_folder = _backup_dir() / rel
    if not backup_folder.exists():
        return None
    backups = sorted(backup_folder.glob("*.bak"), reverse=True)
    return backups[0] if backups else None


# ── Tool creators ──


def create_read_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "read_file",
                "description": "Read the contents of a file from the sandbox directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path within the sandbox"},
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_do_read,
    )


async def _do_read(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        safe = _resolve_safe_path(args["path"])
        if not safe.exists():
            return f"File not found: {args['path']}"
        if not safe.is_file():
            return f"Not a file: {args['path']}"
        size = safe.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"File too large ({size} bytes). Max: {MAX_FILE_SIZE}"
        content = safe.read_text("utf-8", errors="replace")
        return content if content else "(empty file)"
    except Exception as e:
        return f"ERROR: {e}"


def create_write_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "write_file",
                "description": (
                    "Create or overwrite a file in the sandbox. "
                    "Only use when the user explicitly asks you to write or save a file."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path within the sandbox"},
                        "content": {"type": "string", "description": "The full file content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        ),
        execute=_do_write,
    )


async def _do_write(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        safe = _resolve_safe_path(args["path"])
        content = args["content"]
        if len(content) > MAX_FILE_SIZE:
            return f"Content too large ({len(content)} bytes). Max: {MAX_FILE_SIZE}"
        _create_backup(safe)
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, "utf-8")
        # Auto-queue for sending to user
        if ctx and ctx.chat_id:
            from src.agents.tools.send_file_tool import _pending

            _pending.setdefault(ctx.chat_id, []).append(
                {
                    "filename": Path(args["path"]).name,
                    "content": content,
                }
            )
        return f"✓ Wrote {args['path']} ({len(content)} bytes). File will be sent to you."
    except Exception as e:
        return f"ERROR: {e}"


def create_edit_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "edit_file",
                "description": (
                    "Edit a file by replacing the first occurrence of text. A backup is saved before editing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path within the sandbox"},
                        "old_text": {"type": "string", "description": "The exact text to find (first occurrence)"},
                        "new_text": {"type": "string", "description": "The replacement text"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        ),
        execute=_do_edit,
    )


async def _do_edit(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        safe = _resolve_safe_path(args["path"])
        if not safe.exists():
            return f"File not found: {args['path']}"
        content = safe.read_text("utf-8")
        old = args["old_text"]
        if old not in content:
            return f"Text not found: '{old[:50]}...'"
        _create_backup(safe)
        updated = content.replace(old, args["new_text"], 1)
        safe.write_text(updated, "utf-8")
        return f"✓ Edited {args['path']} ({len(old)} chars replaced). Use undo_file to revert."
    except Exception as e:
        return f"ERROR: {e}"


def create_delete_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "delete_file",
                "description": "Delete a file from the sandbox. A backup is saved before deletion.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path within the sandbox"},
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_do_delete,
    )


async def _do_delete(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        safe = _resolve_safe_path(args["path"])
        if not safe.exists():
            return f"File not found: {args['path']}"
        if not safe.is_file():
            return f"Not a file: {args['path']}"
        _create_backup(safe)
        safe.unlink()
        return f"✓ Deleted {args['path']}. Use undo_file to restore."
    except Exception as e:
        return f"ERROR: {e}"


def create_undo_file_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "undo_file",
                "description": "Revert a file to its previous version using the most recent backup.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path of the file to revert"},
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_do_undo,
    )


async def _do_undo(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        safe = _resolve_safe_path(args["path"])
        backup = _find_latest_backup(safe)
        if not backup:
            return f"No backup found for {args['path']}. Nothing to undo."

        current = safe.read_text("utf-8") if safe.exists() else None
        backup_content = backup.read_text("utf-8")

        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(backup_content, "utf-8")

        diff = ""
        if current is not None and current != backup_content:
            diff = (
                f" ({abs(len(current) - len(backup_content))} chars "
                f"{'removed' if len(current) > len(backup_content) else 'restored'})"
            )

        return f"✓ {args['path']} reverted{diff}. Backup preserved for further undo."
    except Exception as e:
        return f"ERROR: {e}"


def create_list_files_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "list_files",
                "description": "List files and directories within the sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path within sandbox (default: root)"},
                    },
                    "required": [],
                },
            },
        ),
        execute=_do_list,
    )


async def _do_list(args: dict, ctx: ToolContext | None = None) -> str:
    _ensure_sandbox()
    try:
        sandbox = _sandbox_root()
        dir_path = _resolve_safe_path(args.get("path", "")) if args.get("path") else sandbox
        if not dir_path.exists():
            return f"Directory not found: {args.get('path', '.')}"
        if not dir_path.is_dir():
            return f"Not a directory: {args.get('path', '.')}"

        entries = list(dir_path.iterdir())
        if not entries:
            return "(empty directory)"
        lines = []
        for e in entries:
            if dir_path == sandbox and e.name == ".backups":
                continue
            if e.is_file():
                size = e.stat().st_size
                lines.append(f"  {e.name} ({size} bytes)")
            else:
                lines.append(f"  {e.name}/")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"
