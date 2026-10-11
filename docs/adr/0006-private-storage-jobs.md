# ADR 0006: Private storage and durable jobs

Status: accepted for the P0-07 implementation; user review pending.

Use the Google Cloud Storage SDK for local emulator and cloud storage. Domain
callers depend on `ObjectStorage` and `JobDispatcher` protocols. The request-scoped
`PrivateRepository` implements durable enqueue/status/cancel without broker calls.
Resolve its scope from a verified principal; storage receives that resolved owner,
never a student ID or raw object path from a request. Admin owner IDs derive from
verified Firebase UIDs. Object keys contain owner, assessment (or unassigned), and
resource UUIDs; filenames and content never become paths.

Keep immutable object manifests and job outboxes separately in student and global
schemas. Student rows have forced RLS. Worker roles can read only their own service's
manifests/jobs and update jobs; they cannot read conversations, profiles, global
teaching tables, student accounts or the other service's outbox. APIs retain their
existing credentials. The runtime worker intentionally processes manifests for all
students, with no access to other student domain tables. This privilege is confined
to a non-public background service and distinct cloud bucket IAM identity.

Use generation-zero uploads and generation-bound reads/deletes. Duplicate uploads
must match digest, size and media type. Bound download ranges and verify SHA-256.
Record retention dates alongside media/size/generation in PostgreSQL and GCS
metadata. Database manifests cannot be updated except to tombstone them; tombstones
cancel pending attempts, prevent new jobs, and allow repeated physical cleanup.
Object UUIDs are never reused after deletion. Later upload handlers must check
existing/tombstoned manifests before writing; partial writes require reconciliation.

A job row is its own transactional outbox. Committing metadata and enqueue together
makes broker outages recoverable. Relays publish bounded batches; failed publication
rolls back delivery markers. An acknowledgement lost at either side can duplicate
messages. Database claims, lease tokens, deadlines and terminal-state guards fence
those duplicates. Expired attempts recover; failures retry twice (three total
attempts). Status and cancellation come from PostgreSQL, not Celery's result backend.
Cancellation is durable and fences completion. The current immutable verification
handler has no derived writes; future handlers must fence every side-effect commit
and make external writes generation/idempotency-safe.

Local services use Celery/Redis with JSON serialization, late acknowledgement,
worker-loss redelivery, bounded task time and one prefetched task. Relays recover
jobs even if broker messages disappear. No raw documents/content enter the broker.
Cloud Tasks and Cloud Run Jobs publishers implement the same job-reference contract;
cloud deployment must supply ADC-authenticated transport and a verified IAM/OIDC
receiver. This step creates no cloud resources or public worker endpoint.

The emulator has no reliable IAM/signature enforcement. It stays private in Compose;
local signed access explicitly refuses. Real GCS uses generation-bound V4 GET URLs
with 1–900 second TTLs and signing-capable credentials. Real bucket IAM, signing,
retention/deletion policy and Cloud Tasks/Run Jobs behavior require staging validation.

See [operations and staging gate](../storage-jobs/operations.md).
