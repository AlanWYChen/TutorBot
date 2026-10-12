# ADR 0011: A focused studio with live labels and reversible deletion

Status: implemented for the P1-03 review changes; awaiting user review.

The user requested PDF-only uploads, a simpler interface, deletion of PDFs/pages/
annotations, hidden revision numbers and saved changes visible in case review.
These requests supersede ADR 0010's frozen review-screen behavior.

Keep two tasks visible: PDFs & annotations, and Review labels. Move collection
creation, membership and JSONL transfer into collapsed tools. Use compact selectors
in a narrow pane and a sidebar at desktop widths. Show the selected question's crop,
editable labels and approval in one place. Require saving or discarding unsaved edits
before navigating or approving. Keep optimistic revision checks and append-only
history internally; users never need to enter or see a revision number.

Uploads derive private metadata from the filename and send unspecified author,
personal-library publisher and a personal-use note. No rights/publication permission
is inferred. PDF sniffing, size/page limits, hashes, private storage and server-side
ownership checks remain. Dataset inclusion/export retains explicit privacy/rights
attestations and separate development/held-out splits.

Keep original dataset snapshots and annotation history intact. Review and export
resolve each case's current owned annotation. Approvals now bind the current local
annotation revision; an edit makes the case need review again. Append a new approval
rather than mutating old reviews. Validate edited question text against global split
reservations, and scan edited dataset labels before committing. Imported transport
approvals still reset to draft; transport labels never overwrite an existing case.
Multiple snapshots of the same annotation display as one current question.

Deletion is reversible removal from the active studio. Annotations and pages gain
private deleted_at flags; PDF deletion uses the existing owned manifest tombstone
and cancels active jobs. Every page/annotation/crop/list/review/export path checks
its active parent. The UI offers Undo. Original PDF bytes, source page numbering,
crops and historical records remain private under existing retention so source
identity and Undo work without rewriting evidence. Physical erasure/lifecycle expiry
is a separate existing operational concern, not what these controls claim to do.

Restore validates ownership; PDF restore verifies the stored bytes against the
manifest before clearing its tombstone and requeuing canceled work with cleared
leases. Page/annotation restore requires an active owned parent. Hidden annotations
stay hidden when their page is restored, and vice versa. Deleted pages and deleted
source manifests are also excluded from source-bearing published views. Public view
column contracts remain unchanged. Workers get no additional table grants.

Migration 0011 adds the deletion flags and approval revision binding, backfills old
reviews to their original case revision and retains mutation-denial triggers. On
downgrade, discard reviews that do not apply to the original snapshot before restoring
the old uniqueness contract; never reinterpret a later-label approval as approval of
an older snapshot.
