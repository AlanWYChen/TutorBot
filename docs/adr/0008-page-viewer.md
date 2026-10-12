# ADR 0008: Canonical private page rendering and viewer

Status: implemented for P1-01; user review pending.

Student uploads now enqueue a durable `render_document` job. Older uploads can be
prepared through an authenticated, owner-scoped render endpoint. Enqueue is
idempotent per source/version. Maintainer uploads retain their verification-only
behavior; the runtime worker never renders maintainer sources.

Render with pinned PyMuPDF at scale 1.5, retaining teacher annotations and original
PDF bytes. Generate private PNG pages as the canonical pixel coordinate surface.
The browser displays those page images rather than running PDF.js against the raw
PDF. This refines the playbook's proposed PDF.js/React-PDF viewer: the same server
pixels used by later crops/evaluation also underlie every displayed selection,
including rotated/cropped documents, and no PDF action executes in the browser.
Text selection/search is not part of this slice. Original PDF download remains
available through its existing authenticated API.

Native rendering runs in a credential-free subprocess with 768 MiB address-space,
50 CPU-second and 65-second wall limits; individual pages have an 8-million-pixel
budget and all output is capped at 128 MiB. These are validation/availability
limits, not a full deployment sandbox. Scanned pages render normally without OCR.
PNG dimensions, rotation and renderer version are persisted. The frontend maps
resized/zoomed pointer positions to those canonical pixels; keyboard selection
provides an alternative to dragging. Selections are transient viewing aids until
P1-02 introduces reviewed annotations and evidence crops.

Numbered native text lines produce tentative navigation hints only. Their boxes
are transformed using the page rotation matrix and render scale, clipped to the
image, and recorded with candidate status/confidence 0.5. Sort hints numerically,
not by UUID or creation-time tie-breaker. This heuristic does not identify complete
questions, grade work, interpret marks or infer reasoning. Scans may have no hints.
No model/provider calls, OCR, profile updates or global promotion occur.

Migration 0006 narrowly grants the runtime worker append-only inserts/selects for
pages and candidate regions, and inserts for derived manifests. It retains forced
RLS and denies unrelated profiles/conversations and every maintainer table. Render
attempts have a 360-second DB lease; Celery hard/soft limits are 300/280 seconds.
Reference-only cloud requests allow 300 seconds; production containment, capacity
and cloud delivery remain staging checks.

Derived object UUIDs are deterministic from source/page/renderer version. Generation
preconditions make repeated uploads safe; derivatives inherit the source retention
intent. Publish all page/region/manifests and terminal job success in one transaction,
under a current lease token and live source check. Reject conflicting page/manifests
instead of overwriting append-only evidence. Uncommitted external writes have no
API path and remain subject to orphan reconciliation at the staging gate. Parent
tombstoning hides all derivative API access; physical retention/deletion must cover
originals and derivatives together.

All page manifests/images and recent assessments resolve trusted student scope.
The web proxy accepts only fixed assessment paths, forwards only authorization and
required upload headers, streams bounded bodies, and disables caching. Image bytes
are drawn on canvas from short-lived blob URLs which are revoked; sign-out/unmount
aborts requests and removes the viewer. Bearer tokens never enter image URLs.

See [viewer operation](../assessments/viewer.md) and [acceptance evidence](../reviews/P1-01.md).
