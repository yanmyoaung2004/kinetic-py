"""Obsidian vault helpers — path resolution, link parsing, frontmatter."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^#|]+)(?:#[^|]*)?(?:\|([^\]]+))?\]\]")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def vault_path() -> Path | None:
    raw = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if not raw:
        return None
    p = Path(raw).resolve()
    return p if p.is_dir() else None


def all_notes() -> list[Path]:
    root = vault_path()
    if not root:
        return []
    return sorted(root.rglob("*.md"))


def resolve_note(name: str) -> Path | None:
    root = vault_path()
    if not root:
        return None
    name = name.replace(".md", "")
    for f in root.rglob("*.md"):
        if f.stem.lower() == name.lower():
            return f
    return None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    import yaml

    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    body = text[m.end() :]
    return data, body


def build_frontmatter(data: dict[str, Any]) -> str:
    if not data:
        return ""
    import yaml

    header = yaml.dump(data, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n\n"


def extract_wikilinks(text: str) -> list[str]:
    return [m.group(1).strip() for m in WIKILINK_RE.finditer(text)]


def build_wikilink(target: str, alias: str | None = None) -> str:
    if alias:
        return f"[[{target}|{alias}]]"
    return f"[[{target}]]"
