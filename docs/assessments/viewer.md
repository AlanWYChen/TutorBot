# Student page viewer

Sign in as a student and choose a PDF in **Your assessments**. Confirm the kind of
work (or leave **Not sure yet**), then upload. The server computes actual page count;
the browser supplies byte size and SHA-256. Existing optional client page counts
still must match. Limits remain 25 MiB and 200 pages; native rendering also has
bounded memory, time, pixels and output bytes. A particularly large/complex PDF
can fail rendering even if its upload validates.

The original, pages and navigation hints stay private to the student. Recent
assessments lists the latest twenty retained uploads; reopening an older upload
prepares its pages if needed. Page controls, fit-width/zoom, tentative numbered
prompt hints, drag selection and keyboard coordinates locate areas on the canonical
page image. The origin is top-left; x/y/width/height use the persisted rendered pixel
space, independent of CSS zoom or window width. Numbered hints sort numerically.
Scanned pages can be selected manually without any invented text or question hints.

Selections are temporary. Candidate hints are not verified questions or complete
answer boxes; analysis, saved/correctable annotations, crops, OCR and grading arrive
in their own tickets. Do not treat renderer success as mathematical verification.
The current viewer uses server raster pages; text search/selection is not supplied.

## Private API

- `GET /v1/student/assessments`: recent owned assessments.
- `POST /v1/student/assessments/{id}/render`: idempotent page preparation.
- `GET /v1/student/assessments/{id}/pages`: canonical dimensions/rotation/version and
  tentative coordinate hints, without storage paths or object URLs.
- `GET /v1/student/assessments/{id}/pages/{number}/image`: authenticated PNG page.
- Existing upload/status/original-download routes retain their ownership checks.

The web `/api/assessments` proxy forwards only these fixed paths. Anonymous calls
return 401, wrong-role calls 403, and another student's IDs 404. Parent tombstones
hide originals and derivatives. No original/PNG public bucket URL is returned.
Production bucket IAM, complete parser containment and original/derivative lifecycle
cleanup still require the [cloud staging gate](../storage-jobs/operations.md).

## Review and verification

`make viewer-integration` sends a generated two-page rotated/cropped PDF through the
actual web proxy, Firebase identity, APIs, GCS and worker. It verifies dimensions,
numbered hints in order, duplicate preparation, originals, PNG privacy, inherited
retention, owned lists and source deletion. Test artifacts are physically removed;
scoped evidence metadata remain. Unit tests also cover image-only pages, rendering
limits, missing client page count and resize/zoom/reverse-drag coordinate mapping.

For a visible local review, use the disposable account `student-a@example.test`
with demo password `TutorBot-local-123!` and
[synthetic-quadratics.pdf](../fixtures/synthetic-quadratics.pdf). The browser acceptance
check uploads this synthetic fixture and leaves it available for review. Reloading
signs out because authentication is kept in memory; signing in again reopens owned
assessment history. No actual student documents are used by the tests.

Primary rendering reference: [PyMuPDF page coordinates and rotation](https://pymupdf.readthedocs.io/en/latest/page.html).
