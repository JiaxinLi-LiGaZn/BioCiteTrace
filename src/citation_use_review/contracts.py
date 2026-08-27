"""Deterministic scientific validation for capsules and agent outputs."""

# Standard-library imports support deep copying through canonical JSON and strict types.
import json
import re
from typing import Any, Mapping

from .errors import ContractError
from .util import canonical_json_bytes


STATUSES = {"CLASSIFIED", "CITATION_NOT_LOCATED", "COVERAGE_INCOMPLETE"}
USE_LABELS = {"APPLY_BIOLOGICAL", "EXTEND_DEVELOP", "BENCHMARK_EVALUATE", "OTHER_EXECUTED_USE", "MENTION_ONLY"}
EXECUTION_LABELS = USE_LABELS - {"MENTION_ONLY"}
PRIMARY_LABELS = USE_LABELS | {"UNRESOLVED"}
INSIGHT_VALUES = {"YES", "NO", "UNCLEAR"}
INSIGHT_ROLES = {"DIRECT", "ENABLING", "CORROBORATIVE", "NONE"}
DATA_ORIGINS = {"NEW_EXPERIMENTAL", "PUBLIC_OR_PRIOR", "MIXED", "SYNTHETIC_ONLY", "UNREPORTED_OR_NOT_APPLICABLE", "NONE"}
CONFIDENCE_VALUES = {"HIGH", "MEDIUM", "LOW"}
CONTEXT_TYPES = {"INTRODUCTION", "METHODS", "RESULTS", "DISCUSSION", "FIGURE_TABLE", "SUPPLEMENT", "REFERENCES", "OTHER"}
CLASSIFICATION_FIELDS = {
    "status", "study_id", "use_labels", "primary_label", "biological_insight", "insight_role", "data_origin",
    "confidence", "method_executed", "citation_instances", "use_evidence", "insight_evidence", "attribution_bridge",
    "risk_codes", "rationale",
}
EVIDENCE_FIELDS = {"quote", "section", "page_index", "printed_page", "paragraph_id", "source_file"}
USE_EVIDENCE_FIELDS = EVIDENCE_FIELDS | {"supports_labels"}
CITATION_INSTANCE_FIELDS = EVIDENCE_FIELDS | {
    "instance_id", "occurrence_id", "citation_marker", "reference_id", "context_type", "supports_use", "description"
}


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    """Require an object to contain exactly a frozen set of fields.

    Args:
        value: Object to inspect.
        expected: Exact allowed and required keys.
        label: Human-readable object name used in errors.

    Returns:
        ``None`` when the field set matches.

    Raises:
        ContractError: If fields are missing or unexpected.
    """

    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise ContractError(f"{label} fields mismatch; missing={missing}, unexpected={unexpected}")


def _require_string(value: Any, label: str, *, allow_empty: bool = False, maximum: int = 4000) -> str:
    """Validate a bounded string field.

    Args:
        value: Candidate field value.
        label: Field name used in errors.
        allow_empty: Whether the empty string is permitted.
        maximum: Maximum character count.

    Returns:
        The validated string.

    Raises:
        ContractError: If the value is not a permitted string.
    """

    if not isinstance(value, str) or (not allow_empty and not value) or len(value) > maximum:
        raise ContractError(f"{label} must be a bounded string")
    return value


def _require_enum(value: Any, allowed: set[str], label: str) -> str:
    """Validate one string enumeration value.

    Args:
        value: Candidate value.
        allowed: Permitted strings.
        label: Field name used in errors.

    Returns:
        The validated string.
    """

    if not isinstance(value, str) or value not in allowed:
        raise ContractError(f"{label} must be one of {sorted(allowed)}")
    return value


def _paragraph_index(capsule: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index capsule paragraphs by source file and paragraph ID.

    Args:
        capsule: Validated or candidate one-study capsule.

    Returns:
        Mapping from ``(source_file, paragraph_id)`` to section records.
    """

    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for document in capsule.get("documents", []):
        source_file = str(document.get("source_file", ""))
        for section in document.get("sections", []):
            key = (source_file, str(section.get("paragraph_id", "")))
            if key in result:
                raise ContractError(f"duplicate paragraph locator: {key}")
            result[key] = section
    return result


def validate_capsule(value: Any, codebook: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one complete, rights-approved study evidence capsule.

    Args:
        value: Decoded candidate capsule.
        codebook: Optional frozen codebook used to validate coverage risk codes.

    Returns:
        A JSON-normalized copy of the capsule.

    Raises:
        ContractError: If identity, rights, coverage, locator, or occurrence invariants fail.
    """

    if not isinstance(value, Mapping):
        raise ContractError("capsule must be a JSON object")
    required = {"capsule_version", "study", "target_method", "evidence_complete", "coverage_risk_codes", "version_coverage", "documents", "physical_target_occurrences"}
    _require_exact_fields(value, required, "capsule")
    if value["capsule_version"] != "1.0.0":
        raise ContractError("unsupported capsule_version")
    study = value["study"]
    method = value["target_method"]
    if not isinstance(study, Mapping) or set(study) != {"study_id", "title", "identifiers"}:
        raise ContractError("study must contain study_id, title, and identifiers")
    _require_string(study["study_id"], "study.study_id", maximum=256)
    _require_string(study["title"], "study.title", maximum=1000)
    if not isinstance(study["identifiers"], Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in study["identifiers"].items()):
        raise ContractError("study.identifiers must map strings to strings")
    if not isinstance(method, Mapping) or set(method) != {"canonical_name", "aliases", "seed_identifiers"}:
        raise ContractError("target_method fields are invalid")
    canonical_name = _require_string(method["canonical_name"], "target_method.canonical_name", maximum=300)
    aliases = method["aliases"]
    if not isinstance(aliases, list) or not aliases or len(set(aliases)) != len(aliases):
        raise ContractError("target_method.aliases must be a nonempty unique list")
    if canonical_name not in aliases or not all(isinstance(alias, str) and len(alias.strip()) >= 2 for alias in aliases):
        raise ContractError("aliases must include the canonical method name and contain nontrivial strings")
    if len({alias.casefold() for alias in aliases}) != len(aliases):
        raise ContractError("target_method.aliases must also be unique after case folding")
    if not isinstance(method["seed_identifiers"], Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in method["seed_identifiers"].items()):
        raise ContractError("target_method.seed_identifiers must map strings to strings")
    if not isinstance(value["evidence_complete"], bool):
        raise ContractError("evidence_complete must be Boolean")
    risks = value["coverage_risk_codes"]
    if not isinstance(risks, list) or len(set(risks)) != len(risks) or not all(isinstance(item, str) for item in risks):
        raise ContractError("coverage_risk_codes must be a unique string list")
    if value["evidence_complete"] and risks:
        raise ContractError("complete evidence cannot retain coverage risk codes")
    if not value["evidence_complete"] and not risks:
        raise ContractError("incomplete evidence requires at least one coverage risk code")
    if codebook is not None:
        allowed_risks = set(codebook.get("risk_codes", []))
        if not set(risks) <= allowed_risks:
            raise ContractError("capsule contains coverage risks absent from the frozen codebook")
    coverage = value["version_coverage"]
    if not isinstance(coverage, list) or not coverage:
        raise ContractError("version_coverage must be a nonempty list")
    included_versions: set[str] = set()
    for index, row in enumerate(coverage):
        if not isinstance(row, Mapping) or set(row) != {"version_id", "version_type", "included", "reason"}:
            raise ContractError(f"version_coverage[{index}] fields are invalid")
        version_id = _require_string(row["version_id"], f"version_coverage[{index}].version_id")
        _require_enum(row["version_type"], {"PREPRINT", "PUBLISHED", "OTHER"}, f"version_coverage[{index}].version_type")
        if not isinstance(row["included"], bool) or not isinstance(row["reason"], str):
            raise ContractError(f"version_coverage[{index}] has invalid included/reason values")
        if row["included"]:
            included_versions.add(version_id)
    documents = value["documents"]
    if not isinstance(documents, list) or not documents:
        raise ContractError("documents must be a nonempty list")
    document_fields = {"source_file", "document_type", "version_id", "license", "cloud_processing_allowed", "sha256", "sections"}
    seen_files: set[str] = set()
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            raise ContractError(f"documents[{index}] must be an object")
        _require_exact_fields(document, document_fields, f"documents[{index}]")
        source_file = _require_string(document["source_file"], f"documents[{index}].source_file", maximum=500)
        if source_file in seen_files:
            raise ContractError(f"duplicate source_file: {source_file}")
        seen_files.add(source_file)
        _require_enum(document["document_type"], {"MAIN", "SUPPLEMENT"}, f"documents[{index}].document_type")
        if document["version_id"] not in included_versions:
            raise ContractError(f"document version is not included in version_coverage: {document['version_id']}")
        _require_string(document["license"], f"documents[{index}].license")
        if document["cloud_processing_allowed"] is not True:
            raise ContractError("every transmitted document must explicitly allow cloud processing")
        if not isinstance(document["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", document["sha256"]):
            raise ContractError(f"documents[{index}].sha256 is invalid")
        if not isinstance(document["sections"], list) or not document["sections"]:
            raise ContractError(f"documents[{index}].sections must be nonempty")
        for section_index, section in enumerate(document["sections"]):
            expected_section = {"section", "page_index", "printed_page", "paragraph_id", "text"}
            if not isinstance(section, Mapping):
                raise ContractError("document section must be an object")
            _require_exact_fields(section, expected_section, f"documents[{index}].sections[{section_index}]")
            _require_string(section["paragraph_id"], "paragraph_id", maximum=500)
            _require_string(section["text"], "section text", maximum=2_000_000)
            if not isinstance(section["section"], str) or not isinstance(section["printed_page"], str):
                raise ContractError("section and printed_page must be strings")
            if section["page_index"] is not None and (not isinstance(section["page_index"], int) or isinstance(section["page_index"], bool) or section["page_index"] < 0):
                raise ContractError("page_index must be null or a nonnegative integer")
    paragraphs = _paragraph_index(value)
    occurrences = value["physical_target_occurrences"]
    if not isinstance(occurrences, list):
        raise ContractError("physical_target_occurrences must be a list")
    occurrence_fields = {"occurrence_id", "citation_marker", "reference_id", "source_file", "section", "page_index", "printed_page", "paragraph_id", "quote"}
    seen_occurrences: set[str] = set()
    for index, occurrence in enumerate(occurrences):
        if not isinstance(occurrence, Mapping):
            raise ContractError(f"occurrence {index} must be an object")
        _require_exact_fields(occurrence, occurrence_fields, f"physical_target_occurrences[{index}]")
        occurrence_id = _require_string(occurrence["occurrence_id"], "occurrence_id", maximum=200)
        if occurrence_id in seen_occurrences:
            raise ContractError(f"duplicate occurrence_id: {occurrence_id}")
        seen_occurrences.add(occurrence_id)
        marker = _require_string(occurrence["citation_marker"], "citation_marker", maximum=500)
        quote = _require_string(occurrence["quote"], "occurrence quote")
        key = (str(occurrence["source_file"]), str(occurrence["paragraph_id"]))
        paragraph = paragraphs.get(key)
        if paragraph is None:
            raise ContractError(f"occurrence references unknown paragraph: {key}")
        if quote not in str(paragraph["text"]) or marker not in quote:
            raise ContractError(f"occurrence {occurrence_id} quote or marker is not grounded in its paragraph")
        for locator in ("section", "page_index", "printed_page"):
            if occurrence[locator] != paragraph[locator]:
                raise ContractError(f"occurrence {occurrence_id} locator differs from its paragraph")
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _validate_evidence_span(
    span: Any,
    capsule: Mapping[str, Any],
    label: str,
    *,
    expected_fields: set[str] = EVIDENCE_FIELDS,
) -> dict[str, Any]:
    """Validate one exact evidence span against a capsule paragraph.

    Args:
        span: Candidate evidence object.
        capsule: Validated one-study capsule.
        label: Error-location label.
        expected_fields: Exact field set required for this evidence type.

    Returns:
        A normalized evidence dictionary.
    """

    if not isinstance(span, Mapping):
        raise ContractError(f"{label} must be an object")
    _require_exact_fields(span, expected_fields, label)
    quote = _require_string(span["quote"], f"{label}.quote")
    key = (str(span["source_file"]), str(span["paragraph_id"]))
    paragraph = _paragraph_index(capsule).get(key)
    if paragraph is None or quote not in str(paragraph["text"]):
        raise ContractError(f"{label} quote is not an exact substring of its capsule paragraph")
    for locator in ("section", "page_index", "printed_page"):
        if span[locator] != paragraph[locator]:
            raise ContractError(f"{label}.{locator} differs from the capsule paragraph")
    return dict(span)


def validate_classification(value: Any, capsule: Mapping[str, Any], codebook: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a model classification against schema semantics and exact evidence.

    Args:
        value: Decoded model response.
        capsule: Validated one-study evidence capsule.
        codebook: Frozen scientific codebook.

    Returns:
        A JSON-normalized classification.

    Raises:
        ContractError: If schema, semantic, occurrence, coverage, or evidence checks fail.
    """

    validated_capsule = validate_capsule(capsule, codebook)
    if not isinstance(value, Mapping):
        raise ContractError("classification must be one JSON object")
    _require_exact_fields(value, CLASSIFICATION_FIELDS, "classification")
    status = _require_enum(value["status"], STATUSES, "status")
    study_id = _require_string(value["study_id"], "study_id", maximum=256)
    if study_id != validated_capsule["study"]["study_id"]:
        raise ContractError("classification study_id does not match capsule")
    labels = value["use_labels"]
    if not isinstance(labels, list) or len(labels) != len(set(labels)) or not set(labels) <= USE_LABELS:
        raise ContractError("use_labels must be a unique list of allowed labels")
    primary = _require_enum(value["primary_label"], PRIMARY_LABELS, "primary_label")
    insight = _require_enum(value["biological_insight"], INSIGHT_VALUES, "biological_insight")
    insight_role = _require_enum(value["insight_role"], INSIGHT_ROLES, "insight_role")
    data_origin = _require_enum(value["data_origin"], DATA_ORIGINS, "data_origin")
    confidence = _require_enum(value["confidence"], CONFIDENCE_VALUES, "confidence")
    if not isinstance(value["method_executed"], bool):
        raise ContractError("method_executed must be Boolean")
    risks = value["risk_codes"]
    allowed_risks = set(codebook.get("risk_codes", []))
    if not isinstance(risks, list) or len(risks) != len(set(risks)) or not set(risks) <= allowed_risks:
        raise ContractError("risk_codes must be a unique subset of the codebook")
    _require_string(value["rationale"], "rationale")
    _require_string(value["attribution_bridge"], "attribution_bridge", allow_empty=True)
    if not isinstance(value["citation_instances"], list) or not isinstance(value["use_evidence"], list) or not isinstance(value["insight_evidence"], list):
        raise ContractError("citation_instances and evidence fields must be arrays")
    use_evidence = [
        _validate_evidence_span(
            item,
            validated_capsule,
            f"use_evidence[{index}]",
            expected_fields=USE_EVIDENCE_FIELDS,
        )
        for index, item in enumerate(value["use_evidence"])
    ]
    for index, item in enumerate(use_evidence):
        supported = item["supports_labels"]
        if not isinstance(supported, list) or not supported or len(supported) != len(set(supported)) or not set(supported) <= USE_LABELS:
            raise ContractError(f"use_evidence[{index}].supports_labels must be a nonempty unique use-label list")
    insight_evidence = [_validate_evidence_span(item, validated_capsule, f"insight_evidence[{index}]") for index, item in enumerate(value["insight_evidence"])]
    if status != "CLASSIFIED":
        if labels or primary != "UNRESOLVED" or value["method_executed"] or value["citation_instances"] or use_evidence or insight_evidence:
            raise ContractError("unresolved evidence statuses must not contain a scientific classification")
        if insight != "UNCLEAR" or insight_role != "NONE" or data_origin != "NONE" or value["attribution_bridge"]:
            raise ContractError("unresolved evidence statuses require neutral insight and data fields")
        if status == "COVERAGE_INCOMPLETE" and validated_capsule["evidence_complete"]:
            raise ContractError("COVERAGE_INCOMPLETE requires an incomplete capsule")
        if status == "CITATION_NOT_LOCATED" and (not validated_capsule["evidence_complete"] or validated_capsule["physical_target_occurrences"]):
            raise ContractError("CITATION_NOT_LOCATED requires complete coverage and an empty occurrence registry")
        if not set(validated_capsule["coverage_risk_codes"]) <= set(risks):
            raise ContractError("classification did not preserve capsule coverage risks")
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    if not labels or primary not in labels:
        raise ContractError("CLASSIFIED requires labels and a primary_label contained in use_labels")
    priority = codebook.get("primary_label_priority")
    if "MENTION_ONLY" not in labels and isinstance(priority, list):
        expected_primary = next((label for label in priority if label in labels), None)
        if expected_primary is None or primary != expected_primary:
            raise ContractError("primary_label does not follow the frozen codebook priority")
    executed_labels = set(labels) & EXECUTION_LABELS
    if "MENTION_ONLY" in labels:
        if len(labels) != 1 or value["method_executed"] or data_origin != "NONE" or not use_evidence:
            raise ContractError("MENTION_ONLY must be exclusive, unexecuted, and have data_origin NONE")
        if not validated_capsule["evidence_complete"]:
            raise ContractError("MENTION_ONLY requires complete evidence coverage")
    else:
        if not executed_labels or value["method_executed"] is not True or data_origin == "NONE" or not use_evidence:
            raise ContractError("executed use requires an execution label, evidence, and non-NONE data origin")
    supported_labels = {label for item in use_evidence for label in item["supports_labels"]}
    if supported_labels != set(labels):
        raise ContractError("use_evidence must directly support every assigned use label and no unassigned label")
    registry = {row["occurrence_id"]: row for row in validated_capsule["physical_target_occurrences"]}
    if not registry:
        raise ContractError("CLASSIFIED requires at least one registered physical target occurrence")
    observed: dict[str, Mapping[str, Any]] = {}
    for index, instance in enumerate(value["citation_instances"]):
        if not isinstance(instance, Mapping):
            raise ContractError(f"citation_instances[{index}] must be an object")
        _require_exact_fields(instance, CITATION_INSTANCE_FIELDS, f"citation_instances[{index}]")
        occurrence_id = _require_string(instance["occurrence_id"], "occurrence_id", maximum=200)
        if occurrence_id in observed or occurrence_id not in registry:
            raise ContractError(f"duplicate or unknown occurrence_id: {occurrence_id}")
        observed[occurrence_id] = instance
        source = registry[occurrence_id]
        for field in ("citation_marker", "reference_id", "source_file", "section", "page_index", "printed_page", "paragraph_id"):
            if instance[field] != source[field]:
                raise ContractError(f"citation instance {occurrence_id} differs from registry field {field}")
        quote = _require_string(instance["quote"], "citation instance quote")
        paragraph = _paragraph_index(validated_capsule)[(instance["source_file"], instance["paragraph_id"])]
        if quote not in paragraph["text"] or instance["citation_marker"] not in quote:
            raise ContractError(f"citation instance {occurrence_id} quote is not grounded")
        _require_enum(instance["context_type"], CONTEXT_TYPES, "context_type")
        if not isinstance(instance["supports_use"], bool):
            raise ContractError("supports_use must be Boolean")
        _require_string(instance["description"], "citation instance description", maximum=2000)
    if set(observed) != set(registry):
        raise ContractError("citation_instances must biject exactly to the physical occurrence registry")
    supporting_instances = [item for item in observed.values() if item["supports_use"]]
    if executed_labels and not supporting_instances:
        raise ContractError("executed use requires at least one local citation occurrence with supports_use=true")
    if "MENTION_ONLY" in labels and supporting_instances:
        raise ContractError("MENTION_ONLY cannot contain a supports_use=true occurrence")
    if insight == "YES":
        if not value["method_executed"] or "APPLY_BIOLOGICAL" not in labels or insight_role == "NONE" or not insight_evidence or not value["attribution_bridge"]:
            raise ContractError("biological insight YES requires applied execution, evidence, a role, and an attribution bridge")
    elif insight == "NO":
        if insight_role != "NONE" or insight_evidence or value["attribution_bridge"]:
            raise ContractError("biological insight NO requires empty insight evidence and bridge")
    elif insight_role != "NONE":
        raise ContractError("biological insight UNCLEAR requires insight_role NONE")
    if not validated_capsule["evidence_complete"]:
        if confidence == "HIGH":
            raise ContractError("incomplete evidence cannot produce HIGH confidence")
        if not set(validated_capsule["coverage_risk_codes"]) <= set(risks):
            raise ContractError("classification did not preserve capsule coverage risks")
    return json.loads(canonical_json_bytes(value).decode("utf-8"))
