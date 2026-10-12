# Maintainer annotation studio

Sign in as the maintainer. The studio has two tabs:

- **PDFs & annotations:** choose a PDF and upload it. Title, author, publisher and
  permission fields are no longer required in the UI. Select a PDF, page or annotation
  and edit its labels. Use **New annotation** and select a region for a new question.
- **Review labels:** choose a collection/question, inspect its crop, edit labels and
  save. The latest saved labels appear immediately, including edits made from the PDF
  tab. Approve only after saving. Collection membership and JSONL tools are collapsed.

The narrow interface uses selectors; desktop layouts use sidebars. Revision numbers
are hidden. History and stale-save protection remain internal. Unsaved changes block
navigation and approval until you save or discard them. Teaching suggestions and
observation details are available in a collapsed section.

**Delete PDF**, **Delete page** and **Delete annotation** remove the item from the
active library/viewer, reviews and exports; **Undo deletion** restores it. Page
removal preserves original page numbering and the original PDF for evidence/Undo.
These controls do not rewrite or physically purge original source bytes. Existing
private retention and lifecycle cleanup still apply.

Upload safeguards and ownership are unchanged. Personal metadata does not assert
publication permission. Dataset transfer still requires rights/privacy review.
Saving creates a private PNG crop tied to source SHA-256, original page, pixel box
and renderer. Editing changes labels while the original box/crop stays fixed.
A teaching suggestion requires rationale, and observation notes distinguish visible
work from tentative interpretations. Student-private sources remain inaccessible.

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

### Current workflow and removal API

`DELETE /sources/{document_id}`, `DELETE /sources/{document_id}/pages/{number}` and
`DELETE /sources/{document_id}/annotations/{annotation_id}` return 204 for owned
items. POST the corresponding path with `/restore` appended to undo. Deleted parents
make their page/annotation/crop routes unavailable. JSONL cases resolve current
labels and current-revision approvals; edits reset approval eligibility. See
[ADR 0011](../adr/0011-studio-workflow.md).
