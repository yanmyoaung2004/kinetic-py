"""Git tools — init, push, pull, clone, status, and GitHub repo creation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


def _git(cmd: list[str], cwd: str) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip()[:2000]
    except Exception as e:
        return f"Error: {e}"


async def _git_exec(args: dict[str, Any], ctx: ToolContext | None) -> str:
    action = args.get("action", "status").strip().lower()
    path = (args.get("path") or ".").strip()
    repo_path = Path(path).resolve()

    if not repo_path.exists():
        return f"ERROR: Path not found: {path}"

    if action == "init":
        (repo_path / ".git").mkdir(parents=True, exist_ok=True)
        return _git(["git", "init"], str(repo_path))

    if action == "status":
        return _git(["git", "status"], str(repo_path))

    if action == "add":
        files = args.get("files", ".")
        return _git(["git", "add", files], str(repo_path))

    if action == "commit":
        msg = args.get("message", "update")
        return _git(["git", "commit", "-m", msg], str(repo_path))

    if action == "push":
        remote = args.get("remote", "origin")
        branch = args.get("branch", "main")
        return _git(["git", "push", remote, branch], str(repo_path))

    if action == "pull":
        remote = args.get("remote", "origin")
        branch = args.get("branch", "main")
        return _git(["git", "pull", remote, branch], str(repo_path))

    if action == "clone":
        url = args.get("url", "")
        if not url:
            return "ERROR: 'url' required for clone."
        return _git(["git", "clone", url, str(repo_path)], str(repo_path.parent))

    if action == "log":
        count = str(args.get("count", 5))
        return _git(["git", "log", f"-{count}", "--oneline"], str(repo_path))

    if action == "remote":
        name = args.get("name", "origin")
        url = args.get("url", "")
        if not url:
            return _git(["git", "remote", "-v"], str(repo_path))
        return _git(["git", "remote", "add", name, url], str(repo_path))

    if action == "create_repo":
        name = args.get("name", "").strip()
        if not name:
            return "ERROR: 'name' required for creating a repo."
        try:
            r = subprocess.run(
                ["gh", "repo", "create", name, "--public", "--source", str(repo_path), "--push"],
                capture_output=True, text=True, timeout=60,
            )
            return (r.stdout or "")[:2000] or (r.stderr or "")[:2000]
        except FileNotFoundError:
            return "ERROR: GitHub CLI (gh) not found. Install it first."
        except Exception as e:
            return f"Error creating repo: {e}"

    return f"Unknown action: {action}. Use: init, status, add, commit, push, pull, clone, log, remote, create_repo"


def create_git_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "git",
                "description": (
                    "Run git: init, status, add, commit, push, pull,"
                    " clone, log, remote, create_repo (via gh CLI)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": (
                                "Operation: init, status, add, commit,"
                                " push, pull, clone, log, remote, create_repo"
                            ),
                        },
                        "path": {"type": "string", "description": "Repository path (default: current dir)"},
                        "message": {"type": "string", "description": "Commit message"},
                        "files": {"type": "string", "description": "Files to add (default: '.')"},
                        "remote": {"type": "string", "description": "Remote name (default: origin)"},
                        "branch": {"type": "string", "description": "Branch name (default: main)"},
                        "url": {"type": "string", "description": "Remote URL (for clone/remote)"},
                        "name": {"type": "string", "description": "Repo name (for create_repo)"},
                        "count": {"type": "number", "description": "Log count (default: 5)"},
                    },
                },
            },
        ),
        execute=_git_exec,
    )
