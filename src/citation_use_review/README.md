# Inside the implementation

| Modules | Responsibility |
| --- | --- |
| `sources.py`, `bibliography.py`, `upstream.py` | Source adapters, record reconciliation, study clustering and immutable snapshots. |
| `rights.py` | Review queues, approved retrieval, basic parsing, duplicate checks and agent handoff. |
| `capsule.py` | Plain-text paragraphs and literal-alias occurrence registration. |
| `contracts.py` | Structural, evidence, locator and label consistency checks. |
| `prompting.py` | One-study prompt assembly and contract hashes. |
| `runner.py`, `pipeline.py`, `comparison.py` | Blind reviewer calls, saved execution state, deterministic comparison and bounded third review. |
| `scoring.py` | Category-wise metrics against supplied human consensus. |
| `cli.py` | The command-line interface used by the small script wrappers. |
| `util.py`, `errors.py` | File operations, hashing, path checks and typed errors. |

## Review and resume behavior

A study gets two separate baseline calls. A conditional third review receives the same study evidence and a generic trigger description, without earlier answers. Agreement is decided from the scientific fields and occurrence-level use support; variation in wording or evidence presentation is retained without necessarily reopening review.

Each role writes a durable claim before an external transmission and a terminal record afterward. If a claim exists without a terminal record, the runner refuses to silently resend. A terminal with a matching contract can be reused. Hash checks reject stale inputs and completed results.

The batch runner checks unique study IDs, runs a bounded number of study pipelines and writes ordered `batch_results.jsonl`. Per-study records retain the role outcomes and the final classification or unresolved state. Its default concurrency is three studies; reviewer retries do not add scientific votes.

## Scope of the public implementation

The parsers and citation detector are deliberately basic. They do not provide complete OCR, reference-to-marker resolution or automatic supplement discovery. Corpus preparation needs manual coverage checks. The public scoring module consumes a completed consensus table; it does not create the sampling plan, perform human adjudication or build a manuscript report.

[How to run it](../../scripts/README.md) · [Offline tests](../../tests/README.md) · [Scientific workflow](../../docs/README.md)
