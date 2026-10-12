# Maintainer annotation studio

Sign in as the maintainer. Upload an authorized reference or synthetic teaching
example with title, author, publisher and a license/permission note. The PDF uses
the same safeguards as student upload; its actual page count is derived server-side.
The studio cannot import or access a student's private account/PDF. All sources
and annotations remain draft and excluded from runtime retrieval.

Open a source, choose its page, then select a source box by dragging or entering
coordinates. Include the relevant question, response and marking evidence in that
area. Record question/response text, awarded/possible marks, first error, observed
work habits, intervention and rationale. Behaviour notes require an observed or
inferred status; empty evidence remains not observed. Record visible work rather
than personality, speed or confidence claims. An intervention requires rationale.

Saving creates a private PNG crop tied to source SHA-256, page, pixel box and renderer
version. Reopen a saved row to retrieve its fields and crop. Editing changes the
notes and creates a new revision; the source box/crop stay fixed. Choose **New
annotation** for a different area. Conflicting saves refuse rather than overwrite.
**Reload annotations** refreshes saved rows while leaving current form edits intact;
select a row to load its current revision. Create retries with unchanged fields reuse
the existing annotation. Edits use optimistic revision checks; after an interrupted
edit, reload to determine whether the prior save committed.

## Private API

The maintainer-only `/v1/admin/studio` group supplies owned source listing, render
preparation, page manifests/images and annotation list/create/edit/crop endpoints.
Create uses `AnnotationCreate` with a client UUID, page number and bounding box.
Edit uses `AnnotationEdit` with `expected_revision`; source fields are not editable.
The web `/api/studio` proxy routes only to the separate maintainer API. JSON annotation
bodies are limited to 96 KiB and crop creation to two active operations. Crop responses
are authenticated PNGs with no-store/nosniff; no public object URLs or tokens appear
in image paths. Students/anonymous users refuse before annotation-body processing.

`annotation_revisions` keeps append-only payload history. Current structured fields
are also retained in the original annotation/rationale columns for compatibility.
The exported contract catalog includes the actual structured studio operations;
planned legacy annotation contracts are not mounted as placeholder handlers.

## Review fixture and tests

`make studio-integration` runs synthetic source upload/render/save/edit/retrieve,
exact crop dimensions, retry reuse, stale-edit rejection, student/anonymous denials,
source bounds, source deletion, revision history and published-view exclusion.
Publication flags deliberately toggled in the test cannot expose annotation regions.
Fixture bytes are cleaned up; audit/provenance/revision metadata remain.

For visible review, `python -m scripts.seed_studio_example` inside a local API checks
container provisions an independently generated marked example. It is local-only,
contains no student data and does not read student tables. The browser check leaves
this example and its revision-2 annotation available for review using the disposable
maintainer account. This is a UI fixture, not a pedagogical development/holdout dataset.

Dataset export/import, consent/sanitization and verified golden labels are P1-03.
No automatic model analysis, knowledge publication or student-profile changes occur.
Real-cloud IAM, complete parser containment and original/derivative/crop lifecycle
cleanup remain the documented staging gates.
