# Full-text citation-use review

**When a biological AI method is cited hundreds of times, how often has it actually changed the science—and how often is it simply named in passing?**

Citation counts cannot answer that question. This project develops a full-text review framework for finding out how later papers really engage with a method: whether they apply it to biological data, extend it, benchmark it, or only mention it. When a method is applied, we also ask whether it contributes to a new biological interpretation.

## Why a full-text review is needed

Titles and abstracts are useful for finding papers, but they rarely describe citation use in enough detail. A paper may name a method in the introduction, compare it with another model in a benchmark, use its representations in a downstream analysis, or modify its architecture. These cases can look almost identical in bibliographic metadata while representing very different scientific uses.

The distinction often lives in a methods paragraph, a figure caption, or a supplementary analysis. For that reason, classification in this project is based on the available full text and its surrounding citation passages. Metadata alone are not treated as sufficient evidence for a citation-use label.

## Workflow overview

The review proceeds in nine stages:

1. Define the method being studied.
2. Discover citing records from multiple literature databases.
3. Link versions and remove duplicate study records.
4. Retrieve full text from approved sources.
5. Check rights, identity, integrity, and evidence coverage.
6. Prepare a self-contained evidence record for each citing study.
7. Obtain two independent machine assessments and, when necessary, a third assessment.
8. Audit a sample with two blinded human reviewers and create a consensus reference.
9. Publish structured results with denominators, uncertainty states, evidence, and provenance.

Each stage is described below.

## 1. Define the method

Before citation discovery begins, the target method is represented as a version cluster rather than as a single title string. The cluster can include a preprint, a journal article, database identifiers, and known title variants.

This prevents a preprint and its published version from being treated as different methods. It also avoids broad searches based on ambiguous short names. A short acronym is never used as the sole basis for discovering or matching citations.

## 2. Discover citing papers

Citation discovery can draw on:

- **OpenAlex** as the primary citation graph;
- **Europe PMC**;
- **OpenCitations**;
- **PubMed**; and
- **Crossref**.

The additional sources are used to cross-check identity and coverage rather than to inflate the citation count. For every candidate, the review retains the source database, identifiers, retrieval date, and relevant links.

## 3. Group versions and deduplicate studies

The scientific counting unit is the **citing study**, not a PDF, DOI record, or database entry.

A preprint, its journal version, and its supplementary files may all provide evidence about one study. They are linked before classification and retained as different evidence sources within the same study record. Records are compared using identifiers, normalized titles, authorship, publication information, and retrieved-file hashes.

This stage is important because bibliographic databases can represent the same paper more than once. Deduplication is therefore checked both before machine review and again before manuscript-level estimates are calculated.

## 4. Retrieve lawful full text

Full text is collected programmatically when it is available through approved publisher or open-repository routes. Each retrieved file is accompanied by provenance such as its source URL, document version, format, retrieval status, and checksum.

The workflow does not rely on Google Scholar scraping, paywall circumvention, automated institutional-login access, or unapproved credentials. A metadata page or text-and-data-mining landing page is not treated as full text unless the article content is actually available through an approved route.

Three common outcomes stop a paper before machine classification:

- **Full text unavailable:** no suitable full text could be retrieved.
- **Rights not approved:** text was found, but permission for the planned machine processing was not established.
- **Parse, coverage, or context gate failed:** the retrieved material could not support a reliable citation-occurrence inventory or complete evidence record.

These outcomes are documented as unresolved access or processing states. They are not evidence that the method was unused.

## 5. Check evidence coverage

For eligible studies, the main article and approved supplementary files are parsed into stable sections and citation passages. Each physical occurrence of the target citation is assigned an identifier and linked to its surrounding context.

The record also describes what was and was not available, including:

- preprint and published-version coverage;
- supplementary-material coverage;
- known missing versions or files; and
- citation passages that could not be located with confidence.

An important distinction is made between a paper that clearly only mentions the method and a paper for which the evidence is incomplete. **Coverage incomplete** means that some relevant material is missing or cannot be processed. It does not mean “mention only,” “no use,” or “no biological insight.”

## 6. Prepare one-study evidence records

Each eligible study is converted into a self-contained review record containing only that study's approved evidence. The record includes the relevant article versions, supplementary material when allowed, citation occurrences, coverage notes, and the classification definitions.

Keeping studies separate prevents the assessment of one paper from being influenced by the content or label distribution of other papers. Accepted conclusions must be supported by passages that can be traced back to the study record.

## 7. Independent machine assessment

Each study is first assessed twice. Review A and Review B are fresh, mutually blinded assessments: neither reviewer sees the other's answer, and neither sees results from other papers.

The principal citation-use labels are:

| Label | Meaning |
| --- | --- |
| `APPLY_BIOLOGICAL` | the method is run on biological data as part of a scientific analysis. |
| `EXTEND_DEVELOP` | the study modifies, adapts, trains, or builds upon the method. |
| `BENCHMARK_EVALUATE` | the study evaluates the method or compares it with other approaches. |
| `OTHER_EXECUTED_USE` | the method is executed in a way not captured by the categories above. |
| `MENTION_ONLY` | the method is cited or discussed but is not used in the reported analysis. |

The use labels are **non-exclusive**. A study can, for example, apply a method to biological data and also extend it. A separate primary label records the dominant use when a single summary label is needed, but multi-label scoring preserves all supported purposes.

Additional fields record whether the method was executed, the origin of the analyzed data, whether a biological insight was reported, the method's role in that insight, and the supporting evidence. A biological-insight label requires more than model performance: it must be tied to a biological interpretation supported by the paper.

Before an assessment is accepted, it is checked for structural validity, evidence consistency, and correspondence between reported citation instances and the recorded citation occurrences.

### Resolving disagreement

Not every difference between the two assessments requires another review. Minor wording or evidence-selection differences can be retained without changing the scientific conclusion.

A third blinded assessment is opened only when there is a material decision or evidence conflict, or when one of the first two assessments ends in a qualifying operational failure. The third reviewer sees the same study evidence but not the earlier answers. There is no fourth reviewer and no repeated voting until agreement is reached.

If the available assessments do not support a defensible resolution, the study remains machine-unresolved. Preserving this outcome is preferable to forcing a label.

The English Codex templates for the baseline classifier, independent reviewer, and conditional blind adjudicator are available in [`prompts/`](prompts/). That folder also records the recommended model settings and the model and reasoning effort used in the production run.

## 8. Sampled human audit

Human validation takes place after the machine review has been frozen. The sample is stratified to include papers classified as executed use, mention-only papers, biological-insight candidates, and uncertain evidence states such as coverage incomplete, citation not located, or machine unresolved.

Within each stratum, selection is fixed before the reviewers see the titles. Machine-defined strata may be used to construct the sample and calculate inverse-probability weights, but the machine labels themselves are hidden from the reviewers.

Two human reviewers independently read each sampled paper. They are shown article identifiers, approved full-text links, and neutral citation-location guidance, but not the machine labels, confidence, selected machine evidence, or machine adjudication history. The reviewers also receive different paper orders. After completing their independent reviews, they discuss disagreements and record a consensus reference.

The human reference treats citation purposes as non-exclusive. A paper judged to both apply and extend a method is counted in both categories while remaining one study.

If an initial review form encourages single-choice answers, the reviewers should revisit the sampled papers under the non-exclusive label scheme before category-level estimates are finalized.

Papers sampled to examine abstention or incomplete evidence are described separately. They are not automatically pooled with the classification sample when accuracy is calculated.

## 9. Reporting and interpretation

The final structured output separates scientific labels from evidence and processing states. In particular:

- `COVERAGE_INCOMPLETE` means that the available evidence is insufficiently complete.
- `CITATION_NOT_LOCATED` means that the target citation could not be confirmed in the reviewed text.
- `MACHINE_UNRESOLVED` means that the review procedure did not produce a defensible machine consensus.

None of these states should be interpreted as `MENTION_ONLY` or as evidence that the method was not used.

Reports retain study identifiers, labels, short supporting passages, coverage information, and provenance. Source full text is stored or deleted according to its access terms and is not intended for redistribution through this public repository.

## Principles for using the results

1. Always state the denominator: all discovered records, eligible formal records, unique papers, classified papers, or the human-validation sample.
2. Do not interpret incomplete or unresolved evidence as non-use.
3. Preserve multi-purpose use rather than forcing every paper into one mutually exclusive category.
4. Distinguish machine-generated biological-insight candidates from human-verified biological findings.
5. Keep the human validation set separate from any later prompt or rule refinement used to improve the classifier.
6. Report uncertainty and per-category results rather than relying on a single overall accuracy value.

## Reproducibility and stewardship

The project uses frozen corpus snapshots, stable study identifiers, ordered manifests, file checksums, version and supplement coverage, and evidence-linked outputs. These records make it possible to trace a result back to the evidence and review contract that produced it.

Public releases are expected to include codebooks, schemas, workflow documentation, analysis code, and structured results that can be shared lawfully. Copyrighted or access-restricted full text will not be redistributed. Temporary full-text storage follows the applicable publisher, repository, institutional, and retention requirements.

## Extending the framework

The workflow is designed to be repeated for different biological AI methods, but every new method begins with a new seed-identity definition, citation snapshot, access review, and method-specific scientific calibration. Results from one method are not reused as ground truth for another.

## Project status

This repository is under active preparation. Documentation and shareable structured artifacts will be added without redistributing restricted full text.
