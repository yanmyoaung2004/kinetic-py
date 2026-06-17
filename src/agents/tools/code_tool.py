"""Code execution tool — run Python in a sandboxed subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


async def _run_code(args: dict[str, Any], ctx: ToolContext | None) -> str:
    code = args.get("code", "")
    language = args.get("language", "python").lower()
    if not code:
        return "ERROR: 'code' parameter is required."

    if language not in ("python", "py", "python3"):
        return f"ERROR: Unsupported language '{language}'. Only 'python' is supported."

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "_sandbox_script.py"

        # Safety: strip dangerous imports and restrict path
        safe_code = _safeguard(code)
        filepath.write_text(safe_code, encoding="utf-8")

        try:
            result = subprocess.run(
                [sys.executable, str(filepath)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmpdir,
                env={**os.environ, "PYTHONPATH": "", "PYTHONHOME": ""},
            )
            output = result.stdout or ""
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            if result.returncode != 0:
                output = f"Exit code: {result.returncode}\n{output}"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "ERROR: Code execution timed out after 30 seconds."
        except Exception as e:
            return f"ERROR: {e}"


def _safeguard(code: str) -> str:
    dangerous = ["__import__", "eval(", "exec(", "compile(", "open(", "__builtins__"]
    lines = []
    for line in code.split("\n"):
        safe = True
        for pat in dangerous:
            if pat in line:
                lines.append(f"# SAFETY: removed -> {line.strip()}")
                safe = False
                break
        if safe:
            lines.append(line)
    return "\n".join(lines)


def create_run_code_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "run_code",
                "description": (
                    "Execute Python code in a sandboxed environment. "
                    "Use for calculations, data analysis, automation scripts. "
                    "Returns stdout/stderr. Timeout: 30s."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                        "language": {"type": "string", "description": "Language (only 'python' supported)"},
                    },
                    "required": ["code"],
                },
            },
        ),
        execute=_run_code,
    )
