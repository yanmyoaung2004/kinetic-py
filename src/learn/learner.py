from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("kinetic.learner")

LEARN_MARKER_START = "<!-- headroom:learn:start -->"
LEARN_MARKER_END = "<!-- headroom:learn:end -->"

_LEARN_AVAILABLE: bool | None = None


def _check_headroom() -> bool:
    global _LEARN_AVAILABLE
    if _LEARN_AVAILABLE is not None:
        return _LEARN_AVAILABLE
    try:
        import headroom  # noqa: F401
        _LEARN_AVAILABLE = True
    except ImportError:
        _LEARN_AVAILABLE = False
    return _LEARN_AVAILABLE


def is_enabled() -> bool:
    return os.environ.get("HEADROOM_LEARN", "0") == "1" and _check_headroom()


@dataclass
class FailureRecord:
    tool: str
    error_text: str
    agent_id: str
    timestamp: str
    input_args: dict[str, Any] | None = None
    retry_success: bool = False
    retry_input: dict[str, Any] | None = None


@dataclass
class LearnedPattern:
    category: str
    pattern: str
    detail: str
    frequency: int = 1


def _scan_agent_log(agent_dir: Path, agent_id: str) -> list[FailureRecord]:
    history_path = agent_dir / "history.jsonl"
    if not history_path.exists():
        return []

    failures: list[FailureRecord] = []
    recent_calls: list[dict] = []

    try:
        for line in history_path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls")
            tool_call_id = msg.get("tool_call_id")

            # Track tool calls
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    recent_calls.append({
                        "type": "call",
                        "tool": fn.get("name", ""),
                        "args": (
                            json.loads(fn.get("arguments", "{}"))
                            if isinstance(fn.get("arguments"), str)
                            else fn.get("arguments", {})
                        ),
                        "tool_call_id": tc.get("id", ""),
                    })

            # Track tool results (errors)
            if role == "tool" and tool_call_id:
                is_error = content.startswith("ERROR:") or "Traceback" in content or "Error:" in content
                if is_error:
                    fail = FailureRecord(
                        tool="",
                        error_text=content[:300],
                        agent_id=agent_id,
                        timestamp=msg.get("timestamp", ""),
                        input_args=None,
                    )
                    # Match with the call
                    for call in recent_calls:
                        if call.get("tool_call_id") == tool_call_id:
                            fail.tool = call["tool"]
                            fail.input_args = call["args"]
                            break
                    # Check if this tool was retried successfully
                    fail.retry_success = _check_retry_success(tool_call_id, recent_calls)
                    failures.append(fail)

            # Assistant messages with errors (LLM failures)
            if role == "assistant" and content and ("I encountered an issue" in content or "ERROR" in content):
                failures.append(FailureRecord(
                    tool="llm",
                    error_text=content[:300],
                    agent_id=agent_id,
                    timestamp=msg.get("timestamp", ""),
                ))

    except Exception as exc:
        logger.warning("[LEARN] Failed scanning %s: %s", agent_id, exc)

    return failures


def _check_retry_success(failed_call_id: str, calls: list[dict]) -> bool:
    found_fail = False
    for call in calls:
        if call.get("tool_call_id") == failed_call_id:
            found_fail = True
            continue
        if found_fail and call["type"] == "call" and call.get("tool_call_id") != failed_call_id:
            return True
    return False


def _analyze_patterns(failures: list[FailureRecord]) -> list[LearnedPattern]:
    patterns: list[LearnedPattern] = []

    tool_errors = defaultdict(list)
    for f in failures:
        if f.tool:
            tool_errors[f.tool].append(f)

    for tool, errs in tool_errors.items():
        if len(errs) >= 2:
            common_errors = Counter(e.error_text[:100] for e in errs).most_common(3)
            for err_text, count in common_errors:
                if count >= 2:
                    patterns.append(LearnedPattern(
                        category="tool_failures",
                        pattern=f"Tool '{tool}' frequently fails",
                        detail=f"Error (seen {count}x): {err_text}",
                        frequency=count,
                    ))

    for f in failures:
        if f.retry_success and f.input_args:
            patterns.append(LearnedPattern(
                category="retry_patterns",
                pattern=f"Retry '{f.tool}' with adjusted params on failure",
                detail=f"Original args: {json.dumps(f.input_args)}",
                frequency=1,
            ))

    error_texts = [f.error_text.lower() for f in failures]
    common_phrases: Counter[str] = Counter()
    for t in error_texts:
        phrases = ["not found", "permission denied", "timeout",
                     "connection refused", "does not exist", "already exists"]
        for phrase in phrases:
            if phrase in t:
                common_phrases[phrase] += 1

    for phrase, count in common_phrases.most_common(3):
        if count >= 2:
            patterns.append(LearnedPattern(
                category="common_errors",
                pattern=f"Frequent error: '{phrase}'",
                detail=f"Occurred {count}x across all agents",
                frequency=count,
            ))

    return patterns


def _generate_markdown(patterns: list[LearnedPattern]) -> str:
    if not patterns:
        return ""

    by_category = defaultdict(list)
    for p in patterns:
        by_category[p.category].append(p)

    sections = []
    for category in ["tool_failures", "retry_patterns", "common_errors"]:
        items = by_category.get(category)
        if not items:
            continue
        items.sort(key=lambda x: x.frequency, reverse=True)
        title = category.replace("_", " ").title()
        sections.append(f"\n### {title}\n")
        for p in items:
            sections.append(f"- **{p.pattern}** (x{p.frequency})\n  {p.detail}")

    return "".join(sections)


def read_learnings(target_file: str | Path) -> str:
    path = Path(target_file)
    if not path.exists():
        return ""
    text = path.read_text("utf-8")
    m = re.search(re.escape(LEARN_MARKER_START) + "(.*?)" + re.escape(LEARN_MARKER_END), text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def write_learnings(markdown: str, target_file: str | Path) -> bool:
    if not markdown:
        return False
    path = Path(target_file)
    block = f"{LEARN_MARKER_START}\n{markdown}\n{LEARN_MARKER_END}"

    if not path.exists():
        path.write_text(f"{block}\n", encoding="utf-8")
        return True

    text = path.read_text("utf-8")
    if LEARN_MARKER_START in text:
        text = re.sub(
            re.escape(LEARN_MARKER_START) + ".*?" + re.escape(LEARN_MARKER_END),
            block,
            text,
            flags=re.DOTALL,
        )
    else:
        text = text.rstrip() + f"\n\n{block}\n"

    path.write_text(text, encoding="utf-8")
    return True


async def run_learn(
    workspace_dir: str | Path = "agents_workspace",
    target_file: str | Path = "AGENTS.md",
    dry_run: bool = True,
) -> dict[str, Any]:
    if not is_enabled() and not dry_run:
        return {"enabled": False, "reason": "HEADROOM_LEARN not set"}

    ws = Path(workspace_dir)
    if not ws.exists():
        return {"error": f"Workspace not found: {ws}"}

    all_failures: list[FailureRecord] = []
    agent_dirs = [d for d in ws.iterdir() if d.is_dir()]

    for agent_dir in agent_dirs:
        agent_id = agent_dir.name
        failures = _scan_agent_log(agent_dir, agent_id)
        all_failures.extend(failures)

    if not all_failures:
        return {"failures": 0, "message": "No failures found"}

    patterns = _analyze_patterns(all_failures)
    markdown = _generate_markdown(patterns)

    if not markdown:
        return {"failures": len(all_failures), "patterns": 0, "message": "No actionable patterns"}

    result = {
        "failures": len(all_failures),
        "patterns": len(patterns),
        "summary": f"Found {len(all_failures)} failures, {len(patterns)} actionable patterns",
    }

    if dry_run:
        result["dry_run"] = True
        result["preview"] = markdown
    else:
        wrote = write_learnings(markdown, target_file)
        result["dry_run"] = False
        result["written"] = wrote
        result["target"] = str(target_file)

    for p in patterns:
        logger.info("[LEARN] %s: %s (x%d)", p.category, p.pattern, p.frequency)

    return result
