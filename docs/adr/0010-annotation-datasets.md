# ADR 0010: Private versioned annotation datasets and split locks

Status: implemented for P1-03; implementation and synthetic labels await user review.

Snapshot an owned maintainer annotation revision into an append-only dataset version.
Keep source and crop hashes, canonical box, renderer and label provenance in the
portable JSONL record. Append local human reviews separately; never infer approval
from assistant generation, dataset creation or a foreign archive's approved flag.

Use five private global tables for dataset headers, case snapshots, source split
locks, question split locks and case reviews. All have version/time provenance and
SELECT/INSERT-only maintainer grants plus mutation-denial triggers. No dataset view
is exposed to runtime; no dataset grants go to workers. Composite foreign keys pin
annotation revisions and enforce source/question partition consistency. Server
ownership checks scope headers/cases/crops to the verified creator. A shared
transaction advisory lock serializes split reservation and bounds dataset capacity.

Require distinct development/holdout exports. Lock exact source SHA and normalized
question hashes globally rather than per dataset, to catch reuploads and response
variants. Exclude held-out sources from all four source-bearing published views;
teaching demonstrations remain private.
Exact normalization is deliberately limited; semantic duplicates still need review.

Refuse identifying text instead of automatic redaction that could alter mathematics.
Combine conservative email/URL/phone scanning with explicit source-origin, rights,
consent reference and manual text/crop attestations. Export no identities or object
locators. Identifying content in images is a manual curation responsibility.

Require an already owned, rendered source on import; validate the complete bounded
archive, split locks, renderer/page geometry and crop hashes. Reconstruct private
annotation/crop evidence locally, preserving the original transport revision while
referencing the local annotation revision in the database. Import as drafts with
atomic DB writes and idempotent case IDs. Source deletion revokes live case evidence
and export eligibility. Private orphan crops from failed writes need lifecycle
reconciliation alongside existing source retention controls.

The user requested 40 synthetic proposals for review. Prepare those without treating
AI labels as the playbook's manually reviewed ground truth. P1-03's human-labelled
acceptance gate remains pending until individual cases are reviewed. Evaluation
implementation belongs to P1-04 and must not consume these draft previews as gold.
