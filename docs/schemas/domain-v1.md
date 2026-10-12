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

## Assignment/project extension boundary

The current Phase 1 workflow targets tests/exams. `assignments` provides task/stage
context and one optional `document_id`; tutoring sessions can reference it. It does
not yet model separately uploaded requirements and student work, submission
versions, or requirement-coverage reviews. Student uploads currently create an
`assessment`, even though the type catalog anticipates homework and IA contexts.

A future assignments/projects section can reuse private documents, pages/regions,
jobs and scoped access, but needs additive assignment-document roles, requirements
and submission versions, and reviews pinned to both sources and stage. New private
links must retain composite ownership keys and forced RLS. Existing question-based
observations are not a general project-feedback store; extending profile evidence
requires explicit provenance and aggregation decisions. Private teacher briefs
remain student-scoped context, separate from published official rubric sources.
See [scheduled workflow](../../TUTORBOT_IMPLEMENTATION_PLAYBOOK.md#scheduled-assignmentsprojects-workflow-and-architecture-extension).
The playbook schedules the additive domain migration in P2-06, upload/workspace UI
in P2-07, review in P3-06..P3-09, rubric resolution in P4-06 and coaching in P5-06.
These remain planned; this documentation update does not apply migrations.

## API contract catalog

[Contract source](../../apps/api/app/domain/contracts.py) defines the 18 section 5 operations plus maintainer upload status
(19 catalog entries) with Pydantic request/response models. [JSON Schema catalog](../contracts/v1.json)
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

## P0-07 infrastructure extension

Migration `0005_private_io` adds `storage_objects` and `jobs` to each of
`student_data` and `global_knowledge` (51 tables total). Student manifests and jobs
have forced RLS and composite owner/object keys; maintainer outboxes are not
published. Separate worker roles can read manifests/jobs and update job status,
with no access to other domain evidence. See the
[storage/job decision](../adr/0006-private-storage-jobs.md).

## P0-05 mounted upload operations

Student/maintainer upload and storage-verification status are implemented, with
separate authenticated original downloads. Other catalog operations remain planned;
the exported catalog lists implemented operations without mounting placeholders.
See [upload policy and multipart envelope](../uploads/api.md). No migration was
needed: validated metadata is retained in existing document metadata columns.

## P1-01 page rendering

Migration 0006 adds runtime render jobs and narrowly grants the runtime worker
append-only page/candidate-region and derived-manifest writes. It preserves forced
RLS and denies unrelated student profiles/conversations and maintainer data.
Pages persist width/height, rotation and renderer version; bounding boxes use those
canonical pixels. No mathematical observations or inferred profile states are created.

## P1-02 maintainer annotations

Migrations 0007/0008 extend maintainer annotations with structured payloads, source
hash/crop references and revision numbers, and add append-only `annotation_revisions`
(52 tables total). Runtime annotation views are removed and annotation source regions
are excluded from published retrieval regardless of status. Admin workers can append
private rendered pages/regions/manifests without student access. Source boxes/crops
remain fixed through the public edit API; note edits append revision history.
