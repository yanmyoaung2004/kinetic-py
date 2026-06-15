# K.I.N.E.T.I.C. — Rebuild Plan

**Goal:** Fix the broken foundations, unify on OpenAI-compatible endpoints, and build an architecture that beats OpenClaw on agent intelligence.

---

## Phase 1 — Fix & Unify (NOW)

### 1.1 Delete dead providers, unify on one

**Problem:** 6 provider files with 2 incompatible abstract classes. 4 providers fail at import (`BaseLLM` doesn't exist). OLLAMA never activates due to `if/if/else` bug.

**Solution:** Delete all 6 existing providers. One `UnifiedProvider` class using the OpenAI SDK — works with OpenRouter, Ollama, Groq, OpenAI, DeepSeek, or any OpenAI-compatible endpoint. The only difference is `baseUrl` + `apiKey`.

**Config-driven endpoints:**
```json
{
  "openrouter": { "baseUrl": "https://openrouter.ai/api/v1", "apiKeyEnv": "OPENROUTER_API_KEY" },
  "ollama":     { "baseUrl": "http://127.0.0.1:11434/v1",    "apiKeyEnv": "OLLAMA_API_KEY" },
  "groq":       { "baseUrl": "https://api.groq.com/openai/v1","apiKeyEnv": "GROQ_API_KEY" }
}
```

### 1.2 Stage-based model routing

Each "stage" of agent processing can use a different provider+model:

| Stage | Purpose | Cost strategy |
|---|---|---|
| `classify` | Quick intent classification | Cheap/fast (Qwen, Gemma) |
| `think` | Deep reasoning on the task | Powerful (Llama 70B, Claude) |
| `tool_call` | Structured output for tool use | Tool-capable (Llama, GPT) |
| `answer` | Final response generation | Same as think, or specialized |

Each agent can override stages. Falls back to global defaults.

### 1.3 Fix critical bugs

| Bug | Fix |
|---|---|
| OLLAMA never activates | `if/else if/else` in constructor |
| 30s agent eviction | Extend to 5m, make configurable |
| Hardcoded secrets | All keys move to `.env`, loaded at startup |
| Duplicate `ChatMessage` types | Single canonical type in `BaseLLM.ts` |
| Sub-agents always GROQ | Use parent's provider config |

---

## Phase 2 — Architecture (next)

### 2.1 SOUL personality engine (the moat)

- Every agent has a `SOUL.md` read on init, writable at runtime
- SOUL enforces response constraints, domain voice, behavioral rules
- Agents can reflect and evolve their own SOUL over time (unique vs OpenClaw)

### 2.2 Agent-to-agent communication

- Agents message each other by ID through the dispatcher
- Registry supports discovery: "find agent that can handle X"
- Async messaging with futures (agents parallelize subtasks)

### 2.3 Memory persistence

- Agent conversation history checkpoints to `agents_workspace/<id>/history/`
- Long-term memory extracted from conversations → curated memory files
- Survives restarts, survives 30s timeout

### 2.4 Autonomous heartbeats

- Background daemon polls on configurable intervals
- Agents register scheduled tasks
- Proactive work without human prompt

---

## Phase 3 — Platform (later)

- Multi-channel gateway (Telegram + Discord + Slack + REST API)
- SOUL marketplace (share agent personalities)
- Provider auto-failover (Groq down → Ollama → OpenRouter)
- Streaming-first responses
- Sub-agent swarms (parallel specialist spawning)

---

## Architecture Diagram (Target)

```
    Telegram / Discord / Slack / API
                    │
            ┌───────┴───────┐
            │    Gateway    │
            └───────┬───────┘
                    │
            ┌───────┴───────┐
            │  Dispatcher   │
            │  - registry   │
            │  - lifecycle  │
            │  - routing    │
            └───────┬───────┘
                    │
        ┌───────────┴───────────┐
        │                       │
    ┌───┴───┐             ┌─────┴─────┐
    │ Agent │◄────────────►│  Agent    │
    │(SOUL) │  ACP msg     │ (SOUL)    │
    └───┬───┘             └─────┬─────┘
        │                       │
        └───────────┬───────────┘
                    │
          ┌─────────┴─────────┐
          │   Stage Router    │
          │ classify / think  │
          │ tool_call / answer│
          └─────────┬─────────┘
                    │
          ┌─────────┴─────────┐
          │  UnifiedProvider  │
          │ (openai SDK)      │
          │ baseUrl + apiKey  │
          └───────────────────┘
```

---

## File Changes Summary

| Action | File | Reason |
|---|---|---|
| **DELETE** | `src/providers/GeminiProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/providers/GroqProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/providers/OllamaProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/providers/OpenAIProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/providers/OpenRouterProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/providers/OpenAICompatibleProvider.ts` | Replaced by UnifiedProvider |
| **DELETE** | `src/test/index.ts` | Dead code, never wired |
| **DELETE** | `src/test/registry.ts` | Dead code |
| **DELETE** | `src/test/security.ts` | Dead code |
| **DELETE** | `src/test/toolLogic.ts` | Dead code |
| **DELETE** | `index.ts` (root) | Fully commented, dead |
| **DELETE** | `kinetic copy.json` | Backup, not needed |
| **CREATE** | `docs/update-plan.md` | This document |
| **CREATE** | `src/providers/UnifiedProvider.ts` | Single provider for all endpoints |
| **CREATE** | `src/types/models.ts` | Stage config types |
| **REWRITE** | `src/types/BaseLLM.ts` | Single canonical ChatMessage, clean exports |
| **REWRITE** | `src/agents/factory/AgentInstance.ts` | Stage-based routing |
| **REWRITE** | `src/agents/dispatcher/AgentDispatcher.ts` | New config system, bug fixes |
| **REWRITE** | `src/main.ts` | Env-based config, no hardcoded secrets |
| **UPDATE** | `.env` | Add new env var docs |
| **UPDATE** | `.gitignore` | Reflect new files |

---

## Environment Variables

| Var | Required | Used By |
|---|---|---|
| `OPENROUTER_API_KEY` | No | openrouter provider endpoint |
| `GROQ_API_KEY` | No | groq provider endpoint |
| `OLLAMA_API_KEY` | No | ollama provider (usually "ollama") |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot interface |
| `BRAVE_API_KEY` | No | braveSearchTool |
| Any custom var | No | Custom OpenAI-compatible endpoints |

No single API key is mandatory. The system can function on Ollama alone (local).
