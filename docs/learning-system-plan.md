# Learning System — "Luck Is All You Need"

## Problem

Same user request → different quality every time. The agent hallucinates useless tool calls (`list_files`, `obsidian_search`, etc.) when it already knows the correct workflow. Successful outcomes are not learned.

## Core Idea

When a task is done perfectly and the user confirms it (`/perfect`), the system records the **exact sequence of tool calls** that won. Next time a similar request comes, the agent skips the wandering and follows the proven path.

## Storage: SQLite

Use the existing SQLite knowledge store instead of JSON files. Lighter, queryable, no new dependencies.

Schema:
```sql
CREATE TABLE workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,          -- "create presentation", "send email", etc.
    tool_sequence TEXT NOT NULL,    -- '["create_presentation", "send_file"]'
    user_message TEXT,              -- original prompt that won
    timestamp TEXT,
    success_count INTEGER DEFAULT 1
);
```

## How It Works

### Learning — Auto-Feedback After Task

After the agent finishes a task (tool calls completed), it appends:
```
Are you satisfied with how that was handled? (yes/no)
```

- **Yes** → Store the workflow automatically
- **No** → Try a different approach next time, don't store
- **Skip** → User can also say `/perfect` later to store manually

### Learning (`/perfect`)

Manual alternative:
```
User: "create a presentation about AI"
Agent: [calls create_presentation → send_file → done]
User: "/perfect"
```

The system:
1. Captures the tool calls from the last successful think loop iteration
2. Extracts the trigger phrase (e.g., "presentation", "create")
3. Stores in SQLite: `trigger="presentation"`, `tool_sequence=["create_presentation","send_file"]`

### Recalling (before think loop)

Before the agent starts its think loop:
1. Extract trigger words from the user's message
2. Query SQLite: `SELECT * FROM workflows WHERE trigger LIKE '%presentation%'`
3. If a match is found, inject a system message:
   ```
   [LEARNED WORKFLOW] For tasks like "create a presentation",
   the proven sequence is: create_presentation → send_file.
   Do NOT call list_files, obsidian_search, or other unrelated tools.
   Stick to the proven sequence.
   ```

### Rejection / Correction

If a learned workflow becomes wrong:
```
User: "/forget presentation"
```
Deletes the workflow entry.

Or:
```
User: "/correct presentation"
``` 
Does the task again, learns the new sequence.

## Implementation Plan

### Phase 1: Storage & `/perfect` command
- Create SQLite table `workflows`
- Add `/perfect` CLI command that captures last tool sequence
- Store trigger words + tool sequence

### Phase 2: Recall & inject
- Before think loop, query for matching workflows
- Inject as system message with proven sequence
- Suppress unrelated tools by listing allowed ones

### Phase 3: Auto-detect success
- If user says "perfect", "great", "exactly" after a response → auto-learn
- `/forget` to delete bad patterns
- `/correct` to replace with new sequence

## Expected Outcome

1st time: Agent might call `list_files`, `obsidian_search`, hallucinate → user rates `/perfect` after one clean run

2nd time: Agent skips to `create_presentation` → `send_file` directly. No wandering.

3rd time: Same. Consistent. Reliable.

"Luck is all you need" — once you get it right, you don't need luck anymore.
