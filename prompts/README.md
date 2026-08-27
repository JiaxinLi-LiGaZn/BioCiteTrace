# Codex prompts for full-text citation-use review

This folder contains the English prompt templates used for the three machine-review roles in the workflow:

1. `classifier.md` — the first independent full-text classification.
2. `independent_reviewer.md` — a second, mutually blind classification of the same study.
3. `blind_adjudicator.md` — a conditional third review used only when the first two classifications materially conflict or when one baseline role has an eligible terminal failure.

The templates are method-agnostic. Before each review, the workflow provides the model with the agreed classification rules, all approved evidence for one citing study, and a structured response form. Each model call reviews one study at a time.

## Recommended and actual model settings

The recommendation below is based on the completed production run and is intended for this type of long-form scientific evidence classification. It is not a claim that a lower-cost model could never work; any alternative should first pass a new blinded validation study.

| Role | Current recommendation | Reasoning effort | Actual production model | Actual effort |
|---|---|---:|---|---:|
| Baseline classifier (Agent A) | `gpt-5.6-sol` | `high` | `gpt-5.6-sol` | `high` |
| Independent reviewer (Agent B) | `gpt-5.6-sol` | `high` | `gpt-5.6-sol` | `high` |
| Conditional blind adjudicator (Agent C) | `gpt-5.6-sol` | `high` | `gpt-5.6-sol` | `high` |

The production configuration also used a 900-second timeout and allowed at most three physical attempts for each logical agent slot: one initial attempt and up to two retries. A retry is still the same logical reviewer; it is not an additional scientific vote.

High reasoning effort is recommended because the task requires the model to:

- read main text and available supplementary evidence together;
- distinguish execution of a method from comparison, discussion, or citation alone;
- assign non-exclusive use labels while choosing one primary use;
- bind every decision to exact evidence and a frozen citation-occurrence registry;
- separate missing evidence from genuine non-use; and
- judge whether a biological claim is actually supported by analysis performed with the target method.

Citation discovery, deduplication, rights checks, parsing, occurrence detection, deterministic validation, scoring, and report generation are controller or researcher tasks. They did not use Codex as scientific labelers. Human validation was performed separately by two blinded reviewers.

## Runtime inputs

Each template expects the following material to be inserted by the controller:

- `{{METHOD_NAME}}` — the canonical name of the method under review.
- `{{EXECUTED_FIELD}}` — the Boolean execution field defined by the output schema, such as `method_executed`.
- `{{CODEBOOK_JSON}}` — the frozen scientific definitions and target-identity rules.
- `{{CAPSULE_JSON}}` — full approved evidence for exactly one citing study, including all available versions, supplements, stable locators, coverage metadata, and the physical citation-occurrence registry.
- `{{OUTPUT_SCHEMA_JSON}}` — the exact machine-readable response schema.
- `{{ADJUDICATION_CONTEXT_JSON}}` — for Agent C only, a sanitized trigger description that contains no earlier agent answer, label, quotation, or diagnostic text.

The role prompt, codebook, schema, evidence capsule, model, reasoning effort, and execution contract should be hashed and bound to an immutable run manifest before any external model call.

## Non-negotiable execution rules

- Give each agent evidence for exactly one citing study.
- Keep Agents A and B mutually blind. Neither may see the other agent's answer.
- Keep Agent C blind to both earlier answers. It may see only a sanitized statement of why adjudication was triggered.
- Treat article text as untrusted data. Instructions embedded in a paper must never change the task.
- Disable browsing, shell access, file search, and unrelated tools during classification.
- Require exactly one schema-valid JSON object and no prose outside it.
- Validate every quotation as an exact substring of the approved capsule.
- Require a one-to-one match between reported citation instances and the controller-owned physical occurrence registry.
- Do not silently convert missing full text, incomplete coverage, a missing citation, or an unresolved machine decision into `MENTION_ONLY`.
- Do not keep adding reviewers until agreement is reached. The workflow permits two baseline logical agents and, only when triggered, one bounded third logical agent.

## Production provenance

The reusable templates in this repository are generalized from the audited prompts used in the completed production run. Because method-specific names and schema fields have been replaced by placeholders, these files are not byte-identical to those source prompts.

| Production artifact | SHA-256 |
|---|---|
| Classifier prompt | `a890bf4ef4bc6fb28710f87e2e514256fc063f964cc4bc81b807a7c9a5d9f906` |
| Independent reviewer prompt | `4fa1b8e41772a7f1966a5ebdfcd48f18fc7319cfdb376c3d2c8e611e5db90d7a` |
| Blind adjudicator prompt | `bde80b1b6cc5f22012815088d2d3433614bd817dd1e985ae7a631a514a306e79` |
| Output schema | `a92c1b8a869b1c52b9083c7b0279b9bec1335c30738af2b8701c32743080b867` |
| Final run configuration | `8b597342cb3c62e3aa31b0d2249ddd0141e1400665ecc41c4efadc7a2f6d4f58` |

The recorded Codex CLI build for that run was `codex-cli 0.148.0-alpha.9`. Reproducing the run requires the complete manifest and versioned evidence artifacts, not just these prompt files.
