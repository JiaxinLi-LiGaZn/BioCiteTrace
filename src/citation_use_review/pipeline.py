"""Orchestrate mutually blind A/B review and one bounded third review."""

# Standard-library imports provide concurrency, stable paths, and typed orchestration records.
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .comparison import adjudication_acceptance, choose_adjudicated_result, compare_classifications
from .contracts import validate_capsule
from .errors import CitationReviewError, ContractError
from .prompting import BLIND_ADJUDICATION_CONTEXT, assemble_prompt, load_contract_files
from .runner import preflight_codex, run_codex_role
from .util import atomic_write_json, atomic_write_text, canonical_json_bytes, load_json, resolve_project_path, sha256_bytes, sha256_file, utc_now


PIPELINE_VERSION = "1.0.0"


def _safe_study_component(study_id: str) -> str:
    """Convert a study ID into a nonempty filesystem-safe component.

    Args:
        study_id: Stable study identifier.

    Returns:
        Safe component containing letters, digits, dots, underscores, or hyphens.
    """

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", study_id).strip("._")
    if not safe:
        raise ContractError("study_id cannot be converted to a safe path component")
    return safe[:180]


def _run_contract(
    project_root: Path,
    config: Mapping[str, Any],
    *,
    config_sha256: str,
    capsule_sha256: str,
) -> dict[str, str]:
    """Hash every public file that determines one study run.

    Args:
        project_root: Repository root.
        config: Decoded configuration.
        config_sha256: Stable hash checked before and after config decoding.
        capsule_sha256: Stable hash checked before and after capsule decoding.

    Returns:
        Hash mapping used to reject stale aggregate results.
    """

    paths = config["paths"]
    result = {
        "pipeline_version": PIPELINE_VERSION,
        "config_sha256": config_sha256,
        "capsule_sha256": capsule_sha256,
    }
    for key in ("codebook", "classification_schema", "capsule_schema", "classifier_prompt", "reviewer_prompt", "adjudicator_prompt"):
        configured = resolve_project_path(project_root, str(paths[key]))
        result[f"{key}_sha256"] = sha256_file(configured)
    result["run_contract_sha256"] = sha256_bytes(canonical_json_bytes(result))
    return result


def _result_or_none(terminal: Mapping[str, Any]) -> dict[str, Any] | None:
    """Extract a successful result from a role terminal.

    Args:
        terminal: Role terminal record.

    Returns:
        Result dictionary for ``SUCCESS``; otherwise ``None``.
    """

    result = terminal.get("result")
    return dict(result) if terminal.get("terminal_status") == "SUCCESS" and isinstance(result, Mapping) else None


def _derive_review_state(
    baseline: Mapping[str, Mapping[str, Any]],
    adjudicator_terminal: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Derive deterministic comparison, trigger, terminal status, and final result.

    Args:
        baseline: Validated classifier and reviewer terminal records.
        adjudicator_terminal: Validated third-role terminal when that slot was opened.

    Returns:
        Scientific state derived only from the role terminals. An empty terminal
        status means that a third role is required but has not yet run.
    """

    primary = _result_or_none(baseline["classifier"])
    secondary = _result_or_none(baseline["reviewer"])
    comparison: dict[str, Any] | None = None
    trigger = "NOT_TRIGGERED"
    final_status = ""
    final_classification: dict[str, Any] | None = None
    if primary is not None and secondary is not None:
        comparison = compare_classifications(primary, secondary)
        if not comparison["material_conflict"]:
            final_status = "TWO_AGENT_NO_MATERIAL_CONFLICT"
            final_classification = primary
        else:
            trigger = str(comparison["comparison_tier"])
    elif primary is not None:
        trigger = "SECOND_REVIEW_FAILED"
    elif secondary is not None:
        trigger = "PRIMARY_REVIEW_FAILED"
    else:
        final_status = "UNRESOLVED_BASELINE_FAILED"
    if trigger != "NOT_TRIGGERED" and adjudicator_terminal is not None:
        adjudicator = _result_or_none(adjudicator_terminal)
        if adjudicator is None:
            final_status = "UNRESOLVED_ADJUDICATOR_FAILED"
        else:
            final_status = adjudication_acceptance(
                trigger=trigger,
                primary=primary,
                secondary=secondary,
                adjudicator=adjudicator,
            )
            if final_status == "MACHINE_CONSENSUS":
                final_classification = primary if primary is not None else secondary
            elif final_status == "MACHINE_ADJUDICATED":
                final_classification = choose_adjudicated_result(
                    primary=primary,
                    secondary=secondary,
                    adjudicator=adjudicator,
                )
    return {
        "comparison": comparison,
        "adjudication_trigger": trigger,
        "terminal_status": final_status,
        "final_classification": final_classification,
    }


def run_one_study(
    *,
    project_root: Path,
    config_path: Path,
    capsule_path: Path,
    output_root: Path,
    skip_preflight: bool = False,
    expected_config_sha256: str | None = None,
    expected_capsule_sha256: str | None = None,
) -> dict[str, Any]:
    """Run or resume the complete bounded machine review for one study.

    Args:
        project_root: Repository root.
        config_path: JSON configuration path.
        capsule_path: One-study capsule JSON path.
        output_root: Root for private claims, terminals, and aggregate output.
        skip_preflight: Skip repeated CLI version preflight when a batch already ran it.
        expected_config_sha256: Optional batch-frozen configuration hash.
        expected_capsule_sha256: Optional batch-frozen capsule hash.

    Returns:
        Aggregate machine-review record containing both baseline terminals,
        optional third-review terminal, comparison, final status, and final result.
    """

    root = project_root.resolve()
    config_sha256 = sha256_file(config_path)
    config = load_json(config_path)
    if sha256_file(config_path) != config_sha256 or (expected_config_sha256 is not None and config_sha256 != expected_config_sha256):
        raise ContractError("configuration changed after the run was prepared")
    if not isinstance(config, Mapping):
        raise ContractError("configuration must be a JSON object")
    if not skip_preflight:
        preflight_codex(config)
    codebook, _schema = load_contract_files(root, config)
    capsule_sha256 = sha256_file(capsule_path)
    capsule = validate_capsule(load_json(capsule_path), codebook)
    if sha256_file(capsule_path) != capsule_sha256 or (expected_capsule_sha256 is not None and capsule_sha256 != expected_capsule_sha256):
        raise ContractError("capsule changed after the run was prepared")
    contract = _run_contract(
        root,
        config,
        config_sha256=config_sha256,
        capsule_sha256=capsule_sha256,
    )
    study_id = capsule["study"]["study_id"]
    study_directory = output_root.resolve() / _safe_study_component(study_id)
    aggregate_path = study_directory / "review_record.json"
    prompts = {
        "classifier": assemble_prompt(project_root=root, config=config, capsule=capsule, role="classifier"),
        "reviewer": assemble_prompt(project_root=root, config=config, capsule=capsule, role="reviewer"),
    }

    def baseline_job(role: str) -> tuple[str, dict[str, Any]]:
        """Run one baseline role in its own durable state directory.

        Args:
            role: ``classifier`` or ``reviewer``.

        Returns:
            Role name and its immutable terminal record.
        """

        terminal = run_codex_role(
            project_root=root,
            config=config,
            capsule=capsule,
            codebook=codebook,
            prompt=prompts[role],
            role=role,
            output_directory=study_directory / "roles" / role,
        )
        return role, terminal

    if aggregate_path.exists():
        aggregate = load_json(aggregate_path)
        expected_fields = {
            "pipeline_version", "created_at", "study_id", "run_contract", "baseline", "comparison",
            "adjudication_trigger", "adjudicator", "terminal_status", "final_classification", "human_validated",
        }
        if not isinstance(aggregate, dict) or set(aggregate) != expected_fields or aggregate.get("run_contract") != contract:
            raise ContractError(f"stale or malformed aggregate review record: {aggregate_path}")
        if aggregate.get("pipeline_version") != PIPELINE_VERSION or aggregate.get("study_id") != study_id or aggregate.get("human_validated") is not False:
            raise ContractError(f"aggregate identity or validation state is invalid: {aggregate_path}")
        baseline_paths = {role: study_directory / "roles" / role / "terminal.json" for role in ("classifier", "reviewer")}
        if not all(path.is_file() for path in baseline_paths.values()):
            raise ContractError("aggregate exists without both baseline terminal files")
        baseline = {role: baseline_job(role)[1] for role in ("classifier", "reviewer")}
        initial_state = _derive_review_state(baseline, None)
        adjudicator_terminal: dict[str, Any] | None = None
        adjudicator_path = study_directory / "roles" / "adjudicator" / "terminal.json"
        if initial_state["adjudication_trigger"] != "NOT_TRIGGERED":
            if not adjudicator_path.is_file():
                raise ContractError("aggregate requires adjudication but its terminal file is missing")
            adjudicator_prompt = assemble_prompt(
                project_root=root,
                config=config,
                capsule=capsule,
                role="adjudicator",
                adjudication_context=BLIND_ADJUDICATION_CONTEXT,
            )
            adjudicator_terminal = run_codex_role(
                project_root=root,
                config=config,
                capsule=capsule,
                codebook=codebook,
                prompt=adjudicator_prompt,
                role="adjudicator",
                output_directory=study_directory / "roles" / "adjudicator",
            )
        elif adjudicator_path.exists() or aggregate.get("adjudicator") is not None:
            raise ContractError("aggregate contains an untriggered adjudicator state")
        derived = _derive_review_state(baseline, adjudicator_terminal)
        expected_scientific = {
            "baseline": baseline,
            "comparison": derived["comparison"],
            "adjudication_trigger": derived["adjudication_trigger"],
            "adjudicator": adjudicator_terminal,
            "terminal_status": derived["terminal_status"],
            "final_classification": derived["final_classification"],
        }
        if any(aggregate.get(key) != value for key, value in expected_scientific.items()):
            raise ContractError(f"aggregate does not match its validated role terminals: {aggregate_path}")
        return aggregate

    baseline: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(baseline_job, role): role for role in ("classifier", "reviewer")}
        for future in as_completed(futures):
            role, terminal = future.result()
            baseline[role] = terminal
    adjudicator_terminal: dict[str, Any] | None = None
    derived = _derive_review_state(baseline, None)
    if derived["adjudication_trigger"] != "NOT_TRIGGERED":
        adjudicator_prompt = assemble_prompt(
            project_root=root,
            config=config,
            capsule=capsule,
            role="adjudicator",
            adjudication_context=BLIND_ADJUDICATION_CONTEXT,
        )
        adjudicator_terminal = run_codex_role(
            project_root=root,
            config=config,
            capsule=capsule,
            codebook=codebook,
            prompt=adjudicator_prompt,
            role="adjudicator",
            output_directory=study_directory / "roles" / "adjudicator",
        )
        derived = _derive_review_state(baseline, adjudicator_terminal)
    aggregate = {
        "pipeline_version": PIPELINE_VERSION,
        "created_at": utc_now(),
        "study_id": study_id,
        "run_contract": contract,
        "baseline": baseline,
        "comparison": derived["comparison"],
        "adjudication_trigger": derived["adjudication_trigger"],
        "adjudicator": adjudicator_terminal,
        "terminal_status": derived["terminal_status"],
        "final_classification": derived["final_classification"],
        "human_validated": False,
    }
    atomic_write_json(aggregate_path, aggregate)
    return aggregate


def _load_capsule_manifest(path: Path) -> list[Path]:
    """Load an ordered JSONL manifest of capsule paths.

    Args:
        path: JSONL file whose rows contain a nonempty ``capsule_path``.

    Returns:
        Ordered capsule paths resolved relative to the manifest directory.
    """

    rows: list[Path] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"invalid manifest JSON on line {line_number}") from error
        if not isinstance(row, Mapping) or not isinstance(row.get("capsule_path"), str) or not row["capsule_path"]:
            raise ContractError(f"manifest line {line_number} lacks capsule_path")
        candidate = Path(row["capsule_path"])
        rows.append((path.parent / candidate).resolve() if not candidate.is_absolute() else candidate.resolve())
    if not rows or len(rows) != len(set(rows)):
        raise ContractError("capsule manifest must be nonempty and contain unique paths")
    return rows


def run_batch(
    *,
    project_root: Path,
    config_path: Path,
    manifest_path: Path,
    output_root: Path,
    max_workers: int | None = None,
) -> list[dict[str, Any]]:
    """Run independent one-study pipelines with bounded study-level concurrency.

    Args:
        project_root: Repository root.
        config_path: JSON configuration path.
        manifest_path: Ordered JSONL capsule manifest.
        output_root: Root for per-study state and final ordered JSONL.
        max_workers: Optional override for concurrent study pipelines.

    Returns:
        Ordered aggregate or error rows, one per manifest entry.
    """

    config_sha256 = sha256_file(config_path)
    config = load_json(config_path)
    if sha256_file(config_path) != config_sha256:
        raise ContractError("configuration changed while the batch was being prepared")
    if not isinstance(config, Mapping):
        raise ContractError("configuration must be a JSON object")
    capsules = _load_capsule_manifest(manifest_path)
    codebook, _schema = load_contract_files(project_root.resolve(), config)
    frozen_capsules: list[tuple[Path, str]] = []
    study_ids: set[str] = set()
    for capsule_path in capsules:
        digest = sha256_file(capsule_path)
        capsule = validate_capsule(load_json(capsule_path), codebook)
        if sha256_file(capsule_path) != digest:
            raise ContractError(f"capsule changed while the batch was being prepared: {capsule_path}")
        study_id = capsule["study"]["study_id"]
        if study_id in study_ids:
            raise ContractError(f"capsule manifest contains duplicate study_id: {study_id}")
        study_ids.add(study_id)
        frozen_capsules.append((capsule_path, digest))
    preflight_codex(config)
    configured_workers = int(config.get("batch", {}).get("max_workers", 1))
    workers = max_workers if max_workers is not None else configured_workers
    if workers < 1 or workers > 64:
        raise ContractError("batch worker count must be between 1 and 64")
    ordered: list[dict[str, Any] | None] = [None] * len(capsules)

    def job(index: int, capsule_path: Path, capsule_sha256: str) -> tuple[int, dict[str, Any]]:
        """Run one indexed study and convert typed failures into an explicit row.

        Args:
            index: Zero-based position in the frozen capsule manifest.
            capsule_path: One-study capsule path for this task.
            capsule_sha256: Batch-frozen hash checked again by the study runner.

        Returns:
            Original position and either a review aggregate or explicit error row.
        """

        try:
            result = run_one_study(
                project_root=project_root,
                config_path=config_path,
                capsule_path=capsule_path,
                output_root=output_root,
                skip_preflight=True,
                expected_config_sha256=config_sha256,
                expected_capsule_sha256=capsule_sha256,
            )
            return index, result
        except CitationReviewError as error:
            return index, {"capsule_path": str(capsule_path), "terminal_status": "PIPELINE_ERROR", "error": type(error).__name__}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(job, index, capsule_path, capsule_sha256)
            for index, (capsule_path, capsule_sha256) in enumerate(frozen_capsules)
        ]
        for future in as_completed(futures):
            index, result = future.result()
            ordered[index] = result
    results = [row for row in ordered if row is not None]
    text = "".join(canonical_json_bytes(row).decode("utf-8") + "\n" for row in results)
    atomic_write_text(output_root / "batch_results.jsonl", text)
    return results
