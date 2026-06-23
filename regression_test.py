"""Regression test — validates all modules import, tools register, and key functions exist."""

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).parent
EXIT_CODE = 0


def check(condition: bool, msg: str) -> None:
    global EXIT_CODE
    if condition:
        print(f"  OK: {msg}")
    else:
        print(f"  FAIL: {msg}")
        EXIT_CODE = 1


# ── Module imports ─────────────────────────────────────

sys.path.insert(0, str(REPO))

modules = [
    "src.providers.provider",
    "src.agents.agent",
    "src.api.server",
    "src.main",
    "src.agents.memory",
    "src.agents.tools.security_tools",
    "src.agents.tools.maintenance_tools",
    "src.agents.tools.pomodoro_tool",
    "src.agents.tools.habit_tool",
    "src.agents.tools.tts_tool",
    "src.agents.tools.obsidian_tools",
    "src.agents.tools.stt_offline",
    "src.agents.tools.send_file_tool",
    "src.agents.tools.monitor_tool",
    "src.agents.tools.knowledge_tool",
    "src.agents.tools.registry",
]

print("\n=== Module Imports ===")
for mod_name in modules:
    try:
        importlib.import_module(mod_name)
        check(True, mod_name)
    except Exception as e:
        check(False, f"{mod_name} -> {e}")


# ── Tool counts ────────────────────────────────────────

print("\n=== Tool Counts ===")
import re

tool_files: dict[str, tuple[str, str]] = {
    "security_tools.py": ("src/agents/tools/security_tools.py", "create_security_tools"),
    "maintenance_tools.py": ("src/agents/tools/maintenance_tools.py", "create_maintenance_tools"),
    "pomodoro_tool.py": ("src/agents/tools/pomodoro_tool.py", "create_pomodoro_tools"),
    "habit_tool.py": ("src/agents/tools/habit_tool.py", "create_habit_tools"),
}

expected_counts = {
    "security_tools.py": 33,
    "maintenance_tools.py": 3,
    "pomodoro_tool.py": 4,
    "habit_tool.py": 6,
}

for fname, (fpath, _) in tool_files.items():
    c = open(fpath).read()
    # Count tool handler registrations (actual tools, not helpers)
    count = len(re.findall(r'_make_handler\(\n\s+_', c))
    exp = expected_counts.get(fname, "?")
    check(count == exp, f"{fname}: {count} tools (expected {exp})")


# ── Agent.py imports and registration ──────────────────

print("\n=== Agent Registration ===")
agent_src = open("src/agents/agent.py").read()
security_imported = "from src.agents.tools.security_tools import create_security_tools" in agent_src
check(security_imported, "security_tools imported in agent.py")

habit_imported = "from src.agents.tools.habit_tool import create_habit_tools" in agent_src
check(habit_imported, "habit_tool imported in agent.py")

pomodoro_imported = "from src.agents.tools.pomodoro_tool import create_pomodoro_tools" in agent_src
check(pomodoro_imported, "pomodoro_tool imported in agent.py")

maintenance_imported = "from src.agents.tools.maintenance_tools import create_maintenance_tools" in agent_src
check(maintenance_imported, "maintenance_tools imported in agent.py")

tts_imported = "from src.agents.tools.tts_tool import create_tts_speak_tool" in agent_src
check(tts_imported, "tts_tool imported in agent.py")


# ── Security tools count ───────────────────────────────

print("\n=== Security Agent Whitelist ===")
agents_json = open("config/agents.json").read()
security_tools_in_config = re.findall(r'"security_[a-z_]+"', agents_json)
coding_tools_in_config = re.findall(r'"security_[a-z_]+"', agents_json[agents_json.find("coding-assistant"):])
check(len(security_tools_in_config) >= 15, f"{len(security_tools_in_config)} security tools in security-agent whitelist")


# ── Key env vars in code ───────────────────────────────

print("\n=== Env Var References ===")
voice_chat = open("voice_chat.py").read()
check("STT_BACKEND" in voice_chat, "STT_BACKEND env var supported")
check("PTT_KEY" in voice_chat, "PTT_KEY env var supported")
check("TTS_VOICE" in voice_chat, "TTS_VOICE env var supported")
check("TTS_SPEED" in voice_chat, "TTS_SPEED env var supported")
check("HIDE_CONSOLE" in voice_chat, "HIDE_CONSOLE env var supported")


# ── Cross-session memory ───────────────────────────────

print("\n=== Cross-session Memory ===")
memory_src = open("src/agents/memory.py").read()
check("forget_fact" in memory_src, "forget_fact method exists")
check("read_global_profile" in memory_src, "read_global_profile method exists")
check("_global_profile_path" in memory_src, "global_profile_path defined")


# ── Telegram commands ──────────────────────────────────

print("\n=== Telegram Commands ===")
main_src = open("src/main.py", encoding="utf-8").read()
check("/tts_on" in main_src, "/tts_on command")
check("/tts_off" in main_src, "/tts_off command")
check("/forget_fact" in main_src, "/forget_fact command")
check("_send_tts" in main_src, "_send_tts method")
check("_tts_enabled_chats" in main_src, "TTS state tracking")


# ── Docker ─────────────────────────────────────────────

print("\n=== Docker ===")
check(Path("Dockerfile").exists(), "Dockerfile exists")
check(Path("docker-compose.yml").exists(), "docker-compose.yml exists")
check(Path(".dockerignore").exists(), ".dockerignore exists")


# ── Tauri ──────────────────────────────────────────────

print("\n=== Desktop UI (Tauri) ===")
check(Path("src-tauri").is_dir(), "src-tauri/ directory exists")
check(Path("src-tauri/Cargo.toml").exists(), "Cargo.toml exists")
check(Path("desktop/index.html").exists(), "desktop/index.html exists")


# ── Summary ────────────────────────────────────────────

print(f"\n{'='*40}")
if EXIT_CODE == 0:
    print("All regression checks PASSED")
else:
    print(f"FAILURES DETECTED (exit code {EXIT_CODE})")

sys.exit(EXIT_CODE)
