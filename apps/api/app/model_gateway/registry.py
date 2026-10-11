import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Alias(StrEnum):
    TUTOR = "tutor-reasoning"
    VISION = "document-vision"
    ASSESSMENT = "assessment-analysis"
    CONTEXT = "context-classification"
    DISTILLATION = "teaching-distillation"
    EMBEDDINGS = "embeddings"


Capability = Literal["text", "vision", "tool_calls", "json_schema", "json_object", "embedding"]
Service = Literal["runtime", "admin"]


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["openai", "deepseek"]
    key_env: Literal["OPENAI_API_KEY", "DEEPSEEK_API_KEY"]
    vision: bool
    tool_calls: bool
    json_schema: bool
    json_object: bool
    context_limit: int = Field(gt=0)
    max_output_tokens: int = Field(ge=0)
    embedding_dimensions: int | None = Field(default=None, gt=0)
    streaming: bool

    def supports(self, capability: Capability) -> bool:
        if capability == "text":
            return self.embedding_dimensions is None
        if capability == "embedding":
            return self.embedding_dimensions is not None
        return bool(getattr(self, capability))


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_env: str = Field(pattern=r"^[A-Z_]+$")
    default_model: str
    services: list[Service]
    fallbacks: dict[Capability, Alias]


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    models: dict[str, ModelCapabilities]
    routes: dict[Alias, Route]

    @model_validator(mode="after")
    def valid_routes(self) -> Self:
        if set(self.routes) != set(Alias):
            raise ValueError("all six aliases required")
        for model, caps in self.models.items():
            if not model.startswith(caps.provider + "/"):
                raise ValueError("model provider mismatch")
            if caps.key_env != (
                "OPENAI_API_KEY" if caps.provider == "openai" else "DEEPSEEK_API_KEY"
            ):
                raise ValueError("provider key mismatch")
        return self

    def resolve(self, env: Mapping[str, str]) -> dict[Alias, str]:
        selected = {}
        for alias, route in self.routes.items():
            model = env.get(route.model_env, route.default_model)
            if model not in self.models:
                raise ValueError("configured model is not in the capability registry")
            if self.models[model].supports("embedding") != (alias == Alias.EMBEDDINGS):
                raise ValueError("embedding and generation routes must remain separate")
            selected[alias] = model
        return selected


def load_registry() -> Registry:
    return Registry.model_validate_json(Path(__file__).with_name("registry.json").read_text())


def configured_models() -> dict[Alias, str]:
    return load_registry().resolve(os.environ)
