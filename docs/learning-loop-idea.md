# Self-Improving Learning Loop

When the agent solves a multi-step task successfully, automatically write a reusable skill document so it never forgets how to do it in the future.

## Current State

- `/perfect` saves tool sequences to SQLite manually
- Agent follows saved workflows but doesn't adapt or improve them
- No learning from user corrections or failures

## Proposed Design

### Automatic Trigger
After every successful multi-step response (no errors, user satisfied), run a background task that:

1. Extracts the user's request, tool sequence, reasoning, and output format
2. Generates a SOUL.md skill document at `config/skills/learned/<topic>.md`
3. Registers it in `agents.json`

### Skill Document Format
```markdown
# Learned Skill: <topic>

## Trigger
When the user asks: <example queries>

## Steps
1. Analyze request
2. Call tool X with parameters Y
3. Format output as Z

## Notes
- Any pitfalls or edge cases discovered
- Model used for verification
```

### Reuse
- Skills are loaded like any other agent skill
- On matching queries, the skill is injected as system prompt context
- Agent follows the proven pattern instead of reasoning from scratch

### Cost Impact
- Learning: background task, zero latency impact
- Reuse: replaces tokens the agent would spend reasoning — roughly cost-neutral or cheaper for repeated tasks

## Not Yet Implemented

Planned but not built:
- [ ] Background extraction of tool sequences and outcomes
- [ ] SOUL.md generation from successful patterns
- [ ] Automatic registration in config/skills/learned/
- [ ] Skill matching and injection on similar queries
- [ ] Skill versioning and improvement from corrections
