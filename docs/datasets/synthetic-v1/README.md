# Synthetic quadratic review pack v1

**40 assistant-authored draft examples. Human label review pending.**

- 30 development questions in `synthetic-development-v1.pdf`.
- 10 held-out questions in `synthetic-holdout-v1.pdf`.
- [Readable review sheet](review.md) lists all 40 proposals and suggested answers.
- `proposed-labels.json` pairs each page with proposed labels and a correct answer.
- `development.preview.jsonl` and `holdout.preview.jsonl` are schema-v1 portable
  snapshots from the private local studio. All records remain draft.

Ten families: square roots, zero product, expansion, vertex, symmetry axis,
discriminant, y-intercept, common factor, turning-point classification and completing
the square. Three numerical variants per family are development material; the fourth
is held out. The PDFs are separate and contain no real learner information.

Run `make seed-dataset` after `make up seed-auth` to populate the review dataset.
The seed script reuses stable source/case identities and never calls label approval.
To regenerate/check the source pack without services, run the generator's `prepare`
mode in the API checks image with this directory mounted as its output argument.
Existing PDFs are preserved so source and crop hashes remain reproducible.

Review each crop, mathematical answer, proposed mark, first visible error and
intervention in **Annotation datasets**. The first-error labels concern the visible
answer, because these short examples do not show earlier working. Correct labels
through a revised source annotation and a new dataset version. Approve cases only
after review; draft previews cannot be used as verified ground truth.

These intentionally similar templates are for MVP development and review. They do
not establish model accuracy or semantic independence of an evaluation corpus.
