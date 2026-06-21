# ruff: noqa: E501
"""Security tools — vulnerability scanning, network monitoring, process management, firewall control."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

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


async def _security_scan_system(args: dict[str, Any], ctx: ToolContext | None) -> str:
    scan_type = args.get("scan_type", "full")
    scripts = {
        "updates": r"""
Write-Host "=== MISSING UPDATES ==="
try {
  $Session = New-Object -ComObject Microsoft.Update.Session
  $Searcher = $Session.CreateUpdateSearcher()
  $Result = $Searcher.Search("IsHidden=0 and IsInstalled=0")
  if ($Result.Updates.Count -eq 0) { Write-Host "None pending." }
  else { $Result.Updates | Select-Object Title, KBArticleIDs, LastDeploymentChangeTime | Format-Table -AutoSize -Wrap }
} catch { Write-Host "Windows Update check requires admin." }
Write-Host ""
Write-Host "=== INSTALLED HOTFIXES ==="
Get-WmiObject Win32_QuickFixEngineering -ErrorAction SilentlyContinue | Select-Object HotFixID, InstalledOn, Description | Format-Table -AutoSize
""",
        "ports": r"""
Write-Host "=== LISTENING TCP PORTS ==="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
Write-Host ""
Write-Host "=== LISTENING UDP PORTS ==="
Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort | Format-Table -AutoSize
""",
        "services": r"""
Write-Host "=== AUTO-START SERVICES THAT ARE STOPPED ==="
Get-Service | Where-Object { $_.StartType -eq 'Auto' -and $_.Status -eq 'Stopped' } | Select-Object Name, DisplayName, Status | Format-Table -AutoSize
Write-Host ""
Write-Host "=== RUNNING NON-MICROSOFT SERVICES ==="
Get-WmiObject Win32_Service | Where-Object { $_.StartName -ne 'LocalSystem' -and $_.StartName -notlike 'NT AUTHORITY*' -and $_.StartName -notlike 'NT SERVICE*' } | Select-Object Name, DisplayName, State, StartName | Format-Table -AutoSize
""",
        "defender": r"""
Write-Host "=== WINDOWS DEFENDER STATUS ==="
Get-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object RealTimeProtectionEnabled, AntivirusEnabled, AntispywareEnabled, LastQuickScanTime, LastFullScanTime, AMProductVersion | Format-List
""",
        "failed_logins": r"""
Write-Host "=== RECENT FAILED LOGINS (Event ID 4625) ==="
Get-WinEvent -LogName Security -FilterXPath "*[System[EventID=4625]]" -MaxEvents 20 -ErrorAction SilentlyContinue | ForEach-Object {
  $time = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm")
  $user = if ($_.Properties[5].Value) { $_.Properties[5].Value } else { "?" }
  $ip = if ($_.Properties[18].Value) { $_.Properties[18].Value } else { "?" }
  Write-Host "$time | $user | $ip"
} | Format-Table -AutoSize
if (-not (Get-WinEvent -LogName Security -FilterXPath "*[System[EventID=4625]]" -MaxEvents 1 -ErrorAction SilentlyContinue)) { Write-Host "None found." }
""",
    }

    if scan_type == "full":
        selected = list(scripts.values())
    elif scan_type in scripts:
        selected = [scripts[scan_type]]
    else:
        return f"ERROR: Unknown scan type '{scan_type}'. Options: full, {', '.join(scripts.keys())}"

    combined = "\n".join(selected)
    result = await _run_ps(combined, timeout=120)
    if result.startswith("ERROR"):
        return result
    return result or "(empty — no results)"


async def _security_scan_network(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== ACTIVE TCP CONNECTIONS (Established) ==="
Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess | Format-Table -AutoSize
Write-Host ""
Write-Host "=== LISTENING PORTS ==="
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
Write-Host ""
Write-Host "=== ARP TABLE (Neighbors) ==="
Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -ne '0.0.0.0' } | Select-Object IPAddress, LinkLayerAddress, State | Format-Table -AutoSize
Write-Host ""
Write-Host "=== DNS CACHE ==="
Get-DnsClientCache -ErrorAction SilentlyContinue | Select-Object Entry, Name, Type, TimeToLive | Format-Table -AutoSize
"""
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(empty — no results)"


async def _security_process_info(args: dict[str, Any], ctx: ToolContext | None) -> str:
    name_filter = args.get("name", "").strip()
    filter_cmd = ""
    if name_filter:
        filter_cmd = " | Where-Object { $_.ProcessName -like '*" + name_filter + "*' }"

    ps = (
        "$procs = Get-Process" + filter_cmd + (
        " | Select-Object Name, Id, @{N='CPU(s)';E={[math]::Round($_.CPU, 1)}},"
        " @{N='MemMB';E={[math]::Round($_.WorkingSet/1MB, 1)}},"
        " Path, StartTime, @{N='Responding';E={$_.Responding}}"
        " | Sort-Object MemMB -Descending"
        "\n$procs | Format-Table -AutoSize"
        "\nWrite-Host ''"
        '\nWrite-Host "Total processes: $(@($procs).Count)"'
        )
    )
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(empty — no results)"


async def _security_kill_process(args: dict[str, Any], ctx: ToolContext | None) -> str:
    pid = args.get("pid")
    name = args.get("name", "").strip()

    if not pid and not name:
        return "ERROR: Provide either 'pid' (number) or 'name' (string)."

    if pid:
        ps = f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop; Write-Host 'Process {pid} terminated.'"
    else:
        ps = f"Stop-Process -Name '{name}' -Force -ErrorAction Stop; Write-Host 'Process \"{name}\" terminated.'"

    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result


async def _security_block_ip(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ip = args.get("ip", "").strip()
    if not ip:
        return "ERROR: 'ip' parameter is required."

    direction = args.get("direction", "in")
    if direction not in ("in", "out", "both"):
        return "ERROR: 'direction' must be 'in', 'out', or 'both'."

    name = f"KINETIC_Block_{ip.replace('.', '_')}"
    commands = []
    dirs = ["in", "out"] if direction == "both" else [direction]
    for d in dirs:
        commands.append(
            f'netsh advfirewall firewall add rule name="{name}_{d}" '
            f'dir={d} action=block remoteip={ip}'
        )

    ps = "; ".join(commands) + f"; Write-Host 'Blocked {ip} ({direction}).'"
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    lines = [line for line in result.split("\n") if line.strip()]
    formatted = "\n".join(f"  {line}" for line in lines)
    return (
        f"✓ IP {ip} blocked ({direction})\n"
        f"  Rule prefix: KINETIC_Block_{ip.replace('.', '_')}\n"
        f"  To unblock: use security_unblock_ip with ip={ip}\n{formatted}"
    )


async def _security_unblock_ip(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ip = args.get("ip", "").strip()
    if not ip:
        return "ERROR: 'ip' parameter is required."

    name = f"KINETIC_Block_{ip.replace('.', '_')}"
    ps = (
        f'netsh advfirewall firewall delete rule name="{name}_in" 2>$null; '
        f'netsh advfirewall firewall delete rule name="{name}_out" 2>$null; '
        f"Write-Host 'Unblocked {ip}.'"
    )
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return f"✓ IP {ip} unblocked."


async def _security_check_logs(args: dict[str, Any], ctx: ToolContext | None) -> str:
    log_name = args.get("log_name", "Security")
    max_events = min(int(args.get("max_events", 20)), 100)
    event_id = args.get("event_id")
    level = args.get("level")
    keyword = args.get("keyword", "").strip()

    conditions = []

    if event_id:
        if isinstance(event_id, list):
            ids = ",".join(str(e) for e in event_id)
            conditions.append(f"*[System[EventID=({ids})]]")
        else:
            conditions.append(f"*[System[EventID={event_id}]]")
    if level:
        conditions.append(f"*[System[Level<={level}]]")

    xpath = " and ".join(f"({c})" for c in conditions) if conditions else "*"
    keyword_filter = ""
    if keyword:
        keyword_filter = (
            f" | Where-Object {{ $_.Message -like '*{keyword}*' }}"
        )

    log_names = ["Security", "System", "Application"]
    if log_name not in log_names:
        log_names = [log_name]

    ps_parts = []
    for ln in log_names:
        ps_parts.append(f"""
Write-Host "=== {ln} (last {max_events} events) ==="
try {{
  Get-WinEvent -LogName {ln} -FilterXPath "{xpath}" -MaxEvents {max_events} -ErrorAction SilentlyContinue{keyword_filter} | ForEach-Object {{
    $time = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
    $id = $_.Id
    $level = $_.LevelDisplayName
    $msg = $_.Message -replace "`n", " " -replace "`r", ""
    if ($msg.Length -gt 200) {{ $msg = $msg.Substring(0, 200) + "..." }}
    Write-Host "$time | ID:$id | $level"
    Write-Host "  $msg"
    Write-Host ""
  }}
}} catch {{ Write-Host "(no events or access denied)" }}
""")
    combined = "\n".join(ps_parts)
    result = await _run_ps(combined, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no matching events found)"


async def _security_set_watch(args: dict[str, Any], ctx: ToolContext | None) -> str:
    from src.agents.tasks.scheduler import add_task

    check_type = args.get("check_type", "failed_logins")
    interval = max(int(args.get("interval_minutes", 60)), 15)
    chat_id = ctx.chat_id if ctx else 0

    prompts = {
        "failed_logins": "Check for recent failed login attempts (Event ID 4625) in the Security log.",
        "suspicious_ports": "Check for unexpected listening ports or new network services.",
        "process_changes": "Check for new suspicious processes or unknown running services.",
    }
    prompt = prompts.get(check_type, f"Security check: {check_type}")

    description = args.get("description", f"Security watch: {check_type}")

    from datetime import UTC, datetime, timedelta
    next_run = (datetime.now(UTC) + timedelta(minutes=interval)).isoformat()

    task = add_task(
        "main",
        {
            "description": description,
            "type": "monitor",
            "interval_ms": interval * 60_000,
            "next_run": next_run,
            "dispatch_to": "main",
            "query": prompt,
            "chat_id": chat_id,
        },
    )
    return (
        f"✓ Security watch created: \"{description}\"\n"
        f"  Check: {prompt}\n"
        f"  Interval: {interval} minutes\n"
        f"  Task ID: {task.id}\n"
        f"  You will be notified when triggered."
    )


async def _security_list_watches(args: dict[str, Any], ctx: ToolContext | None) -> str:
    from src.agents.tasks.scheduler import list_tasks

    tasks = list_tasks("main")
    monitors = [t for t in tasks if t.type == "monitor"]
    security = [m for m in monitors if "security" in m.description.lower() or "watch" in m.description.lower()]

    if not security:
        return "No active security watches."

    lines = ["Active security watches:"]
    for m in security:
        next_str = m.next_run[:19] if m.next_run else "?"
        lines.append(f"  • {m.description} — next check: {next_str} — `{m.id}`")
    return "\n".join(lines)


async def _security_remove_watch(args: dict[str, Any], ctx: ToolContext | None) -> str:
    from src.agents.tasks.scheduler import remove_task

    task_id = args.get("task_id", "").strip()
    if not task_id:
        return "ERROR: 'task_id' parameter is required. Use security_list_watches to find IDs."

    ok = remove_task("main", task_id)
    return f"✓ Security watch '{task_id}' removed." if ok else f"ERROR: Watch '{task_id}' not found."


async def _security_audit_startup(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== STARTUP PROGRAMS (Registry: HKLM) ==="
Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue |
  Select-Object -Property * -ExcludeProperty PSPath, PSParentPath, PSChildName, PSProvider | Format-List
Write-Host ""
Write-Host "=== STARTUP PROGRAMS (Registry: HKCU) ==="
Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue |
  Select-Object -Property * -ExcludeProperty PSPath, PSParentPath, PSChildName, PSProvider | Format-List
Write-Host ""
Write-Host "=== STARTUP PROGRAMS (WMI) ==="
Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue |
  Select-Object Name, Command, Location, User | Format-Table -AutoSize
if (-not (Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue)) { Write-Host "None found." }
"""
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no startup programs found)"


async def _security_audit_scheduled_tasks(args: dict[str, Any], ctx: ToolContext | None) -> str:
    filter_name = args.get("filter", "").strip()
    filter_cmd = ""
    if filter_name:
        filter_cmd = " | Where-Object { $_.TaskName -like '*" + filter_name + "*' }"

    ps = (
        "Write-Host '=== SCHEDULED TASKS ==='"
        "\n$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue"
        + filter_cmd +
        " | Where-Object { $_.State -ne 'Disabled' }"
        "\n$tasks | ForEach-Object {"
        "\n  $info = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue"
        "\n  $lastRun = if ($info.LastRunTime) { $info.LastRunTime.ToString('yyyy-MM-dd HH:mm') } else { 'Never' }"
        "\n  $nextRun = if ($info.NextRunTime) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm') } else { 'N/A' }"
        "\n  Write-Host \"$($_.TaskName) | State: $($_.State) | Last: $lastRun | Next: $nextRun\""
        "\n}"
        "\nif (-not $tasks) { Write-Host 'No enabled scheduled tasks found.' }"
    )
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no scheduled tasks found)"


async def _security_audit_usb(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== CURRENT USB DEVICES ==="
Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
  Where-Object { $_.Class -in 'USB', 'PortableDevices', 'Bluetooth', 'Camera', 'DiskDrive' } |
  Select-Object FriendlyName, Class, Status, InstanceId |
  Format-Table -AutoSize -Wrap
Write-Host ""
Write-Host "=== USB STORAGE HISTORY (last 10 events) ==="
$usbEvents = Get-WinEvent -LogName System -MaxEvents 10 -ErrorAction SilentlyContinue |
  Where-Object { $_.ProviderName -eq 'Microsoft-Windows-Kernel-PnP' -and $_.Id -in (2003, 2006, 2100, 2102) }
if ($usbEvents) {
  $usbEvents | ForEach-Object {
    $time = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm")
    $desc = "USB device event (ID: $($_.Id))"
    Write-Host "$time | $desc"
  }
} else { Write-Host "(no USB PnP events found or access denied)" }
Write-Host ""
Write-Host "=== USB DRIVES (Disk Partitions) ==="
Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceType -eq 'USB' } |
  Select-Object Model, Size, MediaType, Status |
  ForEach-Object {
    $sizeGb = [math]::Round($_.Size / 1GB, 1)
    Write-Host "$($_.Model) | $sizeGb GB | $($_.Status)"
  }
if (-not (Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceType -eq 'USB' })) { Write-Host "No USB drives found." }
"""
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no USB devices found)"


async def _security_generate_report(args: dict[str, Any], ctx: ToolContext | None) -> str:
    sections = args.get("sections", "all").strip().lower()
    sandbox = Path("agent_sandbox")
    sandbox.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = sandbox / f"security_report_{timestamp}.txt"

    all_scans = sections == "all"

    lines = [
        "=" * 60,
        "  K.I.N.E.T.I.C. Security Report",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]

    if all_scans or sections == "system":
        lines.append("[SYSTEM SCAN]")
        lines.append("-" * 40)
        result = await _security_scan_system({"scan_type": "full"}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "network":
        lines.append("[NETWORK SCAN]")
        lines.append("-" * 40)
        result = await _security_scan_network({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "processes":
        lines.append("[TOP PROCESSES]")
        lines.append("-" * 40)
        result = await _security_process_info({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "startup":
        lines.append("[STARTUP PROGRAMS]")
        lines.append("-" * 40)
        result = await _security_audit_startup({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "tasks":
        lines.append("[SCHEDULED TASKS]")
        lines.append("-" * 40)
        result = await _security_audit_scheduled_tasks({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "usb":
        lines.append("[USB DEVICES]")
        lines.append("-" * 40)
        result = await _security_audit_usb({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "logs":
        lines.append("[EVENT LOGS]")
        lines.append("-" * 40)
        result = await _security_check_logs({"max_events": 10}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "wifi":
        lines.append("[WIFI]")
        lines.append("-" * 40)
        result = await _security_audit_wifi({}, ctx)
        lines.append(result)
        lines.append("")

    if all_scans or sections == "ping":
        lines.append("[NETWORK HOSTS]")
        lines.append("-" * 40)
        result = await _security_ping_sweep({}, ctx)
        lines.append(result)
        lines.append("")

    lines.append("=" * 60)
    lines.append("  End of report")
    lines.append("=" * 60)

    report = "\n".join(lines)
    report_path.write_text(report, encoding="utf-8")

    # Count findings for summary
    finding_count = 0
    for keyword in ("suspicious", "warning", "error", "blocked", "failed", "stopped"):
        finding_count += report.lower().count(keyword)

    summary = [
        f"✓ Security report saved to: agent_sandbox/{report_path.name}",
        f"  Size: {len(report)} characters",
        f"  Sections: {'all' if all_scans else sections}",
        f"  Notable findings: {finding_count}",
        "",
        "Use send_file to deliver the report, or review sections above.",
    ]
    return "\n".join(summary)


async def _security_lookup_cve(args: dict[str, Any], ctx: ToolContext | None) -> str:
    cve_id = args.get("cve_id", "").strip().upper()
    if not cve_id:
        return "ERROR: 'cve_id' parameter is required (e.g., 'CVE-2024-12345')."

    url = f"https://cve.circl.lu/api/cve/{cve_id}"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"CVE {cve_id} not found."
            return f"ERROR: API request failed: {e}"
        except Exception as e:
            return f"ERROR: Failed to look up CVE: {e}"

    meta = data.get("cveMetadata", {})
    actual_id = meta.get("cveId", "")
    if not actual_id:
        return f"CVE {cve_id} not found."

    cna = data.get("containers", {}).get("cna", {})

    lines = [f"CVE: {actual_id}"]

    descs = cna.get("descriptions", [])
    if descs:
        lines.append(f"\nDescription: {descs[0].get('value', 'N/A')}")

    metrics = cna.get("metrics", [])
    if metrics:
        cvss = metrics[0].get("cvssV3_1") or metrics[0].get("cvssV3_0") or metrics[0].get("cvssV2_0", {})
        score = cvss.get("baseScore", "N/A")
        severity = cvss.get("baseSeverity", "N/A")
        vector = cvss.get("vectorString", "")
        lines.append(f"\nCVSS Score: {score}/10 ({severity})")
        if vector:
            lines.append(f"Vector: {vector}")

    if meta.get("datePublished"):
        lines.append(f"Published: {meta['datePublished'][:10]}")
    if meta.get("dateUpdated"):
        lines.append(f"Last Modified: {meta['dateUpdated'][:10]}")

    affected = cna.get("affected", [])
    if affected:
        lines.append(f"\nAffected Products ({len(affected)}):")
        for p in affected[:8]:
            vendor = p.get("vendor", "")
            product = p.get("product", "")
            versions = ", ".join(v.get("version", "?") for v in p.get("versions", []))
            lines.append(f"  • {vendor}/{product} ({versions})")

    refs = cna.get("references", [])
    if refs:
        lines.append(f"\nReferences ({len(refs)}):")
        for r in refs[:3]:
            url_ref = r.get("url", "")
            tags = ", ".join(r.get("tags", []))
            lines.append(f"  • {url_ref}" + (f" [{tags}]" if tags else ""))

    return "\n".join(lines)


async def _security_check_ip(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ip = args.get("ip", "").strip()
    if not ip:
        return "ERROR: 'ip' parameter is required."

    api_key = os.environ.get("ABUSEIPDB_API_KEY", "")
    if not api_key:
        return (
            "ERROR: ABUSEIPDB_API_KEY not set in environment.\n"
            "  Get a free key at: https://www.abuseipdb.com/register\n"
            "  Then add to .env: ABUSEIPDB_API_KEY=your_key_here"
        )

    url = "https://api.abuseipdb.com/api/v2/check"
    headers = {"Key": api_key, "Accept": "application/json"}
    params = {"ipAddress": ip, "maxAgeInDays": 90}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception as e:
            return f"ERROR: Failed to check IP: {e}"

    if not data:
        return f"No data returned for {ip}."

    confidence = data.get("abuseConfidenceScore", 0)
    total_reports = data.get("totalReports", 0)

    lines = [f"IP: {ip}"]
    if confidence > 0 or total_reports > 0:
        lines.append(f"Status: ⚠ Reports found (confidence: {confidence}%)")
    else:
        lines.append("Status: ✅ No abuse reports")

    if data.get("domain"):
        lines.append(f"Domain: {data['domain']}")
    if data.get("countryCode"):
        lines.append(f"Country: {data['countryCode']}")
    if data.get("isp"):
        lines.append(f"ISP: {data['isp']}")
    if data.get("usageType"):
        lines.append(f"Usage: {data['usageType']}")
    if total_reports:
        lines.append(f"Total Reports: {total_reports}")
    if data.get("lastReportedAt"):
        lines.append(f"Last Reported: {data['lastReportedAt'][:10]}")

    return "\n".join(lines)


async def _security_ping_sweep(args: dict[str, Any], ctx: ToolContext | None) -> str:
    subnet = args.get("subnet", "").strip()

    parts = [
        "Write-Host '=== REACHABLE HOSTS (ARP Cache) ==='",
        "Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue",
        "  | Where-Object { $_.State -eq 'Reachable' -and $_.IPAddress -ne '0.0.0.0' }",
        "  | Select-Object IPAddress, LinkLayerAddress, InterfaceIndex",
        "  | Format-Table -AutoSize",
    ]

    if not subnet:
        parts.append(
            "Write-Host ''"
            "\nWrite-Host 'To scan a subnet, provide the subnet parameter (e.g., 192.168.1).'"
        )
    else:
        parts.append(
            "\nWrite-Host ''"
            f"\nWrite-Host '=== PING SCAN: {subnet}.1-254 ==='"
            "\n$live = @()"
            f"\nforeach ($i in 1..30) {{"
            f"\n  $ip = '{subnet}.' + $i"
            "\n  $ping = Test-Connection -ComputerName $ip -Count 1 -Quiet -TimeoutSeconds 1 -ErrorAction SilentlyContinue"
            "\n  if ($ping) { $live += $ip; Write-Host \"$ip is alive\" }"
            "\n}"
            "\nif ($live.Count -eq 0) { Write-Host 'No live hosts found in first 30 addresses.' }"
            "\nelse { Write-Host \"Found $($live.Count) live host(s).\" }"
        )

    ps = "\n".join(parts)
    result = await _run_ps(ps, timeout=120)
    if result.startswith("ERROR"):
        return result
    return result or "(no hosts found)"


async def _security_scan_ports(args: dict[str, Any], ctx: ToolContext | None) -> str:
    host = args.get("host", "").strip()
    ports = args.get("ports")
    if not host:
        return "ERROR: 'host' parameter is required."

    port_list = ports if isinstance(ports, list) else [ports] if ports else [22, 80, 443, 3389, 8080]
    port_list = [str(p) for p in port_list]

    ps_parts = [
        f"Write-Host '=== PORT SCAN: {host} ==='",
        "Write-Host ''",
    ]

    for port in port_list:
        ps_parts.append(
            f"$result = Test-NetConnection -ComputerName {host} -Port {port} -WarningAction SilentlyContinue -InformationLevel Quiet 2>$null"
            f"\nif ($result) {{ Write-Host '  Port {port}: OPEN' }}"
            f"\nelse {{ Write-Host '  Port {port}: closed/filtered' }}"
        )

    ps_parts.append(
        "\nWrite-Host ''"
        "\nWrite-Host 'Note: ICMP (ping) may be blocked by firewall -- port results are more reliable.'"
    )

    ps = "\n".join(ps_parts)
    result = await _run_ps(ps, timeout=60)
    if result.startswith("ERROR"):
        return result
    return result or "(no results)"


async def _security_audit_wifi(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== CURRENT WIFI INTERFACE ==="
$iface = netsh wlan show interfaces -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) { $iface } else { Write-Host "No WiFi interface found." }
Write-Host ""
Write-Host "=== AVAILABLE NETWORKS ==="
$nets = netsh wlan show networks mode=bssid -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) { $nets } else { Write-Host "No networks found or WiFi is off." }
Write-Host ""
Write-Host "=== SAVED PROFILES ==="
$profiles = netsh wlan show profiles -ErrorAction SilentlyContinue
if ($LASTEXITCODE -eq 0) { $profiles } else { Write-Host "No profiles found." }
"""
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no WiFi information available)"


async def _security_audit_users(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== LOCAL USER ACCOUNTS ==="
Get-LocalUser -ErrorAction SilentlyContinue |
  Select-Object Name, FullName, Enabled, @{N='LastLogon';E={if ($_.LastLogon -eq '12/31/1600 4:00:00 PM') { 'Never' } else { $_.LastLogon.ToString('yyyy-MM-dd') }}}, PasswordLastSet, UserMayChangePassword |
  Format-Table -AutoSize
Write-Host ""
Write-Host "=== ADMINISTRATOR GROUP ==="
Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue |
  Select-Object Name, PrincipalSource, ObjectClass | Format-Table -AutoSize
Write-Host ""
Write-Host "=== REMOTE DESKTOP USERS ==="
Get-LocalGroupMember -Group 'Remote Desktop Users' -ErrorAction SilentlyContinue |
  Select-Object Name, PrincipalSource | Format-Table -AutoSize
if (-not (Get-LocalGroupMember -Group 'Remote Desktop Users' -ErrorAction SilentlyContinue)) { Write-Host '(none)' }
"""
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no user information available)"


async def _security_firewall_rules(args: dict[str, Any], ctx: ToolContext | None) -> str:
    filter_action = args.get("filter", "all").strip().lower()
    action_filter = ""
    if filter_action == "block":
        action_filter = " | Where-Object { $_.Action -eq 'Block' }"
    elif filter_action == "allow":
        action_filter = " | Where-Object { $_.Action -eq 'Allow' }"
    elif filter_action == "in":
        action_filter = " | Where-Object { $_.Direction -eq 'Inbound' }"
    elif filter_action == "out":
        action_filter = " | Where-Object { $_.Direction -eq 'Outbound' }"

    ps = (
        "Write-Host '=== ACTIVE FIREWALL RULES ==='"
        "\n$rules = Get-NetFirewallRule -Enabled True -ErrorAction SilentlyContinue"
        + action_filter +
        "\n$rules | Select-Object DisplayName, Direction, Action, Profile | Sort-Object Profile, Direction | Format-Table -AutoSize -Wrap"
        "\nWrite-Host ''"
        '\nWrite-Host "Total enabled rules: $(@($rules).Count)"'
    )
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no firewall rules found)"


async def _security_drive_health(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== DISK SPACE ==="
Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue |
  Where-Object { $_.Root -ne 'C:\' -or $_.Used -gt 0 } |
  Select-Object @{N='Drive';E={$_.Root}}, @{N='Used(GB)';E={[math]::Round($_.Used/1GB,1)}}, @{N='Free(GB)';E={[math]::Round($_.Free/1GB,1)}}, @{N='Total(GB)';E={[math]::Round(($_.Used+$_.Free)/1GB,1)}} |
  Format-Table -AutoSize
Write-Host ""
Write-Host "=== PHYSICAL DISKS ==="
Get-PhysicalDisk -ErrorAction SilentlyContinue |
  Select-Object FriendlyName, MediaType, @{N='Size(GB)';E={[math]::Round($_.Size/1GB,1)}}, OperationalStatus, HealthStatus |
  Format-Table -AutoSize
Write-Host ""
Write-Host "=== BITLOCKER STATUS ==="
$bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction SilentlyContinue
if ($bl) {
  $bl | Select-Object MountPoint, ProtectionStatus, EncryptionPercentage |
    ForEach-Object { Write-Host "$($_.MountPoint): $($_.ProtectionStatus) (encrypted: $($_.EncryptionPercentage)%)" }
} else { Write-Host "BitLocker not available or not configured." }
"""
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no drive information available)"


async def _security_persistence_check(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
Write-Host "=== PERSISTENCE CHECK ==="
Write-Host ""
Write-Host "--- Registry Run Keys (HKLM) ---"
$hklm = Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue
$hklm.PSObject.Properties | Where-Object { $_.Name -notin ('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } |
  ForEach-Object { Write-Host "  $($_.Name) -> $($_.Value)" }
Write-Host ""
Write-Host "--- Registry Run Keys (HKCU) ---"
$hkcu = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -ErrorAction SilentlyContinue
$hkcu.PSObject.Properties | Where-Object { $_.Name -notin ('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } |
  ForEach-Object { Write-Host "  $($_.Name) -> $($_.Value)" }
Write-Host ""
Write-Host "--- Auto-Start Services ---"
Get-Service -ErrorAction SilentlyContinue |
  Where-Object { $_.StartType -eq 'Auto' -and $_.Status -eq 'Running' } |
  ForEach-Object { Write-Host "  $($_.Name) ($($_.DisplayName))" }
Write-Host ""
Write-Host "--- Scheduled Tasks (enabled, with triggers) ---"
Get-ScheduledTask -ErrorAction SilentlyContinue |
  Where-Object { $_.State -eq 'Ready' } |
  ForEach-Object { Write-Host "  $($_.TaskName)" }
Write-Host ""
Write-Host "--- WMI Event Subscriptions (malware persistence) ---"
$filters = Get-WmiObject -Namespace root\subscription -Class __EventFilter -ErrorAction SilentlyContinue
if ($filters) { $filters | ForEach-Object { Write-Host "  WMI Filter: $($_.Name)" } }
else { Write-Host "  (none found)" }
"""
    result = await _run_ps(ps, timeout=30)
    if result.startswith("ERROR"):
        return result
    return result or "(no persistence data available)"


async def _security_defender_scan(args: dict[str, Any], ctx: ToolContext | None) -> str:
    scan_type = args.get("scan_type", "quick").strip().lower()
    if scan_type not in ("quick", "full", "custom"):
        return "ERROR: scan_type must be 'quick' (default), 'full', or 'custom'."

    scan_flag = scan_type[0].upper() + scan_type[1:] + "Scan"
    ps = (
        "Write-Host '=== WINDOWS DEFENDER SCAN ==='"
        f"\nWrite-Host 'Starting {scan_type} scan...'"
        f"\nStart-MpScan -ScanType {scan_flag} -ErrorAction SilentlyContinue"
        "\nWrite-Host ''"
        "\nWrite-Host '=== RECENT THREATS ==='"
        "\n$threats = Get-MpThreatDetection -ErrorAction SilentlyContinue | Select-Object -First 20"
        "\nif ($threats) {"
        "\n  $threats | ForEach-Object {"
        "\n    $time = $_.InitialDetectionTime.ToString('yyyy-MM-dd HH:mm')"
        "\n    Write-Host \"$time | $($_.ThreatName) | $($_.Resources)\""
        "\n  }"
        "\n} else { Write-Host 'No threats detected recently.' }"
        "\nWrite-Host ''"
        "\nWrite-Host '=== DEFENDER STATUS ==='"
        "\nGet-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object RealTimeProtectionEnabled, AntivirusEnabled, AMProductVersion | Format-List"
    )
    result = await _run_ps(ps, timeout=120)
    if result.startswith("ERROR"):
        return result
    return result or "(Defender scan completed — no data returned)"


async def _security_hosts_check(args: dict[str, Any], ctx: ToolContext | None) -> str:
    ps = r"""
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
Write-Host "=== HOSTS FILE ==="
Write-Host "Path: $hostsPath"
Write-Host ""
$entries = Get-Content $hostsPath -ErrorAction SilentlyContinue | Where-Object { $_ -notmatch '^\s*#' -and $_.Trim() -ne '' }
if (-not $entries) {
  Write-Host "No custom entries (all are comments or empty)."
} else {
  Write-Host "Non-comment entries ($(@($entries).Count) found):"
  $entries | ForEach-Object {
    $parts = $_ -split '\s+'
    if ($parts.Count -ge 2) {
      $ip = $parts[0]
      $hostname = $parts[1]
      $note = ""
      if ($ip -eq '127.0.0.1' -and $hostname -notlike 'localhost*') { $note = " <- LOCAL REDIRECT" }
      elseif ($ip -notmatch '^127\.' -and $ip -ne '::1') { $note = " <- EXTERNAL TARGET" }
      Write-Host "  $ip`t$hostname$note"
    }
  }
}
"""
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no hosts file information)"


async def _security_browser_audit(args: dict[str, Any], ctx: ToolContext | None) -> str:
    browser = args.get("browser", "all").strip().lower()

    template = """
Write-Host "=== $browser (Machine Policy) ==="
$path = '$regPath'
$pol = Get-ItemProperty $path -ErrorAction SilentlyContinue
if ($pol) {
  $pol.PSObject.Properties | Where-Object { $_.Name -notin ('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } |
    ForEach-Object { Write-Host "  $($_.Name) = $($_.Value)" }
} else { Write-Host "  No policies configured." }
"""

    parts = []
    if browser in ("all", "chrome"):
        parts.append(
            template
            .replace("$browser", "Chrome")
            .replace("$regPath", "'HKLM:\\Software\\Policies\\Google\\Chrome'")
        )
        parts.append("""
Write-Host "=== Chrome (User Policy) ==="
$pol2 = Get-ItemProperty 'HKCU:\\Software\\Policies\\Google\\Chrome' -ErrorAction SilentlyContinue
if ($pol2) {
  $pol2.PSObject.Properties | Where-Object { $_.Name -notin ('PSPath','PSParentPath','PSChildName','PSDrive','PSProvider') } |
    ForEach-Object { Write-Host "  $($_.Name) = $($_.Value)" }
} else { Write-Host "  No user policies configured." }
""")
    if browser in ("all", "edge"):
        parts.append(
            template
            .replace("$browser", "Edge")
            .replace("$regPath", "'HKLM:\\Software\\Policies\\Microsoft\\Edge'")
        )
    if browser in ("all", "ie"):
        parts.append(
            template
            .replace("$browser", "Internet Explorer")
            .replace("$regPath", "'HKLM:\\Software\\Policies\\Microsoft\\Internet Explorer'")
        )

    if not parts:
        return f"ERROR: Unknown browser '{browser}'. Options: all, chrome, edge, ie."

    ps = "\n".join(parts)
    result = await _run_ps(ps, timeout=15)
    if result.startswith("ERROR"):
        return result
    return result or "(no browser policies found)"



def _make_handler(fn, name: str, description: str, parameters: dict) -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={"name": name, "description": description, "parameters": parameters},
        ),
        execute=fn,
    )


def create_security_tools() -> list[ToolHandler]:
    return [
        _make_handler(
            _security_scan_system,
            "security_scan_system",
            "Scan the local system for vulnerabilities: missing updates, open ports, suspicious services, "
            "Defender status, and failed logins. Args: scan_type ('full'|'updates'|'ports'|'services'|'defender'|'failed_logins').",
            {
                "type": "object",
                "properties": {
                    "scan_type": {
                        "type": "string",
                        "description": "Scope: 'full' (default), 'updates', 'ports', 'services', 'defender', 'failed_logins'",
                        "default": "full",
                    },
                },
            },
        ),
        _make_handler(
            _security_scan_network,
            "security_scan_network",
            "Scan network state: active TCP connections, listening ports, ARP table, DNS cache.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_process_info,
            "security_process_info",
            "List running processes with CPU/memory usage. Optionally filter by name.",
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Filter by process name (e.g., 'python', 'chrome')",
                    },
                },
            },
        ),
        _make_handler(
            _security_kill_process,
            "security_kill_process",
            "Kill a process by PID or name. USE WITH CAUTION — confirm with user first.",
            {
                "type": "object",
                "properties": {
                    "pid": {"type": "number", "description": "Process ID to kill"},
                    "name": {"type": "string", "description": "Process name to kill (e.g., 'notepad')"},
                },
            },
        ),
        _make_handler(
            _security_block_ip,
            "security_block_ip",
            "Block an IP address via Windows Firewall. Creates inbound/outbound block rules. USE WITH CAUTION — confirm with user first.",
            {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP address to block"},
                    "direction": {
                        "type": "string",
                        "description": "'in' (default), 'out', or 'both'",
                        "default": "in",
                    },
                },
                "required": ["ip"],
            },
        ),
        _make_handler(
            _security_unblock_ip,
            "security_unblock_ip",
            "Remove a firewall block rule for an IP address previously blocked by security_block_ip.",
            {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP address to unblock"},
                },
                "required": ["ip"],
            },
        ),
        _make_handler(
            _security_check_logs,
            "security_check_logs",
            "Search Windows Event Logs. Default: last 20 Security events. Filter by event_id, level, or keyword.",
            {
                "type": "object",
                "properties": {
                    "log_name": {
                        "type": "string",
                        "description": "Log name: 'Security' (default), 'System', 'Application', or custom",
                        "default": "Security",
                    },
                    "max_events": {
                        "type": "number",
                        "description": "Max events to return (1-100, default 20)",
                        "default": 20,
                    },
                    "event_id": {
                        "type": "number",
                        "description": "Filter by event ID (e.g., 4625 for failed login, 4688 for process creation)",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "Filter by keyword in the event message",
                    },
                },
            },
        ),
        _make_handler(
            _security_set_watch,
            "security_set_watch",
            "Create a recurring security monitor that checks for suspicious activity periodically and notifies you.",
            {
                "type": "object",
                "properties": {
                    "check_type": {
                        "type": "string",
                        "description": "What to monitor: 'failed_logins', 'suspicious_ports', 'process_changes'",
                        "default": "failed_logins",
                    },
                    "interval_minutes": {
                        "type": "number",
                        "description": "How often to check (minimum 15, default 60)",
                        "default": 60,
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable name for this watch",
                    },
                },
                "required": ["check_type"],
            },
        ),
        _make_handler(
            _security_list_watches,
            "security_list_watches",
            "List all active security watches/monitors.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_remove_watch,
            "security_remove_watch",
            "Remove/stop a security watch by task_id. Use security_list_watches to find the ID.",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID of the watch to remove"},
                },
                "required": ["task_id"],
            },
        ),
        _make_handler(
            _security_audit_startup,
            "security_audit_startup",
            "List programs that run automatically at system startup (from registry and WMI).",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_audit_scheduled_tasks,
            "security_audit_scheduled_tasks",
            "List scheduled tasks with last-run and next-run times. Optionally filter by name.",
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Filter tasks by name (e.g., 'Google', 'Windows')",
                    },
                },
            },
        ),
        _make_handler(
            _security_audit_usb,
            "security_audit_usb",
            "List currently connected USB devices, USB storage history, and USB drive details.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_generate_report,
            "security_generate_report",
            "Run a comprehensive security scan across all categories and save the report to agent_sandbox/. "
            "Use send_file to deliver the report file. Optional: sections ('all'|'system'|'network'|'processes'|'startup'|'tasks'|'usb'|'logs'|'wifi'|'ping').",
            {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "string",
                        "description": "Which sections to include: 'all' (default), 'system', 'network', 'processes', 'startup', 'tasks', 'usb', 'logs', 'wifi', 'ping'",
                        "default": "all",
                    },
                },
            },
        ),
        _make_handler(
            _security_ping_sweep,
            "security_ping_sweep",
            "Discover live hosts on the network. Shows ARP cache (instant) + optionally ping-scan a subnet "
            "(e.g., subnet='192.168.1' scans 192.168.1.1-30).",
            {
                "type": "object",
                "properties": {
                    "subnet": {
                        "type": "string",
                        "description": "Subnet prefix to scan (e.g., '192.168.1'). Scans .1-.30. Leave empty for ARP only.",
                    },
                },
            },
        ),
        _make_handler(
            _security_scan_ports,
            "security_scan_ports",
            "Check if specific ports are open on a remote host. Defaults to common ports (22, 80, 443, 3389, 8080). "
            "USE WITH CAUTION — confirm with user before scanning external hosts.",
            {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Hostname or IP address to scan"},
                    "ports": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Port numbers to check (default: [22, 80, 443, 3389, 8080])",
                    },
                },
                "required": ["host"],
            },
        ),
        _make_handler(
            _security_audit_wifi,
            "security_audit_wifi",
            "Show current WiFi connection details, available networks with signal strength, and saved profiles.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_lookup_cve,
            "security_lookup_cve",
            "Look up a CVE (Common Vulnerability and Exposure) by ID. Uses the CIRCL public API — no key needed.",
            {
                "type": "object",
                "properties": {
                    "cve_id": {
                        "type": "string",
                        "description": "CVE ID to look up (e.g., 'CVE-2024-12345')",
                    },
                },
                "required": ["cve_id"],
            },
        ),
        _make_handler(
            _security_check_ip,
            "security_check_ip",
            "Check an IP address against AbuseIPDB for known malicious activity. Requires ABUSEIPDB_API_KEY env var.",
            {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP address to check"},
                },
                "required": ["ip"],
            },
        ),
        _make_handler(
            _security_audit_users,
            "security_audit_users",
            "List local user accounts, administrator group members, and remote desktop users.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_firewall_rules,
            "security_firewall_rules",
            "List enabled Windows Firewall rules. Optionally filter by 'block', 'allow', 'in', or 'out'.",
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Filter: 'all' (default), 'block', 'allow', 'in', 'out'",
                        "default": "all",
                    },
                },
            },
        ),
        _make_handler(
            _security_drive_health,
            "security_drive_health",
            "Show disk space usage, physical disk health status, and BitLocker encryption status.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_persistence_check,
            "security_persistence_check",
            "Check all common persistence mechanisms: registry run keys, auto-start services, scheduled tasks, WMI subscriptions.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_defender_scan,
            "security_defender_scan",
            "Run a Windows Defender scan (quick or full) and show recent threat detections.",
            {
                "type": "object",
                "properties": {
                    "scan_type": {
                        "type": "string",
                        "description": "'quick' (default) or 'full'",
                        "default": "quick",
                    },
                },
            },
        ),
        _make_handler(
            _security_hosts_check,
            "security_hosts_check",
            "Inspect the Windows hosts file for unusual redirects or custom entries.",
            {"type": "object", "properties": {}},
        ),
        _make_handler(
            _security_browser_audit,
            "security_browser_audit",
            "Show browser security policies for Chrome, Edge, and Internet Explorer.",
            {
                "type": "object",
                "properties": {
                    "browser": {
                        "type": "string",
                        "description": "'all' (default), 'chrome', 'edge', or 'ie'",
                        "default": "all",
                    },
                },
            },
        ),
    ]
