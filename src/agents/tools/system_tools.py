from __future__ import annotations

import logging
import os
import platform
from pathlib import Path

import httpx
import psutil

from src.agents.tools.registry import ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.system")

SANDBOX_ROOT = Path("agent_sandbox")


def _ensure_dir() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


# ── Tool creators ──


def create_get_system_info_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "get_system_info",
                "description": (
                    "Get information about the host system: OS, hostname, "
                    "CPU cores, total RAM, free disk space, and platform architecture."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        ),
        execute=lambda args, ctx: _sysinfo(),
    )


async def _sysinfo() -> str:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uname = platform.uname()
    return (
        f"OS:        {uname.system} {uname.release}\n"
        f"Hostname:  {uname.node}\n"
        f"Platform:  {uname.machine}\n"
        f"CPU cores: {psutil.cpu_count()}\n"
        f"RAM:       {mem.available / 1024**3:.1f} GB free / {mem.total / 1024**3:.1f} GB total\n"
        f"Disk (/):  {disk.free / 1024**3:.1f} GB free / {disk.total / 1024**3:.1f} GB total\n"
        f"Uptime:    {int(psutil.boot_time())}s boot"
    )


def create_download_url_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "download_url",
                "description": "Download content from a URL and save it to the sandbox. Max size: 5MB.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The full URL to download"},
                        "filename": {"type": "string", "description": "Optional filename to save as"},
                    },
                    "required": ["url"],
                },
            },
        ),
        execute=lambda args, ctx: _download(args),
    )


async def _download(args: dict) -> str:
    _ensure_dir()
    try:
        url = args["url"]
        if not url.startswith(("http://", "https://")):
            return "ERROR: URL must start with http:// or https://"

        filename = args.get("filename") or _sanitize_filename(url.split("?")[0].rsplit("/", 1)[-1]) or "downloaded.bin"
        filepath = SANDBOX_ROOT / filename

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.content

        max_bytes = 5 * 1024 * 1024
        if len(content) > max_bytes:
            return f"File too large ({len(content) / 1024**2:.1f} MB). Max: 5 MB"

        filepath.write_bytes(content)
        return f"✓ Downloaded {url} -> {filename} ({len(content) / 1024:.1f} KB)"
    except Exception as e:
        return f"ERROR: {e}"


def create_read_env_var_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "read_env_var",
                "description": "Read the value of an environment variable.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "The environment variable name"},
                    },
                    "required": ["name"],
                },
            },
        ),
        execute=lambda args, ctx: _read_env(args),
    )


async def _read_env(args: dict) -> str:
    name = args["name"]
    value = os.environ.get(name)
    if value is None:
        return f"'{name}' is not set."
    is_sensitive = any(kw in name.lower() for kw in ("key", "token", "secret"))
    return f"'{name}' = {'set (value hidden)' if is_sensitive else value}"
