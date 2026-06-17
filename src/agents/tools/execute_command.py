from __future__ import annotations

import asyncio
import logging
import platform
import re
from pathlib import Path

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.execute")

SANDBOX_ROOT = Path("agent_sandbox")
DEFAULT_TIMEOUT_MS = 15_000
MAX_OUTPUT_BYTES = 100_000

WINDOWS_WHITELIST = {
    "ipconfig",
    "systeminfo",
    "netstat",
    "whoami",
    "hostname",
    "tasklist",
    "tracert",
    "ping",
    "curl",
    "nslookup",
    "dir",
    "type",
    "findstr",
    "more",
    "echo",
    "git",
    "where",
    "powershell",
}

POSIX_WHITELIST = {
    "ifconfig",
    "uname",
    "hostname",
    "whoami",
    "id",
    "ls",
    "cat",
    "grep",
    "head",
    "tail",
    "echo",
    "date",
    "ping",
    "curl",
    "nslookup",
    "dig",
    "git",
    "ps",
    "df",
    "du",
    "free",
    "uptime",
    "which",
}

BLOCKED_PATTERNS = [re.compile(p) for p in [r"\b&&\b", r"\|", r";", r"`", r"\$\(.*?\)", r">", r"<", r"\|&"]]


def _get_whitelist() -> set[str]:
    return WINDOWS_WHITELIST if platform.system() == "Windows" else POSIX_WHITELIST


def _validate_args(args: list[str]) -> None:
    for arg in args:
        if ".." in arg and (arg.startswith("..") or "/.." in arg or "\\.." in arg):
            raise ValueError(f"SECURITY: Path escape blocked: '{arg}'")
        for pattern in BLOCKED_PATTERNS:
            if pattern.search(arg):
                raise ValueError(f"SECURITY: Shell chaining blocked in argument: '{arg}'")


def _ensure_sandbox() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


def create_execute_command_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "execute_command",
                "description": "Runs a whitelisted system command in a sandboxed environment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": f"The command to run. Allowed: {', '.join(sorted(_get_whitelist()))}",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Arguments for the command. Shell chaining and path escapes are blocked.",
                        },
                    },
                    "required": ["command"],
                },
            },
        ),
        execute=_execute,
    )


async def _execute(args: dict, ctx: ToolContext | None = None) -> str:
    command = args.get("command", "").lower().strip()
    if not command:
        return "ERROR: No command specified."

    whitelist = _get_whitelist()
    if command not in whitelist:
        return f"ERROR: Command '{command}' is not on the whitelist. Allowed: {', '.join(sorted(whitelist))}"

    cmd_args = [str(a) for a in args.get("args", [])]
    try:
        _validate_args(cmd_args)
    except ValueError as e:
        return str(e)

    _ensure_sandbox()
    timeout_ms = args.get("timeout", DEFAULT_TIMEOUT_MS)

    try:
        proc = await asyncio.create_subprocess_exec(
            command,
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(SANDBOX_ROOT),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_ms / 1000)
        except TimeoutError:
            proc.kill()
            return f"ERROR: Command timed out after {timeout_ms}ms."

        output = ""
        if stdout:
            text = stdout.decode("utf-8", errors="replace")
            if len(text) > MAX_OUTPUT_BYTES:
                text = text[:MAX_OUTPUT_BYTES] + "\n... (output truncated)"
            output += text
        if stderr:
            err = stderr.decode("utf-8", errors="replace")[:10_000]
            output += f"\n[STDERR]\n{err}"
        return output or "(no output)"
    except FileNotFoundError:
        return f"ERROR: Command '{command}' not found on this system."
    except Exception as e:
        return f"ERROR: {e}"
