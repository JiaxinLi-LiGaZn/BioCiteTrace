# Reproducible upstream citation workflow

This workflow prepares the literature evidence that the citation-use reviewers consume. It follows the sequence used in the scGPT audit: define a seed version cluster, discover incoming citations from several public databases, reconcile provider records, review uncertain version links, retrieve lawful full text, check duplicates again, and freeze one study at a time for classification.

The scientific counting unit is a citing study. Provider records, preprints, journal versions, PDFs, XML files, and supplements are evidence associated with a study; they are not separate observations merely because they have different identifiers or files.

## What is deliberately automated

The commands can:

- query OpenAlex as the required citation graph;
- cross-check citations with Europe PMC and OpenCitations;
- enrich identifier-only records through exact PubMed and Crossref lookups;
- save exact response bytes, request parameters, response timestamps, headers, and hashes;
- reconcile records that share strong identifiers;
- cluster versions supported by explicit version relations;
- prepare complete manual queues for uncertain duplicates and rights decisions;
- resume requests from hash-verified raw responses and downloads from terminal checkpoints;
- retrieve only direct documents that a person approved;
- verify document format and article identity;
- detect repeated DOI or byte-identical full text across study IDs; and
- build the existing validated one-study capsules and ordered batch manifest.

## What remains a human decision

The software does not decide whether a license, repository policy, publisher term, or institutional agreement permits machine processing. Provider fields such as `is_oa` or `license: cc-by` are displayed as review evidence only.

The workflow also does not automatically merge records merely because their titles look similar. Ambiguous version and duplicate relationships remain separate until a reviewer records a decision.

No command scrapes Google Scholar, automates institutional login, bypasses a paywall, or uses unapproved credentials. Restricted source files and downloaded full text should not be committed to a public repository.

## 1. Configure the target method

Start with [`config/example_upstream_config.json`](../config/example_upstream_config.json). The method identity contains:

- one canonical method name;
- only unambiguous aliases that can be searched in article text;
- every known seed-paper version;
- stable identifiers for each version; and
- the earliest public date, used to flag impossible citation dates.

The published article and preprint are separate seed versions inside one target cluster. A short ambiguous acronym should not be used as the only seed or text alias.

OpenAlex is required and at least one seed must have an OpenAlex work ID. Europe PMC and OpenCitations are optional citation cross-checks. PubMed and Crossref are optional metadata enrichers for identifier-bearing records that still lack titles. Each optional adapter can be disabled independently.

## 2. Discover and freeze a source snapshot

```bash
citation-use-review --project-root . discover-citations \
  --config config/my_method_upstream.json \
  --snapshot-id 20260827_my_method_source_v1
```

The snapshot ID is immutable. If its final `manifest.json` already exists, the command refuses to overwrite it. An interrupted discovery may reuse exact cached response pages under:

```text
state/upstream/snapshots/<snapshot-id>/raw/
```

A completed source snapshot is written under:

```text
artifacts/upstream/snapshots/<snapshot-id>/
  seed_versions.json
  source_records.jsonl
  citation_edges.jsonl
  works.jsonl
  citing_studies.jsonl
  citing_studies.csv
  cluster_candidates.jsonl
  cluster_candidates.csv
  raw_responses.jsonl
  manifest.json
```

The manifest records the source record, work, study, candidate, and raw-response counts; source-specific failures; and hashes for every frozen artifact.

If OpenAlex fails, discovery stops. If an optional source fails, the snapshot is still available for diagnosis, but `source_complete` is false and the error is retained. Such a snapshot cannot be promoted unless the researcher deliberately supplies `--allow-incomplete-sources` during the review step.

## 3. Reconcile records and review study candidates

Provider records that share a normalized DOI, PMID, PMCID, OpenAlex ID, or Europe PMC ID are reconciled transitively into one version-level work. This means a later metadata record can bridge records that initially looked separate.

Automatic study clustering is narrower. It accepts explicit relationships such as preprint-to-published or corrected-version links. Similar titles, shared authors, and provider cross-version hints create candidates rather than automatic merges.

Copy every row from `cluster_candidates.jsonl` to a review file and complete:

- `recommendation`: `MERGE`, `KEEP_SEPARATE`, or `DO_NOT_MERGE`;
- `reviewer` and `reviewed_at`: who made the decision and when;
- `notes`: a concise reason; and
- any local reviewer metadata your project requires.

Do not delete hard cases. The review must cover every pending candidate exactly once and must preserve the frozen candidate and work IDs.

```bash
citation-use-review --project-root . apply-cluster-review \
  --parent-snapshot 20260827_my_method_source_v1 \
  --review reviews/cluster_review.jsonl \
  --derived-snapshot 20260827_my_method_reviewed_v1
```

This makes a new snapshot and leaves its parent unchanged. The completed decisions are copied into the derivative as `cluster_review.jsonl`; the new manifest binds that file, the parent manifest hash, merge count, source study count, and study-count reduction. A production-eligible reviewed snapshot has no pending candidates and either complete sources or a recorded explicit incomplete-source exception.

## 4. Prepare the rights review

```bash
citation-use-review --project-root . prepare-rights-review \
  --snapshot-id 20260827_my_method_reviewed_v1
```

The queue contains only direct full-text candidates exposed by enabled providers. A landing page without a direct supported article document is not enough. Each row includes the study/version identity, URL, provider OA claim, provider-reported license, and blank decision fields.

The blank queue is stored at:

```text
artifacts/upstream/rights/<snapshot-id>/rights_review_queue.jsonl
```

For every row, a human reviewer must choose:

- `APPROVE`: this exact candidate may be downloaded and processed;
- `DENY`: it is not approved for this workflow; or
- `DEFER`: permission remains unresolved.

Every completed row records a reviewer and review time. `DENY` and `DEFER` rows use the JSON Boolean `false` for `cloud_processing_allowed`; blanks are allowed only in the untouched queue, not in a completed review.

An approved row must also contain:

```json
{
  "decision": "APPROVE",
  "cloud_processing_allowed": true,
  "permission_basis": "Specific license, policy, or documented permission reviewed by the research team.",
  "reviewer": "reviewer identifier",
  "reviewed_at": "2026-08-27T12:00:00+00:00",
  "notes": "Optional context"
}
```

All identity, URL, and provider fields must remain unchanged. `cloud_processing_allowed` must be the JSON Boolean `true`, not a string. A provider-reported license never fills this field automatically.

## 5. Retrieve approved documents

```bash
citation-use-review --project-root . retrieve-approved \
  --config config/my_method_upstream.json \
  --snapshot-id 20260827_my_method_reviewed_v1 \
  --approval reviews/rights_review_completed.jsonl
```

The approval must cover the entire queue exactly once. At most one candidate may be approved for the same study, version, and document role. Approved downloads use bounded concurrency, timeout, maximum-size, retry, and backoff settings from the configuration.

PDF, XML, HTML, and UTF-8 text are supported. The downloaded bytes must match their claimed format and the extracted text must support the expected DOI or title. Successful binary and text files, hashes, identity evidence, rights provenance, terminal checkpoints, and a canonical copy of the completed rights review are stored under:

```text
artifacts/upstream/retrieval/<snapshot-id>/
```

Rerunning the same approval reuses a matching terminal checkpoint. A changed approval row colliding with an old checkpoint fails closed.

Denied and deferred candidates are retained as `EXCLUDED_RIGHTS_NOT_APPROVED`; they are not classified as non-use. Failed downloads are retained as `UNRESOLVED_FULLTEXT`.

Retrieval also writes `evidence_coverage_review_queue.jsonl`, with one row for every study that has approved retrieved text. A researcher must confirm whether all known versions and relevant supplements are represented. Set `evidence_complete` to the JSON Boolean `true` only when there are no missing versions, supplement coverage is `COMPLETE` or `NONE_IDENTIFIED`, and `coverage_risk_codes` is empty. Otherwise set it to `false` and record at least one risk code. This is the public equivalent of the version/supplement coverage gate used in the scGPT audit.

## 6. Check duplicates again after retrieval

Bibliographic deduplication is not sufficient by itself. Metadata can be enriched late, provider records can disagree, and the same article can arrive through more than one route. The retrieval stage therefore compares study-level normalized DOIs and full-text SHA-256 hashes.

Any cross-study collision is written to:

```text
post_retrieval_duplicate_candidates.jsonl
```

Review every collision as:

- `DISTINCT_STUDIES`; or
- `SAME_STUDY`, with `keep_study_id` set to the retained counting unit.

Every collision decision must also record `reviewer` and `reviewed_at`.

This second check was added because the original scGPT formal cohort later proved to contain seven pairs of duplicate papers. The public workflow treats this check as a required denominator gate rather than a reporting cleanup.

## 7. Build the agent handoff

```bash
citation-use-review --project-root . build-agent-handoff \
  --config config/my_method_upstream.json \
  --snapshot-id 20260827_my_method_reviewed_v1 \
  --coverage-review reviews/evidence_coverage_completed.jsonl \
  --duplicate-review reviews/post_retrieval_duplicates.jsonl
```

Omit `--duplicate-review` when the collision queue is empty. The command:

1. verifies the retrieval, coverage-review, and duplicate-queue hashes;
2. applies reviewed duplicate exclusions;
3. converts each approved document to the exact existing document input contract;
4. writes reusable `method.json`, per-study metadata, and per-study document manifests;
5. builds and validates one capsule per study with the reviewed evidence-completeness state; and
6. writes an ordered `capsules.jsonl` accepted directly by `run-batch`.

Studies without retrieved approved text remain in `study_dispositions.jsonl`. They are not silently dropped from provenance and are not converted to `MENTION_ONLY`.

## 8. Run the existing blind review

The handoff manifest path is printed in the final manifest. Pass it to:

```bash
citation-use-review --project-root . run-batch \
  --config config/example_config.json \
  --manifest artifacts/upstream/handoff/<snapshot-id>/capsules.jsonl \
  --output-root artifacts/reviews/<snapshot-id>
```

At this point every model input is still one study, with a frozen codebook, exact output schema, explicit rights provenance, and traceable source evidence.

## Offline testing and adapter extension

The regression suite injects fixture transports; it does not call literature APIs or download papers:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

New citation providers implement the `CitationSourceAdapter` protocol in `sources.py`. An adapter returns normalized provider records and must route every request through `ProvenanceFetcher`. New metadata-only providers should add records that share a strong identifier with an existing work; they must not invent citation edges.

For every new adapter, include fixtures for pagination, identifiers, a retryable failure, malformed output, raw-response persistence, and a source-incomplete snapshot.
