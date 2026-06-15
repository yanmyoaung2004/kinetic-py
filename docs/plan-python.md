# K.I.N.E.T.I.C. v2 — Python Migration Plan

## 1. Overview & Goals

Migrate the TypeScript K.I.N.E.T.I.C. agentic framework to Python, creating **v2** that is strictly **better** in every dimension.

### Core goals
- **100% feature parity** with TS v1 — every function, tool, and route ported
- **Performance** — use `asyncio` throughout, `numpy` for vectors, connection pooling, lazy loading
- **Testability** — comprehensive test suite (unit + integration)
- **Extensibility** — OpenAI-compatible provider model so any endpoint works
- **Cleaner architecture** — separate concerns better than v1, avoid anti-patterns
- **Type safety** — full Python type hints + dataclasses (no raw dicts)

---

## 2. Architecture Comparison

```
TS v1                              Python v2
──────────────────────────────────────────────────
main.ts                           main.py (entrypoint)
  └─ dotenv                         └─ python-dotenv
  └─ TelegramBot (node-telegram)    └─ python-telegram-bot
  └─ KinetiCDispatcher              └─ KinetiCDispatcher
  └─ startApiServer                 └─ Uvicorn + FastAPI
  └─ schedulerTick (setInterval)    └─ asyncio loop

agents/
  agent.ts                          agents/agent.py
  memory.ts                         agents/memory.py
  memory/compressor.ts              agents/memory.py (compressor functions)
  orchestrator.ts                   agents/orchestrator.py
  rag/
    embedding.ts                    agents/rag/embedding.py
    schema.ts                       agents/rag/schema.py
    vectorStore.ts                  agents/rag/vector_store.py
  tasks/
    pipeline.ts                     agents/tasks/pipeline.py
    scheduler.ts                    agents/tasks/scheduler.py
  tools/
    registry.ts                     agents/tools/registry.py
    executeCommand.ts               agents/tools/execute_command.py
    fileTools.ts                    agents/tools/file_tools.py
    knowledgeTool.ts                agents/tools/knowledge_tool.py
    pipelineTool.ts                 agents/tools/pipeline_tool.py
    scheduleTask.ts                 agents/tools/schedule_task.py
    systemTools.ts                  agents/tools/system_tools.py
    webSearch.ts                    agents/tools/web_search.py
    dataConnectors.ts               agents/tools/data_connectors.py

providers/
  provider.ts                       providers/provider.py

config/
  loader.ts                         config/loader.py

types/
  agent.ts                          types/agent.py (dataclasses)
  llm.ts                            types/llm.py (dataclasses)
  modelConfig.ts                    types/model_config.py (dataclasses)

api/
  server.ts                         api/server.py (FastAPI)

cli/
  index.ts                          cli/__init__.py (click-based)
  onboard.ts                        cli/onboard.py
  models.ts                         cli/models.py
  agents.ts                         cli/agents.py
  knowledge.ts                      cli/knowledge.py
  pipelines.ts                      cli/pipelines.py

tests/                              tests/
  (none in v1)                       test_provider.py
                                     test_memory.py
                                     test_vector_store.py
                                     test_tools.py
                                     test_scheduler.py
                                     test_pipeline.py
                                     test_agent.py
                                     test_dispatcher.py
```

---

## 3. Directory Structure (Python)

```
python-code/
├── pyproject.toml
├── README.md
├── .env.example
├── config/
│   ├── models.example.json
│   ├── agents.example.json
│   └── main/
│       └── SOUL.md
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entrypoint
│   │
│   ├── types/
│   │   ├── __init__.py
│   │   ├── agent.py               # AgentCard, IAgent, ToolDefinition
│   │   ├── llm.py                 # ChatMessage, LLMResponse, LLMProvider
│   │   └── model_config.py        # StageModelConfig, ModelConfig
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   └── provider.py            # UnifiedProvider, call_with_fallback
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── loader.py              # load_model_config, validate_endpoints
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── agent.py               # AgentInstance (process, run_think_loop)
│   │   ├── memory.py              # AgentMemory (JSONL, sessions, profiles)
│   │   ├── orchestrator.py        # KinetiCDispatcher
│   │   │
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── embedding.py       # init_embedding, get_embedding
│   │   │   ├── schema.py          # SQLite schema, open_db
│   │   │   └── vector_store.py    # add_chunks, search_similar, chunking
│   │   │
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py        # Pipeline CRUD + execute
│   │   │   └── scheduler.py       # add_task, get_overdue_tasks
│   │   │
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── registry.py        # ToolRegistry
│   │       ├── execute_command.py # Sandboxed shell
│   │       ├── file_tools.py      # read/write/edit/delete/undo/list
│   │       ├── knowledge_tool.py  # query_knowledge_base, index_*
│   │       ├── pipeline_tool.py   # run_pipeline
│   │       ├── schedule_task.py   # schedule_task, get_current_time
│   │       ├── system_tools.py    # get_system_info, download_url, read_env_var
│   │       ├── web_search.py      # Brave Search
│   │       └── data_connectors.py # index_github, scrape_and_index
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py              # FastAPI app + routes
│   │   └── public/                # Static files (SPA)
│   │
│   └── cli/
│       ├── __init__.py
│       ├── onboard.py
│       ├── models.py
│       ├── agents.py
│       ├── knowledge.py
│       └── pipelines.py
│
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_provider.py
    ├── test_memory.py
    ├── test_vector_store.py
    ├── test_tools.py
    ├── test_scheduler.py
    ├── test_pipeline.py
    ├── test_agent.py
    └── test_dispatcher.py
```

---

## 4. Module-by-Module Migration Plan

### 4.1 Types (`src/types/`)

| TS | Python |
|---|---|
| `ChatMessage` type | `@dataclass ChatMessage` with role/content/name/tool_call_id/tool_calls |
| `LLMResponse` interface | `@dataclass LLMResponse` |
| `LLMProvider` abstract class | `ABC LLMProvider` |
| `AgentCard` interface | `@dataclass AgentCard` |
| `IAgent` interface | `Protocol IAgent` |
| `ToolDefinition` interface | `@dataclass ToolDefinition` |
| `StageModelConfig` | `@dataclass StageModelConfig` |
| `ModelConfig` | `@dataclass ModelConfig` with `from_dict()` |

**Improvements:** Use Pydantic-like validation via `__post_init__`, add JSON serialization methods.

### 4.2 Provider (`src/providers/provider.py`)

| TS | Python |
|---|---|
| `supportsSdk()` | `_supports_sdk()` |
| `UnifiedProvider` class | `UnifiedProvider` using `openai` Python SDK for SDK path, `httpx.AsyncClient` for fetch path |
| `sdkGenerate()` | `_sdk_generate()` |
| `fetchGenerate()` | `_fetch_generate()` — detect `<function>` XML tool calls |
| `callWithFallback()` | `async call_with_fallback()` |

**Improvements:**
- Connection pooling via `httpx.AsyncClient` (reuse client, not create per call)
- Proper `asyncio` timeouts with `asyncio.timeout()`
- Retry with exponential backoff for transient failures (v1 does maxRetries=2 without backoff)

### 4.3 Config Loader (`src/config/loader.py`)

| TS | Python |
|---|---|
| `loadModelConfig()` | `load_model_config()` |
| `validateEndpoints()` | `async validate_endpoints()` |

**Improvements:**
- Use `pathlib.Path` instead of string paths
- Better error messages with suggestions
- Validate embedding provider existence before returning

### 4.4 Agent Runtime (`src/agents/agent.py`)

| TS | Python |
|---|---|
| `createThinkProviders()` | `_create_think_providers()` |
| `AgentInstance` class | `AgentInstance` |
| `process()` | `async process()` — main pipeline |
| `runThinkLoop()` | `async _run_think_loop()` — up to 5 iterations |
| `extractProfile()` | `async _extract_profile()` — every 3 messages |
| `evolveSoul()` | `async _evolve_soul()` (legacy) |
| `evolveSoulV2()` | `async _evolve_soul_v2()` |
| `compressHistory()` | `async _compress_history()` |
| `executeSpawnSpecialist()` | `async _execute_spawn_specialist()` |

**Improvements:**
- Use `asyncio.create_task()` for background work instead of `setImmediate`
- Better retry logic with structured backoff
- Extract GLOBAL_PROTOCOLS as a module constant

### 4.5 Memory (`src/agents/memory.py`)

| TS | Python |
|---|---|
| `AgentMemory` class | `AgentMemory` |
| `saveActiveSession()` | `_save_active_session()` |
| `listSessions()` (static) | `@staticmethod list_sessions()` |
| `load()` | `_load()` |
| `append()` | `append()` |
| `needsCompression()` | `needs_compression()` |
| `getCompressionCandidates()` | `get_compression_candidates()` |
| `applyCompression()` | `apply_compression()` |
| `refreshSystemPrompt()` | `refresh_system_prompt()` |
| `trim()` | `_trim()` |
| `rewrite()` | `_rewrite()` |
| `destroy()` | `destroy()` |
| `sanitizeId()` | `_sanitize_id()` |

Plus compressor functions (from `compressor.ts`):
- `should_compress()`
- `select_messages_to_compress()`
- `build_compression_prompt()`
- `build_summary_message()`

**Improvements:**
- Async file operations where beneficial (large rewrites)
- Atomic writes: write to `.tmp` then rename to prevent corruption
- Better session isolation — each session truly isolated

### 4.6 Dispatcher (`src/agents/orchestrator.py`)

| TS | Python |
|---|---|
| `KinetiCDispatcher` class | `KinetiCDispatcher` |
| `loadAndRegisterAgent()` | `load_and_register_agent()` |
| `registerAgent()` | `register_agent()` |
| `createSubAgent()` | `async create_sub_agent()` |
| `dispatch()` | `async dispatch()` |
| `getOrInitializeAgent()` | `async _get_or_initialize_agent()` |
| `clearCachedAgents()` | `_clear_cached_agents()` |
| `setStageOverride()` | `set_stage_override()` |
| `scheduleEviction()` | `_schedule_eviction()` |
| `evict()` | `_evict()` |

**Improvements:**
- Use `asyncio.Timeout` for eviction instead of `setTimeout`
- Use proper async context managers
- Track agent usage stats (calls made, tokens used) for observability

### 4.7 RAG / Knowledge Base

#### Embedding (`src/agents/rag/embedding.py`)

| TS | Python |
|---|---|
| `initEmbedding()` | `init_embedding()` — singleton pattern |
| `getEmbedding()` | `async get_embedding()` |
| `getEmbeddings()` | `async get_embeddings()` |

**Improvements:**
- Use `openai` async client (`AsyncOpenAI`)
- Batch embedding with configurable concurrency
- Auto-detect NVIDIA/GCP/AWS Bedrock vendor params

#### Schema (`src/agents/rag/schema.py`)

| TS | Python |
|---|---|
| `dbPath()` | `db_path()` — returns `pathlib.Path` |
| `openDb()` | `open_db()` — uses `sqlite3` |
| `runSchema()` | `_run_schema()` |
| `migrateFromJson()` | `_migrate_from_json()` |

**Improvements:**
- Use `aiosqlite` for async SQLite access (non-blocking in hot path)
- Better error handling on migration
- Periodic VACUUM to prevent WAL growth

#### Vector Store (`src/agents/rag/vector_store.py`)

| TS | Python |
|---|---|
| `cosineSimilarity()` | `cosine_similarity()` — use `numpy` for vectorized ops |
| `extractKeywords()` | `extract_keywords()` |
| `mmrDiversify()` | `mmr_diversify()` |
| `addChunks()` | `add_chunks()` |
| `searchSimilar()` | `search_similar()` |
| `listDocuments()` | `list_documents()` |
| `removeDocument()` | `remove_document()` |
| `getStoreStats()` | `get_store_stats()` |
| `chunkText()` | `chunk_text()` |
| `stripHtml()` | `strip_html()` — use `beautifulsoup4` instead of regex |
| `extractDocumentMeta()` | `extract_document_meta()` |

**Improvements:**
- `numpy` for all vector operations (20-50x faster than pure Python)
- `beautifulsoup4` for HTML stripping (more robust than regex)
- Proper BM25 integration with FTS5
- Cache DB connections properly
- Async search for concurrent querying

### 4.8 Tools

#### Registry (`src/agents/tools/registry.py`)

| TS | Python |
|---|---|
| `ToolRegistry` class | `ToolRegistry` |
| `register()` | `register()` |
| `getDefinitions()` | `get_definitions()` |
| `execute()` | `async execute()` |
| `createSendMessageTool()` | `create_send_message_tool()` |
| `createWebSearchTool()` | `create_web_search_tool()` |

#### Execute Command (`src/agents/tools/execute_command.py`)

| TS | Python |
|---|---|
| `getWhitelist()` | `_get_whitelist()` |
| `validateArgs()` | `_validate_args()` |
| `createExecuteCommandTool()` | `create_execute_command_tool()` — uses `asyncio.create_subprocess_exec()` |

**Improvements:** Use `asyncio.subprocess` for async execution instead of `execFile` promisify

#### File Tools (`src/agents/tools/file_tools.py`)

| TS | Python |
|---|---|
| `resolveSafePath()` | `_resolve_safe_path()` — use `pathlib.Path.resolve()` |
| `createReadFileTool()` | `create_read_file_tool()` |
| `createWriteFileTool()` | `create_write_file_tool()` |
| `createEditFileTool()` | `create_edit_file_tool()` |
| `createDeleteFileTool()` | `create_delete_file_tool()` |
| `createUndoFileTool()` | `create_undo_file_tool()` |
| `createListFilesTool()` | `create_list_files_tool()` |

#### Knowledge Tool (`src/agents/tools/knowledge_tool.py`)

| TS | Python |
|---|---|
| `initKnowledgeBase()` | `init_knowledge_base()` |
| `ensureEmbedding()` | `ensure_embedding()` |
| `createQueryKnowledgeTool()` | `create_query_knowledge_tool()` |
| `createIndexFileTool()` | `create_index_file_tool()` |
| `createIndexUrlTool()` | `create_index_url_tool()` |
| `createKnowledgeStatsTool()` | `create_knowledge_stats_tool()` |

#### Schedule Task (`src/agents/tools/schedule_task.py`)

| TS | Python |
|---|---|
| `parseTimeToDelay()` | `_parse_time_to_delay()` |
| `createScheduleTaskTool()` | `create_schedule_task_tool()` |
| `createGetTimeTool()` | `create_get_time_tool()` |

#### System Tools (`src/agents/tools/system_tools.py`)

| TS | Python |
|---|---|
| `createGetSystemInfoTool()` | `create_get_system_info_tool()` — use `psutil` for accurate disk/RAM |
| `createDownloadUrlTool()` | `create_download_url_tool()` |
| `createReadEnvVarTool()` | `create_read_env_var_tool()` |

**Improvements:** Use `psutil` for system info instead of parsing `wmic` / `df` output

#### Web Search (`src/agents/tools/web_search.py`)

| TS | Python |
|---|---|
| `webSearch()` | `web_search()` — same Brave API |

#### Data Connectors (`src/agents/tools/data_connectors.py`)

| TS | Python |
|---|---|
| `createGitHubIndexTool()` | `create_github_index_tool()` |
| `createWebScraperTool()` | `create_web_scraper_tool()` |

### 4.9 API Server (`src/api/server.py`)

**TS v1:** Raw `http.createServer()` — manual routing, manual JSON handling, manual CORS.

**Python v2:** FastAPI with `uvicorn` — declarative routes, automatic OpenAPI docs, built-in CORS, Pydantic validation.

| TS | Python (FastAPI) |
|---|---|
| `readBody()` | Built-in `Request.json()` |
| `json()` | `JSONResponse` |
| `serveStatic()` | `StaticFiles` mount |
| `startApiServer()` | `uvicorn.run(app)` |

Routes:
```
GET    /api/status
POST   /api/chat
GET    /api/sessions
POST   /api/sessions
GET    /api/knowledge
POST   /api/knowledge/inject
POST   /api/knowledge/search
DELETE /api/knowledge/{doc_id}
GET    /api/pipelines
POST   /api/pipelines
PUT    /api/pipelines/{id}
DELETE /api/pipelines/{id}
POST   /api/pipelines/execute
GET    /api/config/models
PUT    /api/config/models
GET    /api/config/agents
PUT    /api/config/agents
POST   /api/config/test-provider
POST   /api/config/list-models
```

### 4.10 CLI (`src/cli/`)

**TS v1:** Manual `readline` prompts — repetitive question/switch boilerplate.

**Python v2:** `click` library — declarative commands, auto-help, less boilerplate.

| TS | Python (click) |
|---|---|
| Manual `question()` loops | `click.prompt()`, `click.confirm()` |
| `onboard()` | `@click.command()` |
| `configureModels()` | `@click.group()` with subcommands |
| `manageAgents()` | `@click.group()` with subcommands |
| `manageKnowledge()` | `@click.group()` with subcommands |
| `managePipelines()` | `@click.group()` with subcommands |

### 4.11 Entrypoint (`src/main.py`)

| TS | Python |
|---|---|
| `dotenv/config` | `dotenv.load_dotenv()` |
| `TelegramBot` polling | `Application.builder().build()` |
| `startApiServer()` | `uvicorn.run()` in background thread |
| `schedulerTick()` (setInterval) | `asyncio.create_task(_scheduler_loop())` |
| `shutdown()` | Signal handlers with `asyncio` cleanup |

**Improvements:**
- Use `asyncio.gather()` to run bot + API + scheduler concurrently
- Proper graceful shutdown with `asyncio` cleanup
- Health check / readiness probe endpoints
- Structured logging instead of `console.log`

---

## 5. Testing Strategy

### 5.1 Unit Tests (pytest)

| Module | What to test |
|---|---|
| `test_provider.py` | SDK and fetch paths, tool call detection, fallback logic |
| `test_memory.py` | Append, trim, compression, sessions, profile CRUD |
| `test_vector_store.py` | Cosine similarity, MMR, chunking strategies, FTS5 search |
| `test_tools.py` | Each tool: validation, execution, error handling |
| `test_scheduler.py` | Add/remove/list/getOverdue/markTaskRun |
| `test_pipeline.py` | Save/get/list/delete/execute with template substitution |
| `test_agent.py` | process(), think loop, tool execution, profile extraction |
| `test_dispatcher.py` | Registration, dispatch, sub-agent spawning, eviction, session switch |

### 5.2 Fixtures (`conftest.py`)
- `tmp_path` for workspace dirs
- Mock provider that returns predefined responses
- Mock embedding that returns fixed vectors
- In-memory SQLite for vector store tests

### 5.3 Test Coverage Target
- **Module-level:** 95%+ coverage for types, memory, provider, scheduler, pipeline
- **Integration:** 80%+ coverage for agent, orchestrator, tools
- **E2E:** Full flow tests (message → dispatch → agent → tools → response)

---

## 6. Performance Optimizations

| Area | v1 (TS) | v2 (Python) | Expected gain |
|---|---|---|---|
| Vector similarity | Pure JS loop | `numpy` vectorized | 20-50x |
| HTML stripping | Regex | `beautifulsoup4` | 3-5x (more correct) |
| HTTP client | Per-call `fetch` | `httpx.AsyncClient` pool | 10x for concurrent |
| SQLite | `better-sqlite3` sync | `aiosqlite` async | Non-blocking I/O |
| JSONL append | Sync write | Sync write (acceptable) | Same |
| Embedding batch | Sequential per-chunk | `asyncio.gather` parallel | 3-5x for multi-chunk |
| System info | `wmic`/`df` subprocess | `psutil` | 10x (no spawn) |
| Async model | Promises | `asyncio` | Same |
| Tool execution | Sequential | Sequential via asyncio | Same |
| Agent eviction | `setTimeout` | `asyncio.create_task` + cancel | More precise |
| Logging | `console.log` | `structlog` or `loguru` | Structured + faster |

### Key optimization decisions:
1. **numpy for vectors** — `cosine_similarity` via `numpy.dot` / `numpy.linalg.norm`
2. **httpx connection pooling** — single `AsyncClient` shared across all providers
3. **aiosqlite** — async SQLite access for vector store queries
4. **pathlib everywhere** — no string path concatenation
5. **psutil** — one-call system info (CPU, RAM, disk, network)

---

## 7. Dependencies

### Production
```toml
[project]
dependencies = [
    "python-dotenv>=1.1",
    "openai>=1.68",
    "httpx>=0.28",
    "python-telegram-bot>=21",
    "aiosqlite>=0.21",
    "numpy>=2.0",
    "psutil>=6.0",
    "beautifulsoup4>=4.13",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "click>=8.1",
    "pydantic>=2.10",
    "structlog>=25.1",
]
```

### Dev
```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "pytest-cov>=6.0",
    "ruff>=0.9",
    "mypy>=1.14",
]
```

---

## 8. Implementation Order

| Phase | Modules | Depends on | Est. files |
|---|---|---|---|
| **Phase 1:** Foundation | types/**, providers/**, config/** | Nothing | 6 files |
| **Phase 2:** Data layer | agents/memory.py, agents/rag/** | Phase 1 | 4 files |
| **Phase 3:** Tasks | agents/tasks/** | Phase 1 | 2 files |
| **Phase 4:** Tools | agents/tools/** | Phase 1, 2, 3 | 9 files |
| **Phase 5:** Agent | agents/agent.py, agents/orchestrator.py | Phase 1-4 | 2 files |
| **Phase 6:** Interfaces | api/**, cli/** | Phase 5 | 7 files |
| **Phase 7:** Entrypoint | main.py | Phase 1-6 | 1 file |
| **Phase 8:** Tests | tests/** | All | 9 files |
| **Phase 9:** Polish | pyproject.toml, README, configs | All | 3 files |

---

## 9. Key Improvements Over v1

### What we fix from v1
1. **No tests** — v1 has zero tests. v2 has comprehensive pytest suite.
2. **Sync SQLite** — v1 uses `better-sqlite3` which blocks the event loop. v2 uses `aiosqlite`.
3. **Raw HTTP server** — v1 uses `http.createServer()` with manual routing. v2 uses FastAPI with auto-docs.
4. **Per-call fetch** — v1 creates new HTTP connections per provider call. v2 uses connection pooling.
5. **Regex HTML stripping** — v1 strips HTML with fragile regex. v2 uses `beautifulsoup4`.
6. **Shell subprocess for sysinfo** — v1 calls `wmic`/`df`. v2 uses `psutil` (cross-platform, instant).
7. **Pure JS vector math** — v1 loops over arrays for cosine similarity. v2 uses `numpy` (vectorized).
8. **No structured logging** — v1 has `console.log` scattered. v2 uses `structlog`.
9. **Manual readline CLI** — v1 has repetitive prompt loops. v2 uses `click` decorators.
10. **v1 uses sync file I/O** for JSONL rewrites. v2 keeps sync where appropriate but uses atomic writes.

### New capabilities in v2
1. **OpenAPI docs** at `/docs` — auto-generated from FastAPI routes
2. **Health checks** — `/health` endpoint for container orchestration
3. **Structured logging** with JSON output option
4. **Better error classification** — retryable vs non-retryable errors
5. **Graceful shutdown** — SIGTERM/SIGINT properly drains connections
6. **Connection pooling** — configurable pool size for provider HTTP
7. **Parallel embedding** — batched embedding with configurable concurrency
8. **Atomic file writes** — no partial-file corruption on crash
9. **Type safety** — mypy strict mode, pydantic validation at boundaries

---

## 10. Migration Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| python-telegram-bot API diff | Medium | High | Read v21 docs carefully, use `Application` class |
| asyncio learning curve | Low | Medium | Use well-known patterns, avoid raw asyncio where higher-level API exists |
| aiosqlite vs better-sqlite3 perf | Low | Medium | Benchmark hot paths, fallback to sync if needed |
| numpy installation on Windows | Low | Low | Document pre-requisites, optional fallback |
| Brave Search API changes | Low | Low | Web search tool is already isolated |
| Telegram MarkdownV2 formatting | Medium | Low | Implement custom `convert()` with full V2 spec support |
