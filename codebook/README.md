# What counts as use?

The definitions used by the code live in [citation_use_codebook.json](citation_use_codebook.json). The counting unit is one citing study.

| Label | Meaning |
| --- | --- |
| `APPLY_BIOLOGICAL` | the method is run on biological data as part of a scientific analysis. |
| `EXTEND_DEVELOP` | the study modifies, adapts, trains, or builds upon the method. |
| `BENCHMARK_EVALUATE` | the study evaluates the method or compares it with other approaches. |
| `OTHER_EXECUTED_USE` | the method is executed in a way not captured by the categories above. |
| `MENTION_ONLY` | the method is cited or discussed but is not used in the reported analysis. |

## Several purposes can coexist

A study can apply a method to biological data and also extend it. The four execution labels are non-exclusive; `MENTION_ONLY` excludes all of them. Background discussion, related work and proposed future use do not establish execution. Directly evidenced use of a method's outputs can count as execution.

The optional single-label summary follows a fixed priority: `APPLY_BIOLOGICAL`, `EXTEND_DEVELOP`, `BENCHMARK_EVALUATE`, then `OTHER_EXECUTED_USE`. It is a display convention, not a separate judgment about which purpose dominates the paper. A primary benchmark fraction therefore does not count every paper with any benchmark use.

## Biological interpretation is a separate question

A positive biological-insight assignment requires execution on biological data, a concrete biological interpretation, and evidence connecting the method's output to that interpretation. Improved prediction or benchmark performance alone is insufficient.

The result also records data origin, the method's role in the interpretation, supporting passages and uncertainty. See the [output format](../schemas/README.md).

## Incomplete evidence is not non-use

- `COVERAGE_INCOMPLETE`: missing or unreadable evidence could change the assessment.
- `CITATION_NOT_LOCATED`: coverage was marked adequate, but the target citation was not located.
- Machine review can also terminate without a defensible consensus; these operational and scientific states are recorded by the runner.

Do not turn any of these into `MENTION_ONLY`. Freeze a new codebook version if definitions change, and validate against a fresh or held-out human sample.
