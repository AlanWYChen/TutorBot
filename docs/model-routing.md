# Model routing and capability checks

The application gateway exposes `generate`, `generate_structured`, `call_tools`,
`analyze_images` and `embed`. Use `model_gateway(Settings())` as an async context
manager; it builds an authenticated, bounded HTTP client for the configured
LiteLLM proxy. No provider key belongs in an API or browser environment.

## Configuration

The source of truth is `apps/api/app/model_gateway/registry.json`. The API and
proxy both load it with the same resolver and environment selectors. The proxy
startup renderer writes a temporary JSON configuration; `infra/litellm/config.yaml`
is a generated default snapshot, using environment references rather than secrets.
Unknown models, cross-modal embedding routes and missing aliases fail closed.

| Task alias | Environment selector | Default model |
| --- | --- | --- |
| tutor-reasoning | TUTOR_MODEL | openai/gpt-4o-mini-2024-07-18 |
| document-vision | VISION_MODEL | openai/gpt-4o-2024-08-06 |
| assessment-analysis | ASSESSMENT_MODEL | openai/gpt-4o-mini-2024-07-18 |
| context-classification | CONTEXT_MODEL | openai/gpt-4o-mini-2024-07-18 |
| teaching-distillation | DISTILLATION_MODEL | openai/gpt-4o-mini-2024-07-18 |
| embeddings | EMBEDDING_MODEL | openai/text-embedding-3-small |

To switch text tutoring, set `TUTOR_MODEL=deepseek/deepseek-v4-pro` in `.env` and
restart/recreate the proxy and API services with `make up`. The renderer chooses
`DEEPSEEK_API_KEY` for that deployment. Other task selectors, embeddings and the
profile DB stay unchanged. `TEXT_MODEL` and the old `*_MODEL_ALIAS` scaffold
variables are superseded by this table; aliases themselves are fixed.

Existing `openai/gpt-4o-mini` and `openai/gpt-4o` selectors remain registered for
local-volume compatibility. Prefer the snapshot defaults for repeatable behavior.
Additional providers/models need documented capabilities and dispatch tests
before being added to the registry. An unused Gemini key is not evidence that
a Gemini model has been registered or validated.

## Capability evidence

OpenAI documents text/image input, tool calls, structured output and streaming
for [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
[GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o). The registry uses
those documented snapshots and context/output bounds.

DeepSeek's current [model documentation](https://api-docs.deepseek.com/quick_start/pricing/)
lists `deepseek-v4-pro`, JSON output and tools, and excludes vision for that model.
Its [tool-call guide](https://api-docs.deepseek.com/guides/tool_calls/) describes
function proposals. This registry conservatively enables JSON-object output and
tools, disables native JSON Schema and vision, caps output at 8,192 tokens, and
uses non-thinking mode. The pinned LiteLLM image recognizes the `deepseek/`
provider prefix; actual dispatch is verified by synthetic HTTP integration tests.
See [LiteLLM DeepSeek support](https://docs.litellm.ai/docs/providers/deepseek).

OpenAI documents the embedding model's default 1,536 dimensions in its
[embedding guide](https://developers.openai.com/api/docs/guides/embeddings).
The gateway conservatively bounds input below the documented maximum.

## Validation and failure behavior

- Text returns a Pydantic `Generation` with usage and route trace.
- Native structured requests require `json_schema`; schemas forbid extra fields,
  require all transport properties, and retain local Pydantic validation. Open-ended
  dictionaries are explicitly rejected for native strict transport.
- `mode="validated_json"` explicitly opts into JSON-object transport and local
  schema validation. It provides no provider-side schema guarantee.
- Capability fallback requires `allow_fallback=True`. A result records requested
  alias, selected alias, provider model, fallback reason and structured mode.
  Default calls refuse unsupported capabilities before sending any HTTP request.
- There is no fallback/retry after invalid JSON, wrong tool arguments, refusal,
  truncation, rate limit, authentication or transport failure. Stable error codes
  exclude provider body, prompts and keys.
- Function names and argument schemas are caller-defined allowlists. Returned
  proposals are validated, including unknown function/extra-field rejection.
  The gateway executes no tools. Future orchestration must authorize every action
  against the verified student principal before execution.
- Teaching distillation is admin-only at the gateway boundary. API routing and
  database credentials continue to enforce the established service boundaries.

Messages, tool definitions, text context, output, image count/size and response
size are bounded. Text context uses a conservative UTF-8-byte upper bound, with
message/schema overhead and reserved output. Low-detail data-URI images have a
separate conservative token budget; arbitrary image URLs are not accepted.
Workers still validate/decode/render image contents in their upload pipeline.
Provider streaming support is recorded, while this MVP validates completed output.
Conversation state remains in TutorBot; no provider-hosted memory/tools are used.

## Embedding index compatibility

Every embedding request requires an `EmbeddingIndex` specifying model ID,
dimensions, chunker version and index release. Configured model/dimensions must
match before a request is sent. Results are reordered by input index and checked
for count, dimension and finite values; each carries SHA-256 of the input content
and the complete index specification. There is no embedding fallback.

Changing embedding models requires a new index release and re-embedding; do not
write those vectors into the old index. Database/vector retrieval work follows
in its own ticket. Switching text tutoring does not alter this metadata.

## Executable review

`make model-integration` starts two pinned LiteLLM proxies and a synthetic provider
on an internal Docker network, checks text, JSON, tools, images and embeddings,
and stops those services afterward. Provider keys and responses are synthetic;
there are no host ports or provider internet access. The fixture verifies the
actual dispatched model ID and credential family.

`make check` covers the gateway unit cases. `make auth-integration` retains the
real account/service/isolation/audit/migration checks. CI runs all three.
Tests establish transport and validation behavior. Actual provider availability,
teaching quality, math/tool behavior and comparative eval scores are checked
with real provider credentials at the later staging/provider-substitution gate.
