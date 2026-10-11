# TutorBot domain schema v1

Migration head: `0004_domain_guards`. 47 tables: 3 identity/audit, 19 global,
25 student-owned. Migration 0003 adds 40 tables and extends the existing 7;
0004 adds relationship guards and removes runtime evaluation views.

## Ownership and provenance

| Area | Tables | Access and relationships |
| --- | --- | --- |
| `public` | users, student_accounts, audit_events | Verified Firebase UID resolves account; default curriculum FK; append-only audit. |
| `global_knowledge` catalog | subjects, programs, curricula, concepts, concept_prerequisites, curriculum_concepts, fingerprint_traits | Maintainer controlled; prerequisite self-link prohibited; unique course/version and concept/trait identities. |
| `global_knowledge` sources | documents, document_pages, document_regions, maintainer_annotations | Documents require maintainer author, SHA-256, positive size and private object key; ordered page identity and exact region references. |
| `global_knowledge` teaching | knowledge_chunks, teaching_demonstrations, teaching_strategies, skill_versions, knowledge_releases, rubric_versions | New chunks/demonstrations require a global document; rubric source is a global document; strategies reference versioned skills. |
| `global_knowledge` evaluation | evaluation_cases, evaluation_runs | Cases reference global documents or maintainer demonstrations; development/holdout partition; no runtime views. |
| `student_data` sources | documents, document_pages, document_regions, examiners, assessments, questions, question_concepts | Composite owner FKs on every private link; question region must come from its assessment document. |
| `student_data` raw evidence | student_responses, response_regions, marking_observations, mistake_observations, fingerprint_observations, concept_evidence | Append-only runtime grants; corrections append superseding records. Concept evidence has exactly one question/session source. |
| `student_data` projections | student_learning_profiles, student_concept_states, student_trait_states | Separate from account record; course/context states unique even for null course; no demonstrated state with zero evidence. |
| `student_data` longitudinal history | student_profile_revisions, profile_revision_evidence, student_interventions | Append-only revisions and evidence; evidence join binds supported revision to the same student. |
| `student_data` tutoring | assignments, tutoring_sessions, tutoring_messages, student_memory_chunks | Sessions pin published knowledge/skills; messages append-only. Memory has exactly one question/session/profile source and student-only scope. |
| `student_data` marking hypotheses | examiner_hypotheses, hypothesis_evidence | Private hypothesis, supporting/contradicting marking evidence and examiner are bound to the same student. |

All records use UUIDs, `created_at` timestamps and `schema_version=1`. Specific
state/review/release fields are constrained strings. Confidence/quality/uncertainty
are bounded to 0–1. Counts, marks, sizes and page numbers have appropriate lower
bounds. JSONB holds structured annotations, context, licensing, manifests and
locators; source and ownership predicates use relational columns and indexes.

`published_knowledge` contains security-barrier views. Runtime has read-only
access to published catalogs, sources, rubrics, strategies, skills and releases.
Chunks require both a published release and a published global source document.
Pages/regions also require published source parents. Evaluations and maintainer
base tables are inaccessible to runtime. There is no student-to-global FK,
promotion trigger, worker or copying mechanism.

## Student scope and evidence history

Every private table has forced row-level security. Missing scope returns no
rows and denies writes. `StudentDomain` derives an account from a verified
principal and sets `app.student_id` only for its active transaction. Repository
reads additionally bind that ID in SQL. Commit/rollback clears the setting,
including on pooled connections. Admin has no private-schema access.

This protects against omitted SQL filters and forged resource IDs. The runtime
credential can set a transaction scope, so trusted principal resolution remains
an application boundary; RLS does not defend against a fully compromised runtime
service. No request contract accepts a student account or vector namespace.

Raw evidence is not rewritten by runtime. Superseding observations and profile
revisions preserve history; state/summary projections can be recomputed. Trait
levels include `not_observed` and `insufficient_evidence`. There are no seed
traits, curricula, rubrics, inferred personalities or fabricated student records.

## API contract catalog

[Contract source](../../apps/api/app/domain/contracts.py) defines all 18 section 5
operations with Pydantic request/response models. [JSON Schema catalog](../contracts/v1.json)
is exported without mounting placeholder routes. Regenerate with the API's
`python -m scripts.export_contracts` command.

Uploads accept PDF/PNG/JPEG metadata, SHA-256, at most 25 MiB and 200 pages;
unknown extra fields and path-like filenames are rejected. Handlers must still
inspect actual bytes, count rendered pages and resolve ownership when implemented.
Expensive operations have job responses. Tutor session requests accept assignment
and learning context; the server chooses authorized published release pins.

`ResolvedLearningContext` retains null unknowns and records unresolved fields.
Context evidence separates student confirmation, document evidence and published
metadata. Profile responses keep concept mastery and observable work traits
separate, with uncertainty and source references. Contract schema versions are
independent of the `/v1` HTTP namespace.

## Upgrade and rollback

Startup applies migrations through the restricted migrator. Existing account,
audit, release and chunk rows survive upgrade. Legacy chunks/demonstrations
without global provenance remain in their base tables; new writes must have a
global source. Unlinked legacy chunks are excluded from published retrieval.

The tested path is P0-03 → head → P0-03 → head → base → head, in a disposable
PostgreSQL database. Rollback to P0-03 removes domain tables/data and restores
its original columns/views; it preserves P0-03 rows. Never downgrade a live
student database without exporting domain data first. The vector extension is
retained because infrastructure owns it; vectors remain optional and unindexed
until a verified embedding configuration is selected.

Business upload, extraction, profile computation, vector retrieval and release
publishing handlers are implemented by later tickets, using this schema.
