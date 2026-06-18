"""Docker sandbox — persistent container reused across executions."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("kinetic.sandbox")

IMAGE = os.environ.get("KINETIC_SANDBOX_IMAGE", "python:3.13-slim")
MEMORY_LIMIT = os.environ.get("KINETIC_SANDBOX_MEMORY", "128m")
CPU_LIMIT = os.environ.get("KINETIC_SANDBOX_CPU", "0.5")
TIMEOUT = int(os.environ.get("KINETIC_SANDBOX_TIMEOUT", "30"))

CONTAINER_NAME = "kinetic-sandbox"
_cleaned_up = False


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ensure_container() -> str | None:
    """Start the persistent sandbox container if not running. Return container ID or None."""
    # Check if already running
    check = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check.returncode == 0 and check.stdout.strip() == "true":
        return CONTAINER_NAME

    # Remove stale container if exists
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        timeout=10,
    )

    # Start new container with a long-running process
    logger.info("[SANDBOX] Starting persistent container %s (%s)...", CONTAINER_NAME, IMAGE)
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "--memory",
            MEMORY_LIMIT,
            "--cpus",
            CPU_LIMIT,
            "--network",
            "none",
            "--init",
            IMAGE,
            "python",
            "-c",
            "import time; time.sleep(86400)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning("[SANDBOX] Failed to start container: %s", result.stderr.strip())
        return None
    logger.info("[SANDBOX] Container %s started", CONTAINER_NAME)
    return CONTAINER_NAME


def _cleanup_container() -> None:
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
        timeout=10,
    )
    logger.info("[SANDBOX] Container %s stopped", CONTAINER_NAME)


async def run_in_docker(code: str, image: str = IMAGE) -> str:
    """Run Python code in the persistent sandbox container."""
    if not _docker_available():
        logger.info("[SANDBOX] Docker not available — falling back to subprocess")
        result = await _fallback_subprocess(code)
        return f"[Subprocess] {result}"

    container = _ensure_container()
    if not container:
        logger.info("[SANDBOX] Could not start container — falling back to subprocess")
        result = await _fallback_subprocess(code)
        return f"[Subprocess] {result}"

    logger.info("[SANDBOX] Running in Docker container %s", container)

    # Write code to a temp file and copy into container
    with tempfile.TemporaryDirectory(prefix="kinetic_") as tmpdir:
        script_path = Path(tmpdir) / "_run.py"
        script_path.write_text(code, encoding="utf-8")

        subprocess.run(
            ["docker", "cp", str(script_path), f"{container}:/_run.py"],
            capture_output=True,
            timeout=10,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                "-i",
                container,
                "python",
                "/_run.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
            except TimeoutError:
                proc.kill()
                return f"ERROR: Code execution timed out after {TIMEOUT}s."

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                output += f"\n[stderr]\n{stderr.decode('utf-8', errors='replace')}"
            if proc.returncode != 0:
                output = f"Exit code: {proc.returncode}\n{output}"
            result = output.strip() or "(no output)"
            return f"[Docker] {result}"
        except Exception as e:
            return f"ERROR: {e}"


async def _fallback_subprocess(code: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "_sandbox_script.py"
        filepath.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                [sys.executable, str(filepath)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
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
            return f"ERROR: Code execution timed out after {TIMEOUT}s."
        except Exception as e:
            return f"ERROR: {e}"
