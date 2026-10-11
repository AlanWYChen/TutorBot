# ADR 0007: Bounded authenticated PDF ingestion

Status: implemented for P0-05; user review pending.

Expose separate student assessment and maintainer knowledge upload routes. Resolve
roles before reading multipart bodies; resolve student ownership from verified
Firebase identity inside the database transaction. Accept exactly one PDF and one
JSON metadata part, with a UUID idempotency header. Ignore untrusted scope headers
and reject scope fields in metadata. Maintainer source uploads stay draft in the
teaching-private bucket and never enter published retrieval automatically.

Use one shared 25 MiB/200-page limit across contracts, binary validation and object
storage. Enforce declared and streamed multipart limits (25 MiB plus 64 KiB framing),
one file/one metadata field, a 16 KiB metadata part, a 10-second receive idle limit
and a 60-second overall receive limit. Bound each API process to two concurrent
uploads. Partial temporary files close on parser errors, body-limit errors, idle
expiry, disconnects and normal completion. No credentials, metadata or parser
exceptions are returned or logged.

Validate PDF extension, declared MIME, header, final EOF, byte size and SHA-256
independently. Inspect the structure and actual page count with pinned PyMuPDF in
a subprocess, with no inherited service credentials, no core dumps, 512 MiB address
space, five CPU seconds and ten seconds wall time. Reject encrypted, repaired,
malformed, over-page-limit and active-content/attachment PDFs, including inline
JavaScript/action dictionaries. This is an upload validation policy, not a claim
that arbitrary PDFs are malware-free or that the subprocess is a complete security
sandbox. Rendering/OCR and deployment containment are verified in their own gates.

Persist the document, immutable storage manifest, assessment (student only) and
verification job together. Derive document/assessment IDs from the trusted owner
and client idempotency UUID; serialize same-key attempts using a transaction advisory
lock. Identical retries return the same resource/job. Changed metadata or bytes and
reuse after deletion refuse. Validate supplied curriculum IDs against published
curricula. No inference, extraction, profile update or global learning is triggered.

The private write precedes DB commit. If the commit fails, a generation-conditional
retry can recover the same private object; it is unservable without a committed
owned manifest/document. Do not blindly delete on commit failure, since that could
remove an object adopted by a concurrent retry. Unclaimed orphan reconciliation
and production retention enforcement remain required staging controls documented
in ADR 0006. HTTP success is returned only after the DB transaction commits.

Serve originals through authenticated, owner-scoped API download routes, with fixed
attachment filenames, no-store, nosniff and sandbox headers. Never return emulator
object URLs, bearer tokens in URLs or unsigned cloud fallbacks. Status describes
storage verification, not extraction or mathematical correctness; student evidence
remains unverified. Student upload/viewer UI and page rendering belong to P1-01;
maintainer metadata UI and publishing belong to later studio/release tickets.

See [API contract and policy](../uploads/api.md) and
[P0-05 acceptance evidence](../reviews/P0-05.md).
