from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from src.types.model_config import EmbeddingConfig, ModelConfig, ProviderEndpoint

logger = logging.getLogger("kinetic.config")

LOCAL_HOST_RE = re.compile(r"localhost|127\.0\.0\.1", re.IGNORECASE)

MODELS_CONFIG_PATH = Path("config/models.json")
AGENTS_CONFIG_PATH = Path("config/agents.json")


def load_model_config(config_path: str | Path | None = None) -> tuple[
    ModelConfig,
    dict[str, dict[str, str]],
    EmbeddingConfig | None,
]:
    path = Path(config_path) if config_path else MODELS_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found at {path.resolve()}. Copy config/models.example.json "
            f"to config/models.json and configure your providers."
        )

    raw: dict[str, Any] = json.loads(path.read_text("utf-8"))
    model_config = ModelConfig.from_dict(raw)

    endpoints: dict[str, dict[str, str]] = {}
    for name, ep in model_config.providers.items():
        is_local = bool(LOCAL_HOST_RE.search(ep.base_url))
        api_key = "" if is_local else os.environ.get(ep.api_key_env, "")
        endpoints[name] = {"base_url": ep.base_url, "api_key": api_key}
        if not is_local and not api_key:
            logger.warning(
                "[CONFIG] Provider '%s': env var '%s' is not set. API calls will fail.",
                name,
                ep.api_key_env,
            )

    embedding: EmbeddingConfig | None = None
    if model_config.embedding:
        emb_provider = model_config.embedding.get("provider", "")
        emb_model = model_config.embedding.get("model", "text-embedding-3-small")
        emb_ep = endpoints.get(emb_provider)
        if emb_ep:
            embedding = EmbeddingConfig(
                base_url=emb_ep["base_url"],
                api_key=emb_ep["api_key"],
                model=emb_model,
                extra_body=model_config.embedding.get("extraBody"),
                encoding_format=model_config.embedding.get("encodingFormat"),
            )
        else:
            logger.warning(
                "[CONFIG] Embedding provider '%s' not found in providers. Knowledge base won't work.",
                emb_provider,
            )

    return model_config, endpoints, embedding


async def validate_endpoints(endpoints: dict[str, dict[str, str]]) -> None:
    async def check_one(name: str, ep: dict[str, str]) -> tuple[str, bool, str | None]:
        if not ep.get("api_key"):
            return name, False, "no key configured"
        url = ep["base_url"].rstrip("/") + "/models"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {ep['api_key']}"})
                if resp.is_success:
                    return name, True, None
                return name, False, f"HTTP {resp.status_code}"
        except Exception as e:
            return name, False, str(e)

    results = [await check_one(name, ep) for name, ep in endpoints.items()]
    for name, ok, msg in results:
        if ok:
            logger.info("[VALIDATE] %s — reachable", name)
        elif msg != "no key configured":
            logger.warning("[VALIDATE] %s — unreachable (%s)", name, msg)


def load_agents_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else AGENTS_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Agent config not found at {path.resolve()}. Copy config/agents.example.json "
            f"to config/agents.json and configure your agents."
        )
    return json.loads(path.read_text("utf-8"))
