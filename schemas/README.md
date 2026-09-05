# Evidence and result formats

The JSON schemas describe the exchange formats. The additional scientific and provenance checks are implemented in [contracts.py](../src/citation_use_review/contracts.py) and the upstream modules.

| File | What it records |
| --- | --- |
| [evidence_capsule.schema.json](evidence_capsule.schema.json) | One study, its approved documents, coverage and citation-occurrence registry. |
| [classification.schema.json](classification.schema.json) | A reviewer's status, use labels, primary label, execution, biological interpretation, data origin and evidence. |
| [upstream_config.schema.json](upstream_config.schema.json) | Target identity and literature-source settings. |
| [cluster_review.schema.json](cluster_review.schema.json) | Recorded decisions about uncertain study/version relationships. |
| [rights_review.schema.json](rights_review.schema.json) | Download and processing decisions for exact document candidates. |
| [evidence_coverage_review.schema.json](evidence_coverage_review.schema.json) | Known version and supplement coverage for a study. |
| [post_retrieval_duplicate_review.schema.json](post_retrieval_duplicate_review.schema.json) | Resolutions of cross-study DOI or file-hash collisions. |

A classified answer must account for the registered physical citation occurrences. Quotes must occur in their stated source paragraphs, and each assigned use label must have supporting evidence. These checks do not replace an audit of the original occurrence registry or the interpretation of a quote.

Review records distinguish multiple supported `use_labels` from the priority-based `primary_label`. Saved pipeline status is also separate from the scientific classification's status.

See the [input contract](../docs/INPUT_CONTRACT.md) for field preparation, the [codebook](../codebook/README.md) for meanings, and [examples](../examples/README.md) for a complete synthetic record. Version these contracts when changing a completed study.
