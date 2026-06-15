from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("kinetic.rag.embedding")

_client: AsyncOpenAI | None = None
_model = "text-embedding-3-small"
_extra_body: dict[str, Any] | None = None
_format = "float"


def init_embedding(
    base_url: str,
    api_key: str,
    model: str | None = None,
    options: dict[str, Any] | None = None,
) -> None:
    global _client, _model, _extra_body, _format

    is_local = "localhost" in base_url.lower() or "127.0.0.1" in base_url.lower()
    key = api_key or ("noop-key" if is_local else "")
    _client = AsyncOpenAI(base_url=base_url, api_key=key)
    if model:
        _model = model
    if options:
        _extra_body = options.get("extraBody") or options.get("extra_body")
        _format = options.get("encodingFormat") or options.get("encoding_format", "float")

    # Auto-detect NVIDIA vendor params
    if "nvidia" in base_url.lower():
        _extra_body = _extra_body or {}
        _extra_body.setdefault("input_type", "query")
        _extra_body.setdefault("truncate", "NONE")

    logger.info("[RAG] Embedding initialized: %s via %s", _model, base_url)


async def get_embedding(text: str) -> list[float]:
    if not _client:
        raise RuntimeError("Embedding client not initialized. Add 'embedding' provider to models.json")
    params: dict[str, Any] = {
        "model": _model,
        "input": [text],
        "encoding_format": _format,
    }
    if _extra_body:
        params.update(_extra_body)
    res = await _client.embeddings.create(**params)
    return res.data[0].embedding


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    if not _client:
        raise RuntimeError("Embedding client not initialized")
    params: dict[str, Any] = {
        "model": _model,
        "input": texts,
        "encoding_format": _format,
    }
    if _extra_body:
        params.update(_extra_body)
    res = await _client.embeddings.create(**params)
    return [d.embedding for d in res.data]
