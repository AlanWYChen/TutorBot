# ADR 0003: Service privileges and audit

Separate runtime and maintainer API processes, using separate non-superuser DB
logins. A one-shot privileged local bootstrap creates roles; a separate migrator
owns schema objects and runs Alembic. Neither API receives migration/owner or
other-service credentials. All new tables fail closed until explicit grants.

Use global_knowledge base tables and security-barrier views in published_knowledge.
Runtime can SELECT only the published views; maintainer can maintain base tables
and has no access to student account tables. Add minimal protected release,
skill, chunk and demonstration tables now to prove permissions; P0-04 extends
contracts/schema. Do not expose ingestion/publishing APIs before their tickets.

Record v1 requests in append-only audit_events with trusted actor identity,
server-generated request ID, route template, method, HTTP status and outcome.
No tokens, bodies, raw URLs/IDs/query strings, IPs or exceptions enter logs.
Runtime may append audits but cannot read/change/delete them; maintainer can
read audits but not alter history. Failed audit persistence returns generic 503
for otherwise-successful requests; authorization denials stay denied. Safe JSON
logs include only bounded operational fields; third-party/unstructured logging
is disabled in API processes to avoid accidental content/credential traces.

This ticket enforces database and API separation locally. Real Firebase IAM
(runtime read-user vs privileged claim setter), private GCS IAM and separate
Cloud Run service identities must be verified at the GCP staging gate. Firebase
and fake-GCS emulators cannot reproduce those production IAM guarantees.

Reference: https://www.postgresql.org/docs/17/rules-privileges.html.
