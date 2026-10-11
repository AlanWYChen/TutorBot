# ADR 0001: Local foundation

Status: accepted for P0-01.

Use the playbook defaults at the repository root: Next.js/TypeScript/Tailwind,
FastAPI/Pydantic, PostgreSQL/pgvector, Redis, fake GCS, Firebase Auth emulator,
and upstream LiteLLM. Compose is the reproducible development entry point.
Pinned dependencies and lockfiles accompany application builds.

Expose web/API/auth on loopback only. Storage, database, Redis and model proxy
have no host ports. fake GCS is an internal development emulator, not an IAM
security implementation. Named volumes preserve local database, storage and
emulator state. No real student records or live API keys belong in this scaffold.

Liveness tests the process; readiness checks infrastructure (including pgvector).
It never calls a generation provider or implies auth/security acceptance.
Health output omits connection errors and credentials. P0-02/P0-03 implement
identity and DB privileges before student or admin tools are exposed.

No domain migrations are introduced in P0-01; pgvector bootstrap is idempotent.
The initial relational schema is explicitly reserved for P0-04. A worker is
introduced with P0-07 rather than an empty Celery application.

References: https://docs.litellm.ai/docs/proxy/deploy and
https://firebase.google.com/docs/emulator-suite/connect_auth.
