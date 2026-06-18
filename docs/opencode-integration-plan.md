# OpenCode Integration — Plan

## Goal

Delegate complex coding tasks from K.I.N.E.T.I.C. to OpenCode (Go), so OpenCode handles multi-file project work while K.I.N.E.T.I.C. handles daily life.

## Architecture

```
User: "add user authentication"
         │
         ▼
  K.I.N.E.T.I.C. main agent
         │
         ├── Detects: multi-file, project-level task
         │
         ▼
  call_opencode tool
         │
         ▼
  opencode run "implement JWT auth..."
  --dangerously-skip-permissions
  --dir D:/Projects/kinetic
  --format json
         │
         ▼
  Captures JSON output (tool_use events)
  Extracts: files changed, diff, tokens, cost
         │
         ▼
  Returns summary to main agent
         │
         ▼
  Main agent shows user:
    "OpenCode modified 3 files:
      • src/api/auth.py (new)
      • src/api/server.py (modified)
      • requirements.txt (modified)
    Token cost: $0.02
    Apply these changes? (yes/no/approve)"
```

## Files to Create

```
src/agents/tools/opencode_tool.py   — the call_opencode tool
config/skills/opencode-assistant/   — skill pack
├── skill.json
└── SOUL.md
```

## Implementation Steps

### Step 1: Create `call_opencode` tool
- Runs `opencode run TASK --dangerously-skip-permissions --dir PROJECT --format json`
- Captures stdout + stderr
- Parses JSON events to extract:
  - Files written/edited (from `tool_use` events with `write` tool)
  - Token usage + cost (from `step_finish` events)
  - Final text output
- Returns structured summary

### Step 2: Show diff (optional)
- Before applying, run `git diff` to show all changes
- Return diff text in the summary

### Step 3: Apply / Reject flow
- If user says "yes" → run `git add -A && git commit -m "opencode: TASK"`
- If user says "no" → run `git checkout -- .` (or `git restore .`)
- If user says "edit" → leave changes unstaged, let user modify

### Step 4: Register + Auto-detect
- Register `call_opencode` tool
- Auto-detect complex coding tasks (anything with "add feature", "implement", "refactor", "create component")
- Route to `call_opencode` instead of `coding-assistant`

## Config

```env
# Optional overrides
OPENCODE_PROJECT_DIR=D:\Projects_And_Learning\AI\K.I.N.E.T.I.C\dev-python
OPENCODE_DEFAULT_MODEL=go/sonnet
```

## No History Pollution

- `--dangerously-skip-permissions` → no permission prompts from OpenCode
- All tool output captured internally by `call_opencode`
- Only the final summary (files changed, diff) reaches the main agent's conversation
- The main agent doesn't see individual tool calls or file reads
