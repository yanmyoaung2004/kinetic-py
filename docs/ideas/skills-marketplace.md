# Skill System for K.I.N.E.T.I.C.

## Problem Statement

K.I.N.E.T.I.C. has 31 tools and unlimited agent potential, but every agent loads every tool and adding new capabilities requires editing Python files. There's no way to install, share, or compose focused capabilities without touching code.

## Recommended Direction

Turn **skills into installable sub-agents** with tool whitelisting, distributed via a community GitHub repo.

Three layers that work together:

| Layer | What | How |
|-------|------|-----|
| **Architecture** (Var 6) | A skill = a sub-agent with its own SOUL.md + tool subset | `spawn_specialist` already exists; skills are just pre-made specialist configs |
| **Isolation** (Var 4) | Each skill agent only gets the tools it needs | Add `"tools"` whitelist to `AgentCard` / `agents.json` |
| **Distribution** (Var 5) | Install skills from a community repo | `kinetic skill install <name>` pulls from `github.com/kinetic-skills/<name>` |

## MVP Scope

### 1. Tool whitelist (`AgentCard.tools`)
```python
@dataclass
class AgentCard:
    ...
    tools: list[str] | None = None  # None = all tools, [] = no tools, ["web_search"] = only these
```
- Agents.json gains optional `"tools"` array per entry
- `AgentInstance.__init__` filters registered tools against whitelist
- All 31 tools get canonical string IDs (already implied by factory function names)

### 2. Skill manifest convention
A skill is a directory (local or in a repo) with:
```
my-skill/
├── skill.json        # manifest
└── SOUL.md           # system prompt
```
**skill.json:**
```json
{
  "id": "web-research",
  "name": "Web Research",
  "description": "Search the web, scrape pages, and index results",
  "version": "1.0.0",
  "tools": ["web_search", "scrape_and_index", "index_url"],
  "provider": "lightning",
  "model": "gpt-4o-mini"
}
```

### 3. `kinetic skill` CLI commands
```
kinetic skill list                    # show installed skills
kinetic skill install <name>          # download from community repo
kinetic skill install <path>          # install from local folder
kinetic skill remove <name>           # uninstall
kinetic skill info <name>             # show manifest
kinetic skill search <query>          # search community repo
```

### 4. Community repo
`github.com/kinetic-skills/skills` with a `registry.json` index and per-skill subdirectories. The `install` command clones/fetches from this repo by default (configurable via `KINETIC_SKILLS_REPO` env var).

### 5. Bundled starter skills (ship with project)
First 3-5 skills to seed the ecosystem:
- **web-research** — web search + scrape + index
- **file-organizer** — read, list, delete, undo file ops
- **email-assistant** — read, send, reply emails
- **code-runner** — execute code in sandbox
- **scheduler** — create/list/remove timed tasks

## Key Assumptions to Validate

- [ ] Tool whitelisting doesn't break existing agents that implicitly rely on all tools — all existing configs keep `tools: null` (unrestricted) by default
- [ ] Sub-agent delegation (`spawn_specialist`) is fast enough for real-time skill chaining — latency of spawning sub-agent + LLM call + return
- [ ] A community repo will get contributions — validate by shipping 5 skills and seeing if early users extend them
- [ ] The `skill install` UX is simple enough to feel like `npm install` or `brew install` — one command, no config

## Not Doing (and Why)

- **Visual UI for skill management** — CLI first, matches the project's current delivery model; GUI later if demand grows
- **Skill builder/editor** — users write JSON + Markdown; a visual editor is premature
- **Version resolution / dependency management** — skills are flat, no diamond dependencies; revisit at 50+ skills
- **Monetization / skill store payments** — this is a personal productivity tool first
- **Docker/cloud deployment** — not needed for the skill system itself; can be added later
- **Hot-reloading skills without restart** — skills load at agent init; hot reload is a future optimization
- **Per-user skill permissions** — single-user tool; multi-tenant would need auth

## Open Questions

- Should `kinetic skill install` clone the entire community repo or fetch individual skill tarballs from GitHub releases?
- How does a skill declare "I need the `BRAVE_API_KEY` env var" so the installer can warn if it's missing?
- Should skills be able to depend on other skills (e.g., `email-assistant` depends on `contact-resolver`)?
