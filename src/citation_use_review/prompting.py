"""Assemble role prompts from frozen files and one validated capsule."""

# Standard-library imports provide JSON rendering, path handling, hashing, and placeholder checks.
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .contracts import validate_capsule
from .errors import ContractError
from .util import canonical_json_bytes, load_json, resolve_project_path, sha256_bytes, sha256_file


ROLE_PATH_KEYS = {
    "classifier": "classifier_prompt",
    "reviewer": "reviewer_prompt",
    "adjudicator": "adjudicator_prompt",
}
BLIND_ADJUDICATION_CONTEXT = {
    "mode": "BLIND_INDEPENDENT_REVIEW",
    "reason": "A further independent assessment is required before the study can be resolved.",
}


def load_contract_files(project_root: Path, config: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the frozen codebook and classification schema configured for a run.

    Args:
        project_root: Repository root.
        config: Decoded workflow configuration.

    Returns:
        ``(codebook, schema)`` dictionaries.
    """

    paths = config.get("paths")
    if not isinstance(paths, Mapping):
        raise ContractError("config.paths must be an object")
    codebook = load_json(resolve_project_path(project_root, str(paths.get("codebook", ""))))
    schema = load_json(resolve_project_path(project_root, str(paths.get("classification_schema", ""))))
    if not isinstance(codebook, dict) or not isinstance(schema, dict):
        raise ContractError("codebook and schema must be JSON objects")
    return codebook, schema


def assemble_prompt(
    *,
    project_root: Path,
    config: Mapping[str, Any],
    capsule: Mapping[str, Any],
    role: str,
    adjudication_context: Mapping[str, Any] | None = None,
) -> str:
    """Render one standalone prompt for one role and one study.

    Args:
        project_root: Repository root used for configured paths.
        config: Workflow configuration.
        capsule: Candidate one-study evidence capsule.
        role: ``classifier``, ``reviewer``, or ``adjudicator``.
        adjudication_context: Sanitized trigger-only context for the adjudicator.

    Returns:
        Fully assembled prompt text with no unresolved placeholders.

    Raises:
        ContractError: If configuration, role, capsule, or placeholders are invalid.
    """

    if role not in ROLE_PATH_KEYS:
        raise ContractError(f"unsupported role: {role}")
    codebook, schema = load_contract_files(project_root, config)
    normalized_capsule = validate_capsule(capsule, codebook)
    paths = config["paths"]
    prompt_path = resolve_project_path(project_root, str(paths.get(ROLE_PATH_KEYS[role], "")))
    try:
        template = prompt_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractError(f"cannot read prompt template {prompt_path}: {error}") from error
    replacements = {
        "{{METHOD_NAME}}": normalized_capsule["target_method"]["canonical_name"],
        "{{EXECUTED_FIELD}}": "method_executed",
        "{{CODEBOOK_JSON}}": json.dumps(codebook, indent=2, sort_keys=True, ensure_ascii=False),
        "{{CAPSULE_JSON}}": json.dumps(normalized_capsule, indent=2, sort_keys=True, ensure_ascii=False),
        "{{OUTPUT_SCHEMA_JSON}}": json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False),
    }
    if role == "adjudicator":
        if not isinstance(adjudication_context, Mapping) or dict(adjudication_context) != BLIND_ADJUDICATION_CONTEXT:
            raise ContractError("adjudicator requires the exact sanitized, answer-free context")
        replacements["{{ADJUDICATION_CONTEXT_JSON}}"] = json.dumps(BLIND_ADJUDICATION_CONTEXT, indent=2, sort_keys=True)
    for placeholder, replacement in replacements.items():
        template = template.replace(placeholder, replacement)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", template)))
    if unresolved:
        raise ContractError(f"prompt contains unresolved placeholders: {unresolved}")
    return template


def prompt_contract(project_root: Path, config: Mapping[str, Any], capsule: Mapping[str, Any], role: str, prompt: str) -> dict[str, str]:
    """Return hashes that bind one rendered prompt to its configured inputs.

    Args:
        project_root: Repository root.
        config: Workflow configuration.
        capsule: Validated capsule embedded in the prompt.
        role: Agent role.
        prompt: Fully rendered prompt.

    Returns:
        Mapping of role, prompt, capsule, codebook, schema, and template hashes.
    """

    paths = config["paths"]
    template = resolve_project_path(project_root, str(paths[ROLE_PATH_KEYS[role]]))
    return {
        "role": role,
        "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        "capsule_sha256": sha256_bytes(canonical_json_bytes(capsule)),
        "template_sha256": sha256_file(template),
        "codebook_sha256": sha256_file(resolve_project_path(project_root, str(paths["codebook"]))),
        "schema_sha256": sha256_file(resolve_project_path(project_root, str(paths["classification_schema"]))),
    }
