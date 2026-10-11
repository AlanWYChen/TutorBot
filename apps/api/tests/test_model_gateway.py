import asyncio
import hashlib
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.domain.contracts import ResolvedLearningContext
from app.model_gateway.gateway import LiteLLMModelGateway, provider_schema
from app.model_gateway.registry import Alias, load_registry
from app.model_gateway.types import EmbeddingIndex, GatewayError, ImageInput, Message, ToolSpec


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: int


class MathArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expression: str


MESSAGES = [Message(role="user", content="Synthetic: what is 2 + 2?")]
TOOLS = [ToolSpec("validate_math", "Validate a mathematical expression", MathArguments)]


def completion(
    content: str | None = "4",
    *,
    finish: str = "stop",
    refusal: str | None = None,
    calls: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"content": content, "refusal": refusal, "tool_calls": calls or []},
                "finish_reason": finish,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def gateway(
    response: object = None,
    *,
    env: dict[str, str] | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
    service: str = "runtime",
) -> tuple[LiteLLMModelGateway, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer synthetic-proxy-key"
        return handler(request) if handler else httpx.Response(200, json=response or completion())

    registry = load_registry()
    client = httpx.AsyncClient(
        base_url="http://proxy.test/v1/",
        transport=httpx.MockTransport(respond),
        headers={"Authorization": "Bearer synthetic-proxy-key"},
    )
    return LiteLLMModelGateway(client, registry, registry.resolve(env or {}), service), requests  # type: ignore[arg-type]


@pytest.mark.parametrize("model", ["openai/gpt-4o-mini-2024-07-18", "deepseek/deepseek-v4-pro"])
def test_tutor_model_switch_changes_only_config(model: str) -> None:
    gw, requests = gateway(env={"TUTOR_MODEL": model})
    result = asyncio.run(gw.generate(Alias.TUTOR, MESSAGES))
    assert result.text == "4" and result.trace.provider_model == model
    assert requests[0]["model"] == "tutor-reasoning"
    assert "student_id" not in requests[0]
    assert gw.models[Alias.EMBEDDINGS] == "openai/text-embedding-3-small"


def test_registry_rejects_unknown_models_and_cross_modal_routes() -> None:
    registry = load_registry()
    for env in (
        {"TUTOR_MODEL": "openai/invented"},
        {"TUTOR_MODEL": "openai/text-embedding-3-small"},
        {"EMBEDDING_MODEL": "deepseek/deepseek-v4-pro"},
    ):
        with pytest.raises(ValueError):
            registry.resolve(env)


def test_structured_output_validates_domain_and_required_schema() -> None:
    context = ResolvedLearningContext(subject="Mathematics")
    gw, requests = gateway(completion(context.model_dump_json()))
    result = asyncio.run(gw.generate_structured(Alias.CONTEXT, MESSAGES, ResolvedLearningContext))
    assert result.value.curriculum_version is None
    assert "curriculum_version" in result.value.unresolved_fields
    transport = requests[0]["response_format"]["json_schema"]
    assert transport["strict"] is True
    assert set(transport["schema"]["required"]) == set(transport["schema"]["properties"])


@pytest.mark.parametrize(
    "content",
    [
        '{"answer": "four"}',
        '{"answer":4,"student_id":"forged"}',
        '```json\n{"answer":4}\n```',
        "not-json",
        '{"answer":',
    ],
)
def test_malformed_structured_output_never_falls_back(content: str) -> None:
    gw, requests = gateway(completion(content))
    with pytest.raises(GatewayError, match="invalid_structured_output"):
        asyncio.run(gw.generate_structured(Alias.CONTEXT, MESSAGES, Answer, allow_fallback=True))
    assert len(requests) == 1


def test_schema_capability_refusal_explicit_fallback_and_validated_json() -> None:
    gw, requests = gateway(
        completion('{"answer":4}'), env={"TUTOR_MODEL": "deepseek/deepseek-v4-pro"}
    )
    with pytest.raises(GatewayError, match="unsupported_json_schema"):
        asyncio.run(gw.generate_structured(Alias.TUTOR, MESSAGES, Answer))
    assert not requests
    fallback = asyncio.run(
        gw.generate_structured(Alias.TUTOR, MESSAGES, Answer, allow_fallback=True)
    )
    assert fallback.trace.selected_alias == Alias.CONTEXT
    assert fallback.trace.fallback_reason == "unsupported_json_schema"
    json_mode = asyncio.run(
        gw.generate_structured(Alias.TUTOR, MESSAGES, Answer, mode="validated_json")
    )
    assert json_mode.value.answer == 4
    assert json_mode.trace.selected_alias == Alias.TUTOR
    assert json_mode.trace.structured_mode == "validated_json"
    assert requests[-1]["response_format"] == {"type": "json_object"}


def test_vision_refuses_text_only_provider_before_transport() -> None:
    gw, requests = gateway(env={"TUTOR_MODEL": "deepseek/deepseek-v4-pro"})
    image = ImageInput(media_type="image/png", data=b"\x89PNG\r\n\x1a\nsynthetic")
    with pytest.raises(GatewayError, match="unsupported_vision"):
        asyncio.run(gw.analyze_images(Alias.TUTOR, MESSAGES, [image]))
    assert not requests
    result = asyncio.run(gw.analyze_images(Alias.TUTOR, MESSAGES, [image], allow_fallback=True))
    assert result.trace.selected_alias == Alias.VISION
    assert result.trace.fallback_reason == "unsupported_vision"
    assert requests[0]["model"] == "document-vision"
    image_url = requests[0]["messages"][-1]["content"][0]["image_url"]
    assert image_url["detail"] == "low" and image_url["url"].startswith("data:image/png;base64,")
    with pytest.raises(ValidationError):
        ImageInput(media_type="image/png", data=b"not a png")


def test_tools_are_validated_proposals_only() -> None:
    calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "validate_math", "arguments": '{"expression":"2+2"}'},
        }
    ]
    gw, requests = gateway(
        completion(None, finish="tool_calls", calls=calls),
        env={"TUTOR_MODEL": "deepseek/deepseek-v4-pro"},
    )
    result = asyncio.run(gw.call_tools(Alias.TUTOR, MESSAGES, TOOLS))
    assert result.calls[0].arguments.model_dump() == {"expression": "2+2"}
    assert requests[0]["tools"][0]["function"]["strict"] is False
    assert requests[0]["tool_choice"] == "required"


@pytest.mark.parametrize(
    "name,args",
    [
        ("read_other_student", "{}"),
        ("validate_math", '{"expression":"2+2","student_id":"forged"}'),
        ("validate_math", "not-json"),
    ],
)
def test_unapproved_or_invalid_tool_calls_rejected(name: str, args: str) -> None:
    gw, _ = gateway(
        completion(
            None,
            finish="tool_calls",
            calls=[
                {"id": "call-1", "type": "function", "function": {"name": name, "arguments": args}}
            ],
        )
    )
    with pytest.raises(GatewayError, match="invalid_tool_output"):
        asyncio.run(gw.call_tools(Alias.TUTOR, MESSAGES, TOOLS))


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_authentication_failed"),
        (403, "provider_authentication_failed"),
        (429, "provider_rate_limited"),
        (500, "provider_unavailable"),
    ],
)
def test_provider_errors_redacted_and_not_retried(status: int, code: str) -> None:
    gw, requests = gateway(
        handler=lambda request: httpx.Response(status, text="secret token prompt")
    )
    with pytest.raises(GatewayError, match=code) as error:
        asyncio.run(gw.generate(Alias.TUTOR, MESSAGES))
    assert "secret" not in str(error.value) and len(requests) == 1


@pytest.mark.parametrize(
    "finish,refusal,code",
    [
        ("length", None, "output_truncated"),
        ("stop", "private refusal", "model_refused"),
        ("content_filter", None, "model_refused"),
    ],
)
def test_refusal_and_partial_results_are_explicit(
    finish: str, refusal: str | None, code: str
) -> None:
    gw, _ = gateway(completion("private incomplete", finish=finish, refusal=refusal))
    with pytest.raises(GatewayError, match=code):
        asyncio.run(gw.generate(Alias.TUTOR, MESSAGES))


def test_runtime_cannot_call_distillation_and_context_budget_is_checked() -> None:
    gw, requests = gateway()
    with pytest.raises(GatewayError, match="alias_not_authorized"):
        asyncio.run(gw.generate(Alias.DISTILLATION, MESSAGES))
    with pytest.raises(GatewayError, match="context_budget_exceeded"):
        asyncio.run(gw.generate(Alias.TUTOR, [Message(role="user", content="x" * 20000)] * 7))
    with pytest.raises(GatewayError, match="request_budget_exceeded"):
        asyncio.run(gw.generate(Alias.TUTOR, MESSAGES, max_tokens=100000))
    assert not requests


def index() -> EmbeddingIndex:
    return EmbeddingIndex(
        model_id="openai/text-embedding-3-small",
        dimensions=1536,
        chunker_version="synthetic-v1",
        index_release="synthetic-index-1",
    )


def test_embeddings_are_ordered_and_have_complete_index_metadata() -> None:
    gw, requests = gateway(
        {"data": [{"index": 1, "embedding": [0.2] * 1536}, {"index": 0, "embedding": [0.1] * 1536}]}
    )
    result = asyncio.run(gw.embed(["first", "second"], index()))
    assert result.records[0].vector == [0.1] * 1536
    record = result.records[0]
    assert record.content_hash == hashlib.sha256(b"first").hexdigest()
    assert record.model_id == index().model_id and record.index_release == index().index_release
    assert record.chunker_version == "synthetic-v1" and record.dimensions == 1536
    assert requests[0]["model"] == "embeddings"


@pytest.mark.parametrize("change", [{"dimensions": 768}, {"model_id": "different-space"}])
def test_embedding_index_mismatch_fails_before_request(change: dict[str, object]) -> None:
    gw, requests = gateway()
    with pytest.raises(GatewayError, match="embedding_index_mismatch"):
        asyncio.run(gw.embed(["synthetic"], index().model_copy(update=change)))
    assert not requests


@pytest.mark.parametrize(
    "vectors",
    [
        [{"index": 0, "embedding": [0.1]}],
        [{"index": 1, "embedding": [0.1] * 1536}],
        [{"index": 0, "embedding": [float("nan")] * 1536}],
    ],
)
def test_bad_embeddings_rejected(vectors: list[dict[str, object]]) -> None:
    # Inject NaN as bytes; httpx refuses invalid JSON numbers during serialization.
    gw, _ = gateway(
        handler=lambda request: httpx.Response(200, content=json.dumps({"data": vectors}))
    )
    with pytest.raises(GatewayError, match="invalid_embedding_output"):
        asyncio.run(gw.embed(["synthetic"], index()))


def test_open_ended_strict_schema_is_explicitly_rejected() -> None:
    class OpenSchema(BaseModel):
        model_config = ConfigDict(extra="forbid")
        values: dict[str, int]

    with pytest.raises(GatewayError, match="unsupported_schema"):
        provider_schema(OpenSchema)


def test_tool_proposals_serialize_validated_arguments() -> None:
    calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "validate_math", "arguments": '{"expression":"2+2"}'},
        }
    ]
    gw, _ = gateway(completion(None, finish="tool_calls", calls=calls))
    result = asyncio.run(gw.call_tools(Alias.TUTOR, MESSAGES, TOOLS))
    assert result.model_dump()["calls"][0]["arguments"] == {"expression": "2+2"}


def test_transport_timeout_is_redacted_and_not_retried() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private prompt or token", request=request)

    gw, requests = gateway(handler=fail)
    with pytest.raises(GatewayError, match="provider_transport_failed") as error:
        asyncio.run(gw.generate(Alias.TUTOR, MESSAGES))
    assert "private" not in str(error.value) and len(requests) == 1


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"litellm_base_url": "http://user:secret@proxy/v1"}, "invalid_proxy_url"),
        ({"litellm_base_url": "https://proxy/v1?secret=x"}, "invalid_proxy_url"),
        (
            {"app_env": "production", "litellm_base_url": "http://proxy/v1"},
            "production_proxy_requires_tls",
        ),
        ({"litellm_master_key": "not-configured"}, "proxy_key_missing"),
    ],
)
def test_factory_rejects_unsafe_proxy_configuration(changes: dict[str, object], code: str) -> None:
    from app.config import Settings
    from app.model_gateway.factory import model_gateway

    payload = dict(
        app_env="test", litellm_base_url="https://proxy.test/v1", litellm_master_key="synthetic"
    )
    payload.update(changes)

    async def exercise() -> None:
        async with model_gateway(Settings.model_validate(payload)):
            pytest.fail("unsafe configuration accepted")

    with pytest.raises(GatewayError, match=code):
        asyncio.run(exercise())


def test_unexpected_tool_finish_cannot_be_returned_as_text() -> None:
    gw, _ = gateway(completion("4", finish="tool_calls"))
    with pytest.raises(GatewayError, match="invalid_provider_output"):
        asyncio.run(gw.generate(Alias.TUTOR, MESSAGES))
