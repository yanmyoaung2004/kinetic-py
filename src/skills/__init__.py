from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SKILLS_DIR = Path("config/skills")
CONFIG_DIR = Path("config")
COMMUNITY_REPO = os.environ.get("KINETIC_SKILLS_REPO", "https://github.com/kinetic-skills/skills.git")


@dataclass
class SkillManifest:
    id: str
    name: str
    description: str
    version: str
    tools: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    soul: str = ""


def _skill_path(skill_id: str) -> Path:
    return SKILLS_DIR / skill_id


def _manifest_path(skill_id: str) -> Path:
    return _skill_path(skill_id) / "skill.json"


def _soul_path(skill_id: str) -> Path:
    return _skill_path(skill_id) / "SOUL.md"


def discover_skills() -> list[SkillManifest]:
    if not SKILLS_DIR.exists():
        return []
    results: list[SkillManifest] = []
    for entry in sorted(SKILLS_DIR.iterdir()):
        if entry.is_dir():
            manifest = load_skill(entry.name)
            if manifest:
                results.append(manifest)
    return results


def load_skill(skill_id: str) -> SkillManifest | None:
    mp = _manifest_path(skill_id)
    if not mp.exists():
        return None
    try:
        data = json.loads(mp.read_text("utf-8"))
        sp = _soul_path(skill_id)
        soul = sp.read_text("utf-8") if sp.exists() else ""
        return SkillManifest(
            id=data.get("id", skill_id),
            name=data.get("name", skill_id),
            description=data.get("description", ""),
            version=data.get("version", "0.1.0"),
            tools=data.get("tools", []),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            soul=soul,
        )
    except (json.JSONDecodeError, KeyError):
        return None


def install_skill(name: str, activate: bool = True, url: str | None = None) -> str:
    target = _skill_path(name)
    if target.exists():
        return f"Skill '{name}' is already installed at {target}."

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    import httpx

    if url:
        # User provided a custom URL — fetch skill from there
        manifest_url = url.rstrip("/") + "/skill.json"
        soul_url = url.rstrip("/") + "/SOUL.md"
    else:
        # Default: fetch from community repo
        repo_base = COMMUNITY_REPO.rstrip("/")
        if repo_base.endswith(".git"):
            repo_base = repo_base[:-4]
        repo_base = repo_base.replace("github.com/", "raw.githubusercontent.com/")
        manifest_url = f"{repo_base}/main/{name}/skill.json"
        soul_url = f"{repo_base}/main/{name}/SOUL.md"

    try:
        resp = httpx.get(manifest_url, timeout=15)
        resp.raise_for_status()
        manifest_data = resp.json()
    except Exception:
        hint = f"from {url}" if url else f"from {COMMUNITY_REPO}"
        return (
            f"Could not fetch skill '{name}' {hint}.\n"
            f"Make sure the URL is correct and the repo has a '{name}/' directory\n"
            f"with skill.json and SOUL.md files.\n"
            f"Alternatively, place the skill directory at {SKILLS_DIR / name}."
        )

    target.mkdir(parents=True, exist_ok=True)
    (target / "skill.json").write_text(json.dumps(manifest_data, indent=2))

    try:
        soul_resp = httpx.get(soul_url, timeout=15)
        if soul_resp.status_code == 200:
            (target / "SOUL.md").write_text(soul_resp.text)
    except Exception:
        pass

    if activate:
        _register_skill_in_agents_json(name, manifest_data)

    return f"Installed skill '{name}' (v{manifest_data.get('version', '?')})."


def _register_skill_in_agents_json(skill_id: str, manifest: dict[str, Any]) -> None:
    agents_path = CONFIG_DIR / "agents.json"
    if not agents_path.exists():
        return

    try:
        data = json.loads(agents_path.read_text("utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        data = {"registry": []}

    registry = data.setdefault("registry", [])
    for existing in registry:
        if existing.get("id") == skill_id:
            return

    soul_rel = f"./skills/{skill_id}/SOUL.md"
    entry = {
        "id": skill_id,
        "name": manifest.get("name", skill_id),
        "soulPath": soul_rel,
        "provider": manifest.get("provider", ""),
        "model": manifest.get("model", ""),
        "type": "library",
        "can_delegate": False,
        "tools": manifest.get("tools", []),
    }
    registry.append(entry)
    agents_path.write_text(json.dumps(data, indent=2))


def remove_skill(skill_id: str) -> bool:
    target = _skill_path(skill_id)
    if not target.exists():
        return False

    import shutil

    shutil.rmtree(target)

    agents_path = CONFIG_DIR / "agents.json"
    if agents_path.exists():
        try:
            data = json.loads(agents_path.read_text("utf-8"))
            registry = data.get("registry", [])
            data["registry"] = [a for a in registry if a.get("id") != skill_id]
            agents_path.write_text(json.dumps(data, indent=2))
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    return True
