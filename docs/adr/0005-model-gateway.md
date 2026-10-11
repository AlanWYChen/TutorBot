# ADR 0005 — Capability-gated model gateway

P0-06 adds one provider-neutral application gateway using the existing pinned
LiteLLM proxy. Six task aliases remain stable. One checked-in JSON registry owns
provider model IDs, key environment names, capabilities, route selectors and
explicit capability fallbacks. Proxy configuration is generated from that same
registry at startup, preventing independent configuration drift. Unknown model
IDs fail before the service starts. Only the proxy receives provider keys.

Strict JSON Schema and JSON-object mode are distinct. Native structured output
requires declared schema support. An explicit validated-JSON mode uses JSON-object
transport plus local Pydantic validation; it never claims provider schema guarantees.
Capability fallback must be requested and appears in result metadata. There is
no retry or fallback after malformed output, refusal, authentication failure or
transport failure, and no embedding fallback that could change vector spaces.

The gateway sends stateless messages, client schemas and function definitions.
It returns validated tool proposals; it executes no tools or provider-hosted
state. Service-mode allowlists keep teaching distillation out of runtime.
Input/context/output budgets are bounded. Conservative UTF-8 byte accounting
bounds text tokens; low-detail image inputs receive a separate conservative
budget. Streaming is recorded in capabilities but this MVP returns completed,
validated responses only.

Embedding results carry model ID, dimensions, content hash, chunker version and
index release. A required index specification must match the configured model
and dimensions before a request is sent. Changing text tutor routing cannot
change the embedding configuration or student DB schema.

Tests use httpx transport fixtures and two real pinned LiteLLM proxies with
synthetic provider HTTP servers. Those proxies have fixed local provider URLs
and synthetic keys. They exercise actual provider dispatch without paid inference.
Provider quality, live account availability and math/pedagogy equivalence still
require the later staging/provider-substitution evaluation gate.
