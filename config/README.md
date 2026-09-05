# Configure a review

[example_upstream_config.json](example_upstream_config.json) defines the target method, its seed-paper versions, enabled bibliographic sources and retrieval settings. Replace the placeholder identifiers before using it. OpenAlex is required; the other adapters can be configured separately.

[example_config.json](example_config.json) selects the codebook, schemas, prompts and Codex settings for machine review. All configured paths are resolved from the project root.

The supplied review configuration records the original `gpt-5.6-sol`, `high` reasoning setting, a 900-second timeout, up to two retries after the initial attempt, and three concurrent study pipelines. Each retry belongs to the same logical reviewer.

The exact CLI pin is `codex-cli 0.148.0-alpha.9`. A different installed version fails preflight. For a new environment, deliberately check and update the pin, command flags, supported structured-output schema, model availability and authentication before a small pilot. Offline tests do not establish compatibility with a live model service.

The controller limits assembled prompt size, disables unrelated agent features and records run hashes. A project still needs its own permission and transmission decisions before sending real article text for processing.

[Input contract](../docs/INPUT_CONTRACT.md) · [Upstream preparation](../docs/UPSTREAM_WORKFLOW.md) · [Run commands](../scripts/README.md)
