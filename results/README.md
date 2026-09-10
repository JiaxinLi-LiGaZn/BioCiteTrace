# Citation-analysis results

**Interpretation note:** LLMs produced the corpus-wide citation-use classifications and may make errors. Human consensus was used as a sampled reference standard, not as absolute ground truth. Sampled human validation is complete for scVI, scGPT, scGen and GEARS.

Among papers with resolved primary-use classifications, biological application was much more common for scVI. For scGPT, scGen and GEARS, mention only was the most common primary category.

[Open the high-resolution complete Figure 2](../site/assets/figures/figure-2-high-resolution.png)

## What is being counted?

The figure assigns each classified study one **primary category**. The reusable workflow also keeps non-exclusive use labels, but those answer a different question. A paper whose primary category is biological application can still include benchmarking or method development.

| Method | Candidate records | LLM reviewed | Classified studies |
| --- | ---: | ---: | ---: |
| scVI | 2,382 | 1,634 | 951 |
| scGPT | 1,291 | 726 | 402 |
| scGen | 582 | 274 | 214 |
| GEARS | 353 | 100 | 84 |

Panel C uses the **classified-studies column** as its denominator. Coverage differs across methods. Duplicate study versions, unavailable or ineligible evidence, coverage-incomplete cases, citation-not-located cases and unresolved classifications are not silently treated as mention only.

| Method | Biological application | Method extension | Benchmark evaluation | Other executed use | Mention only |
| --- | ---: | ---: | ---: | ---: | ---: |
| scVI | 40.2% | 6.9% | 35.9% | 0.6% | 16.4% |
| scGPT | 5.0% | 10.2% | 13.7% | 0.2% | 70.9% |
| scGen | 7.9% | 3.7% | 14.5% | 0.5% | 73.4% |
| GEARS | 7.1% | 11.9% | 19.0% | 0.0% | 61.9% |

Values are rounded to one decimal place as displayed. A row can sum to 99.9% because of rounding. The biological-application column does not by itself measure validated biological discoveries.

[Download the primary-category and funnel data](figure_2_primary_categories.csv)

## Human-validation results

Panel D evaluates studies in the classification-validation samples that have resolved LLM primary labels: 39 for scVI and 40 each for scGPT, scGen and GEARS. It reports unweighted one-vs-rest precision and recall for each primary category; the macro-average group has been removed.

| Primary category | scVI precision / recall | scGPT precision / recall | scGen precision / recall | GEARS precision / recall |
| --- | ---: | ---: | ---: | ---: |
| Biological application | 88.9% / 80.0% | 44.4% / 100.0% | 100.0% / 100.0% | N/A / N/A |
| Method extension | 50.0% / 50.0% | 33.3% / 40.0% | N/A / N/A | N/A / N/A |
| Benchmark evaluation | 88.9% / 80.0% | 100.0% / 45.5% | 100.0% / 75.0% | 100.0% / 50.0% |
| Mention only | 89.5% / 100.0% | 100.0% / 100.0% | 96.6% / 100.0% | 92.6% / 96.2% |

N/A indicates a method-category pair with zero positive human-reference labels: scGen method extension, GEARS biological application and GEARS method extension. By reporting convention, both precision and recall are shown as N/A rather than zero for those pairs. This does not imply that the LLM review made no false-positive assignments.

These values are point estimates; confidence intervals have not yet been calculated. Hard labels supply one operating point, not a precision-recall curve, and the sample metrics are not a correction factor for the full citation corpus.

[Download the human-validation data](figure_2_human_validation.csv) · [Human-review procedure](../human_reviewers/README.md)

## Figure files and provenance

- [High-resolution PNG, 600 dpi](../site/assets/figures/figure-2-high-resolution.png)
- [Publication PDF](../site/assets/figures/figure-2.pdf)
- [Editable SVG](../site/assets/figures/figure-2-editable.svg)
- [Source and file-integrity record](provenance.json)

The public repository contains the aggregate figure data and a reusable workflow, but not the complete production corpus, row-level classifications, full-text papers or sampling probabilities needed to reproduce every study estimate independently.
