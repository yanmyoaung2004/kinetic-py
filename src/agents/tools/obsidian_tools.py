"""Obsidian tools — read, write, search, and link notes in your vault."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.agents.tools.obsidian_vault import (
    all_notes,
    build_frontmatter,
    extract_wikilinks,
    parse_frontmatter,
    vault_path,
)
from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition


async def _obsidian_create_note(args: dict[str, Any], ctx: ToolContext | None) -> str:
    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    path_str = args.get("path", "").strip()
    content = args.get("content", "").strip()
    if not path_str:
        return "ERROR: 'path' is required (e.g., 'Projects/Idea.md')."

    file_path = (root / path_str).resolve()
    if not str(file_path).startswith(str(root)):
        return "ERROR: Path escapes vault."

    if file_path.exists():
        return f"ERROR: Note already exists at {path_str}"

    tags = args.get("tags", [])
    frontmatter = {
        "title": file_path.stem,
        "created": datetime.now().strftime("%Y-%m-%d"),
    }
    if tags:
        frontmatter["tags"] = tags if isinstance(tags, list) else [tags]

    file_path.parent.mkdir(parents=True, exist_ok=True)
    full = build_frontmatter(frontmatter) + content + "\n"
    file_path.write_text(full, encoding="utf-8")
    return f"Created note: {path_str}"


async def _obsidian_search(args: dict[str, Any], ctx: ToolContext | None) -> str:
    query = args.get("query", "").strip().lower()
    tag = args.get("tag", "").strip().lower()
    folder = args.get("folder", "").strip().lower()

    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."
    notes = all_notes()
    if not notes:
        return "Vault is empty."

    results = []
    for fp in notes:
        if folder and not fp.relative_to(root).as_posix().lower().startswith(folder):
            continue
        text = fp.read_text("utf-8", errors="replace")
        fm, body = parse_frontmatter(text)

        if tag:
            note_tags = fm.get("tags", [])
            if isinstance(note_tags, str):
                note_tags = [note_tags]
            if tag not in [t.lower() for t in note_tags]:
                continue

        if query and query not in text.lower():
            continue

        rel = fp.relative_to(root).as_posix()
        title = fm.get("title", fp.stem)
        results.append(f"  [[{rel[:-3]}]]  — {title}")

    if not results:
        return "No matching notes found."
    return f"Matching notes ({len(results)}):\n" + "\n".join(results[:30])


async def _obsidian_graph_query(args: dict[str, Any], ctx: ToolContext | None) -> str:
    note_ref = args.get("note", "").strip()
    find_orphans = args.get("orphans", False)

    notes = all_notes()
    if not notes:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    # Build link graph: note_name -> set of linked note names
    graph: dict[str, set[str]] = {}
    all_names: set[str] = set()
    for fp in notes:
        name = fp.stem
        all_names.add(name)
        text = fp.read_text("utf-8", errors="replace")
        note_links = extract_wikilinks(text)
        graph[name] = set(note_links)

    if find_orphans:
        # Notes with zero inbound links from other notes
        inbound: dict[str, int] = {n: 0 for n in all_names}
        for name, links in graph.items():
            for target in links:
                target_stem = target.replace(".md", "")
                if target_stem in inbound:
                    inbound[target_stem] += 1
        orphaned = sorted([n for n, c in inbound.items() if c == 0 and n != "Welcome"])
        if not orphaned:
            return "No orphan notes found. Every note has at least one backlink."
        return f"Orphan notes ({len(orphaned)}):\n" + "\n".join(f"  [[{n}]]" for n in orphaned)

    if note_ref:
        target = note_ref.replace(".md", "")
        # Forward links: what does this note link to?
        outbound = graph.get(target, set())
        # Backlinks: which notes link to this one?
        backlinks = sorted(n for n, links in graph.items() if target in links and n != target)
        parts = [f"Links from [[{target}]] ({len(outbound)}):"]
        for link_name in sorted(outbound):
            parts.append(f"  → [[{link_name}]]")
        parts.append(f"\nBacklinks to [[{target}]] ({len(backlinks)}):")
        for b in backlinks:
            parts.append(f"  ← [[{b}]]")
        return "\n".join(parts)

    # Summary stats
    linked = sum(1 for links in graph.values() if links)
    total = len(notes)
    orphan_count = sum(
        1 for n in all_names if n not in ("Welcome",) and not any(n in links for links in graph.values())
    )
    return f"Vault: {total} notes, {linked} with outgoing links.\nOrphans: {orphan_count} notes with zero backlinks."


async def _obsidian_daily_note(args: dict[str, Any], ctx: ToolContext | None) -> str:
    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    date_str = args.get("date", datetime.now().strftime("%Y-%m-%d"))
    folder = args.get("folder", "Daily")
    file_path = root / folder / f"{date_str}.md"

    append = args.get("append", "").strip()
    if file_path.exists() and append:
        with file_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{append}\n")
        return f"Appended to daily note: {folder}/{date_str}.md"

    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = {
            "title": date_str,
            "created": date_str,
            "tags": ["daily"],
        }
        content = f"# {date_str}\n\n## Tasks\n\n## Notes\n\n"
        file_path.write_text(build_frontmatter(frontmatter) + content, encoding="utf-8")
        return f"Created daily note: {folder}/{date_str}.md"
    else:
        text = file_path.read_text("utf-8", errors="replace")
        return f"Daily note ({date_str}):\n{text[:2000]}"


def create_obsidian_create_note_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_create_note",
                "description": "Create a new Obsidian note with optional tags and wikilinks in the content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path within vault (e.g., 'Projects/Idea.md')"},
                        "content": {"type": "string", "description": "Markdown content with [[wikilinks]]"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tags for frontmatter",
                        },
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_obsidian_create_note,
    )


def create_obsidian_search_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_search",
                "description": "Search notes in your Obsidian vault by keyword, tag, or folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text to search for in note content"},
                        "tag": {"type": "string", "description": "Filter by tag (e.g., 'ai', 'project')"},
                        "folder": {"type": "string", "description": "Filter by folder path (e.g., 'Projects')"},
                    },
                },
            },
        ),
        execute=_obsidian_search,
    )


def create_obsidian_graph_query_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_graph_query",
                "description": "Explore how notes are connected. Find backlinks, orphans, or link stats for a note.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {"type": "string", "description": "Note name to query links for (e.g., 'My Note')"},
                        "orphans": {
                            "type": "boolean",
                            "description": "Set to true to find notes with zero backlinks",
                        },
                    },
                },
            },
        ),
        execute=_obsidian_graph_query,
    )


def create_obsidian_daily_note_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_daily_note",
                "description": "Read, create, or append to your daily Obsidian note. Auto-creates if missing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date string (default: today, format: YYYY-MM-DD)"},
                        "folder": {"type": "string", "description": "Subfolder for daily notes (default: 'Daily')"},
                        "append": {"type": "string", "description": "Text to append to today's daily note"},
                    },
                },
            },
        ),
        execute=_obsidian_daily_note,
    )
