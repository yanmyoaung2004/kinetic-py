"""Zip/unzip tool — package projects and extract archives."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

SANDBOX = Path("agent_sandbox")


async def _zip_dir(args: dict[str, Any], ctx: ToolContext | None) -> str:
    source = args.get("source", "").strip()
    output = args.get("output", "").strip()

    if not source:
        return "ERROR: 'source' path is required."

    src_path = Path(source).resolve()
    if not src_path.is_dir():
        return f"ERROR: Directory not found: {source}"

    if not output:
        output = src_path.name + ".zip"

    out_path = (SANDBOX / output).resolve()
    SANDBOX.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in src_path.rglob("*"):
                if file.is_file():
                    arcname = str(file.relative_to(src_path))
                    zf.write(file, arcname)

        size = out_path.stat().st_size
        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        return f"Created {output} ({size_str}) — {len(list(src_path.rglob('*')))} files"
    except Exception as e:
        return f"ERROR: Failed to zip: {e}"


async def _unzip(args: dict[str, Any], ctx: ToolContext | None) -> str:
    source = args.get("source", "").strip()
    output_dir = args.get("output", "").strip()

    if not source:
        return "ERROR: 'source' path is required."

    # Search sandbox first, then as-is
    src_path = SANDBOX / source
    if not src_path.exists():
        src_path = Path(source)
    if not src_path.exists():
        return f"ERROR: File not found: {source}"

    dest = Path(output_dir).resolve() if output_dir else SANDBOX / src_path.stem
    dest.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(src_path, "r") as zf:
            zf.extractall(dest)
        count = len(list(dest.rglob("*")))
        return f"Extracted to {dest} ({count} files)"
    except Exception as e:
        return f"ERROR: Failed to unzip: {e}"


def create_zip_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "zip_project",
                "description": "Zip a directory into a .zip file saved to agent_sandbox/. Use after OpenCode creates a project.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Directory to zip (e.g., 'D:/Projects/myapp')"},
                        "output": {"type": "string", "description": "Output filename (default: <dirname>.zip)"},
                    },
                    "required": ["source"],
                },
            },
        ),
        execute=_zip_dir,
    )


def create_unzip_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "unzip",
                "description": "Extract a .zip file from the sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Zip file path (in sandbox or absolute)"},
                        "output": {"type": "string", "description": "Output directory (default: sandbox/<filename>)"},
                    },
                    "required": ["source"],
                },
            },
        ),
        execute=_unzip,
    )
