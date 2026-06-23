from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.types.llm import ChatMessage

logger = logging.getLogger("kinetic.memory")

DEFAULT_MAX_MESSAGES = 500


@dataclass
class UserProfile:
    known_facts: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    last_updated: str = ""
    extraction_count: int = 0


def _sanitize_id(id_str: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "_", id_str)


class AgentMemory:
    def __init__(
        self,
        agent_id: str,
        workspaces_dir: str | Path,
        max_messages: int | None = None,
        session_id: str | None = None,
    ) -> None:
        self.session_id = session_id or "default"
        self.max_messages = max_messages or DEFAULT_MAX_MESSAGES
        self._history: list[ChatMessage] = []
        self._user_message_count = 0

        agent_dir = Path(workspaces_dir) / _sanitize_id(agent_id)
        self._agent_dir = agent_dir

        if self.session_id == "default":
            self._history_path = agent_dir / "history.jsonl"
            self._profile_path = agent_dir / "profile.json"
        else:
            session_dir = agent_dir / "sessions" / _sanitize_id(self.session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            self._history_path = session_dir / "history.jsonl"
            self._profile_path = session_dir / "profile.json"

        agent_dir.mkdir(parents=True, exist_ok=True)
        self._global_profile_path = agent_dir / "global_profile.json"
        self._save_active_session()
        self._load()

    def _save_active_session(self) -> None:
        meta = {"sessionId": self.session_id, "updated": __import__("datetime").datetime.now().isoformat()}
        (self._agent_dir / "active_session.json").write_text(json.dumps(meta))

    @staticmethod
    def list_sessions(agent_id: str, workspaces_dir: str | Path) -> list[str]:
        base_dir = Path(workspaces_dir) / _sanitize_id(agent_id) / "sessions"
        if not base_dir.exists():
            return []
        try:
            return [d.name for d in base_dir.iterdir() if d.is_dir()]
        except OSError:
            return []

    @staticmethod
    def get_active_session(agent_id: str, workspaces_dir: str | Path) -> str:
        meta_path = Path(workspaces_dir) / _sanitize_id(agent_id) / "active_session.json"
        try:
            return json.loads(meta_path.read_text("utf-8")).get("sessionId", "default")
        except (FileNotFoundError, json.JSONDecodeError):
            return "default"

    def _load(self) -> None:
        if not self._history_path.exists():
            return
        for line in self._history_path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = ChatMessage.from_dict(json.loads(line))
                self._history.append(msg)
                if msg.role == "user":
                    self._user_message_count += 1
            except json.JSONDecodeError:
                continue

    def append(self, msg: ChatMessage) -> None:
        self._history.append(msg)
        with self._history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg.to_dict()) + "\n")
        self._trim()
        if msg.role == "user":
            self._user_message_count += 1

    def get_messages(self) -> list[ChatMessage]:
        return list(self._history)

    def get_user_message_count(self) -> int:
        return self._user_message_count

    def needs_compression(self, threshold: int = 60) -> bool:
        non_system = [m for m in self._history if m.role != "system"]
        return len(non_system) > threshold

    def get_compression_candidates(self, tail_size: int = 20) -> list[ChatMessage]:
        non_system = [m for m in self._history if m.role != "system"]
        if len(non_system) <= tail_size + 5:
            return []
        return non_system[: len(non_system) - tail_size]

    def apply_compression(self, summary: ChatMessage, tail_size: int = 20) -> None:
        system = [m for m in self._history if m.role == "system"]
        non_system = [m for m in self._history if m.role != "system"]
        tail = non_system[-tail_size:]
        self._history = [*system, summary, *tail]
        self._rewrite()
        logger.info(
            "[COMPRESS] Compressed %d messages into summary. Total history: %d",
            len(non_system) - len(tail),
            len(self._history),
        )

    def refresh_system_prompt(self, new_prompt: str) -> bool:
        if not self._history:
            return False
        first = self._history[0]
        if first.role != "system" or first.content == new_prompt:
            return False
        self._history[0] = ChatMessage(role="system", content=new_prompt)
        self._rewrite()
        return True

    def read_profile(self) -> UserProfile | None:
        session = None
        if self._profile_path.exists():
            try:
                data = json.loads(self._profile_path.read_text("utf-8"))
                session = UserProfile(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        global_p = None
        if self._global_profile_path.exists():
            try:
                data = json.loads(self._global_profile_path.read_text("utf-8"))
                global_p = UserProfile(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        if global_p is None and session is None:
            return None
        if global_p is None:
            return session
        if session is None:
            return global_p
        return UserProfile(
            known_facts=list(dict.fromkeys(global_p.known_facts + session.known_facts)),
            preferences=list(dict.fromkeys(global_p.preferences + session.preferences)),
            last_updated=session.last_updated or global_p.last_updated,
            extraction_count=session.extraction_count or global_p.extraction_count,
        )

    def write_profile(self, profile: UserProfile) -> None:
        self._profile_path.write_text(json.dumps(profile.__dict__, default=str, indent=2))
        global_p = self.read_global_profile()
        merged = UserProfile(
            known_facts=list(dict.fromkeys(profile.known_facts + (global_p.known_facts if global_p else []))),
            preferences=list(dict.fromkeys(profile.preferences + (global_p.preferences if global_p else []))),
            last_updated=profile.last_updated,
            extraction_count=profile.extraction_count,
        )
        self._global_profile_path.write_text(json.dumps(merged.__dict__, default=str, indent=2))

    def read_global_profile(self) -> UserProfile | None:
        if not self._global_profile_path.exists():
            return None
        try:
            data = json.loads(self._global_profile_path.read_text("utf-8"))
            return UserProfile(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def forget_fact(self, keyword: str) -> bool:
        global_p = self.read_global_profile()
        if not global_p:
            return False
        before = len(global_p.known_facts) + len(global_p.preferences)
        global_p.known_facts = [f for f in global_p.known_facts if keyword.lower() not in f.lower()]
        global_p.preferences = [p for p in global_p.preferences if keyword.lower() not in p.lower()]
        after = len(global_p.known_facts) + len(global_p.preferences)
        if before != after:
            self._global_profile_path.write_text(json.dumps(global_p.__dict__, default=str, indent=2))
            return True
        return False

    def reset(self) -> None:
        self._history.clear()
        self._user_message_count = 0
        if self._history_path.exists():
            self._history_path.write_text("")

    def destroy(self) -> None:
        if self._agent_dir.exists():
            shutil.rmtree(self._agent_dir)

    def _trim(self) -> None:
        if len(self._history) <= self.max_messages:
            return
        system = [m for m in self._history if m.role == "system"]
        rest = [m for m in self._history if m.role != "system"]
        keep = rest[-(self.max_messages - len(system)) :]
        self._history = [*system, *keep]
        self._rewrite()

    def _rewrite(self) -> None:
        content = "\n".join(json.dumps(m.to_dict()) for m in self._history)
        # Atomic write: write to .tmp then rename
        tmp = self._history_path.with_suffix(".jsonl.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self._history_path)


# ── Compressor functions (ported from compressor.ts) ──


def should_compress(messages: list[ChatMessage], threshold: int = 60) -> bool:
    non_system = [m for m in messages if m.role != "system"]
    return len(non_system) > threshold


def select_messages_to_compress(
    messages: list[ChatMessage], tail_size: int = 20
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    system = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    tail = non_system[-tail_size:]
    to_compress = non_system[: len(non_system) - tail_size]
    return to_compress, [*system, *tail]


def build_compression_prompt(messages: list[ChatMessage]) -> str:
    conversation = "\n".join(
        f"{'Human' if m.role == 'user' else 'Assistant' if m.role == 'assistant' else m.role}: {m.content[:300]}"
        for m in messages
    )
    return f"""Summarize this conversation.
CRITICAL: preserve time of day (morning/afternoon/evening) and what was just discussed.

Include:
- Current time of day / period (morning, afternoon, evening — if mentioned)
- Key decisions and information shared
- What was being worked on or discussed
- The assistant's last response
- Any ongoing tasks or projects
- Code execution environment if mentioned (Docker, subprocess, etc.)

Keep it under 200 words. Write in third person.

{conversation}"""


def build_summary_message(summary: str) -> ChatMessage:
    return ChatMessage(
        role="system",
        content=(
            f"[COMPRESSED HISTORY] Earlier conversation summary:\n{summary}\n\n"
            "Key context from earlier in this conversation is captured above."
            " Continue naturally."
        ),
    )
