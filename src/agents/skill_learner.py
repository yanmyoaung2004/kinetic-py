"""Skill learner — auto-generates reusable skill documents from successful tool sequences."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("kinetic.skill_learner")

SKILLS_DIR = Path("config") / "skills" / "learned"
INDEX_PATH = SKILLS_DIR / "index.json"


def _ensure_dirs() -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> dict[str, Any]:
    _ensure_dirs()
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text("utf-8"))
        except (json.JSONDecodeError, Exception):
            pass
    return {"skills": []}


def _save_index(index: dict[str, Any]) -> None:
    _ensure_dirs()
    INDEX_PATH.write_text(json.dumps(index, indent=2))


def _extract_topic(message: str) -> str:
    """Extract a short topic name from the user message."""
    words = re.findall(r"[a-zA-Z]{4,}", message.lower())
    stopwords = {
        "what", "when", "where", "why", "how", "which", "who", "whom",
        "tell", "show", "give", "make", "want", "need", "know", "think",
        "help", "let", "get", "find", "check", "see", "look", "use", "try",
        "please", "thanks", "thank", "would", "could", "should", "will", "shall",
        "with", "that", "this", "these", "those", "have", "has", "had", "not",
        "can", "you", "your", "for", "the", "and", "but", "are", "was", "were",
    }
    meaningful = [w for w in words if w not in stopwords]
    return "_".join(meaningful[:4]) if meaningful else "unnamed_skill"


async def extract_and_save_skill(
    message: str,
    tool_sequence: list[str],
    agent_id: str,
) -> str | None:
    """Analyze a successful tool sequence and save as a reusable skill document.
    Returns the skill name if saved, None if skipped."""
    if len(tool_sequence) < 2:
        return None  # Single-tool sequences aren't worth learning

    topic = _extract_topic(message)
    if not topic or topic == "unnamed_skill":
        name = f"skill_{len(_load_index()['skills']) + 1}"
    else:
        name = topic

    skill_path = SKILLS_DIR / f"{name}.md"
    if skill_path.exists():
        return None  # Don't overwrite existing skills

    steps = []
    for i, tool in enumerate(tool_sequence, 1):
        if tool == "send_message":
            steps.append(f"{i}. Delegate to the appropriate specialist agent via send_message")
        elif tool.startswith("security_") or tool.startswith("network_"):
            steps.append(f"{i}. Use the security-agent for this task")
        elif tool.startswith("obsidian_"):
            steps.append(f"{i}. Use the obsidian-assistant for this task")
        elif tool.startswith("habit_") or tool.startswith("pomodoro_"):
            steps.append(f"{i}. Use the productivity-agent for this task")
        elif tool.startswith("system_"):
            steps.append(f"{i}. Use the system-agent for this task")
        else:
            steps.append(f"{i}. Call {tool}")

    content = (
        f"# Learned Skill: {name}\n\n"
        f"## Trigger\n"
        f"When the user asks about: {message}\n\n"
        f"## Steps\n"
    )
    content += "\n".join(f"{s}" for s in steps) + "\n\n"
    content += "## Notes\n"
    content += f"- Learned from: {agent_id}\n"
    content += f"- Learned at: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    content += f"- Tool sequence: {' → '.join(tool_sequence)}\n"

    skill_path.write_text(content, encoding="utf-8")

    # Update index
    index = _load_index()
    index["skills"].append({
        "name": name,
        "trigger": message[:200],
        "trigger_keywords": re.findall(r"[a-zA-Z]{4,}", message.lower()),
        "tool_sequence": tool_sequence,
        "path": str(skill_path.relative_to(Path("config").parent)),
        "created": datetime.now().isoformat(),
    })
    _save_index(index)

    logger.info("[SKILL] Learned new skill '%s' (%d steps)", name, len(steps))
    return name


async def find_matching_skills(message: str) -> list[dict[str, Any]]:
    """Find learned skills that match the user's message."""
    index = _load_index()
    if not index["skills"]:
        return []

    words = set(re.findall(r"[a-zA-Z]{4,}", message.lower()))
    matches = []
    for skill in index["skills"]:
        skill_keywords = set(skill.get("trigger_keywords", []))
        overlap = words & skill_keywords
        if len(overlap) >= 2:
            # Read the skill content
            skill_path = Path("config") / "skills" / "learned" / f"{skill['name']}.md"
            if skill_path.exists():
                try:
                    content = skill_path.read_text("utf-8")
                    matches.append({
                        "name": skill["name"],
                        "content": content,
                        "overlap": len(overlap),
                    })
                except Exception:
                    pass

    matches.sort(key=lambda x: -x["overlap"])
    return matches[:2]


async def list_skills() -> list[dict[str, Any]]:
    """List all learned skills."""
    index = _load_index()
    return index["skills"]


async def forget_skill(name: str) -> bool:
    """Remove a learned skill."""
    skill_path = SKILLS_DIR / f"{name}.md"
    found = False
    if skill_path.exists():
        skill_path.unlink()
        found = True

    index = _load_index()
    before = len(index["skills"])
    index["skills"] = [s for s in index["skills"] if s["name"] != name]
    if len(index["skills"]) != before:
        found = True
        _save_index(index)

    return found
