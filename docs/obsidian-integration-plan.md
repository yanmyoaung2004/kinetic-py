# Obsidian Integration — Plan

## Goal

Connect K.I.N.E.T.I.C. to the user's local Obsidian vault so the AI agent becomes a second brain co-pilot — reading, writing, linking, and querying notes just like a human.

## Prerequisites (what you need)

- An **Obsidian vault** folder (e.g., `D:/Obsidian/MyVault/`)
- Set env var: `OBSIDIAN_VAULT_PATH=D:/Obsidian/MyVault`

---

## Phase 1 — Read & Understand (existing tools work already)

K.I.N.E.T.I.C. already has file tools that work on any markdown file:

| Tool | What it does for Obsidian |
|------|--------------------------|
| `read_file` | Read any `.md` note from vault |
| `list_files` | List all notes, browse by folder |
| `grep/search` (via execute_command) | Find notes by keyword |
| `query_knowledge_base` | Semantic search over indexed notes (RAG) |

**What to add:** nothing yet — these already work. Point K.I.N.E.T.I.C. to the vault path and test.

---

## Phase 2 — Write & Create (new tools needed)

### Tool: `obsidian_create_note`
- Creates a new `.md` file at `vault/path/to/note.md` with frontmatter
- Supports `[[wikilinks]]` to existing notes
- Auto-generates YAML frontmatter (status, tags, dates)

### Tool: `obsidian_update_note`
- Edit an existing note — add content, update frontmatter, append to bottom
- Preserves existing `[[wikilinks]]` and formatting

### Tool: `obsidian_link_notes`
- Find orphan notes (no backlinks) and suggest connections
- Insert `[[wikilink]]` between related notes
- Returns a link map: "Note A ← → Note B ← → Note C"

---

## Phase 3 — Search & Query

### Tool: `obsidian_search`
- Full-text search across vault using `grep`/ripgrep
- Filter by folder, tag, frontmatter field
- Returns matching note paths + preview

### Tool: `obsidian_graph_query`
- Query the link graph: "Which notes link to Project X?"
- Find unlinked notes: "List notes that mention 'AI' but don't link to `[[AI]]`"
- Visualize: return related notes as a connected list

### Tool: `obsidian_daily_note`
- Read or create today's daily note (`Daily/2026-06-18.md`)
- Append tasks, journal entries, or meeting notes
- Auto-tag based on content (AI detects if it's a meeting note vs journal)

---

## Phase 4 — Smart Features (K.I.N.E.T.I.C. differentiator)

### Bi-directional linking assistant
When you write a note, K.I.N.E.T.I.C. automatically suggests `[[links]]` to existing notes based on semantic similarity. Uses the vector store (already built!) to find related content before you finish typing.

### "What's floating alone?" — orphan detector
1. Scan all `.md` files
2. Parse all `[[wikilinks]]` 
3. Compare against all note filenames
4. Return list of notes with zero inbound links

### Auto-tagging
When a note is created, K.I.N.E.T.I.C. reads the content and suggests relevant tags and frontmatter:
```yaml
---
title: Agentic AI Workflow
tags: [ai, agents, workflow]
status: draft
created: 2026-06-18
related: [[Multi-Agent Systems]], [[LangChain]]
---
```

### Daily digest agent
Every morning, K.I.N.E.T.I.C. reads:
- Yesterday's daily note (what you worked on)
- Your scheduled tasks (what's due)
- Recent GitHub activity (if indexed)
Then creates a new daily note with:
```markdown
## Morning Brief — 2026-06-18
### ⏳ Due Today
- [ ] Finish Obsidian integration plan

### 📝 Yesterday's Notes
- [[Agentic AI Workflow]] — added implementation notes

### 🔗 Suggested Connections
- [[RAG Pipeline]] might relate to [[Vector Store Tuning]]
```

---

## Phase 5 — Canvas & Visuals

### Tool: `obsidian_canvas_add`
- Canvas files are JSON (`.canvas` file extension)
- Parse and append new cards to an existing canvas
- Create new canvas from a query: "Make a canvas of all my AI project notes"

### Tool: `obsidian_spaced_repetition`
- Detect `#flashcard` or `::` markers in notes (SR plugin format)
- Generate Anki-compatible CSV from tagged content
- "Quiz me on what I learned this week" — pulls from notes with flashcard markers

---

## Files to create

```
src/agents/tools/obsidian_tools.py   — all Obsidian tools
src/agents/tools/obsidian_vault.py   — vault path resolver, link parser, frontmatter helpers
config/skills/obsidian-assistant/    — skill pack with tool whitelist
├── skill.json
└── SOUL.md
```

## Config

```env
OBSIDIAN_VAULT_PATH=D:/Obsidian/MyVault
```

```json
// agents.json skill entry
{
  "id": "obsidian-assistant",
  "name": "Second Brain Assistant",
  "soulPath": "./skills/obsidian-assistant/SOUL.md",
  "tools": [
    "read_file", "write_file", "edit_file", "list_files",
    "obsidian_create_note", "obsidian_update_note",
    "obsidian_search", "obsidian_graph_query",
    "obsidian_daily_note", "obsidian_canvas_add"
  ],
  "can_delegate": false
}
```

## Test Prompts

### obsidian_edit_note
```
edit obsidian note AI Notes.md and append "## New Section\nAdded via edit tool"
edit my note about transformers and prepend "## Updated\nThis was prepended"
edit Daily/2026-06-18.md and replace the content with "# New content only"
```

### obsidian_search
```
search my vault for "transformers"
search notes with tag ai
find notes in my Projects folder about agents
```

### obsidian_graph_query
```
what links to my Transformers note?
show me orphan notes
which notes have no backlinks?
```

### obsidian_daily_note
```
show my daily note for today
create a daily note for 2026-06-20
append "- reviewed PR" to today's daily note
```

### obsidian_suggest_links
```
suggest links for "building AI agents with LangChain and vector databases"
find related notes about "multi-agent orchestration patterns"
```

### obsidian_daily_digest
```
run daily digest for today
generate my morning brief
```

### obsidian_canvas_add
```
add a card to Brainstorm.canvas titled "Multi-Agent Design" with notes about orchestration patterns
create a canvas called "Project Ideas.canvas" and add a card about RAG pipelines
add a card to Brainstorm.canvas titled "TODO" colored red
```

### obsidian_spaced_repetition
```
show me all flashcards in my vault
quiz me on my flashcards
export flashcards as CSV for Anki
list flashcards from my notes
```

---

## Dependency

- `pip install pyyaml` (for frontmatter parsing) — already in pyproject.toml as optional

---

## Timeline

| Phase | What | Time |
|-------|------|------|
| P1 | Read/search existing vault | Already works |
| P2 | Create/edit notes + wikilinks | ~1 session |
| P3 | Search, graph query, daily notes | ~1 session |
| P4 | Orphan detector, auto-tagging, daily digest | ~1-2 sessions |
| P5 | Canvas, spaced repetition | ~1 session |
