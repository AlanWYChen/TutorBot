# TutorBot

An evidence-backed high-school mathematics tutor, built ticket by ticket from
[TUTORBOT_IMPLEMENTATION_PLAYBOOK.md](TUTORBOT_IMPLEMENTATION_PLAYBOOK.md).

Current slice: **P1-02, maintainer annotation studio**. Sign-in, role checks,
student-scoped account reads, service isolation and maintainer activity review are functional.
Students can upload and reopen PDFs, navigate their rendered pages and locate question areas. Maintainers can save/edit source-linked annotations; dataset tooling and tutoring follow in later tickets.

The current implementation and Phase 1 workflow cover **tests/exams**. The planned
**assignments/projects** section will link a separate requirements upload to a
student proposal, draft or completed-work upload and review coverage, strengths,
gaps and suggested changes. This needs an additive domain/API/review extension;
it is not implemented by the current viewer or assignment classification scaffold.
See [product scope and extension plan](TUTORBOT_IMPLEMENTATION_PLAYBOOK.md#product-sections-and-current-implementation-scope).
Phase 1 remains focused on tests/exams; assignment foundations and review are now
scheduled in Phases 2–3, with rubric resolution and coaching in Phases 4–5.

## Start locally

Requires Docker Desktop with Compose v2, Node.js 24.12+ and Python 3 (smoke script only).

```sh
make setup
make up
make smoke
```

Open http://localhost:3000. API docs: http://localhost:8000/docs.
`make status` lists service health; `make down` stops services while preserving
named volumes. Initial image downloads/builds may take several minutes.

The stack includes Next.js/Tailwind, separate runtime/maintainer FastAPI services, PostgreSQL 17 + pgvector, Redis,
fake GCS, separate runtime/maintainer Celery workers and durable relays, Firebase Auth emulator (`demo-tutorbot`), and LiteLLM with all six task
aliases. Provider credentials are server-only in `.env`; no live keys are needed
for startup or smoke checks. Model inference still requires an external provider.
The gateway checks capabilities and records explicit fallback decisions.
`make model-integration` verifies provider substitution with synthetic responses.

Database, object storage, Redis and LiteLLM are accessible only within the Docker
network. Web/API/auth emulator ports bind to loopback. Emulator storage does not
implement production IAM. **Use synthetic data in the emulator stack.** Real student deployment requires
the documented cloud security gate. The student upload/viewer UI is available; tutoring follows in later tickets.

## Verify

```sh
make setup check   # web lint/types/tests; API lint/types/tests in Python 3.12
make up smoke     # production builds and live infrastructure/readiness checks
```

Web-only commands: `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`,
`npm run build`. API commands inside the checks image: `ruff check .`,
`mypy app`, `pytest`. CI runs these same checks and the Compose smoke test.

Liveness endpoints: `/health/live` (API), `/health` (web).
API `/health/ready` verifies database/pgvector, Redis, storage, auth emulator and
model proxy; returns 503 on any failure and omits error details/credentials.
Provider inference is deliberately excluded from infrastructure readiness.

Domain migrations are applied before either API starts. The schema migrator
uses a separate database role. Named volumes survive container replacement.

See [foundation decisions](docs/adr/0001-local-foundation.md) and
[P0-01 review evidence](docs/reviews/P0-01.md).

## Authentication review

After startup, `make seed-auth` provisions synthetic local accounts only.
Sign in as `student-a@example.test`, `student-b@example.test`, or
`maintainer@example.test`, using the demo password `TutorBot-local-123!`.
These are disposable development fixtures, never production credentials.

`make auth-integration` runs real Firebase-emulator/PostgreSQL access tests and
migration roundtrips in a disposable database. CI includes this command.
A separate migration job applies `alembic upgrade head` before either API starts. Production must
omit `FIREBASE_AUTH_EMULATOR_HOST` and configure a real `GOOGLE_CLOUD_PROJECT`.
Maintainer roles are assigned through privileged Firebase custom claims, never
through the web interface. The browser stores auth in memory only; reload signs
out. Tokens are sent in headers, not URLs or application logs.

See [P0-02 evidence](docs/reviews/P0-02.md) and
[identity decisions](docs/adr/0002-identity-and-scope.md).

## Service boundaries and audit

Runtime API: http://localhost:8000. Maintainer API: http://localhost:8001.
The web routes student requests to the runtime API and maintainer activity to
the maintainer API. Each process mounts only its permitted route group and uses
its own restricted database login. Runtime reads published global knowledge
through security-barrier views; it has no access to global base tables/drafts.
Maintainer DB credentials have no student-account access.

Local startup uses a privileged, one-shot role bootstrap and a separate schema
migrator. Only those jobs receive their respective elevated credentials. Existing
local volumes are upgraded without deleting student accounts. `make down`
preserves data. Do not copy the example local passwords to production.

Sign in as the synthetic maintainer and choose **View recent activity** to review
audit records. Events store only trusted actor identity, route templates and
operational outcome, and cannot be changed/deleted by either API. Application
JSON logs contain no raw paths, query strings, headers, student content or secrets.
Auditing failure closes otherwise-successful requests with a generic 503.

`make auth-integration` now also verifies actual DB login permissions, audit
immutability and API separation. Production GCS/Firebase IAM and Cloud Run
service identities are verified at the staging gate; emulators cannot reproduce
cloud IAM.

See [P0-03 evidence](docs/reviews/P0-03.md) and
[service privilege decisions](docs/adr/0003-service-privileges-and-audit.md).

## Domain schema and contracts

The initial schema includes private assessments, question evidence, learning
profiles and history, tutoring sessions and memory; maintainer curricula,
source documents, rubrics, skills, releases and evaluations are stored separately.
Private records have forced row policies and composite ownership keys. Runtime
reads published global views and cannot access maintainer evaluation partitions.

The typed catalog includes the original 18 planned `/v1` operations and maintainer
upload status. Upload/status handlers are implemented; others arrive in their tickets. Unknown learning context stays explicit and
no-evidence traits remain unknown. No curriculum/rubric/student facts are seeded.

See [schema inventory](docs/schemas/domain-v1.md), [API contract catalog](docs/contracts/v1.json),
[P0-04 review evidence](docs/reviews/P0-04.md), and
[domain decisions](docs/adr/0004-domain-schema.md).

## Model gateway review

The gateway supports text, typed JSON, validated tool proposals, images and
embedding batches through the pinned LiteLLM proxy. It checks model capabilities
before transport and rejects malformed/refused/truncated output with safe error
codes. Runtime cannot call teaching distillation; tool execution remains in the
future authorized orchestration layer.

`TUTOR_MODEL=deepseek/deepseek-v4-pro` switches text tutoring by configuration.
Vision and embeddings retain independent selections. `.env.example` lists the
six active selectors; old `TEXT_MODEL`/`*_MODEL_ALIAS` scaffold variables are
superseded. Unknown models fail closed. Embedding requests must match an explicit
index model/dimension and return complete provenance metadata.

`make model-integration` runs two isolated proxies with synthetic provider
responses and stops them afterward; it needs no paid API keys. Real quality and
account availability are verified at the later staging gate. See
[routing documentation](docs/model-routing.md) and [P0-06 review](docs/reviews/P0-06.md).

## Private storage and jobs review

The GCS SDK stores immutable objects in three separate buckets. PostgreSQL keeps
hashes, media types, sizes, retention dates and generations in scoped manifests.
The job dispatcher commits enqueue/status/cancel in the database; relays deliver
through Celery/Redis and recover queued work after outages. Worker credentials
are distinct and limited to their service's manifests and job states.

`make private-io-integration` verifies synthetic storage and worker behavior, then
restarts storage/API and interrupts Redis to prove objects and queued work persist.
It restores local services when it exits. Cloud Tasks/Cloud Run Jobs have fixed
job-reference request contracts; real IAM, V4 signing and cloud delivery are checked
in staging. Emulator signed access explicitly refuses.

See [operations and staging tests](docs/storage-jobs/operations.md),
[storage/job decision](docs/adr/0006-private-storage-jobs.md), and
[P0-07 review evidence](docs/reviews/P0-07.md). Upload safeguards are implemented in P0-05; parsing and the viewer follow
in their own tickets.

## PDF upload safeguards review

The runtime API accepts student PDFs and the maintainer API accepts draft references.
Both validate actual bytes, checksum, PDF structure and page count before storage.
Requests are limited to 25 MiB and 200 pages, with bounded multipart parsing and
native inspection. Originals download through authenticated owner-scoped routes;
no public storage URL is returned. Identical retries reuse their resource and job.

`make upload-integration` checks the real authenticated upload/private-download flow
with generated fixtures. See [API usage and policy](docs/uploads/api.md) and
[P0-05 review evidence](docs/reviews/P0-05.md). P1-01 now supplies the upload UI, page rendering and private viewer; saved
annotations are the next reviewed step.

## Student page viewer review

Sign in as the synthetic student, upload a PDF, then use page navigation, zoom,
numbered prompt hints and drag/keyboard coordinates. The worker retains private
canonical page images and coordinate metadata; numbered hints remain tentative.
Selections are temporary until the annotation step. Scans display normally without
invented hints. No model call or mathematical grading runs in this slice.

`make viewer-integration` tests the complete web-proxy/API/worker flow. See
[viewer operations](docs/assessments/viewer.md),
[synthetic review fixture](docs/fixtures/synthetic-quadratics.pdf), and
[P1-01 acceptance evidence](docs/reviews/P1-01.md).

## Maintainer annotation studio

Sign in as the synthetic maintainer, upload an authorized source with rights metadata,
and select a question/response area. Save structured notes, marks, observations and
teaching rationale, then reopen or edit them alongside their original crop. The studio
cannot read student accounts/PDFs. Sources/annotations stay draft; edits preserve the
source box/crop and append revision history.

`make studio-integration` verifies save/edit/retrieve, stale-edit rejection, private
crops, runtime exclusion and source deletion. See [studio operation](docs/studio/annotations.md)
and [P1-02 acceptance evidence](docs/reviews/P1-02.md). Dataset export/import is next,
after user review. Every completed implementation step is committed and pushed.
