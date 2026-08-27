# Independent human citation-use review

Use this form to determine how one citing study engages with the target method. Complete the review independently and use only the approved article versions and supplementary files supplied for that study. Do not view machine labels, machine-selected evidence, confidence scores, or another reviewer's answers before locking the record.

Citation-use purposes are non-exclusive. A study may both apply a method to biological data and extend it, or extend it while also benchmarking it. Record every supported purpose rather than forcing a single choice.

## Question 1 — Is the target citation valid?

Choose `YES`, `NO`, or `UNCLEAR`.

Select `YES` when the cited reference or clearly identified method is the intended target. Select `NO` when the occurrence refers to a different work or method. Use `UNCLEAR` when the available evidence cannot resolve the identity.

## Question 2 — Was the target method executed?

Choose `YES`, `NO`, or `UNCLEAR`.

Execution requires evidence that the authors actually ran the method, used its outputs, trained or adapted it, or evaluated it in the reported study. A literature-review sentence, general description, bibliography entry, or statement about what the method can do is not execution.

## Question 3 — What purpose or purposes did the citation serve?

Mark each category independently as `YES`, `NO`, or `UNCLEAR`:

- `APPLY_BIOLOGICAL`: the method was run on biological data to answer a biological question or produce a biological result.
- `EXTEND_DEVELOP`: the method was modified, adapted, fine-tuned, integrated, or used as a direct basis for a new method or workflow.
- `BENCHMARK_EVALUATE`: the method was run as a comparator, baseline, ablation component, or evaluated system.
- `OTHER_EXECUTED_USE`: the method was substantively executed for another purpose.
- `MENTION_ONLY`: the method was cited or discussed but was not executed in the reported analysis.

`MENTION_ONLY = YES` requires all four execution categories to be `NO`. If one or more execution categories are `YES`, set `MENTION_ONLY = NO`.

The optional `primary_use` field provides a single summary label. It must not erase additional positive use categories.

## Question 4 — Did the method support a biological insight?

Choose `YES`, `NO`, or `UNCLEAR`.

Select `YES` only when the paper makes a concrete biological claim, discovery, prioritization, or experimentally relevant interpretation and the evidence links that claim to analysis performed with the target method. Technical performance, embeddings, predictions, or reconstructed profiles alone do not automatically constitute a biological insight.

## Question 5 — Is the evidence sufficient for classification?

Choose one:

- `SUFFICIENT`: the available versions and supplements support a defensible decision.
- `COVERAGE_INCOMPLETE`: missing or unreadable material could materially change the decision.
- `CITATION_NOT_LOCATED`: coverage is otherwise adequate, but the target citation cannot be found.
- `UNCLEAR`: another evidence problem prevents a defensible judgment.

Do not convert incomplete evidence into `MENTION_ONLY` or a negative biological-insight judgment.

## Question 6 — What exact evidence supports the decision?

Copy the shortest exact quotation that establishes the relevant action or non-executed mention. Record a stable locator such as the section, page, paragraph, figure, table, supplement, or citation-occurrence ID. For a positive biological-insight decision, record both the method-use evidence and the biological claim, then explain their connection briefly in `notes`.

## Locking the record

Use `DRAFT` while reviewing. Change `review_status` to `LOCKED` only after all fields are complete and internally consistent. After locking, preserve the original response. Any later consensus decision belongs in a separate consensus record rather than overwriting the independent review.
