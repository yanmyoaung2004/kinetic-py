"""Image generation tool — calls an OpenAI-compatible image endpoint."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

logger = logging.getLogger("kinetic.tools.image")

_IMG_PROVIDER: str | None = None
_IMG_API_KEY: str | None = None
_IMG_MODEL: str | None = None


def _ensure_config() -> str | None:
    global _IMG_PROVIDER, _IMG_API_KEY, _IMG_MODEL
    if _IMG_PROVIDER:
        return None
    try:
        from pathlib import Path

        config = json.loads(Path("config/models.json").read_text("utf-8"))
        img_cfg = config.get("image", {})
        provider_name = img_cfg.get("provider", "")
        model = img_cfg.get("model", "dall-e-3")
        if not provider_name:
            return 'Add \'image\' section to models.json (e.g., {"provider": "openai", "model": "dall-e-3"})'
        prov = config.get("providers", {}).get(provider_name)
        if not prov:
            return f"Provider '{provider_name}' not found in models.json"
        import os

        api_key = os.environ.get(prov.get("apiKeyEnv", ""), "")
        if not api_key:
            return f"Env var {prov.get('apiKeyEnv')} not set"
        _IMG_PROVIDER = prov["baseUrl"].rstrip("/")
        _IMG_API_KEY = api_key
        _IMG_MODEL = model
        return None
    except Exception as e:
        return f"Failed to load image config: {e}"


async def _generate_image(args: dict[str, Any], ctx: ToolContext | None) -> str:
    err = _ensure_config()
    if err:
        return f"ERROR: {err}"
    prompt = args.get("prompt", "")
    if not prompt:
        return "ERROR: 'prompt' parameter is required."
    size = args.get("size", "1024x1024")
    n = min(args.get("n", 1), 4)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_IMG_PROVIDER}/images/generations",
                json={"model": _IMG_MODEL, "prompt": prompt, "n": n, "size": size},
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {_IMG_API_KEY}"},
            )
            if resp.status_code == 404:
                # Try /v1/images/generations if base ends with /v1
                alt_resp = await client.post(
                    f"{_IMG_PROVIDER}/images/generations",
                    json={"model": _IMG_MODEL, "prompt": prompt, "n": n, "size": size},
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {_IMG_API_KEY}"},
                )
                resp = alt_resp
            data = resp.json()
            if not resp.is_success:
                return f"Image generation failed: {data}"
            urls = []
            for item in data.get("data", []):
                url = item.get("url") or item.get("b64_json", "")[:50]
                urls.append(url)
            return f"Generated {len(urls)} image(s):\n" + "\n".join(f"  • {u}" for u in urls)
    except Exception as e:
        return f"ERROR generating image: {e}"


def create_generate_image_tool() -> ToolHandler:
    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "generate_image",
                "description": (
                    "Generate an image from a text prompt using AI image generation. "
                    "Configure 'image' section in models.json."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Detailed description of the image to generate"},
                        "size": {
                            "type": "string",
                            "description": "Image size: 1024x1024, 1792x1024, or 1024x1792 (default: 1024x1024)",
                        },
                        "n": {"type": "number", "description": "Number of images to generate (default: 1, max: 4)"},
                    },
                    "required": ["prompt"],
                },
            },
        ),
        execute=_generate_image,
    )
