from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("kinetic.api")

PUBLIC_DIR = Path(__file__).parent / "public"
IMAGES_DIR = Path(__file__).parent.parent / "images"
CONFIG_DIR = Path("config")


def create_app(dispatcher: Any, agent_target: str) -> FastAPI:
    app = FastAPI(title="K.I.N.E.T.I.C. API", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # ── API Routes ──

    @app.post("/api/chat")
    async def chat(request: Request) -> JSONResponse:
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("session_id", "default")
        if session_id != dispatcher.get_active_session():
            dispatcher.set_session(session_id)
        response = await dispatcher.dispatch(agent_target, message, 0)
        return JSONResponse({"response": response})

    @app.post("/api/chat/upload")
    async def chat_upload(file: UploadFile | None = None, message: str = Form("")) -> JSONResponse:
        from src.utils.file_reader import get_type_label, read_file

        sandbox = Path("agent_sandbox")
        sandbox.mkdir(exist_ok=True)

        if not file or not file.filename:
            if not message:
                return JSONResponse({"error": "No file or message provided"}, status_code=400)
            response = await dispatcher.dispatch(agent_target, message, 0)
            return JSONResponse({"response": response})

        file_path = sandbox / file.filename
        content_bytes = await file.read()
        file_path.write_bytes(content_bytes)

        result = read_file(file_path)
        if result.get("error"):
            return JSONResponse({"error": result["error"]}, status_code=400)

        label = get_type_label(result)
        file_info = f"[Uploaded {label}: {result['name']} ({result.get('size', 0)} bytes)]\n\n"
        file_content = result.get("content", "")
        if len(file_content) > 50000:
            file_content = file_content[:50000] + "\n\n[...content truncated at 50000 chars]"

        full_message = f"{file_info}{file_content}"
        if message.strip():
            full_message += f"\n\nUser message: {message}"

        response = await dispatcher.dispatch(agent_target, full_message, 0)
        return JSONResponse({"response": response, "file": result["name"]})

    @app.get("/api/sessions")
    @app.post("/api/sessions")
    async def sessions(request: Request | None = None) -> JSONResponse:
        from src.agents.memory import AgentMemory

        assert request is not None
        if request.method == "GET":
            sessions_list = AgentMemory.list_sessions(agent_target, "agents_workspace")
            return JSONResponse({"sessions": sessions_list, "active": dispatcher.get_active_session()})
        else:
            body = await request.json()
            name = body.get("name", f"session_{int(__import__('time').time() * 1000)}")
            dispatcher.set_session(name)
            return JSONResponse({"session": name})

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse(
            {
                "uptime": dispatcher.get_uptime(),
                "agents": dispatcher.get_agent_count(),
                "target": agent_target,
                "session": dispatcher.get_active_session(),
                "config": dispatcher.get_active_config(),
            }
        )

    # ── Knowledge routes ──

    @app.get("/api/knowledge")
    async def knowledge_list() -> JSONResponse:
        from src.agents.rag.vector_store import get_store_stats, list_documents

        stats = await get_store_stats(agent_target)
        docs = await list_documents(agent_target)
        return JSONResponse({"stats": stats, "documents": [d.__dict__ for d in docs]})

    @app.post("/api/knowledge/inject")
    async def knowledge_inject(request: Request) -> JSONResponse:
        from src.agents.rag.embedding import get_embedding
        from src.agents.rag.vector_store import add_chunks, chunk_text, strip_html
        from src.agents.tools.knowledge_tool import ensure_embedding

        body = await request.json()
        if not body.get("text") and not body.get("url") and not body.get("filePath"):
            return JSONResponse({"error": "Provide 'text', 'url', or 'filePath'"}, status_code=400)

        text = body.get("text", "")
        title = body.get("title", "Untitled")
        source = body.get("source", "manual")

        if body.get("url"):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(body["url"])
                    resp.raise_for_status()
                    html = resp.text
                cleaned = strip_html(html)
                text = cleaned[:50000]
                source = body["url"]
                title = body.get("title", body["url"].split("/")[-1] or "Untitled")
            except Exception as e:
                return JSONResponse({"error": f"Failed to fetch URL: {e}"}, status_code=400)
        elif body.get("filePath") and not body.get("text"):
            try:
                fpath = Path(body["filePath"]).resolve()
                text = fpath.read_text("utf-8", errors="replace")[:50000]
                source = body["filePath"]
                title = body.get("title", fpath.name)
            except Exception as e:
                return JSONResponse({"error": f"Failed to read file: {e}"}, status_code=400)

        segments = await chunk_text(text)
        if not segments:
            return JSONResponse({"error": "No content to index"}, status_code=400)

        ensure_embedding()
        chunks_data = []
        for seg in segments:
            emb = await get_embedding(seg)
            chunks_data.append(
                {
                    "doc_id": f"doc_{int(__import__('time').time() * 1000)}",
                    "title": title,
                    "source": source,
                    "text": seg,
                    "embedding": emb,
                    "metadata": {},
                }
            )
        count = await add_chunks(agent_target, chunks_data)
        return JSONResponse({"ok": True, "inserted": count, "title": title, "segments": len(segments)})

    @app.post("/api/knowledge/search")
    async def knowledge_search(request: Request) -> JSONResponse:
        from src.agents.rag.embedding import get_embedding
        from src.agents.rag.vector_store import SearchOptions, search_similar
        from src.agents.tools.knowledge_tool import ensure_embedding

        body = await request.json()
        query = body.get("query")
        if not query:
            return JSONResponse({"error": "Provide 'query'"}, status_code=400)

        try:
            ensure_embedding()
            query_emb = await get_embedding(query)
            opts = SearchOptions(
                top_k=body.get("topK", 5),
                keyword_weight=body.get("keywordWeight", 0.15),
                diversify=True,
            )
            results = await search_similar(agent_target, query_emb, query, opts)
            return JSONResponse(
                {
                    "results": [
                        {
                            "text": r.chunk.text,
                            "title": r.chunk.title,
                            "source": r.chunk.source,
                            "score": r.score,
                            "docId": r.chunk.doc_id,
                        }
                        for r in results
                    ],
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.delete("/api/knowledge/{doc_id}")
    async def knowledge_delete(doc_id: str) -> JSONResponse:
        from src.agents.rag.vector_store import remove_document

        ok = await remove_document(agent_target, doc_id)
        return JSONResponse({"deleted": ok}, status_code=200 if ok else 404)

    # ── Pipeline routes ──

    @app.get("/api/pipelines")
    async def pipelines_list() -> JSONResponse:
        from src.agents.tasks.pipeline import list_pipelines

        return JSONResponse(
            {
                "pipelines": [
                    {"id": p.id, "name": p.name, "steps": len(p.steps), "description": p.description}
                    for p in list_pipelines()
                ]
            }
        )

    @app.post("/api/pipelines")
    async def pipelines_create(request: Request) -> JSONResponse:
        from src.agents.tasks.pipeline import save_pipeline

        body = await request.json()
        pipeline = save_pipeline(body)
        return JSONResponse({"id": pipeline.id, "name": pipeline.name}, status_code=201)

    @app.get("/api/pipelines/{pipeline_id}")
    async def pipelines_get(pipeline_id: str) -> JSONResponse:
        from src.agents.tasks.pipeline import get_pipeline

        p = get_pipeline(pipeline_id)
        if not p:
            raise HTTPException(404, "Pipeline not found")
        return JSONResponse(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "steps": [s.__dict__ for s in p.steps],
                "created": p.created,
            }
        )

    @app.put("/api/pipelines/{pipeline_id}")
    async def pipelines_update(pipeline_id: str, request: Request) -> JSONResponse:
        from src.agents.tasks.pipeline import delete_pipeline, get_pipeline, save_pipeline

        if not get_pipeline(pipeline_id):
            raise HTTPException(404, "Pipeline not found")
        delete_pipeline(pipeline_id)
        body = await request.json()
        body["id"] = pipeline_id
        p = save_pipeline(body)
        return JSONResponse({"id": p.id, "name": p.name})

    @app.delete("/api/pipelines/{pipeline_id}")
    async def pipelines_delete(pipeline_id: str) -> JSONResponse:
        from src.agents.tasks.pipeline import delete_pipeline

        ok = delete_pipeline(pipeline_id)
        return JSONResponse({"deleted": ok}, status_code=200 if ok else 404)

    @app.post("/api/pipelines/execute")
    async def pipelines_execute(request: Request) -> JSONResponse:
        from src.agents.tasks.pipeline import execute_pipeline, get_pipeline

        body = await request.json()
        pipeline = get_pipeline(body.get("pipeline_id", ""))
        if not pipeline:
            raise HTTPException(404, "Pipeline not found")

        async def _dispatch(agent_id: str, msg: str) -> str:
            return await dispatcher.dispatch(agent_id, msg, 0)

        outputs = await execute_pipeline(pipeline, body.get("variables", {}), _dispatch)
        return JSONResponse({"outputs": outputs})

    # ── Config routes ──

    def _read_models() -> dict[str, Any]:
        path = CONFIG_DIR / "models.json"
        if not path.exists():
            raise HTTPException(404, "models.json not found")
        return json.loads(path.read_text("utf-8"))

    def _read_agents() -> dict[str, Any]:
        path = CONFIG_DIR / "agents.json"
        if not path.exists():
            return {"settings": {"defaults": {"type": "library", "can_delegate": True}}, "registry": []}
        return json.loads(path.read_text("utf-8"))

    @app.get("/api/config/models")
    async def config_models_get() -> JSONResponse:
        return JSONResponse(_read_models())

    @app.put("/api/config/models")
    async def config_models_put(request: Request) -> JSONResponse:
        body = await request.json()
        if not body.get("providers") or not body.get("defaults"):
            return JSONResponse({"error": "Config must have 'providers' and 'defaults'"}, status_code=400)

        # Validate apiKeyEnv
        for name, ep in body["providers"].items():
            val = ep.get("apiKeyEnv", "")
            if re.match(r"^(sk-|gsk_|gsb_|pds-gpt_|fk|skev_|nvapi|lightning-|lt-)", val, re.IGNORECASE):
                return JSONResponse(
                    {"error": f"'{name}': '{val}' looks like an API key, not an env var name"}, status_code=400
                )

        (CONFIG_DIR / "models.json").write_text(json.dumps(body, indent=2))
        return JSONResponse({"ok": True, "message": "models.json saved. Restart to apply changes."})

    @app.get("/api/config/agents")
    async def config_agents_get() -> JSONResponse:
        return JSONResponse(_read_agents())

    @app.put("/api/config/agents")
    async def config_agents_put(request: Request) -> JSONResponse:
        body = await request.json()
        if not body.get("registry"):
            return JSONResponse({"error": "Config must have a 'registry' array"}, status_code=400)

        soul_template = (
            "# SOUL.md — Who You Are\n\n"
            "You are a specialized K.I.N.E.T.I.C. agent.\n\n"
            "## Core Directives\n"
            "- Be helpful, precise, and technically accurate\n"
            "- Stay in character as your assigned role\n"
            "- Use Markdown for structured responses\n"
            '- Never state "As an AI language model"\n\n'
            "## Communication Style\n"
            "- Be concise and direct\n"
            "- Use bullet points and code blocks where appropriate\n"
            "- Ask clarifying questions when requirements are ambiguous\n\n"
            "## Boundaries\n"
            "- You can read and write files within the sandbox\n"
            "- You can search the web and index knowledge\n"
            "- You can delegate tasks to other agents if permitted"
        )

        for agent in body["registry"]:
            if agent.get("soulPath"):
                abs_path = (CONFIG_DIR / agent["soulPath"]).resolve()
                if not abs_path.exists():
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(soul_template)

        (CONFIG_DIR / "agents.json").write_text(json.dumps(body, indent=2))
        return JSONResponse({"ok": True, "message": "agents.json saved. Restart to apply changes."})

    @app.post("/api/config/test-provider")
    async def config_test_provider(request: Request) -> JSONResponse:
        body = await request.json()
        provider_name = body.get("providerName")
        if not provider_name:
            return JSONResponse({"error": "providerName required"}, status_code=400)

        try:
            config = _read_models()
            ep = config.get("providers", {}).get(provider_name)
            if not ep:
                return JSONResponse({"error": "Provider not found"}, status_code=404)
            api_key = os.environ.get(ep.get("apiKeyEnv", ""), "")
            url = ep["baseUrl"].rstrip("/") + "/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
            return JSONResponse({"ok": resp.is_success, "status": resp.status_code, "statusText": resp.reason_phrase})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})

    @app.post("/api/config/list-models")
    async def config_list_models(request: Request) -> JSONResponse:
        body = await request.json()
        provider_name = body.get("providerName")
        if not provider_name:
            return JSONResponse({"error": "providerName required"}, status_code=400)

        try:
            config = _read_models()
            ep = config.get("providers", {}).get(provider_name)
            if not ep:
                return JSONResponse({"error": "Provider not found"}, status_code=404)
            api_key = os.environ.get(ep.get("apiKeyEnv", ""), "")
            base = ep["baseUrl"].rstrip("/")
            url_lower = base.lower()

            if "localhost" in url_lower or "127.0.0.1" in url_lower or "ollama" in url_lower:
                base_for_api = re.sub(r"/v1/?$", "", base)
                models_url = base_for_api + "/api/tags"
                headers = {}
            else:
                models_url = base + "/models"
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(models_url, headers=headers)
                if not resp.is_success:
                    return JSONResponse({"error": f"HTTP {resp.status_code}"}, status_code=502)
                raw = resp.json()

            # Parse models
            if "localhost" in url_lower or "127.0.0.1" in url_lower or "ollama" in url_lower:
                models = sorted(m.get("name", "") for m in raw.get("models", []) if m.get("name"))
            else:
                models = sorted(m.get("id", "") for m in raw.get("data", []) if m.get("id"))

            return JSONResponse({"models": models})
        except Exception as e:
            return JSONResponse({"error": str(e), "models": []}, status_code=500)

    @app.get("/api/config/active-providers")
    async def config_active_providers() -> JSONResponse:
        try:
            config = _read_models()
            return JSONResponse({"providers": list(config.get("providers", {}).keys())})
        except Exception:
            return JSONResponse({"providers": []})

    # ── Image routes ──

    @app.get("/favicon.ico")
    async def favicon():
        path = IMAGES_DIR / "logo-white.png"
        if not path.exists():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="image/x-icon", headers={"Cache-Control": "no-cache"})

    @app.get("/logo-dark.png")
    async def logo_dark():
        path = IMAGES_DIR / "logo-dark.png"
        if not path.exists():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get("/logo-white.png")
    async def logo_white():
        path = IMAGES_DIR / "logo-white.png"
        if not path.exists():
            return Response(status_code=404)
        return Response(content=path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-cache"})

    # ── Static files ──

    if PUBLIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")

    return app
