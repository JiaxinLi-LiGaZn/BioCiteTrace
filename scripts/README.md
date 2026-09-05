# Run the workflow

Run these commands from the repository root. Start with the fictional example before trying a real method.

## Install and try the example

Python 3.11 or newer is required. The core package has no third-party Python dependency.

```bash
git clone https://github.com/JiaxinLi-LiGaZn/BioCiteTrace.git
cd BioCiteTrace
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Install the optional PDF/XML readers when discovery and approved retrieval are needed:

```bash
python -m pip install -e '.[upstream]'
```

Rebuild the synthetic capsule from the plain-text article and rights manifest:

```bash
python scripts/build_capsule.py \
  --study examples/example_study.json \
  --method examples/example_method.json \
  --documents examples/example_documents.json \
  --output artifacts/example_study_capsule.json

python scripts/validate_output.py \
  --config config/example_config.json \
  --capsule artifacts/example_study_capsule.json \
  --result examples/example_classification.json
```

Render a complete prompt without contacting a model:

```bash
citation-use-review --project-root . assemble-prompt \
  --config config/example_config.json \
  --capsule artifacts/example_study_capsule.json \
  --role classifier \
  --output artifacts/example_classifier_prompt.txt
```

Run the actual two-reviewer workflow after checking the model, CLI version, permissions, expected cost, and configuration. This command makes external Codex calls:

```bash
python scripts/run_one_study.py \
  --config config/example_config.json \
  --capsule artifacts/example_study_capsule.json \
  --output-root artifacts/reviews
```

For a batch, make one capsule per study and list the capsule paths in an ordered JSONL manifest like [`example_capsules.jsonl`](../examples/example_capsules.jsonl):

```bash
python scripts/run_batch_review.py \
  --config config/example_config.json \
  --manifest examples/example_capsules.jsonl \
  --output-root artifacts/reviews \
  --workers 3
```

The classifier and reviewer for a study run as separate blind calls. Batch workers control how many study pipelines are active at once. A durable claim is written before each external transmission; if a process dies after that point but before a terminal record is written, the starter fails closed instead of silently resending the same logical review.

The full offline regression suite also needs the optional `upstream` dependencies above. Run it with:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The exact input fields and the boundary between upstream literature work and the runnable review core are described in [the input contract](../docs/INPUT_CONTRACT.md).

## Prepare a real corpus

Follow the [upstream workflow](../docs/UPSTREAM_WORKFLOW.md) for the exact commands and decision files:

1. `discover-citations`: collect and freeze citation-source records.
2. `apply-cluster-review`: resolve version and duplicate candidates into a new snapshot.
3. `prepare-rights-review`: prepare the download-permission queue.
4. `retrieve-approved`: retrieve and parse the approved documents.
5. `build-agent-handoff`: apply coverage and duplicate decisions, then write the capsule manifest.
6. `run-batch`: pass that manifest to the blind-review pipeline.

Use `citation-use-review --help` for the command index and a subcommand's `--help` for its arguments. The Python files here are small wrappers around the same interface.

## Score a human-validation sample

```bash
python scripts/score_human_validation.py \
  --input examples/example_human_scoring.csv \
  --output artifacts/example_human_metrics.json
```

The example is synthetic. A real analysis needs a completed [category scoring table](../human_reviewers/templates/blank_category_scoring_template.csv), with one row per study and category. See [human review](../human_reviewers/README.md) for sampling, consensus and scoring conventions.
