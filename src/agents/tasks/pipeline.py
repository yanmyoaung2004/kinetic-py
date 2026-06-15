from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("kinetic.pipeline")

PIPELINES_DIR = Path("agents_workspace") / ".pipelines"


@dataclass
class PipelineStep:
    id: str
    agent: str
    prompt: str
    output_var: str


@dataclass
class Pipeline:
    id: str
    name: str
    description: str = ""
    steps: list[PipelineStep] = field(default_factory=list)
    created: str = ""


def _sanitize(id_str: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", id_str)


def _p_path(pipeline_id: str) -> Path:
    return PIPELINES_DIR / f"{_sanitize(pipeline_id)}.json"


def _ensure_dir() -> None:
    PIPELINES_DIR.mkdir(parents=True, exist_ok=True)


def save_pipeline(pipeline: dict[str, Any]) -> Pipeline:
    _ensure_dir()
    existing = get_pipeline(pipeline.get("id", "")) if pipeline.get("id") else None
    full = Pipeline(
        id=pipeline.get("id", f"pipe_{int(__import__('time').time() * 1000)}"),
        name=pipeline.get("name", "Unnamed"),
        description=pipeline.get("description", ""),
        steps=[PipelineStep(**s) for s in pipeline.get("steps", [])],
        created=existing.created if existing else datetime.now(timezone.utc).isoformat(),
    )
    _p_path(full.id).write_text(json.dumps(_pipeline_to_dict(full), indent=2))
    return full


def _pipeline_to_dict(p: Pipeline) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "steps": [s.__dict__ for s in p.steps],
        "created": p.created,
    }


def get_pipeline(pipeline_id: str) -> Pipeline | None:
    p = _p_path(pipeline_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
        return Pipeline(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            steps=[PipelineStep(**s) for s in data.get("steps", [])],
            created=data.get("created", ""),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def list_pipelines() -> list[Pipeline]:
    _ensure_dir()
    if not PIPELINES_DIR.exists():
        return []
    pipelines: list[Pipeline] = []
    for f in PIPELINES_DIR.iterdir():
        if f.suffix == ".json":
            p = get_pipeline(f.stem)
            if p:
                pipelines.append(p)
    return pipelines


def delete_pipeline(pipeline_id: str) -> bool:
    p = _p_path(pipeline_id)
    if not p.exists():
        return False
    p.unlink()
    return True


async def execute_pipeline(
    pipeline: Pipeline,
    variables: dict[str, str],
    dispatch_fn: Any,
) -> dict[str, str]:
    outputs: dict[str, str] = dict(variables)

    for step in pipeline.steps:
        resolved = re.sub(r"\{\{(\w+)\}\}", lambda m: outputs.get(m.group(1), ""), step.prompt)
        result = await dispatch_fn(step.agent, resolved)
        outputs[step.output_var] = result
        logger.info("[PIPELINE] Step '%s' -> %s completed (%d chars)", step.id, step.agent, len(result))

    return outputs
