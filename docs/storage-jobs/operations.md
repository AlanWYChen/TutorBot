# Storage and background jobs

## Local operation

`make up` provisions three emulator buckets and starts separate runtime/admin Celery
workers and durable relays. PostgreSQL, Redis and fake-GCS use named volumes;
`make down` preserves them. Do not use `down -v` against retained evidence.

`make private-io-integration` uses only synthetic fixtures. It verifies SDK upload,
read, conflict detection, repeated delete, manifests, tenant/service isolation,
Celery delivery, duplicate claims, bounded retries, lease fencing and cancellation.
It then stops the runtime worker/relay and Redis, writes an object and enqueues a
job in PostgreSQL, restarts storage/API, restores Redis/workers, and verifies that
both the object and the queued job resume. A shell trap restores stopped services
on failure. This gate briefly interrupts local background processing/readiness;
run it against synthetic local development data only.

Worker health requires a post-DB-connection readiness signal and recent Celery
heartbeats. Relay health requires a recent successful outbox pass. The API's
existing readiness report is unchanged. No upload, parsing or public job routes
are exposed until their own implementation steps. The only registered job is
`verify_object`, which validates the immutable source bytes against its manifest.

Call `PrivateRepository` inside a request transaction using a verified principal.
Commit storage registration and `enqueue()` together. Call `tombstone()` and commit
before physical deletion; the returned manifest supports cleanup retries. A
terminal job is unchanged by a repeated cancel or delivery. New processing after
failure requires a fresh idempotency key; reusing a key with another object refuses.
Never let a request construct storage references, service mode, broker destination,
cloud URL or command. Published references must be resolved from published DB views.

The relay resends unclaimed jobs after ten seconds. Attempts have a 120-second lease
and a 90-second Celery hard limit. Transient failures become available after two
seconds, with at most three attempts. Object absence, changed generation and digest
failures are permanent. Errors persist safe codes, not provider responses or content.
Retries are at-least-once; all future processing handlers must be idempotent.

## Cloud contract

Set distinct globally unique `STUDENT_PRIVATE_BUCKET`, `CURRICULUM_PUBLISHED_BUCKET`
and `TEACHING_PRIVATE_BUCKET` names. Omit `STORAGE_EMULATOR_HOST` in production;
production configuration rejects it. `OBJECT_RETENTION_DAYS` defaults to 30 for
local fixtures; production must configure the approved retention policy. The
metadata date is recorded policy intent, not an enforced GCS bucket retention lock
or a scheduled purge. Those lifecycle decisions belong to the deployment/privacy
gate. No live student evidence should be onboarded before it passes.

Give runtime API/worker identities student-bucket object permissions and read-only
published-bucket access. Give maintainer identities teaching-bucket permissions and
published-bucket publishing permissions, without student-bucket access. Enable
uniform bucket-level access and public access prevention. SQL worker roles mirror
this service split, with no inheritance/superuser/BYPASSRLS. There is no API ability
to enumerate worker jobs across students.

For signed reads use signing-capable, preferably impersonated service-account
credentials; plain compute ADC may not sign. Grant only the necessary signing
permission to the service identity. Signing failures refuse access; no public URL
fallback. Local preview must use a future authenticated API streaming route, since
the emulator does not validate signatures.

`CloudTasksPublisher` constructs a fixed HTTPS POST with a configured dedicated
service account/audience and only `job_id` in its body. An authenticated HTTP client
must create it using ADC. The private worker receiver must verify OIDC signature,
issuer, audience and allowed service-account identity before calling `run_job`.
A delivery is acknowledged after the durable state transition, with retries
recoverable by the relay. Do not make this receiver publicly callable with only a
job UUID. The current step provides the request contract, not a deployed receiver.

`CloudRunJobsPublisher` invokes one configured Cloud Run Job with only
`TUTORBOT_JOB_ID` as an override. Its fixed image/identity/command uses
`python -m scripts.run_cloud_job`. Reject caller-controlled images, commands,
resource names and environment overrides. The shared runner loads job/manifest
from the service's DB schema; transport never supplies a student or object path.

## Required real-GCS / cloud staging gate

Use a disposable project and synthetic documents only; retain an evidence report
with deployed versions, region, service identities and test outputs. Clean up all
fixtures afterwards. Local results cannot establish these cloud properties.

1. Provision the three private buckets and SQL roles. Attempt anonymous reads,
   cross-service writes/reads and public ACL changes; all must refuse. Confirm
   runtime cannot write the published bucket or read teaching fixtures; maintainer
   cannot read student fixtures.
2. Upload PDF/image/text fixtures through the SDK with generation-zero preconditions.
   Restart API and worker; read the same generation from the DB manifest. Repeat
   identical upload; reject changed bytes/media/size under the same resource ID.
   Replace a fixture through a privileged staging tool and prove stale generation
   reads/deletes refuse without affecting the replacement.
3. Generate a V4 URL for a server-authorized object at short TTL. Prove success
   before expiry, denial after expiry, and denial for tampered path/generation/
   signature. Prove another student cannot request it and signing failure does
   not yield an unsigned URL. Avoid logging the URL bearer credential.
4. Verify SHA-256/size checks against deliberately corrupted fixture metadata.
   Tombstone and cancel, retry physical delete, restart services and prove absence.
   Confirm approved lifecycle/retention settings, deletion recovery and orphan
   reconciliation; record whether legal retention locks affect deletion timing.
5. With a private Cloud Tasks receiver, validate real OIDC/IAM and refuse forged
   audience/issuer/service-account tokens. Interrupt delivery/DB commits and replay
   the task; one durable job reaches terminal state with bounded attempts. Expire
   a lease and prove an old attempt cannot commit completion. Cancel a running job
   and prove side effects/completion respect the cancellation fence.
6. Execute the fixed Cloud Run Job with the job-ID override. Verify its SQL/GCS
   service split and refusal of unauthorized invocation/overrides. Interrupt its
   execution and verify relay recovery. Monitor only safe status/error codes.

Primary references: [GCS SDK Blob operations](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob),
[GCS signed URLs](https://docs.cloud.google.com/storage/docs/access-control/signed-urls),
[Celery task acknowledgement and retry behavior](https://docs.celeryq.dev/en/stable/userguide/tasks.html),
[Cloud Tasks HTTP/OIDC requests](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks),
and [Cloud Run Job execution](https://docs.cloud.google.com/run/docs/execute/jobs).
