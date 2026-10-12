# Annotation datasets (P1-03)

Maintainers create a named, versioned dataset in the annotation studio. Add a saved
annotation with its current revision, split, label author and explicit rights,
deidentification and crop-review attestations. Adding creates an immutable snapshot;
later annotation edits do not rewrite it. Correct a snapshot by editing the source
annotation and adding the new revision to a new dataset version. Dataset names and
versions are unique per maintainer. Each dataset supports at most 50 cases.

Open a case to compare the source crop with its pinned labels. The explicit **I
reviewed these labels — approve case** action appends a local review. Preview exports
include drafts; evaluation exports include only locally approved cases. Assistant
labels keep their `assistant_draft` authorship even after a human review. Importing an
approved transport record always resets its local state to draft.

## JSONL v1

Each UTF-8 line is a `CaseRecord` (`schema_version: 1`, `record_type:
annotation_case`): opaque case UUID, development/holdout partition, label origin/state,
source SHA-256, page number, pixel bbox, renderer version, crop SHA-256, pinned
annotation revision, structured labels and safety attestations. Nested records are
also versioned. Unknown fields/versions, duplicate keys/IDs and malformed labels
refuse. No user IDs, filenames, storage paths, URLs, raw PDF or image bytes are
exported. Limits: 50 records, 128 KiB per line and 5 MiB per archive.

Development and held-out material are exported separately. A global immutable
registry locks both source PDF hash and normalized question-text hash to one split;
response variants of the same question cannot cross splits. Normalization uses Unicode
NFKC, case folding and collapsed whitespace. This catches exact normalized duplicates,
not paraphrases or semantic near-duplicates. Review those when curating evaluation sets.
Held-out source documents, pages, regions and chunks remain absent from published
runtime views even if publication flags change. Teaching demonstrations remain
maintainer-only, with no runtime view or grants.

Import requires the same source PDF already uploaded and rendered by the signed-in
maintainer. Its hash, renderer, page bounds and recomputed crop hash must match.
There is no external source download or student-source import path. The archive is
validated before writes; database changes are atomic and unchanged retries reuse
cases. External private crops written before a failed commit can remain orphans;
storage lifecycle reconciliation remains an operational requirement.

## Sanitization and consent

Use synthetic or licensed sources, or maintainer material with documented consent.
Record an opaque `consent-*` reference for consented material; keep consent documents
in your authorized external records, outside JSONL. Never put student names or other
identifying details in labels or crops. Remove identifying information from a source
before uploading it, then annotate the sanitized version. Scanner refusals require
correction rather than silently changing mathematical content.

The text scanner blocks recognizable email addresses, web URLs and long phone-like
numbers. It is a guard, not a complete PII detector: names, handwriting, faces and
other identifiers require manual text/crop review. Rights and privacy attestations
are required on add and reconfirmed for an entire import. Privacy review does not
approve mathematical labels. Sources and case evidence remain private; exporting
JSONL is an explicit maintainer action. Source tombstones revoke crop/export access.

## Local synthetic review pack

[The v1 pack](synthetic-v1/README.md) contains 40 assistant-authored proposals: 30
development and 10 held-out questions across ten quadratic error families. These are
review materials, not human-approved gold labels. `make seed-dataset` prepares the
matching private sources, annotations and dataset locally; it never approves labels.
The command is restricted to local Firebase/storage emulators. Exported previews
remain labelled draft. Approval of an implementation step is distinct from approval
of each mathematical label.

The corpus is intentionally small and templated; it does not measure handwriting,
OCR, marking ambiguity, multi-step reasoning or generalization to real learner work.
Its synthetic 1/2 marks are review proposals rather than an official marking scheme.

## API

All paths are under `/v1/admin/studio/datasets`, mounted only on the maintainer API:

| Method/path | Purpose |
| --- | --- |
| GET / | List owned datasets and counts |
| POST / | Create a named version with a client UUID |
| GET /{id}/cases | List live-source snapshots and local approval states |
| POST /{id}/cases | Pin an owned annotation revision as a draft case |
| GET /{id}/cases/{case}/crop | Authenticated private source evidence |
| POST /{id}/cases/{case}/review | Append explicit local label approval |
| GET /{id}/export?partition=development\|holdout&preview=true\|false | Separate preview or approved JSONL |
| POST /{id}/import | Import JSONL with privacy/rights reconfirmation |

The web proxy admits only these fixed paths, validates export query options, bounds
request bodies and forwards verified bearer authentication without client scope
headers. Responses disable caching; audit events store route templates, never labels
or archive bodies. No dataset table or draft record is granted to runtime or workers.
