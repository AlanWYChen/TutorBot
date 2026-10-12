# PDF upload safeguards

Current product scope is **tests/exams**. The student handler stores one PDF and
creates an assessment; broader `assessment_type` values do not implement separate
assignment requirements and student-work uploads. The future assignments/projects
workflow needs distinct document roles linked to an assignment and versioned,
stage-aware reviews. See [extension plan](../../TUTORBOT_IMPLEMENTATION_PLAYBOOK.md#scheduled-assignmentsprojects-workflow-and-architecture-extension).

## Endpoints

| Service | Upload | Status | Authenticated original |
| --- | --- | --- | --- |
| Runtime | `POST /v1/student/assessments/upload` | `GET /v1/student/assessments/{resource_id}/status` | `GET /v1/student/assessments/{resource_id}/file` |
| Maintainer | `POST /v1/admin/knowledge/upload` | `GET /v1/admin/knowledge/{resource_id}/status` | `GET /v1/admin/knowledge/{resource_id}/file` |

Send a Firebase bearer token in the Authorization header and a client-generated UUID
in `Idempotency-Key`. Use multipart/form-data with exactly `file` and `metadata`:
`file` has its original `.pdf` filename and `application/pdf` MIME; `metadata` is a
JSON text part. No student ID, object path, service mode, publish status or job action
is accepted from the client. Neither service mounts the other service's routes.

Student metadata uses `AssessmentUpload`: filename, media_type, actual size_bytes,
lowercase SHA-256, optional page_count, assessment_type and optional published curriculum_id.
Maintainer metadata uses `KnowledgeUpload`, with title, author, publisher, kind,
source_authority and nonempty license_metadata; source_url, curriculum_id and
cohort_range are optional. A source URL is stored as provenance and never fetched.
The broader metadata catalog anticipates image types; these upload handlers accept
PDFs only. The mounted API OpenAPI describes the multipart envelope and UUID header.

Example student metadata (replace the digest/size with values for the synthetic PDF):

```json
{
  "filename": "synthetic.pdf",
  "media_type": "application/pdf",
  "size_bytes": 1234,
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "page_count": 2,
  "assessment_type": "marked_test"
}
```

A valid upload returns 202 with schema_version, job_id, resource_id and status.
For students resource_id is the assessment ID; for maintainers it is the document
ID. Repeating the same idempotency UUID and identical metadata/bytes returns the
same IDs. Reuse with different content/metadata or a deleted upload returns 409.
Retry a transient 503 with the original key. A successful verification job means
the stored bytes match their manifest; it does not mean extraction or marking is
complete. Student status retains `verified_state=unverified`; maintainer status
explicitly reports `processing_kind=storage_verification`.

## Policy

- Maximum PDF: 25 MiB (26,214,400 bytes), 200 actual pages. Multipart framing has
  a separate 64 KiB allowance. The streamed limit applies without Content-Length
  and when the declared length is false. Compressed HTTP request bodies refuse.
- Require consistent filename, PDF MIME, PDF signature, final EOF, actual size,
  checksum and actual page count. Reject malformed/repaired/password-protected
  PDFs, attachments, XFA, JavaScript and automatic/launch/external action features.
  Originals stay byte-for-byte intact; the service never silently strips evidence.
- At most two active uploads per API process. Idle receives expire after ten seconds,
  and total receives after sixty; native inspection has its own memory/CPU/deadline.
- Only the owning student can download/status its assessment. Unknown or another
  student's ID returns 404; missing sign-in returns 401 and the wrong role 403.
  Download responses are attachments with a fixed safe filename and no caching.
- Maintainer sources remain draft in teaching-private. A student upload cannot set
  official source authority or enter global sources, teaching examples or retrieval.
- Rejection occurs before a storage write or domain/job registration. Safe errors
  distinguish 400 invalid multipart, 408 timeout, 413 size, 415 unsupported transport/
  type, 422 invalid PDF/metadata, 429 capacity, 409 conflicting retry and 503 service
  failure. Parser output and user metadata never appear in error details or logs.

The local emulator is reachable only inside the Compose network and cannot prove
GCS IAM or signature security. API downloads do not rely on emulator access controls.
Real bucket public-access prevention, service identities, signing, orphan cleanup
and retention remain covered by the [staging gate](../storage-jobs/operations.md).
P1-01 now supplies student upload UI, server-derived page count and private rendering;
OCR and tutoring remain later work.

## Verification

`make upload-integration` sends generated synthetic PDFs through real Firebase
sign-in, runtime/maintainer APIs, PostgreSQL and GCS. It checks owner/role access,
retry reuse, safe failure cases, private originals, durable worker completion,
tombstones and maintainer draft status. Fixtures' raw objects are removed afterwards;
scoped tombstone/audit metadata remain for retry and evidence checks. CI also runs
the existing service-security and storage/job suites.

[PyMuPDF document inspection APIs](https://pymupdf.readthedocs.io/en/latest/document.html)
and [Starlette bounded multipart parsing](https://www.starlette.io/requests/)
provide the parser interfaces used here; application limits and refusal policy are
defined and tested by this repository.
