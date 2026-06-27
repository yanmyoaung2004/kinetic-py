"""Second brain features — auto-indexing, cross-linking, knowledge injection for Obsidian vault."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.agents.tools.obsidian_vault import all_notes, vault_path

# ── Auto-indexing ──────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "and", "but", "or", "if", "while", "about", "up",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their", "please", "thanks",
    "thank", "yes", "no", "ok", "okay", "hello", "hi", "hey", "goodbye",
    "bye", "tell", "show", "give", "make", "want", "need", "know", "think",
    "help", "can", "could", "would", "should", "will", "shall", "may",
    "might", "let", "get", "find", "check", "see", "look", "use", "try",
}


def _extract_keywords(text: str, max_words: int = 8) -> list[str]:
    """Extract meaningful keywords from text for vault search."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = text.split()
    words = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    # Deduplicate while preserving order, take top meaningful words
    seen = set()
    result = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result[:max_words]


def _score_note(note_path: Path, keywords: list[str]) -> int:
    """Score a note by how many keywords appear in its title and content."""
    title = note_path.stem.lower()
    try:
        content = note_path.read_text("utf-8", errors="replace").lower()
    except Exception:
        return 0

    score = 0
    for kw in keywords:
        if kw in title:
            score += 3
        count = content.count(kw)
        score += min(count, 5)  # cap per keyword to avoid spam
    return score


async def search_vault_for_context(message: str, max_notes: int = 4) -> str:
    """Search Obsidian vault for notes relevant to the message. Returns formatted context."""
    root = vault_path()
    if not root:
        return ""

    keywords = _extract_keywords(message)
    if not keywords:
        return ""

    notes = all_notes()
    scored = [(n, _score_note(n, keywords)) for n in notes]
    scored.sort(key=lambda x: -x[1])
    top = [n for n, s in scored[:max_notes] if s > 2]

    if not top:
        return ""

    parts = ["[Relevant vault notes:]"]
    for note in top:
        rel = note.relative_to(root)
        try:
            content = note.read_text("utf-8", errors="replace")
            mtime = datetime.fromtimestamp(note.stat().st_mtime).strftime("%Y-%m-%d")
            # Strip frontmatter
            content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL).strip()
            excerpt = content[:300].strip()
            if len(content) > 300:
                excerpt += "..."
            parts.append(f"  - [[{rel.stem}]] (modified {mtime}): {excerpt}")
        except Exception:
            parts.append(f"  - [[{rel.stem}]]: (unreadable)")

    return "\n\n".join(parts)


# ── Cross-linking ──────────────────────────────────────

async def suggest_cross_links(note_title: str, note_content: str) -> str:
    """Find related notes in the vault for cross-linking suggestions."""
    root = vault_path()
    if not root:
        return ""

    keywords = _extract_keywords(note_title + " " + note_content, max_words=12)
    if not keywords:
        return ""

    notes = all_notes()
    scored = [(n, _score_note(n, keywords)) for n in notes]

    # Exclude the note itself
    scored = [(n, s) for n, s in scored if n.stem.lower() != note_title.lower()]
    scored.sort(key=lambda x: -x[1])
    top = [n for n, s in scored[:5] if s > 1]

    if not top:
        return ""

    parts = ["Related notes found — consider linking:"]
    for note in top:
        rel = note.relative_to(root)
        parts.append(f"  - [[{rel.stem}]]")
    return "\n".join(parts)


# ── Knowledge injection ────────────────────────────────

async def inject_knowledge(conversation: list[dict[str, str]], agent_id: str) -> str | None:
    """Extract insights from conversation and save as a vault note. Returns note path or None."""
    root = vault_path()
    if not root:
        return None

    # Only inject if there's meaningful exchange
    user_msgs = [m["content"] for m in conversation if m.get("role") == "user" and len(m.get("content", "")) > 20]
    if not user_msgs:
        return None

    # Use last user message as title seed
    last_msg = user_msgs[-1]
    title_words = re.sub(r"[^a-z0-9\s]", "", last_msg.lower()).split()
    title_words = [w for w in title_words if w not in _STOPWORDS and len(w) > 3]
    title = " ".join(title_words[:5]).title() if title_words else "Knowledge Snapshot"

    # Format the conversation excerpt
    excerpts = []
    for m in conversation[-6:]:
        role = "Q" if m.get("role") == "user" else "A"
        content = m.get("content", "")[:200]
        if len(content) > 200:
            content += "..."
        excerpts.append(f"**{role}:** {content}")

    content = (
        f"# {title}\n\n"
        f"Auto-saved on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        + "\n\n".join(excerpts) + "\n\n"
        "---\n*Auto-injected by K.I.N.E.T.I.C.*\n"
    )

    # Save to vault
    note_dir = root / "Inbox"
    note_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:80]
    path = note_dir / f"{safe_title}.md"

    if path.exists():
        return None  # Don't overwrite

    from src.agents.tools.obsidian_vault import build_frontmatter

    fm = build_frontmatter({"title": title, "created": datetime.now().strftime("%Y-%m-%d"), "tags": ["inbox", "auto"]})
    path.write_text(fm + content, encoding="utf-8")
    return str(path.relative_to(root))
