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
    stopwords = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "what",
        "when",
        "where",
        "which",
        "their",
        "there",
        "about",
        "would",
        "could",
        "should",
        "into",
        "than",
        "then",
        "also",
        "very",
        "just",
        "more",
        "some",
        "them",
        "make",
        "than",
        "note",
    }
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
        n
        for n in all_names
        if n not in ("Welcome",) and not any(n in links for links in graph.values()) and n.lower() != "daily"
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
                "description": (
                    "Create a new note in your permanent Obsidian vault"
                    " (OBSIDIAN_VAULT_PATH). Use this for knowledge, ideas,"
                    " journal entries. NOT the same as write_file which goes to"
                    " agent_sandbox/."
                ),
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
                    "SEARCH YOUR OBSIDIAN VAULT for notes related to the given text."
                    " Use this when the user asks to find or suggest links,"
                    " resources, or related notes about a topic."
                    " Returns [[wikilinks]] to matching vault notes."
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


# ── Phase 5: Canvas & Spaced Repetition ──


async def _obsidian_canvas_add(args: dict[str, Any], ctx: ToolContext | None) -> str:
    import json
    import uuid

    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    path_str = args.get("path", "").strip()
    if not path_str.endswith(".canvas"):
        path_str += ".canvas"

    file_path = (root / path_str).resolve()
    if not str(file_path).startswith(str(root)):
        return "ERROR: Path escapes vault."

    card_text = args.get("card", "").strip()
    card_title = args.get("title", "").strip() or "Card"
    color = args.get("color", "").strip()

    # Load or create canvas
    if file_path.exists():
        try:
            canvas = json.loads(file_path.read_text("utf-8"))
        except json.JSONDecodeError:
            canvas = {"nodes": [], "edges": []}
    else:
        canvas = {"nodes": [], "edges": []}

    # Add card node
    node_id = str(uuid.uuid4())
    x = args.get("x", len(canvas["nodes"]) * 50)
    y = args.get("y", len(canvas["nodes"]) * 50)
    node = {
        "id": node_id,
        "x": x,
        "y": y,
        "width": 400,
        "height": 200 if card_text else 60,
        "type": "text",
        "text": f"# {card_title}\n{card_text}" if card_text else card_title,
    }
    if color:
        node["color"] = color
    canvas["nodes"].append(node)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(canvas, indent=2), encoding="utf-8")
    return f"Added card '{card_title}' to canvas: {path_str}"


async def _obsidian_spaced_repetition(args: dict[str, Any], ctx: ToolContext | None) -> str:
    import re

    root = vault_path()
    if not root:
        return "ERROR: OBSIDIAN_VAULT_PATH not set."

    action = args.get("action", "list").strip().lower()

    # Scan all notes for flashcard markers
    flashcards: list[dict[str, str]] = []
    for fp in all_notes():
        try:
            text = fp.read_text("utf-8", errors="replace")
            _, body = parse_frontmatter(text)
            rel = fp.relative_to(root).as_posix()[:-3]

            # Parse :: format: Question::Answer
            for line in body.split("\n"):
                line = line.strip()
                if "::" in line and not line.startswith("```"):
                    parts = line.split("::", 1)
                    q, a = parts[0].strip(), parts[1].strip()
                    if q and a and len(q) > 5:
                        flashcards.append({"note": rel, "question": q, "answer": a, "type": "qa"})

            # Parse ? / ! format (Obsidian SR plugin)
            q_lines = []
            for line in body.split("\n"):
                if line.startswith("?"):
                    q_lines.append(line[1:].strip())
                elif line.startswith("!") and q_lines:
                    answer = line[1:].strip()
                    for question in q_lines:
                        flashcards.append({"note": rel, "question": question, "answer": answer, "type": "qa"})
                    q_lines = []
                elif not line.startswith("?"):
                    q_lines = []

            # Detect cloze deletions {c1:...}
            clozes = re.findall(r"\{c\d+:(.*?)\}", body)
            for cloze in clozes:
                preview = body[:100]
                flashcards.append({"note": rel, "question": f"Cloze: {preview}...", "answer": cloze, "type": "cloze"})

        except Exception:
            continue

    if action == "quiz":
        if not flashcards:
            return "No flashcards found in your vault. Add #flashcard tag or use Question::Answer format."

        import random

        sample = random.sample(flashcards, min(5, len(flashcards)))
        lines = [f"Quiz ({len(sample)} questions):\n"]
        for i, card in enumerate(sample, 1):
            lines.append(f"{i}. {card['question']}")
            lines.append(f"   → {card['answer']}  (from [[{card['note']}]])")
        return "\n".join(lines)

    if action == "csv":
        import io

        buf = io.StringIO()
        for card in flashcards:
            escaped_q = card["question"].replace('"', '""')
            escaped_a = card["answer"].replace('"', '""')
            buf.write(f'"{escaped_q}","{escaped_a}","{card["note"]}"\n')
        return f"CSV ({len(flashcards)} cards):\n\n{buf.getvalue()[:3000]}"

    # Default: list stats
    if not flashcards:
        return "No flashcards found. Add #flashcard tag or Question::Answer format to your notes."

    return f"Flashcards found: {len(flashcards)}\n\n" + "\n".join(
        f"  • {c['question'][:60]} → {c['answer'][:60]}  ([[{c['note']}]])" for c in flashcards[:15]
    )


def create_obsidian_canvas_add_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_canvas_add",
                "description": (
                    "Add a card to an Obsidian Canvas (.canvas file). "
                    "Creates the canvas if it doesn't exist. "
                    "Use for brainstorming, mind maps, and visual layouts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to .canvas file (e.g., 'Brainstorm.canvas')"},
                        "title": {"type": "string", "description": "Card title"},
                        "card": {"type": "string", "description": "Card content (markdown)"},
                        "color": {"type": "string", "description": "Optional card color"},
                    },
                    "required": ["path", "title"],
                },
            },
        ),
        execute=_obsidian_canvas_add,
    )


def create_obsidian_spaced_repetition_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "obsidian_spaced_repetition",
                "description": (
                    "Scan vault for flashcards (#flashcard tag, Question::Answer format,"
                    " or cloze deletions) and list, quiz, or export as CSV."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": (
                                "'list' (default) to show all, 'quiz' for sample questions, 'csv' for Anki export"
                            ),
                        },
                    },
                },
            },
        ),
        execute=_obsidian_spaced_repetition,
    )
