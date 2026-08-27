"""Deterministic comparison and bounded third-review acceptance rules."""

# Standard-library imports provide stable JSON projections and mapping types.
import json
from typing import Any, Mapping

from .errors import ContractError
from .util import canonical_json_bytes


DECISION_FIELDS = (
    "status",
    "primary_label",
    "biological_insight",
    "insight_role",
    "data_origin",
    "method_executed",
)


def _decision_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project a classification onto material scientific decision fields.

    Args:
        result: Validated classification.

    Returns:
        Stable decision mapping including a sorted multi-label set.
    """

    projection = {field: result.get(field) for field in DECISION_FIELDS}
    projection["use_labels"] = sorted(result.get("use_labels", []))
    return projection


def _occurrence_support(result: Mapping[str, Any]) -> dict[str, bool]:
    """Project physical occurrence IDs onto local use-support decisions.

    Args:
        result: Validated classification.

    Returns:
        Mapping from occurrence ID to ``supports_use``.
    """

    return {str(row["occurrence_id"]): bool(row["supports_use"]) for row in result.get("citation_instances", [])}


def _evidence_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    """Project non-decisional evidence presentation for audit-only variation.

    Args:
        result: Validated classification.

    Returns:
        Canonically sortable evidence and rationale fields.
    """

    return {
        "use_evidence": result.get("use_evidence", []),
        "insight_evidence": result.get("insight_evidence", []),
        "attribution_bridge": result.get("attribution_bridge", ""),
        "rationale": result.get("rationale", ""),
    }


def compare_classifications(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two independently validated classifications.

    Args:
        first: First blinded result.
        second: Second blinded result.

    Returns:
        Deterministic conflict tier, reasons, and material-conflict flag.
    """

    first_decision = _decision_projection(first)
    second_decision = _decision_projection(second)
    decision_differences = sorted(key for key in first_decision if first_decision[key] != second_decision[key])
    first_support = _occurrence_support(first)
    second_support = _occurrence_support(second)
    evidence_differences = ["occurrence_support"] if first_support != second_support else []
    assessment_differences = []
    if first.get("confidence") != second.get("confidence"):
        assessment_differences.append("confidence")
    if sorted(first.get("risk_codes", [])) != sorted(second.get("risk_codes", [])):
        assessment_differences.append("risk_codes")
    evidence_variation = canonical_json_bytes(_evidence_projection(first)) != canonical_json_bytes(_evidence_projection(second))
    if decision_differences:
        tier = "DECISION_CONFLICT"
    elif evidence_differences:
        tier = "EVIDENCE_CONFLICT"
    elif assessment_differences:
        tier = "ASSESSMENT_VARIATION"
    elif evidence_variation:
        tier = "EVIDENCE_VARIATION"
    else:
        tier = "EXACT_AGREEMENT"
    reasons = [
        *(f"decision:{field}" for field in decision_differences),
        *(f"evidence:{field}" for field in evidence_differences),
        *(f"assessment:{field}" for field in assessment_differences),
    ]
    if evidence_variation:
        reasons.append("variation:evidence_presentation")
    if not reasons:
        reasons = ["exact_agreement"]
    return {
        "comparison_tier": tier,
        "material_conflict": tier in {"DECISION_CONFLICT", "EVIDENCE_CONFLICT"},
        "reasons": reasons,
    }


def adjudication_acceptance(
    *,
    trigger: str,
    primary: Mapping[str, Any] | None,
    secondary: Mapping[str, Any] | None,
    adjudicator: Mapping[str, Any],
) -> str:
    """Apply the bounded blind third-review acceptance contract.

    Args:
        trigger: Material-conflict or single-baseline-failure trigger.
        primary: Valid Agent A result when available.
        secondary: Valid Agent B result when available.
        adjudicator: Valid fresh Agent C result.

    Returns:
        ``MACHINE_ADJUDICATED``, ``MACHINE_CONSENSUS``, or
        ``UNRESOLVED_SCIENTIFIC``.

    Raises:
        ContractError: If the trigger and available baseline results disagree.
    """

    agrees_primary = primary is not None and not compare_classifications(primary, adjudicator)["material_conflict"]
    agrees_secondary = secondary is not None and not compare_classifications(secondary, adjudicator)["material_conflict"]
    if trigger == "SECOND_REVIEW_FAILED":
        if primary is None or secondary is not None:
            raise ContractError("SECOND_REVIEW_FAILED requires only a primary result")
        return "MACHINE_CONSENSUS" if agrees_primary else "UNRESOLVED_SCIENTIFIC"
    if trigger == "PRIMARY_REVIEW_FAILED":
        if secondary is None or primary is not None:
            raise ContractError("PRIMARY_REVIEW_FAILED requires only a secondary result")
        return "MACHINE_CONSENSUS" if agrees_secondary else "UNRESOLVED_SCIENTIFIC"
    if trigger in {"DECISION_CONFLICT", "EVIDENCE_CONFLICT"}:
        if primary is None or secondary is None:
            raise ContractError("material-conflict adjudication requires two baseline results")
        return "MACHINE_ADJUDICATED" if agrees_primary ^ agrees_secondary else "UNRESOLVED_SCIENTIFIC"
    raise ContractError(f"unsupported adjudication trigger: {trigger}")


def choose_adjudicated_result(
    *,
    primary: Mapping[str, Any] | None,
    secondary: Mapping[str, Any] | None,
    adjudicator: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the baseline result uniquely supported by Agent C.

    Args:
        primary: Agent A result when available.
        secondary: Agent B result when available.
        adjudicator: Agent C result.

    Returns:
        A normalized baseline result when exactly one available baseline has no
        material conflict with C; otherwise ``None``.
    """

    matching = [
        result
        for result in (primary, secondary)
        if result is not None and not compare_classifications(result, adjudicator)["material_conflict"]
    ]
    if len(matching) != 1:
        return None
    return json.loads(canonical_json_bytes(matching[0]).decode("utf-8"))
