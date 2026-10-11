# ADR 0004 — Domain schema, provenance and typed API contracts

P0-04 uses separate `student_data` and `global_knowledge` schemas. Documents,
pages and regions exist in both: a global document cannot refer to a student
account or student evidence. Shared subject/course/concept definitions are
maintainer managed. Runtime reads their published views only.

Every private table carries a student account ID. Composite foreign keys bind
child records and source evidence to that same student. Row policies deny all
rows without transaction-local scope. The application resolves that scope from
a verified principal, never a request student ID. Admin has no private-schema
grants. These policies protect against omitted filters; a compromised runtime
credential remains a service-level risk, covered by deployment isolation.

Raw observations, responses, messages, evidence links and profile revisions are
append-only for runtime. Review/correction history is appended rather than
rewriting evidence. Current concept/trait states and profile summaries are
mutable projections. Examiner hypotheses are private, because their supporting
marks belong to a student. No private-to-global promotion relationship exists.

UUID keys, UTC timestamps and schema version 1 are common metadata. Relational
keys and indexes handle ownership, curriculum and evidence predicates. JSONB
holds bounded annotations and source locators; optional vectors have no fixed
dimension until P0-06 selects the embedding capability. No vector search index
or inferred trait seed is introduced here.

Migration 0003 extends P0-03 tables without discarding rows. Legacy chunks
without a global document are hidden from published retrieval; a NOT VALID
constraint requires provenance on new writes without inventing it for old rows.
Migration 0004 checks question source documents and published session pins, and
keeps evaluation cases/runs out of runtime views. Rollback returns the exact
P0-03 columns/views. All new grants are explicit.

Pydantic contracts describe the section 5 endpoints; they do not mount future
business routes. Upload metadata is bounded and SHA-256 checked; binary
signature inspection, page rendering and authorization happen in later upload
handlers. Unknown learning context remains null with explicit unresolved fields.
