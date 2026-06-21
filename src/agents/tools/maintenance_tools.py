# ruff: noqa: E501
"""System maintenance tools — disk cleanup, temp files, startup optimization."""

from __future__ import annotations

import asyncio
from typing import Any

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


async def _run_ps(script: str, timeout: int = 30) -> str:
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe", "-NoProfile", "-Command", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return "ERROR: Command timed out."
    out = stdout.decode("utf-8", errors="replace").strip()
    if not out and proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        return f"ERROR: {err}" if err else "ERROR: Non-zero exit code."
    return out


async def _system_temp_cleanup(args: dict[str, Any], ctx: ToolContext | None) -> str:
    dry_run = args.get("dry_run", True)
    action = "WOULD DELETE" if dry_run else "DELETED"

    ps = f"""
Write-Host "=== TEMP FILE CLEANUP ==="
Write-Host "Mode: {'Dry run (no changes)' if dry_run else 'Live (deleting files)'}"
Write-Host ""

$locations = @(
  @{{Path="$env:TEMP"; Label="User Temp"}},
  @{{Path="$env:WINDIR\\Temp"; Label="System Temp"}},
  @{{Path="$env:WINDIR\\Prefetch"; Label="Prefetch"}}
)

$totalBytes = 0
foreach ($loc in $locations) {{
  $path = $loc.Path
  $label = $loc.Label
  Write-Host "--- $label ($path) ---"
  if (Test-Path $path) {{
    $items = Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue
    $count = @($items).Count
    $size = ($items | Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
    if (-not $size) {{ $size = 0 }}
    $sizeMB = [math]::Round($size / 1MB, 2)
    Write-Host "  Items: $count | Size: $sizeMB MB"
    $totalBytes += $size

    if (-not $dry_run) {{
      $removed = 0
      Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force -Recurse -ErrorAction SilentlyContinue 2>$null
      Write-Host "  {action}: $count files"
    }}
  }} else {{
    Write-Host "  (not found)"
  }}
  Write-Host ""
}}

$totalMB = [math]::Round($totalBytes / 1MB, 2)
Write-Host "Total reclaimable: $totalMB MB"
if ($dry_run) {{
  Write-Host ""
  Write-Host "To actually delete, retry with dry_run=false"
}}
"""
    result = await _run_ps(ps, timeout=60)
    if result.startswith("ERROR"):
        return result
    return result or "(no temp files found)"


async def _system_disk_usage(args: dict[str, Any], ctx: ToolContext | None) -> str:
    path = args.get("path", "").strip() or "$env:SystemDrive"
    top = min(int(args.get("top", 15)), 50)

    ps = f"""
Write-Host "=== DISK USAGE ==="
Write-Host "Path: {path}"
Write-Host "Top {top} largest folders:"
Write-Host ""

$items = Get-ChildItem "{path}" -Directory -ErrorAction SilentlyContinue |
  ForEach-Object {{
    $size = (Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue |
      Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
    if (-not $size) {{ $size = 0 }}
    [PSCustomObject]@{{Name=$_.Name; SizeMB=[math]::Round($size / 1MB, 2)}}
  }} |
  Sort-Object SizeMB -Descending |
  Select-Object -First {top}

$items | Format-Table Name, SizeMB -AutoSize -Wrap

$total = ($items | Measure-Object -Property SizeMB -Sum).Sum
Write-Host ""
Write-Host "Total (top {top}): [math]::Round($total, 2) MB"
"""
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no data)"


async def _system_startup_optimize(args: dict[str, Any], ctx: ToolContext | None) -> str:
    action = args.get("action", "list").strip().lower()
    name = args.get("name", "").strip()

    if action == "list":
        ps = r"""
Write-Host "=== STARTUP PROGRAMS ==="
Write-Host "--- WMI Startup Commands ---"
Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue |
  Select-Object Name, Command, Location, User |
  Format-Table -AutoSize -Wrap
Write-Host ""
Write-Host "--- Registry: HKLM Run ---"
Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue |
  Select-Object * -ExcludeProperty PSPath, PSParentPath, PSChildName, PSProvider | Format-List
Write-Host ""
Write-Host "--- Registry: HKCU Run ---"
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue |
  Select-Object * -ExcludeProperty PSPath, PSParentPath, PSChildName, PSProvider | Format-List
"""
    elif action == "disable" and name:
        ps = (
            f"$path = 'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'"
            f"\n$val = (Get-ItemProperty $path -Name '{name}' -ErrorAction SilentlyContinue).'{name}'"
            f"\nif (-not $val) {{"
            f"\n  $path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'"
            f"\n  $val = (Get-ItemProperty $path -Name '{name}' -ErrorAction SilentlyContinue).'{name}'"
            f"\n}}"
            f"\nif ($val) {{"
            f"\n  Remove-ItemProperty -Path $path -Name '{name}' -Force -ErrorAction Stop"
            f"\n  Write-Host 'Disabled startup entry: {name}'"
            f"\n}} else {{"
            f"\n  Write-Host 'ERROR: Startup entry \"{name}\" not found.'"
            f"\n}}"
        )
    elif action == "enable" and name:
        cmd = args.get("command", "").strip()
        if not cmd:
            return "ERROR: 'command' parameter required when enabling a startup entry."
        ps = f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name '{name}' -Value '{cmd}' -Force -ErrorAction Stop; Write-Host 'Enabled startup entry: {name}'"
    else:
        return "ERROR: Use action='list' or action='disable'/'enable' with name (and command for enable)."

    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no startup items)"


def _make_handler(fn, name: str, description: str, parameters: dict) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={"name": name, "description": description, "parameters": parameters},
        ),
        execute=fn,
    )


def create_maintenance_tools() -> list[ToolHandler]:
    return [
        _make_handler(
            _system_temp_cleanup,
            "system_temp_cleanup",
            "Show or clean temporary files from User Temp, System Temp, and Prefetch. "
            "Use dry_run=true (default) to preview before deleting.",
            {
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "true = preview only (default), false = actually delete",
                        "default": True,
                    },
                },
            },
        ),
        _make_handler(
            _system_disk_usage,
            "system_disk_usage",
            "Show the largest folders on a drive or path. Defaults to system drive C:.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to scan (default: system drive, e.g., C:\\)",
                        "default": "$env:SystemDrive",
                    },
                    "top": {
                        "type": "number",
                        "description": "Number of folders to show (default 15, max 50)",
                        "default": 15,
                    },
                },
            },
        ),
        _make_handler(
            _system_startup_optimize,
            "system_startup_optimize",
            "List, disable, or re-enable startup programs from registry Run keys. "
            "Use action='list' to see all. Use action='disable' with name to remove (⚠ confirm with user). "
            "Use action='enable' with name and command to re-add.",
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "'list' (default), 'disable', or 'enable'",
                        "default": "list",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name of the startup entry (required for disable/enable)",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command/path for the startup entry (required for enable)",
                    },
                },
            },
        ),
    ]
