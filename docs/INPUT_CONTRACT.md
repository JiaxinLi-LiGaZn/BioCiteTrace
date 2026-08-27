# Input contract for a new method

This document describes the minimum handoff needed to repeat the citation-use review for another biological method. It separates literature preparation, which depends on databases and access rights, from the machine-review core included in this repository.

## 1. Freeze the target identity

Create one method file using the shape of `examples/example_method.json`:

```json
{
  "canonical_name": "MethodName",
  "aliases": ["MethodName", "Unambiguous long-form name"],
  "seed_identifiers": {
    "doi": "10.xxxx/example",
    "openalex": "W0000000000"
  }
}
```

The canonical name must also appear in `aliases`. Include only aliases that identify the method unambiguously in article text. A broad acronym should not be added merely because it is convenient for searching.

Citation discovery should start from stable identifiers for the seed paper or version cluster. Keep the query date, source database, citation edge, and source identifier for every candidate.

## 2. Define one citing study

Create one study metadata file like `examples/example_study.json`:

```json
{
  "study_id": "stable-study-id",
  "title": "Citing paper title",
  "identifiers": {
    "doi": "10.xxxx/citing-paper",
    "openalex": "W1111111111"
  }
}
```

The `study_id` is the counting key. A preprint, journal publication, corrected version, and supplement should not receive separate study IDs when they belong to the same scientific work. Resolve duplicates before classification and check them again before estimating corpus-level proportions.

## 3. Prepare rights-approved text

The starter capsule builder accepts UTF-8 text with Markdown-like headings. Blank lines separate paragraphs; lines beginning with `#` begin a section. PDF, XML, OCR, and supplementary archives should be parsed upstream with tools appropriate to their formats.

For each included file, add one row to a JSON array like `examples/example_documents.json`:

| Field | Meaning |
| --- | --- |
| `path` | Local UTF-8 text path inside the repository checkout. |
| `source_file` | Stable file name used in evidence locators. |
| `document_type` | `MAIN` or `SUPPLEMENT`. |
| `version_id` | Stable identifier linking files from the same article version. |
| `version_type` | `PREPRINT`, `PUBLISHED`, or `OTHER`. |
| `license` | Nonempty license or permission evidence recorded by the researcher. |
| `cloud_processing_allowed` | Must be exactly `true` before the file can enter a capsule. |

Setting `cloud_processing_allowed` to `true` is a research-governance assertion, not an automated legal opinion. Verify the relevant license, publisher terms, repository policy, and institutional requirements before doing so. Do not place restricted full text in a public repository.

## 4. Record incomplete coverage honestly

If an unavailable version, supplement, unreadable region, or incomplete occurrence inventory could change the result, build the capsule with `--incomplete` and at least one `--coverage-risk` from the codebook:

```bash
python scripts/build_capsule.py \
  --study path/to/study.json \
  --method path/to/method.json \
  --documents path/to/documents.json \
  --incomplete \
  --coverage-risk SUPPLEMENT_RETRIEVAL_INCOMPLETE \
  --output artifacts/capsules/study.json
```

An incomplete capsule may produce `COVERAGE_INCOMPLETE`; it must not be converted into `MENTION_ONLY` merely because an execution passage is missing.

## 5. Inspect the physical occurrence registry

The public builder detects literal method aliases and assigns stable occurrence IDs. This transparent detector is suitable for the included plain-text example, but real citation styles can require a stronger upstream registry builder. Before running agents, confirm that:

- every physical citation of the target method is present exactly once;
- bibliography entries and repeated local citations remain distinguishable;
- each marker is attached to the correct target reference;
- locators point to the intended source file and paragraph; and
- ambiguous same-name methods are excluded or explicitly flagged.

The result validator requires a classified agent output to account for every registered occurrence. It does not permit the model to invent or silently omit occurrences.

## 6. Freeze the scientific contract

Review the codebook, output schema, and all three prompts before a run. If the new scientific question requires different definitions, create versioned replacements and update `config/example_config.json` or a copied project config. Do not revise these files after seeing human-validation outcomes and then report performance on the same sample.

The supplied execution labels are non-exclusive. `primary_label` follows the frozen priority for summaries, but category-level reporting and human validation retain every supported label.

## 7. Check the execution environment

The example configuration pins:

- model `gpt-5.6-sol`;
- reasoning effort `high`;
- Codex CLI `0.148.0-alpha.9`;
- a 900-second timeout;
- at most three physical attempts per logical review slot; and
- three concurrent study pipelines.

The version preflight fails when the installed CLI differs from the explicit pin. Audit and deliberately update the pin for a new environment. Confirm authentication, costs, quota, network policy, model availability, and the disabled feature list before any external call.

## 8. Run a small blinded pilot first

Begin with synthetic data, then a small real pilot. Check capsule completeness, structured-output validity, exact quotations, occurrence coverage, disagreement patterns, retry rates, and human-review feasibility. Freeze a cohort manifest and obtain any required transmission approval before scaling.

Each paper receives two fresh blind assessments. A third blind assessment is conditional and bounded. Retries repair the same logical slot; they do not add scientific votes. There is no fourth reviewer.

## 9. Validate with humans

Select the validation sample before showing machine labels to reviewers. Give the two reviewers separate blinded forms and paper orders. Treat each use category as its own yes/no question so that a paper can be positive for several purposes.

After independent review, reconcile disagreements into a consensus reference. Score each category one-vs-rest. State the reviewed and target-population denominators, keep process-audit states separate from classifiable papers, and use sampling weights only when the sampling design calls for them.

The scoring template accepts an optional frozen continuous `machine_score`. Without such a score, report precision and recall at the observed hard-label operating point; do not describe it as a full precision-recall curve or AUROC.

## What this repository does not automate

The public starter does not automatically:

- query citation databases;
- merge bibliographic versions or adjudicate difficult duplicates;
- download publisher files;
- interpret licenses or publisher terms;
- parse arbitrary PDF, XML, OCR, or supplement formats;
- approve transmission of article text; or
- design a statistically powered validation sample.

Those steps remain visible parts of the scientific workflow. Their decisions and provenance should be frozen alongside the runnable review artifacts.
