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


async def _obsidian_edit_note(args: dict[str, Any], ctx: ToolContext | None) -> str:
    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    path_str = args.get("path", "").strip()
    if not path_str:
        return "ERROR: 'path' is required (e.g., 'Projects/Idea.md')."

    file_path = (root / path_str).resolve()
    if not str(file_path).startswith(str(root)):
        return "ERROR: Path escapes vault."
    if not file_path.exists():
        return f"ERROR: Note not found: {path_str}"

    content = args.get("content", "").strip()
    mode = args.get("mode", "replace")

    if mode == "replace":
        fm, _ = parse_frontmatter(file_path.read_text("utf-8"))
        full = build_frontmatter(fm) + content + "\n"
        file_path.write_text(full, encoding="utf-8")
        return f"Replaced content in: {path_str}"
    elif mode == "append":
        with file_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{content}\n")
        return f"Appended to: {path_str}"
    elif mode == "prepend":
        fm, body = parse_frontmatter(file_path.read_text("utf-8"))
        full = build_frontmatter(fm) + content + "\n\n" + body
        file_path.write_text(full, encoding="utf-8")
        return f"Prepended to: {path_str}"
    else:
        return f"ERROR: Unknown mode '{mode}'. Use replace, append, or prepend."


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


async def _obsidian_suggest_links(args: dict[str, Any], ctx: ToolContext | None) -> str:
    text = args.get("text", "").strip()
    if not text:
        return "ERROR: 'text' parameter is required."

    import re

    # Extract significant words (4+ chars, not common stopwords)
    stopwords = {"this", "that", "with", "from", "have", "been", "were", "what",
                 "when", "where", "which", "their", "there", "about", "would",
                 "could", "should", "into", "than", "then", "also", "very",
                 "just", "more", "some", "them", "make", "than", "note"}
    words = set()
    for w in re.findall(r"[A-Za-z]{4,}", text.lower()):
        if w not in stopwords:
            words.add(w)

    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    scored: list[tuple[str, str, int]] = []  # (rel_path, title, score)
    for fp in all_notes():
        try:
            note_text = fp.read_text("utf-8", errors="replace")
            fm, body = parse_frontmatter(note_text)
            title = fm.get("title", fp.stem)
            rel = fp.relative_to(root).as_posix()[:-3]

            # Score: title matches count double, body matches count once
            score = 0
            lower_body = body.lower()
            lower_title = title.lower()
            for w in words:
                if w in lower_title:
                    score += 3
                if w in lower_body:
                    score += 1

            if score > 0 and fp.stem.lower() not in text.lower():
                scored.append((rel, title, score))
        except Exception:
            continue

    scored.sort(key=lambda x: -x[2])
    top = scored[:10]

    if not top:
        return "No related notes found. The vault might be empty or the text doesn't match existing content."

    parts = [f"Suggested [[wikilinks]] ({len(top)}):"]
    for rel, title, score in top:
        parts.append(f"  [[{rel}]]  — {title}")
    return "\n".join(parts)


async def _obsidian_daily_digest(args: dict[str, Any], ctx: ToolContext | None) -> str:
    from datetime import timedelta

    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    today = datetime.now()
    yesterday = today - timedelta(days=1)
    date_str = args.get("date", today.strftime("%Y-%m-%d"))
    folder = args.get("folder", "Daily")
    target_path = root / folder / f"{date_str}.md"
    yesterday_path = root / folder / f"{yesterday.strftime('%Y-%m-%d')}.md"

    # 1. Read yesterday's note
    yesterday_content = ""
    if yesterday_path.exists():
        _, y_body = parse_frontmatter(yesterday_path.read_text("utf-8"))
        yesterday_content = y_body.strip()

    # 2. Scan recently modified notes (last 24h from vault)
    recent_notes: list[str] = []
    for fp in all_notes():
        try:
            mtime = datetime.fromtimestamp(fp.stat().st_mtime)
            if mtime > yesterday:
                fm, _ = parse_frontmatter(fp.read_text("utf-8", errors="replace"))
                rel = fp.relative_to(root).as_posix()[:-3]
                recent_notes.append(f"  - [[{rel}]] — {fm.get('title', fp.stem)}")
        except Exception:
            continue

    # 3. Build digest content
    digest_lines = [f"# Morning Brief — {date_str}\n"]

    if yesterday_content:
        digest_lines.append("## 📝 Yesterday's Notes\n")
        # Just show a summary of yesterday's content
        yesterday_summary = yesterday_content[:500]
        digest_lines.append(yesterday_summary + "\n")

    if recent_notes:
        digest_lines.append("### 🆕 Recently Modified\n")
        digest_lines.extend(recent_notes[:10])
        digest_lines.append("")

    # Find orphan notes and offer suggestions
    graph: dict[str, set[str]] = {}
    all_names: set[str] = set()
    for fp in all_notes():
        name = fp.stem
        all_names.add(name)
        text = fp.read_text("utf-8", errors="replace")
        graph[name] = set(extract_wikilinks(text))

    orphaned = sorted(
        n for n in all_names
        if n not in ("Welcome",)
        and not any(n in links for links in graph.values())
        and n.lower() != "daily"
    )
    if orphaned:
        digest_lines.append("\n### 🔗 Notes Without Backlinks\n")
        digest_lines.append(f"  {len(orphaned)} orphan notes. Try linking them somewhere:\n")
        for o in orphaned[:5]:
            digest_lines.append(f"  - [[{o}]]")
        digest_lines.append("")

    digest = "\n".join(digest_lines)

    # Create or update today's daily note
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {"title": date_str, "created": date_str, "tags": ["daily", "digest"]}
    full = build_frontmatter(frontmatter) + digest + "\n## Tasks\n\n## Notes\n\n"
    target_path.write_text(full, encoding="utf-8")

    return f"Morning brief created: {folder}/{date_str}.md\n\n{digest[:1000]}"


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


def create_obsidian_edit_note_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_edit_note",
                "description": "Edit an existing Obsidian note. Supports replace, append, or prepend mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path within vault (e.g., 'Projects/Idea.md')"},
                        "content": {"type": "string", "description": "Markdown content to write"},
                        "mode": {
                            "type": "string",
                            "description": "'replace' (default), 'append', or 'prepend'",
                        },
                    },
                    "required": ["path"],
                },
            },
        ),
        execute=_obsidian_edit_note,
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


def create_obsidian_suggest_links_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_suggest_links",
                "description": (
                    "Analyze text and suggest related [[wikilinks]] to existing vault notes"
                    " based on keyword matching."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to analyze and find related notes for"},
                    },
                    "required": ["text"],
                },
            },
        ),
        execute=_obsidian_suggest_links,
    )


def create_obsidian_daily_digest_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_daily_digest",
                "description": (
                    "Generate a morning brief: reads yesterday's daily note,"
                    " finds recently modified files, detects orphans,"
                    " and creates today's daily note."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date string (default: today, format: YYYY-MM-DD)"},
                        "folder": {"type": "string", "description": "Subfolder for daily notes (default: 'Daily')"},
                    },
                },
            },
        ),
        execute=_obsidian_daily_digest,
    )
