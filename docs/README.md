# The review workflow

BioCiteTrace asks how a citing study engages with a particular method. Titles and abstracts help us find studies, but the relevant evidence often sits in a methods paragraph, a figure caption or a supplement. The review therefore works from the available full text.

## From citations to study evidence

Start with the method's known preprint and published versions. Search their identifiers, then link and deduplicate the citing records. One scientific study is the counting unit, even when it has several records or files.

OpenAlex supplies the main citation graph. Europe PMC and OpenCitations provide additional citation checks; PubMed and Crossref enrich bibliographic identity. Every source response is retained with a timestamp and checksum. Uncertain version links require recorded decisions before a reviewed snapshot is frozen.

Retrieve approved full text and record which versions and supplements are available. After retrieval, check study identities, file integrity and duplicate files again. Incomplete evidence remains visible throughout the workflow.

The public parsers and literal-alias occurrence detector are a starting point. Real PDFs, numbered citations, author-year citations and supplements can need additional preparation and manual checking. Output validation checks the supplied occurrence registry; it cannot establish that the registry has found every citation.

[Follow the upstream procedure](UPSTREAM_WORKFLOW.md) · [Prepare the inputs](INPUT_CONTRACT.md)

## From evidence to classifications

Each study gets a self-contained evidence capsule. Two fresh LLM reviews receive the same evidence, without seeing each other's answers or other studies' results. The controller checks the structure of each answer, its quotations and its correspondence to registered citation occurrences.

A difference in wording does not require another vote. A material decision or evidence conflict, or one qualifying baseline failure, can trigger a third blind assessment. If the assessments still do not support a resolution, the study stays unresolved. Retries belong to the same reviewer slot; there is no fourth scientific reviewer.

An exact quotation check establishes that text exists in the capsule. The scientific interpretation still needs review.

[Classification rules](../codebook/README.md) · [Review prompts](../prompts/README.md) · [Execution and saved state](../src/citation_use_review/README.md)

## From classifications to a study result

Freeze the machine results before selecting and showing the human-validation sample. Two reviewers work independently, then discuss disagreements to establish reference labels. Sampling should cover the use categories and also examine unresolved evidence states. Keep those process-audit cases distinct when estimating classification performance.

Report the denominator for every result: discovered records, unique studies, reviewed studies, classified studies or a human-validation subset. Preserve non-exclusive labels when estimating any-use categories. A primary-category display answers a different question.

Treat biological-insight assignments as machine-supported candidates until checked. A method producing a useful representation is not by itself evidence of a biological discovery.

[Human review and scoring](../human_reviewers/README.md) · [Current results and scope](../results/README.md)

## Repeating or extending the workflow

A new target method needs its own identity definition, citation snapshot, full-text preparation and scientific calibration. Freeze new versions of the codebook, schema and prompts before changing a completed run. Keep the human-validation set separate from later prompt refinement.

Publish the structured records and provenance that can be shared, while retaining or deleting source full text according to its applicable terms. The public repository contains a reusable starter and an illustrative results snapshot; the complete original production corpus is not included.

[Run the example](../scripts/README.md) · [Configuration](../config/README.md) · [Data formats](../schemas/README.md) · [Offline tests](../tests/README.md)
