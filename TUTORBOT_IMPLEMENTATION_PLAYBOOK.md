# TutorBot — Agent Implementation Playbook

**Version:** 0.2 · **Status:** Build specification · **Initial scope:** High-school mathematics (Ontario first; IB Math AA SL IA vertical slice) · **Owner:** Platform maintainer

> **For implementation agents:** This file is the authoritative build sequence. Implement small vertical slices, keep code executable, add tests and migrations with each slice, and stop at each phase gate to report evidence. Do not silently expand scope, invent curriculum requirements, or modify published teaching knowledge through student activity.

## 0. Product contract and non-negotiable rules

Build a curriculum-aware, assignment-aware, personalized high-school math tutor. It must (1) analyze uploaded, marked PDF exams, (2) detect mistakes and evidence-backed student reasoning/presentation fingerprints, (3) infer *tentative* examiner marking preferences, (4) retrieve licensed/authorized textbooks, official curriculum documents, and applicable rubrics, (5) tutor using **only maintainer-approved/published** pedagogy and assignment skills together with the authorized student's history and current work, and (6) let the maintainer privately annotate examples, distill instructional methods, evaluate them, and publish versioned skill releases.

### Non-negotiable boundaries

1. **No automatic global learning from students.** Student uploads, conversations, and analyses may update *that student's profile only*; never put them into global RAG, global mistake exemplars, the distillation dataset, or draft/published skills. No automatic promotion path.
2. **Admin-only teaching studio.** Only the authenticated maintainer can upload/publish global knowledge, create teaching demonstrations, edit drafts, approve skill changes, and release teaching bundles.
3. **Runtime read-only global knowledge.** Student TutorBot service identity can read only `published` releases; cannot read drafts or write global knowledge, skills, or training data. Enforce in API, DB grants, storage permissions, and tool registry—not prompts alone.
4. **Tenant isolation.** All reads/writes of student data are scoped using trusted server-side identity, not student-supplied IDs. Test cross-student access failures.
5. **Evidence before claims.** Every meaningful mistake, fingerprint claim, examiner hypothesis, and rubric-related suggestion links to source PDF page/bounding box, authoritative rubric passage, or tagged interaction. Explicitly label observation vs interpretation vs confirmed finding.
6. **Unknown is valid.** Do not infer intentions, personality, confidence, or hidden mental processes from written work alone. Use `not_observed`, confidence and review flags; abstain when uncertain.
7. **Curriculum versioning.** Requirements are keyed by jurisdiction/program/course/level/assessment cohort/version. Resolve based on actual student cohort and assignment, not just today's date. Do not hardcode rubric criteria without approved source material.
8. **No weight training required.** Use models via API, structured data, retrieval, skills, deterministic subject tools, and human-approved revisions. Fine-tuning is outside MVP.
9. **Student ownership and academic integrity.** Coach and critique, don't silently fabricate marks or present unverified grading as official. Preserve the student's authorship of substantial assessed work, especially IB IAs.
10. **Privacy/security.** Protect minors' educational records; minimize PII, control retention, support export/deletion, redact logs, require appropriate consent, and review applicable local privacy rules before production use.

### Definitions

- **Global knowledge:** Maintainer-approved textbooks, curricula, rubrics, examples and published instructional policies.
- **Student knowledge:** Only a given student's exams, mistakes, profile, fingerprints, assignments, and tutoring history.
- **Skill:** Versioned procedure/instruction used by an agent; not a factual database or trainable model weight.
- **Distillation:** Transform maintainer demonstrations and corrections into proposed structured strategies/skill edits, reviewed and evaluated before publication.
- **Assignment context:** Recognized task (test, homework, IB IA, etc.), stage, and approved assessment framework.

## 1. MVP scope and explicit exclusions

**First vertical slice:** Grade 11 Ontario quadratic functions, marked multi-page PDF upload; question-by-question review with editable extraction; error and fingerprint evidence; retrieval from one published curriculum guide/textbook excerpt; individualized report; guided tutoring using 2–3 maintainer-authored skills. Add one **IB Math AA SL IA recognition + applicable rubric** path to prove curriculum/assignment switching.

**MVP includes:** student/admin auth; private PDF storage; question coordinates/crops; human correction; structured extraction; basic SymPy checks; student-level mistake history; fingerprint observations; source citations; published global documents/skills; RAG filters; admin-only approval; baseline evals.

**MVP excludes:** autonomous skill editing/publishing, automatic examiner “personality” judgments, instant perfect grading, unsupported disciplines, model fine-tuning, multi-agent debate loops, extensive live collaboration, mobile native app, large-scale graph DB. Architecture must allow later physics, chemistry, AP, further IB/other Ontario courses.

## 2. Technology defaults — GCP-first, Docker-first, provider-agnostic

| Layer | MVP/local Docker Compose | GCP deployment | Notes |
|---|---|---|---|
| Web | Next.js + TypeScript + Tailwind, Node container | Cloud Run | PDF.js/React-PDF viewer and annotations |
| API | Python 3.12+ FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | Cloud Run | Explicit student/admin route and service authorization |
| Agent orchestration | Application-owned Python workflows, typed tools, Pydantic validation | Same on Cloud Run | Do not bind domain logic to one provider SDK |
| **LLM gateway** | **Self-hosted LiteLLM Proxy** container | LiteLLM Proxy on Cloud Run or another managed service | Pin image version; aliases per task, not provider-specific IDs in business logic |
| Generation providers | OpenAI / DeepSeek / Gemini selected through LiteLLM | Same | External APIs require internet/API keys; capability differences remain |
| Embeddings | Provider-configurable API routed through LiteLLM | Same | Embedding model fixed/versioned per index; changing chat provider doesn't require re-embedding |
| SQL + vector/FTS | PostgreSQL + pgvector container | Cloud SQL for PostgreSQL + pgvector | Prefer hybrid filtered retrieval; no separate vector DB needed |
| PDF storage | **fake-gcs-server** container + persistent Docker volume | **Google Cloud Storage (GCS)** private buckets | Google Cloud Storage SDK behind `ObjectStorage` adapter |
| PDF processing | PyMuPDF + multimodal LLM | Cloud Run Jobs/worker | Retain original, page coordinates and crops in GCS |
| Mathematics | SymPy + NumPy | Same | Math validation is not merely string or expression similarity |
| Jobs | Celery + Redis containers | Cloud Tasks + Cloud Run Jobs or workers | Implement `JobDispatcher`, idempotent handlers, retry/status persistence |
| Auth | Firebase Auth emulator | Firebase Authentication | Server verifies tokens; admin role set via trusted backend/custom claims |
| Monitoring | JSON logs + OpenTelemetry (optional collector) | Cloud Logging + Cloud Trace | Redact student content, prompts and tokens as needed |
| CI/CD / IaC | Docker Compose, pytest, Playwright, Vitest | GitHub Actions, Artifact Registry, Terraform | Pin versions and run integration tests |

**Local limitation:** the application, DB, pgvector, PDF storage, Firebase auth emulator, workers and LiteLLM proxy run in Docker. Default OpenAI/DeepSeek/Gemini inference and embeddings still call external APIs. Full offline use requires separately configured local inference/embedding models (optional, out of MVP). Fake GCS does not fully reproduce IAM, signed URLs, events or lifecycle behaviour; test production-specific behaviour on real GCS.

### Provider abstraction contract

- The app calls one **LiteLLM Proxy** `base_url=http://litellm:4000/v1`, using **logical model aliases**: `tutor-reasoning`, `document-vision`, `assessment-analysis`, `context-classification`, `teaching-distillation`, `embeddings`.
- All model calls go through an application `ModelGateway` interface exposing `generate`, `generate_structured`, `call_tools`, `embed`, and (when available) `analyze_images`; normalize outputs to Pydantic domain schemas.
- Maintain a **model capability registry**: `vision`, `tool_calls`, `json_schema`, `context_limit`, `embedding_dimensions`, `streaming`; routing MUST check capability and fail closed/fallback explicitly when unsupported.
- LiteLLM unifies transport, **not** equivalent model capability or response quality. Validate model/tool/structured-output behaviour in tests before remapping aliases.
- Keep conversation state, prompt assembly, RAG, skills, tool execution, student data and approval state **inside TutorBot**, not provider-hosted state. Do not depend on provider-specific hosted tools.
- For MVP, self-host upstream LiteLLM (no fork needed). Fork only for justified internal changes. Pin a tested image tag/digest and treat proxy credentials/secrets as server-only.
- Embedding metadata MUST include model ID, dimension, chunker version, content hash and index release. Re-embed into a **new index** when switching embedding models; do not mix vector spaces in a single similarity index.

### Minimal model routing config (illustrative)

```yaml
# infra/litellm/config.yaml — validate aliases against current model/provider docs
model_list:
  - model_name: tutor-reasoning
    litellm_params:
      model: deepseek/deepseek-chat
      api_key: os.environ/DEEPSEEK_API_KEY
  - model_name: document-vision
    litellm_params:
      model: openai/YOUR_TESTED_VISION_MODEL_ID  # replace with verified deployed model
      api_key: os.environ/OPENAI_API_KEY
  - model_name: embeddings
    litellm_params:
      model: openai/text-embedding-3-small
      api_key: os.environ/OPENAI_API_KEY
```

Implement real provider IDs as explicit environment/config values supported by the pinned LiteLLM version; avoid assuming DeepSeek models support vision/structured JSON without verification. Provide `.env.example` with `LITELLM_BASE_URL`, proxy key, and per-task aliases. Never commit live keys.

### Storage and job abstractions

- `ObjectStorage.put/get/delete/signed_access` backed by **GCS SDK**; local emulator via `STORAGE_EMULATOR_HOST`/client endpoint as validated. Private buckets: `student-private`, `curriculum-published`, `teaching-private` (separate IAM roles in cloud). Objects organized by student/assessment IDs, stored alongside DB `sha256`, media type, size and retention metadata.
- `JobDispatcher.enqueue/status/cancel` backed by Celery locally and Cloud Tasks/Run Jobs when deployed. Do not hardcode Celery calls in domain logic. Use durable DB job states and idempotency keys.
- Signed URL and IAM behaviours differ under emulator: include real-GCS staging tests before public launch.

### Suggested repository

```text
tutorbot/
  apps/web/                         # student UI, admin annotation/knowledge studio
  apps/api/app/
    auth/                           # roles, authorization, tenant scoping
    assessments/                    # upload, extraction, annotations
    students/                       # profiles, errors, fingerprints
    examiners/                      # evidence-backed hypotheses
    curriculum/                     # program/course/version mapping
    assignments/                    # task recognition & rubrics
    knowledge/                      # ingestion, hybrid retrieval, citations
    tutor/                          # runtime orchestration & tools
    distillation/                   # admin-only proposals/evaluations
    skills/                         # published loader & registry
    subject_capabilities/math/      # validation & math tooling
  apps/worker/
  skills/pedagogy/
  skills/subjects/mathematics/
  skills/assignments/ib-math-ia/
  evals/                            # anonymized gold datasets, test runners
  infra/compose/                    # Docker Compose, fake-gcs, Redis, Postgres, LiteLLM
  infra/litellm/config.yaml         # logical model aliases
  infra/gcp/                        # Cloud Run, Cloud SQL, GCS, IAM, Terraform
  packages/model_gateway/           # provider-neutral inference/embedding interface
  packages/storage/                 # GCS adapter / emulator support
  packages/jobs/                    # Celery / Cloud Tasks adapters
  docs/                              # ADRs, schemas, threat model
```

## 3. Roles and system trust boundaries

| Capability | Student | Student runtime service | Maintainer/admin | Admin distillation service |
|---|---|---|---|---|
| Upload own assignments/tests | Yes | Scoped write | Optional authorized access | No default access |
| Read another student's records | No | No | Controlled, auditable only | No |
| Update own profile from observations | Via API | Scoped write | Controlled | No |
| Read approved global reference and skills | Via tutor | Read only | Yes | Yes |
| Read global drafts | No | No | Yes | Yes |
| Add global curriculum/textbook/rubric | No | No | Yes | Admin-controlled draft only |
| Propose/edit global skill | No | No | Yes | Draft only |
| Publish teaching release | No | No | Explicit approval only | No direct production write |

**Implementation:** separate API route groups and service accounts; RLS or scoped DB access; private GCS bucket IAM/prefix policies; signed URLs only for authorized object access; no tool accepting arbitrary `student_id`, filesystem paths, vector namespace, or skill ID from untrusted input. Disable public ingestion into global retrieval. Treat PDFs, student messages, and retrieved text as untrusted content (prompt-injection defenses). Keep admin credentials out of runtime worker environments.

## 4. Core data model (first migrations)

Use UUID IDs, timestamps, provenance links, status enum, and a schema version. Prefer indexed relational columns for predicates, JSONB for detailed annotation payloads.

- `users(id, role, created_at)`; `student_accounts(id, user_id, default_curriculum_id, ...)`.
- `programs(id, organization, jurisdiction)`; `curricula(id, program_id, course_code, course_name, level, first_assessment, last_assessment, version, status)`.
- `concepts(id, subject_id, canonical_name)`; `concept_prerequisites(parent_id, child_id)`; `curriculum_concepts(curriculum_id, concept_id, expected_depth)`.
- `documents(id, owner_type [global/student], owner_id, kind, object_key, sha256, source_authority, license_metadata, status, curriculum_id?, cohort_range?, created_at)`.
- `document_pages(id, document_id, page_num, dimensions, image_object_key)`; `document_regions(id, page_id, bbox, kind, crop_key, extraction_confidence)`.
- `assessments(id, student_id, document_id, examiner_id?, curriculum_id?, type, verified_state)`; `questions(id, assessment_id, region_id, prompt_text, concepts, marks_possible)`.
- `student_responses(id, question_id, response_text, ordered_steps JSONB, correctness_status, source_regions)`.
- `marking_observations(id, question_id, marks_awarded, raw_annotation, source_region, explicit_reason?, verified_by?)`.
- `mistake_observations(id, student_id, question_id, error_type, concept_id, evidence_region, interpretation, confidence, review_status)`.
- `fingerprint_observations(id, student_id, question_id, dimension, value, evidence_region, certainty, observed_vs_inferred)`.
- **Student profile is NOT the account record:** `student_learning_profiles(id, student_id, subject_id, current_summary, summary_version, revised_at)` holds evidence-backed *learning identity*, not username or uploaded-file list.
- `student_concept_states(student_id, concept_id, course_id?, level [proficient/developing/etc], trend, evidence_count, uncertainty, updated_at)` for current demonstrated knowledge; `concept_evidence(id, student_id, question_id?, session_id?, concept_id, observed_performance, quality, timestamp)` for history.
- `fingerprint_traits(id, subject_id, code, definition, published_status)` are maintainer-controlled trait definitions (e.g., organization, reasoning transparency, strategy selection, procedural consistency, conceptual flexibility, notation precision, observed self-checking).
- `student_trait_states(student_id, trait_id, course_id?, context_scope, level, trend, evidence_count, uncertainty, last_evaluated_at)` represents a current *inferred, mutable, recomputable* trait state.
- `student_profile_revisions(id, profile_id, revision, summary, algorithm_version, triggering_evidence_ids, created_at)` preserves longitudinal change; `student_interventions(id, student_id, session_id, strategy_id, rationale, observed_outcome, evidence_id)` tracks what coaching was tried and its outcome.
- `student_memory_chunks(id, student_id, source_type, source_id, text, embedding, embedding_version, access_scope)` for optionally embedded mistake narratives, notable session episodes, and profile summaries. NEVER mix into global curriculum chunks or omit authorized-student filter.

- `examiner_hypotheses(id, examiner_id, curriculum_id, rule, context, evidence_count, contradiction_count, status, version)`; `hypothesis_evidence(hypothesis_id, marking_observation_id, polarity)`.
- `assignments(id, student_id, document_id?, curriculum_id, assignment_type, stage, rubric_release_id?, classification_confidence, confirmed_by_user)`.
- `knowledge_chunks(id, document_id, section, page_range, content_text, embedding, parent_chunk_id?, publish_release_id, source_locator)`; metadata filter indexes.
- `teaching_demonstrations(id, created_by_admin_id, concept_id?, scenario, intervention, rationale, provenance)`.
- `teaching_strategies(id, status, skill_id, trigger, steps, evidence_links, admin_approval)`.
- `skill_versions(id, name, version, status [draft/evaluating/approved/published/retired], content_hash, artifact_key, approved_by, published_at)`.
- `knowledge_releases(id, status, manifest_hash, published_at)`; `rubric_versions(id, curriculum_id, assignment_type, cohort_range, source_document_id, criteria JSONB, status)`.
- `tutoring_sessions(id, student_id, skill_release_id, knowledge_release_id, assignment_id?, created_at)`; `tutoring_messages(...)`; `interventions(...)`.
- `evaluation_cases(id, task, expected_result, source, partition [development/holdout])`; `evaluation_runs(id, release_candidate, metric_results, verdict)`; `audit_events(actor_id, action, target, outcome)`.

**Invariant:** no foreign-key/trigger/worker that implicitly promotes `owner_type=student` documents or tutoring messages into global `knowledge_chunks`, `teaching_demonstrations`, or skill inputs. The release pipeline must only accept maintainer-uploaded or explicitly maintained admin materials. Do not auto-copy student examples, even anonymized.

### Student learning profile semantics and retrieval — mandatory

The **student fingerprint** is a longitudinal, subject/context-specific model of *observable work habits and mathematical communication*, not a psychological personality label. Distinguish three layers: (1) immutable/reviewable raw question and interaction **evidence**, (2) recomputable structured **concept mastery and trait states**, (3) concise versioned **narrative summary** for runtime. Example narrative: “Frequently chooses appropriate algebraic methods, but skips written transitions; evidence from 9 of 14 comparable questions. Ask for explicit justification before introducing new procedures.” Maintain `not_observed` when a trait cannot be inferred. Never equate absence of written checking with absence of mental checking.

**Update workflow:** assessment extraction → human-verified or quality-tagged question evidence → append `mistake_observations`, `concept_evidence`, `fingerprint_observations` → recompute only affected concept/trait states (context/course-specific, recency, evidence quality, uncertainty) → generate evidence-linked summary → append profile revision; retain old evidence, mark superseded interpretations. Support whole-profile recomputation after model or taxonomy changes. Student sessions can optionally append their own interaction observations; none may update global traits/skills/dataset.

**Runtime retrieval workflow (not vector-search-first):** authenticate and resolve student server-side → SQL fetch current `student_learning_profiles`, course-specific concept states and trait states, top supported patterns/trends → for relevant topic fetch question-level observations by concept/trait/time → optionally vector-search **that student's** historical narrative chunks (filtered by trusted `student_id`) → retrieve published curriculum + teacher-approved skills → assemble `StudentLearningContext` with provenance and uncertainty. Profile summaries are cached projections, never the source of truth. For exact mark-loss explanation, retrieve the original PDF region. Never allow LLM-supplied student IDs to control access.

**Profile acceptance:** a student scoring well but omitting reasoning must show proficient concept state and weaker communication trait separately; one unusual answer must not override many consistent prior observations; no-evidence trait shows `insufficient_evidence`; the summary links to source evidence and revisions; attempts to read another student's profile or vector history are denied.

## 5. APIs and typed contracts

Initial endpoints (version under `/v1`):

```text
POST /student/assessments/upload
GET  /student/assessments/{id}/status
GET  /student/assessments/{id}/questions
PATCH /student/assessments/{id}/questions/{qid}/corrections
GET  /student/profile
GET  /student/fingerprint
POST /student/assignments/classify
POST /student/tutor/sessions
POST /student/tutor/sessions/{id}/messages

POST /admin/knowledge/upload
POST /admin/knowledge/{id}/process
POST /admin/knowledge/{id}/publish-candidate
POST /admin/annotations
POST /admin/demonstrations
POST /admin/skills/proposals
POST /admin/skills/{id}/evaluate
POST /admin/releases/publish
GET  /admin/evaluations
```

**Every contract** uses Pydantic validation; enforce upload limits, MIME/signature checks, document page limits, ownership and per-action authorization. `POST` operations with expensive work return job ID + status. Never let the model itself choose authorized student scope.

A typed `ResolvedLearningContext` should include: `subject`, `program`, `course`, `level`, `assessment_cohort`, `curriculum_version`, `assignment_type`, `stage`, `topics`, `confidence`, `evidence`, `unresolved_fields`. Prefer a nullable value and confirmation flow over guessed versions.

## 6. Agent topology and permitted data flow

**Use deterministic orchestration for document pipelines.** Split tasks into bounded modules or agents, not an uncontrolled swarm:

1. **Document Extractor:** pages, regions, questions, handwriting, teacher marks; produces structured candidates and uncertainty flags.
2. **Math Validator:** deterministic checks of expressions/equations and LLM-assisted step analysis; flags limitations and domain assumptions.
3. **Mistake Analyzer:** first incorrect step, cause hypotheses, error taxonomy; cite evidence.
4. **Fingerprint Analyzer:** recurring *observable* reasoning/communication patterns, separated by concept/context, with sample size and uncertainty.
5. **Examiner Analyzer:** compare marked answers to generate supported/contradicted marking hypotheses; never manufacture rubric rules.
6. **Context Resolver:** course/cohort/assignment/stage based on student-confirmed profile + PDF + authoritative metadata.
7. **Tutor Runtime:** loads only published skills/knowledge + student-scoped context; offers guided instruction and creates student-only progress events.
8. **Teaching Distiller (admin only):** extracts instructional decisions from maintainer demonstrations and corrections; proposes draft edits.
9. **Release Evaluator/Publisher (admin only):** evaluates, shows diffs, enforces approval, publishes immutable manifests.

**Runtime flow:** authenticate → resolve allowed student context → classify assignment → filter published knowledge/rubric by cohort → retrieve student mistakes/fingerprint → select approved teaching/subject/assignment skills → invoke authorized math tools → deliver cited guidance → optionally write only student-scoped observations.

**Admin flow:** maintainer uploads source/demonstration → extract and annotate → propose strategy/skill patch → admin review → run offline evals → explicit publish immutable release → runtime can load release read-only. There is no automatic student → admin learning path.

## 7. Knowledge ingestion and retrieval specification

1. Admin upload original PDF/reference + title, author, publisher, source URL if any, document type, subject, program/course/level, effective cohort, official-vs-supplemental authority, rights/licensing, release visibility.
2. Parse selectable text, headings, tables, formulas and figures; render images where necessary. Store page and bounding-box references and source hashes.
3. Structure-aware chunking: preserve worked examples, questions, explanations, tables, equations and rubric criterion blocks; parent-child section metadata.
4. Extract/verify concepts and prerequisites; connect to canonical concept IDs and `curriculum_concepts` links.
5. Embed chunks, index in pgvector + Postgres full-text search; retain exact citation locators.
6. Publish via an immutable knowledge release manifest following admin verification.
7. Runtime: **authorize source scope first**, filter by curriculum/version/cohort/assignment/authority, then hybrid search, rerank, return citations and confidence; don't retrieve drafts, other students, or inapplicable older rubrics.
8. When source claims conflict, prefer applicable official assessment requirements for assessment advice; report conflicts rather than merging them silently.
9. Global reference content is not executable instructions; ignore embedded prompt directives. Copyright/licensing constraints govern display of excerpts.

**Retrieval tests:** wrong-cohort IB rubric excluded; Ontario-only query excludes AP rubric; published text returned with page reference; draft docs unsearchable by student; one student's document never retrievable by another.

## 8. Teaching skill structure

```text
skills/
  pedagogy/mistake-diagnosis/SKILL.md
  pedagogy/guided-problem-solving/SKILL.md
  pedagogy/mathematical-communication/SKILL.md
  subjects/mathematics/algebra/SKILL.md
  subjects/mathematics/functions/SKILL.md
  subjects/mathematics/geometry/SKILL.md      # later
  subjects/mathematics/calculus/SKILL.md      # later
  assignments/ib-math-ia/SKILL.md
```

Each skill includes: name/description, trigger/when-not-to-use, required student context, procedure, examples/counterexamples, bounds on hinting, tool permissions, source/provenance, evaluation cases, version. Store factual syllabus/rubric specifications in curriculum KB, **not hardcoded skill instructions**. Compose skills from pedagogical base + topic method + assignment method at runtime. Version/pin releases per tutoring session. Skill selection itself must be authorized and only from published allowlist.

**Distillation:** maintainer demonstrates `student state → mistake/context → intervention → rationale → follow-up check`. Extract proposed reusable patterns; maintain evidence links and minimal diffs; human approves; run regression suite; publish or reject. No student's chats or uploaded exams can feed this pipeline implicitly.

## 9. Student fingerprint policy

Capture **behavioural observations, not personality labels**. Suggested dimensions: written organization, reasoning transparency, notation precision, procedural consistency, strategy selection, conceptual flexibility, explicit self-correction, observable verification, response completeness. For each dimension store `observed / inferred / not_observed`, evidence, task complexity, topic, count, time, confidence. Aggregate across comparable tasks; distinguish correct solution with poor presentation from conceptual or arithmetic error. Don't infer speed/confidence from static PDFs. Explain patterns as *tentative and improvable*, and show supporting examples.

## 10. Examiner hypothesis policy

Distinguish explicit marks, teacher annotation, mathematical correctness, and inferred cause of deduction. Build hypotheses only with multiple examples or direct explicit feedback; keep contrary cases and scope to examiner/course/task/cohort. Provide predicted marking ranges only with uncertainty; label estimated marks as unofficial. Never claim exact examiner intentions or penalize students based solely on an unverified rule.

## 11. Math and assignment capabilities

Use an extensible subject capability interface:

```python
class SubjectCapability(Protocol):
    def classify_concepts(self, content: str) -> list[str]: ...
    def validate_solution(self, question, solution) -> ValidationResult: ...
    def diagnose_errors(self, question, steps) -> list[ErrorObservation]: ...
    def get_prerequisites(self, concept_id: str) -> list[str]: ...
```

Start with `MathCapability`: SymPy expressions/equations; domain restriction checks, extraneous roots, answer completeness; graph/function checks where possible. Future `PhysicsCapability` adds units/dimensional analysis and physics modelling; `ChemistryCapability` adds equation balancing and stoichiometry. No science implementation in MVP.

**Assignment classifier:** student-confirmed course + content + headings + rubric references → `ResolvedLearningContext`; detect `ordinary_homework`, `marked_test`, `exam`, `IB_math_IA`. For IB IA, retrieve correct **approved rubric version by cohort** and load IA support skill. Classify stage (topic selection, modelling, derivation, analysis, reflection, draft review) with uncertainty and optional confirmation. Do not treat self-described uploads as official rules.

## 12. Phased tickets for coding agents

Each task is independently reviewable. Implement in order; a phase is complete only when its gate passes. Suggested IDs facilitate issue tracking.

### Phase 0 — Foundation and trust boundaries

- **P0-01** Scaffold monorepo, lint/type/test commands, Docker Compose, local Postgres/pgvector/fake-gcs-server/LiteLLM/Redis/Firebase emulator. **Done:** clean clone launches API/web/db/storage with health checks.
- **P0-02** Auth and admin/student RBAC; explicit student-scoped repository methods. **Done:** integration tests deny cross-student access and admin routes for students.
- **P0-03** Separate service credentials for runtime and admin knowledge writes; audit events and safe logging. **Done:** runtime DB role fails to mutate draft/published global tables.
- **P0-04** Initial schema migrations and typed contracts from §4–5. **Done:** migration up/down tests, relation and isolation constraints.
- **P0-06** LiteLLM Proxy aliases, provider-capability registry, Pydantic-normalized ModelGateway; test text/tool/structured/image capabilities and fallback/explicit refusal. **Done:** remap tutor from OpenAI to DeepSeek by config only; vision routes only to supported model; app and profile DB code unchanged.
- **P0-07** GCS ObjectStorage and JobDispatcher adapters (fake-gcs-server/Celery in Compose; GCS/Cloud Tasks/Jobs contracts for cloud). **Done:** local upload/read/delete survives restarts; idempotent retries and real-GCS staging test plan recorded.
- **P0-05** Upload safeguards and private object storage. **Done:** file spoofing/oversize rejected; raw PDFs not publicly accessible.

**Phase gate:** Security boundaries tested before agent tools exist.

### Phase 1 — Annotation studio and golden dataset

- **P1-01** Student PDF upload job + page rendering and PDF viewer with page coordinates. **Done:** opens multi-page math test, locates individual question regions.
- **P1-02** Admin annotation UI for question, response, marks, source box, first error, observed behaviours, teaching intervention/rationale. **Done:** save/edit/retrieve and link back to image crop.
- **P1-03** Annotation export/import (`JSONL`, schema-versioned); sanitize/consent strategy. **Done:** 30–50 manually annotated questions available for dev, with separate held-out examples.
- **P1-04** Evaluation harness comparing predicted structured records against ground truth. **Done:** repeatable command returns field-level precision/recall and mismatch examples.

**Phase gate:** A human can fully annotate a question without LLMs; dataset provenance preserved.

### Phase 2 — Document and mathematical analysis

- **P2-01** Async extraction worker: text/rendering → vision extraction → question segmentation → typed candidates. **Done:** stable region/page IDs, confidence/review states.
- **P2-02** Teacher marking parser and mark-question alignment. **Done:** ambiguous markings queued for review, no silent mark fabrication.
- **P2-03** SymPy-backed validator and step analyzer. **Done:** detects selected correct, incorrect, incomplete, and domain-sensitive algebra cases.
- **P2-04** Error taxonomy classifier with evidence and earliest wrong step. **Done:** field-level evaluation on held-out annotated questions.
- **P2-05** Review/correction UI. **Done:** user corrections retained distinctly from raw extraction with audit history.

**Phase gate:** Uploaded marked PDF becomes evidence-linked, correctable assessment objects with baseline accuracy report.

### Phase 3 — Student and examiner intelligence

- **P3-00** Implement student learning-profile tables, canonical trait definitions, immutable observation provenance, profile revisions and `StudentLearningContext` retrieval contract. **Done:** account info does not substitute for learning fingerprint; SQL retrieval by authenticated identity works without embeddings.
- **P3-01** Student mastery summaries by concept and time. **Done:** distinguish observed evidence from inferred mastery.
- **P3-02** Fingerprint analyzer and trend UI. **Done:** no personality labels, no inference from absent data, clickable source evidence.
- **P3-03** Examiner marking hypothesis engine. **Done:** hypotheses cite supporting and contradicting marking examples, show provisional status.
- **P3-05** Incremental evidence-driven recomputation, context-specific trait aggregation, uncertainty, and optional student-only historical vector retrieval. **Done:** isolated per-student search, `insufficient_evidence`, controlled revisions, and no global-index write verified.
- **P3-04** Student report page: mistakes, presentation, fingerprints, confidence, recommended areas. **Done:** separate conceptual gaps and communicating reasoning.

**Phase gate:** Multiple assessments yield coherent student-only longitudinal reports; no global KB changes.

### Phase 4 — Curriculum KB and context intelligence

- **P4-01** Admin-only document upload/classification/version/rights metadata UI. **Done:** official vs supplemental and draft vs published clearly distinct.
- **P4-02** Structure-aware chunking, embedding, pgvector/FTS retrieval with source locators. **Done:** retrieval returns exact page/section links.
- **P4-03** Publish immutable knowledge manifest. **Done:** runtime reads only published corpus; draft invisible.
- **P4-04** Curriculum, cohort, and assignment resolver for Ontario G11 Functions + IB Math AA SL IA. **Done:** handles ambiguous cases without invented rubric.
- **P4-05** Citation- and filter-based RAG integration. **Done:** wrong course/cohort docs excluded in adversarial retrieval tests.

**Phase gate:** Same mathematical question produces context-appropriate sources for Ontario vs IB; IA recognized with correct source version.

### Phase 5 — Published skills + student TutorBot

- **P5-01** Skill artifact format, validator, published-only registry, per-session release pinning. **Done:** forbidden draft skills cannot load.
- **P5-02** Hand-author 3 skills: guided problem solving, mistake diagnosis, mathematical communication; plus math-functions and IB-IA assignment procedures. **Done:** instructions include triggers, constraints, evals.
- **P5-03** Tool registry and typed runtime context assembler. **Done:** student toolset contains no admin/write-global functions.
- **P5-04** Tutor session workflow: context → profile/fingerprint → relevant knowledge/skills → deterministic math check → guided feedback. **Done:** result cites student evidence and source passages.
- **P5-05** Student-scoped session history and optional profile evidence updates. **Done:** all writes limited to the current student, no auto-distillation.

**Phase gate:** One Ontario test and one IB IA receive different justified coaching from the same base tutor, using approved skills.

### Phase 6 — Maintainer-only skill distillation

- **P6-01** Teaching demonstration capture UI (scenario, response, why, fallback, understanding check). **Done:** explicit admin-only data source.
- **P6-02** Extract generalized strategy proposals linked to maintainer evidence. **Done:** propose not publish; duplicates/conflicts flagged.
- **P6-03** Skill diff editor, approve/reject, changelog and release manifest. **Done:** maintainer approval mandatory.
- **P6-04** Regression eval gate and rollback. **Done:** harmful release blocked or rolled back; existing sessions pinned.

**Phase gate:** A maintainer correction can improve a published skill through controlled review; student actions cannot invoke this pipeline.

### Phase 7 — Reliability, operations and expansion readiness

- **P7-01** Full E2E flows, upload failures/retries, latency/cost dashboards, tracing scrubbed for PII.
- **P7-02** Threat model: prompt injection via PDFs, broken object-level authorization, unsafe retrieval, file parsing, leaked minors' data; penetration-style tests.
- **P7-03** Student data export/delete/retention and consent controls; licensing review for textbooks.
- **P7-04** Add another math unit/course using configuration and plugins, not duplicated agent code.
- **P7-06** GCP staging deployment using Cloud Run, Cloud SQL/pgvector, private GCS buckets, Firebase Auth, Secret Manager, Artifact Registry; compare local emulator with real IAM/signed URLs. **Done:** cloud smoke test and DB migration test pass, no public bucket objects.
- **P7-07** Provider substitution regression: switch `tutor-reasoning` from one provider to another without business-logic changes; compare tool/JSON/math/pedagogy evals, version and cost trace. **Done:** failures and capability gaps surfaced explicitly, embedding index intact.
- **P7-05** Document integration interfaces for future AP/physics/chemistry; no implementation needed yet.

**Phase gate:** security, eval, performance and operations checklists satisfied for pilot users.

## 13. Evaluation and release gates

Maintain **development vs held-out** question/teaching scenarios; don't let retrieved examples contaminate held-out tests. Evaluate:

- **Extraction:** question segmentation, handwriting/notation, grade annotations and mark linking.
- **Math:** factual correctness, equivalent expressions, missing roots, extraneous solutions, first incorrect step.
- **Fingerprint:** precision of documented claims, evidence traceability, abstention on ambiguous cases.
- **Examiner inference:** predicted marks/reasons on withheld samples versus rubric-only baseline; coverage and contradictions.
- **Curriculum/assignment:** classification accuracy, rubric/cohort correctness, citation validity, no wrong-course leakage.
- **Teaching:** diagnosis quality, intervention alignment with maintainer-labeled scenarios, age appropriateness, non-revelatory hint progression, transfer learning checks when available.
- **Security:** student isolation, no admin tool exposure, no student-to-global KB write or retrieval path, injection resistance.

**Release policy:** maintainer reviews metrics and representative failures before approval. Set concrete numerical thresholds after baseline data; do not pretend arbitrary LLM confidence scores are calibrated. On failure, mark incomplete and record counterexamples.

## 14. Operational workflows and observability

- Every extraction/analysis job is idempotent and retries safely; include document/content hash and model/prompt/parser version.
- Emit task states `queued → processing → review_required | complete | failed`; capture structured errors without logging raw student answers by default.
- Version prompts, model IDs, skills, knowledge manifests and tool outputs sufficiently for reproducibility; redact sensitive content from traces.
- Retain originals, annotations, model-generated candidates, and human corrections as distinct records; support reprocessing after model upgrades.
- Provide cost guardrails: max pages, batch quotas, bounded retries, model-selection policy, ingestion deduplication, caching of immutable source processing.

## 15. First four engineering sprints (milestone-oriented, not time promises)

1. **Sprint A:** P0 all + P1-01/P1-02. Demonstrate secure upload, page viewer and a question annotation saved to DB.
2. **Sprint B:** P1-03/P1-04 + P2 all. Demonstrate one fully extracted, corrected, evidence-linked marked quadratic test.
3. **Sprint C:** P3 all + P4-01..P4-03. Demonstrate student fingerprint trends and published textbook/curriculum retrieval, with isolation tests.
4. **Sprint D:** P4-04/P4-05 + P5 all. Demonstrate context-aware Ontario/IB tutoring and correct IA recognition. Implement P6 only after core quality is measurable.

## 16. Instructions to the next implementation agent

1. Read this entire specification, inspect the repo, then produce a **short phase-specific plan** and work on the **earliest incomplete ticket**. Never assume earlier tickets are implemented without verifying.
2. Before coding, write/update an ADR only for materially new decisions; preserve the separation of global and student knowledge.
3. Implement the smallest end-to-end change; include DB migration, API contract, tests, and UI when the ticket calls for them. Prefer runnable code over placeholder scaffolds.
4. Use strong types, composable modules, explicit permissions, dependency injection, and tests that simulate malicious students and wrong-curriculum retrieval.
5. For each ticket, report: changed paths, commands run, tests passed/failed, screenshots/trace if relevant, migration impact, unresolved risks, next ticket.
6. If external official rubric sources are not yet supplied or verified, build metadata/version plumbing and use **clearly labeled fixtures**; do not manufacture official requirements.
7. Never use real student data in fixtures, public commits, traces, or evaluation artifacts without appropriate protection and authorization.
8. Never bypass admin approval to satisfy a demo. A prototype may use locally approved seed skills, but must preserve the release/permissions boundary.
9. If something is uncertain, record it explicitly as `unknown`/`review_required`; do not guess at grading rationales or profile traits.
10. Stop at each phase gate and deliver a concise acceptance-test report. Next agent picks up from the tracker below.

11. At the end of each implemented step/phase, commit the completed changes with a short descriptive message and push to GitHub. Stop for user review before starting the next step.

## 17. Progress tracker (agents update this file as work completes)

| Phase | Status | Evidence / PR / commit | Blockers |
|---|---|---|---|
| 0 Foundation | Complete locally — all P0 tickets approved; local security gate passed | [P0-05 evidence](docs/reviews/P0-05.md) | Local security checks pass; cloud staging gates pending |
| 1 Annotation studio | P1-01/P1-02 approved; P1-03 implemented, awaiting review | [P1-03 refinement](docs/reviews/P1-03-refinement.md) | Human label review and P1-04 pending |
| 2 PDF + math analysis | Not started | | |
| 3 Student/examiner intelligence | Not started | | |
| 4 Curriculum + RAG | Not started | | |
| 5 Tutor runtime | Not started | | |
| 6 Admin distillation | Not started | | |
| 7 Security + pilot readiness | Not started | | |

### Ticket review checkpoint

- **P0-01:** Implemented, verified, and approved by the user. See [acceptance report](docs/reviews/P0-01.md).
- **P0-02:** Implemented, verified, and approved by the user. See [acceptance report](docs/reviews/P0-02.md).
- **P0-03:** Implemented, verified, and approved by the user. See [acceptance report](docs/reviews/P0-03.md).
- **P0-04:** Implemented, verified, and approved by the user. See [acceptance report](docs/reviews/P0-04.md).
- **P0-06:** Implemented, verified and approved. See [acceptance report](docs/reviews/P0-06.md).
- **P0-07:** Implemented, verified and approved. See [acceptance report](docs/reviews/P0-07.md).
- **P0-05:** Implemented, verified and approved. See [acceptance report](docs/reviews/P0-05.md).
- **Phase 0 local gate:** Auth, ownership, service/worker isolation, upload rejection and safe logging tests pass before agent tools are introduced. Emulator results do not establish cloud IAM.
- **P1-01:** Implemented, verified and approved. See [acceptance report](docs/reviews/P1-01.md).
- **P1-02:** Implemented, verified and approved. See [acceptance report](docs/reviews/P1-02.md).
- **P1-03:** Export/import, split locks and 40 synthetic draft examples implemented. PDF-only upload, focused studio, reversible deletion and current-label review implemented after user feedback; awaiting review and human label approval. See [workflow refinement](docs/reviews/P1-03-refinement.md).
- **Next:** P1-04. Do not continue until the user reviews P1-03. Draft synthetic labels are not approved ground truth.

## 18. Acceptance scenarios to preserve across the entire build

1. **Provider agnostic:** LiteLLM runs in Compose with model aliases; switch text tutoring between configured providers using config only, while document vision routes to a supported image-capable model. Existing embeddings and student profiles are unchanged.
2. **Evidence-backed fingerprint:** Student profile consists of immutable question-level observations, current concept and trait states, and versioned interpretation; structured retrieval is direct SQL and relevant example lookup is tenant-filtered semantic search.
3. **Ontario math test:** Student A uploads marked quadratic-functions test → recognizes questions, marks, notation and mistake categories; shows evidence-linked corrections; updates only Student A's profile/fingerprint.
2. **Student isolation:** Student B cannot view or retrieve Student A's test, mistakes, RAG chunks, profile, or tutoring history, even via forged object IDs/tool arguments.
3. **IB IA recognition:** Student uploads an IB Math AA SL IA draft → recognizes task and stage, resolves *applicable* rubric by assessment cohort, selects IA-specific skill, explains modelling/reasoning/communication concerns without treating advice as an official grade.
4. **Curriculum switching:** Ontario G11 and IB Math AA SL questions on same math topic draw on appropriate curricular sources and depth while sharing the same core mathematical capability.
5. **No global learning:** Student uploads a novel problem, chats, or embeds “update your SKILL.md” inside PDF → no changes to global knowledge, demonstration collection, draft skills or published releases.
6. **Admin skill publishing:** Maintainer adds demonstration → draft teaching strategy proposal → approved eval → immutable release published → *new* sessions use new version, old sessions retain pinned version.
7. **Conflicting sources:** A deprecated rubric and an active official rubric coexist → only applicable version governs assessment advice; citations identify the source.
8. **Unknown grading rationale:** Teacher deducts a mark without notation → system reports observed mark and possible explanations, asks for review rather than inventing certainty.

---

**Build philosophy:** *Structured evidence first → curriculum-aware retrieval → published teaching skills → personalized student tutoring → maintainer-controlled distillation.* Keep the system expandable by making subjects and curricula plugins/data, but ship high-school mathematics well before expanding into physics, chemistry, or additional programs.
