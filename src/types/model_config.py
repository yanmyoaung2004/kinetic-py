from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageModelConfig:
    provider: str
    model: str
    fallbacks: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StageModelConfig:
        return cls(
            provider=d.get("provider", ""),
            model=d.get("model", ""),
            fallbacks=d.get("fallbacks", []),
        )


@dataclass
class ProviderEndpoint:
    base_url: str
    api_key_env: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProviderEndpoint:
        return cls(
            base_url=d.get("baseUrl", d.get("base_url", "")),
            api_key_env=d.get("apiKeyEnv", d.get("api_key_env", "")),
        )


@dataclass
class EmbeddingConfig:
    base_url: str
    api_key: str
    model: str
    extra_body: dict[str, Any] | None = None
    encoding_format: str | None = None


@dataclass
class ModelConfig:
    mode: str = "single"  # "single" | "multi"
    embedding: dict[str, Any] | None = None
    defaults: dict[str, StageModelConfig] = field(default_factory=dict)
    providers: dict[str, ProviderEndpoint] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelConfig:
        defaults_raw = d.get("defaults", {})
        defaults: dict[str, StageModelConfig] = {}
        for stage in ("classify", "think", "tool_call", "answer"):
            if stage in defaults_raw:
                defaults[stage] = StageModelConfig.from_dict(defaults_raw[stage])

        providers_raw = d.get("providers", {})
        providers: dict[str, ProviderEndpoint] = {}
        for name, ep in providers_raw.items():
            providers[name] = ProviderEndpoint.from_dict(ep)

        return cls(
            mode=d.get("mode", "single"),
            embedding=d.get("embedding"),
            defaults=defaults,
            providers=providers,
        )
