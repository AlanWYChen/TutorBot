# ADR 0009: Private maintainer annotation studio

Status: implemented for P1-02; approved by the user.

The studio operates only on sources uploaded by the verified maintainer into
teaching-private. It cannot read student accounts, private PDFs or assessment
records, and there is no student-to-maintainer copy path. Source metadata retains
explicit title/author/publisher/rights provenance; source uploads and annotations
remain draft. No models, profile updates, distillation or publication run here.

Reuse canonical page rendering in the separate admin worker/schema/bucket. Its
additional grants permit only page/region and derived-manifest inserts/reads;
student data and unrelated global teaching tables remain unavailable to the worker.
Both render pipelines retain generation checks, resource bounds, lease fencing,
atomic page publication and inherited source retention.

Store structured question/response/marks/first-error/behaviour/intervention/rationale
fields in maintainer annotations. Behaviour status explicitly distinguishes observed,
inferred and not observed. Validate finite numeric marks, possible-vs-awarded limits,
source bounds, bounded text, observation notes and intervention rationale. Read the
page/crop through server-resolved owner scope. Native crop generation is credential-
free, resource-bounded and limited to two concurrent create operations per API.

A client UUID gives creation a stable document-bound identity. Equal creation retries
reuse the annotation and crop; conflicting retries refuse. Keep the original source
box/region/crop, source SHA-256 and render version fixed through edits. A revision
precondition prevents silent concurrent overwrites. Every saved revision is appended
to a separate table with a mutation-denial trigger and restricted grants. Legacy text
annotations are retained but not silently reinterpreted as structured records.

Migration 0007 adds private maintainer rendering, annotation fields and revision
history, removing runtime's annotation view. Migration 0008 also excludes annotation
source regions from published retrieval regardless of status flags. This preserves
ordinary published document regions without exposing working annotation crops.

The proxy admits only fixed maintainer paths and bounded bodies, forwarding bearer
authorization without client scope headers. Errors/logs omit note content and object
paths. Crop responses disable caching; browser blob URLs are revoked and requests
aborted on unmount/sign-out. An external crop written before a failed DB commit has
no API path; identical retry can recover it, with orphan/lifecycle reconciliation
remaining a cloud staging control.

This step supplies editable working annotations and linked crops. Dataset splits,
JSONL import/export, consent/sanitization, verified labels and evaluation/publishing
are later gates. A saved human annotation is not an automated grading judgment.
