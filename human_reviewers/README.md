# Human-review materials

This folder contains point-in-time backups of the two completed, independent human-review forms and method-agnostic templates for future citation-use validation.

## Completed reviewer backups

The files in `completed/` were exported from the final Google Docs on 27 August 2026. Reviewer identities are represented only as Reviewer 1 and Reviewer 2.

Each completed form is preserved in two formats:

- PDF: a stable reading snapshot;
- DOCX: an editable backup that retains the table structure and hyperlinks.

The completed forms are project-specific records and include article titles, DOI links, human labels, short evidence quotations, and reviewer notes. They do not contain the source articles themselves. Do not use these completed answers as a blank form for a new method.

`completed/MANIFEST.tsv` records the source document identifiers, source revisions, export time, file sizes, and SHA-256 checksums. Both DOCX exports passed ZIP-integrity checks and contain 50 unique formal-validation IDs plus three calibration records, with all 53 records marked `LOCKED`.

## Reusable blank templates

The files in `templates/` do not name a particular method or study:

- `reviewer_instructions.md` explains the six review questions and the non-exclusive citation-use labels.
- `blank_independent_review_form.csv` is a one-row-per-study data-entry form for an independent human reviewer.
- `blank_category_scoring_template.csv` is a long-format table for comparing a frozen machine result with the human consensus, one study-category pair per row.

The independent reviewer form deliberately gives `APPLY_BIOLOGICAL`, `EXTEND_DEVELOP`, `BENCHMARK_EVALUATE`, and `OTHER_EXECUTED_USE` separate columns. A paper may receive more than one of these labels. `MENTION_ONLY` is mutually exclusive with all execution labels.

## Scoring convention

Treat the adjudicated human consensus as the reference standard. For each category independently:

- true positive: machine positive and human positive;
- false positive: machine positive and human negative;
- false negative: machine negative and human positive;
- true negative: machine negative and human negative.

Then calculate:

- precision = TP / (TP + FP);
- recall = TP / (TP + FN);
- F1 = 2 × precision × recall / (precision + recall).

A genuine precision-recall curve requires a frozen continuous or ordered machine score. A hard yes/no machine label supplies only one operating point, not a curve. Cases judged unevaluable because of insufficient coverage, an unlocated citation, or unresolved human evidence should be reported separately rather than silently counted as negative.

Use `sample_weight = 1` for an unweighted validation sample. If the sample was selected with unequal probabilities and the goal is a population estimate, insert the preregistered inverse-probability weight and report both weighted and unweighted results.
