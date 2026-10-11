import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.model_gateway.registry import Alias, Capability, ModelCapabilities, Registry, Service
from app.model_gateway.types import (
    EmbeddingBatch,
    EmbeddingIndex,
    EmbeddingRecord,
    GatewayError,
    Generation,
    ImageInput,
    Message,
    StructuredGeneration,
    ToolGeneration,
    ToolProposal,
    ToolSpec,
    Trace,
    Usage,
)

T = TypeVar("T", bound=BaseModel)


class ModelGateway(Protocol):
    async def generate(
        self, alias: Alias, messages: Sequence[Message], *, max_tokens: int = 1024
    ) -> Generation: ...

    async def generate_structured(
        self,
        alias: Alias,
        messages: Sequence[Message],
        schema: type[T],
        *,
        max_tokens: int = 2048,
        mode: Literal["json_schema", "validated_json"] = "json_schema",
        allow_fallback: bool = False,
    ) -> StructuredGeneration[T]: ...

    async def call_tools(
        self,
        alias: Alias,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int = 2048,
        allow_fallback: bool = False,
    ) -> ToolGeneration: ...

    async def analyze_images(
        self,
        alias: Alias,
        messages: Sequence[Message],
        images: Sequence[ImageInput],
        *,
        max_tokens: int = 2048,
        allow_fallback: bool = False,
    ) -> Generation: ...

    async def embed(self, texts: Sequence[str], index: EmbeddingIndex) -> EmbeddingBatch: ...


class WireMessage(BaseModel):
    content: str | None = Field(default=None, max_length=100000)
    refusal: str | None = None
    tool_calls: list[dict[str, object]] = Field(default_factory=list, max_length=16)


class Choice(BaseModel):
    message: WireMessage
    finish_reason: str


class Completion(BaseModel):
    choices: list[Choice] = Field(min_length=1, max_length=1)
    usage: Usage


class VectorItem(BaseModel):
    index: int = Field(ge=0, strict=True)
    embedding: list[float]


class VectorResponse(BaseModel):
    data: list[VectorItem] = Field(min_length=1, max_length=32)


def provider_schema(schema: type[BaseModel]) -> dict[str, object]:
    """All fields required for native strict transport; local validation retains bounds."""
    if schema.model_config.get("extra") != "forbid":
        raise GatewayError("schema_must_forbid_extra_fields")
    raw: dict[str, object] = schema.model_json_schema()

    def tighten(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if not isinstance(properties, dict):
                    raise GatewayError("unsupported_schema")
                # Arbitrary dict payloads cannot truthfully use strict additionalProperties=false.
                if isinstance(node.get("additionalProperties"), dict):
                    raise GatewayError("unsupported_schema")
                node["additionalProperties"] = False
                node["required"] = list(properties)
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for value in node:
                tighten(value)

    tighten(raw)
    return raw


class LiteLLMModelGateway:
    def __init__(
        self,
        client: httpx.AsyncClient,
        registry: Registry,
        selected_models: Mapping[Alias, str],
        service: Service,
    ):
        self.client = client
        self.registry = registry
        self.models = dict(selected_models)
        self.service = service
        if set(self.models) != set(Alias) or any(
            m not in registry.models for m in self.models.values()
        ):
            raise GatewayError("invalid_registry_selection")

    def _route(
        self, alias: Alias, capability: Capability, allow_fallback: bool = False
    ) -> tuple[Trace, ModelCapabilities]:
        if alias not in self.models:
            raise GatewayError("unknown_alias")
        route = self.registry.routes[alias]
        if self.service not in route.services:
            raise GatewayError("alias_not_authorized")
        selected = alias
        reason = None
        if not self.registry.models[self.models[alias]].supports(capability):
            fallback = route.fallbacks.get(capability) if allow_fallback else None
            if fallback is None or self.service not in self.registry.routes[fallback].services:
                raise GatewayError("unsupported_" + capability)
            selected = fallback
            reason = "unsupported_" + capability
        caps = self.registry.models[self.models[selected]]
        if not caps.supports(capability):
            raise GatewayError("unsupported_" + capability)
        return Trace(
            requested_alias=alias,
            selected_alias=selected,
            provider_model=self.models[selected],
            fallback_reason=reason,
        ), caps

    def _payload(
        self,
        trace: Trace,
        caps: ModelCapabilities,
        messages: Sequence[Message],
        max_tokens: int,
        extra_budget: int = 0,
    ) -> dict[str, object]:
        if not 1 <= len(messages) <= 64 or not 1 <= max_tokens <= min(8192, caps.max_output_tokens):
            raise GatewayError("request_budget_exceeded")
        budget = sum(len(m.content.encode("utf-8")) + 64 for m in messages)
        if budget + extra_budget + max_tokens > caps.context_limit:
            raise GatewayError("context_budget_exceeded")
        return {
            "model": trace.selected_alias.value,
            "messages": [m.model_dump() for m in messages],
            "max_tokens": max_tokens,
            "stream": False,
        }

    async def _post(
        self, path: Literal["chat/completions", "embeddings"], payload: dict[str, object]
    ) -> object:
        try:
            response = await self.client.post(path, json=payload)
            if response.status_code in (401, 403):
                raise GatewayError("provider_authentication_failed")
            if response.status_code == 429:
                raise GatewayError("provider_rate_limited")
            if response.status_code >= 300:
                raise GatewayError("provider_unavailable")
            if len(response.content) > 4 * 1024 * 1024:
                raise GatewayError("provider_response_too_large")
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise GatewayError("provider_transport_failed") from None

    async def _completion(
        self, payload: dict[str, object], *, require_tools: bool = False
    ) -> tuple[WireMessage, Usage]:
        raw = await self._post("chat/completions", payload)
        try:
            result = Completion.model_validate(raw)
        except ValidationError:
            raise GatewayError("invalid_provider_output") from None
        choice = result.choices[0]
        if choice.message.refusal or choice.finish_reason == "content_filter":
            raise GatewayError("model_refused")
        if choice.finish_reason == "length":
            raise GatewayError("output_truncated")
        if choice.finish_reason != ("tool_calls" if require_tools else "stop"):
            raise GatewayError("invalid_provider_output")
        return choice.message, result.usage

    async def generate(
        self, alias: Alias, messages: Sequence[Message], *, max_tokens: int = 1024
    ) -> Generation:
        trace, caps = self._route(alias, "text")
        message, usage = await self._completion(self._payload(trace, caps, messages, max_tokens))
        if not message.content or message.tool_calls:
            raise GatewayError("invalid_provider_output")
        return Generation(text=message.content, trace=trace, usage=usage)

    async def generate_structured(
        self,
        alias: Alias,
        messages: Sequence[Message],
        schema: type[T],
        *,
        max_tokens: int = 2048,
        mode: Literal["json_schema", "validated_json"] = "json_schema",
        allow_fallback: bool = False,
    ) -> StructuredGeneration[T]:
        capability: Capability = "json_schema" if mode == "json_schema" else "json_object"
        trace, caps = self._route(alias, capability, allow_fallback)
        trace = trace.model_copy(update={"structured_mode": mode})
        if schema.model_config.get("extra") != "forbid":
            raise GatewayError("schema_must_forbid_extra_fields")
        json_schema = (
            provider_schema(schema) if mode == "json_schema" else schema.model_json_schema()
        )
        schema_text = json.dumps(json_schema)
        instruction = Message(
            role="system", content="Return only a JSON object matching this schema: " + schema_text
        )
        payload = self._payload(
            trace,
            caps,
            [instruction, *messages],
            max_tokens,
            extra_budget=len(schema_text.encode()),
        )
        payload["response_format"] = (
            {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": json_schema},
            }
            if mode == "json_schema"
            else {"type": "json_object"}
        )
        message, usage = await self._completion(payload)
        if not message.content or message.tool_calls:
            raise GatewayError("invalid_provider_output")
        try:
            value = schema.model_validate_json(message.content)
        except ValidationError:
            raise GatewayError("invalid_structured_output") from None
        return StructuredGeneration[T](value=value, trace=trace, usage=usage)

    async def call_tools(
        self,
        alias: Alias,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        *,
        max_tokens: int = 2048,
        allow_fallback: bool = False,
    ) -> ToolGeneration:
        trace, caps = self._route(alias, "tool_calls", allow_fallback)
        specs = {tool.name: tool for tool in tools}
        if not 1 <= len(specs) == len(tools) <= 16:
            raise GatewayError("invalid_tool_definitions")
        definitions = []
        for tool in tools:
            if (
                not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", tool.name)
                or len(tool.description) > 1000
            ):
                raise GatewayError("invalid_tool_definitions")
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": provider_schema(tool.arguments),
                        "strict": caps.json_schema,
                    },
                }
            )
        payload = self._payload(
            trace, caps, messages, max_tokens, extra_budget=len(json.dumps(definitions).encode())
        )
        payload.update(tools=definitions, tool_choice="required")
        message, usage = await self._completion(payload, require_tools=True)
        calls = []
        seen = set()
        try:
            for raw in message.tool_calls:
                function = raw["function"]
                if not isinstance(function, dict) or raw.get("type") != "function":
                    raise ValueError
                name, arguments = function["name"], function["arguments"]
                call_id = raw["id"]
                if not isinstance(name, str) or name not in specs or not isinstance(arguments, str):
                    raise ValueError
                if not isinstance(call_id, str) or call_id in seen:
                    raise ValueError
                seen.add(call_id)
                calls.append(
                    ToolProposal(
                        call_id=call_id,
                        name=name,
                        arguments=specs[name].arguments.model_validate_json(arguments),
                    )
                )
            return ToolGeneration(calls=calls, trace=trace, usage=usage)
        except (KeyError, ValueError):
            raise GatewayError("invalid_tool_output") from None

    async def analyze_images(
        self,
        alias: Alias,
        messages: Sequence[Message],
        images: Sequence[ImageInput],
        *,
        max_tokens: int = 2048,
        allow_fallback: bool = False,
    ) -> Generation:
        trace, caps = self._route(alias, "vision", allow_fallback)
        if not 1 <= len(images) <= 4 or sum(len(i.data) for i in images) > 8 * 1024 * 1024:
            raise GatewayError("image_budget_exceeded")
        payload = self._payload(trace, caps, messages, max_tokens, extra_budget=8192 * len(images))
        wire = [m.model_dump() for m in messages]
        wire.append(
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": i.data_url(), "detail": "low"}}
                    for i in images
                ],
            }
        )
        payload["messages"] = wire
        message, usage = await self._completion(payload)
        if not message.content or message.tool_calls:
            raise GatewayError("invalid_provider_output")
        return Generation(text=message.content, trace=trace, usage=usage)

    async def embed(self, texts: Sequence[str], index: EmbeddingIndex) -> EmbeddingBatch:
        trace, caps = self._route(Alias.EMBEDDINGS, "embedding")
        if index.model_id != trace.provider_model or index.dimensions != caps.embedding_dimensions:
            raise GatewayError("embedding_index_mismatch")
        if not 1 <= len(texts) <= 32 or any(
            not t.strip() or len(t.encode()) > caps.context_limit for t in texts
        ):
            raise GatewayError("embedding_budget_exceeded")
        raw = await self._post(
            "embeddings",
            {
                "model": trace.selected_alias.value,
                "input": list(texts),
                "dimensions": index.dimensions,
                "encoding_format": "float",
            },
        )
        try:
            response = VectorResponse.model_validate(raw)
            vectors = sorted(response.data, key=lambda item: item.index)
            if [v.index for v in vectors] != list(range(len(texts))):
                raise ValueError
            if any(len(v.embedding) != index.dimensions for v in vectors):
                raise ValueError
            records = [
                EmbeddingRecord(
                    vector=v.embedding,
                    model_id=trace.provider_model,
                    dimensions=index.dimensions,
                    chunker_version=index.chunker_version,
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    index_release=index.index_release,
                )
                for text, v in zip(texts, vectors, strict=True)
            ]
        except (ValidationError, ValueError):
            raise GatewayError("invalid_embedding_output") from None
        return EmbeddingBatch(records=records, trace=trace)
