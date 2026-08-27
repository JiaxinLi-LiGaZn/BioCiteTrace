"""Build a transparent one-study capsule from rights-approved UTF-8 text."""

# Standard-library imports parse headings, detect aliases, hash files, and manage paths.
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import validate_capsule
from .errors import ContractError


def _paragraphs_from_text(text: str) -> list[dict[str, Any]]:
    """Split simple Markdown-like text into stable section paragraphs.

    Args:
        text: UTF-8 article or supplement text. Lines beginning with ``#``
            introduce a section; blank lines separate paragraphs.

    Returns:
        Ordered paragraph records. Each record contains section name, a null
        page index, blank printed-page label, stable paragraph ID, and text.
    """

    section = "UNSPECIFIED"
    buffer: list[str] = []
    paragraphs: list[dict[str, Any]] = []

    def flush() -> None:
        """Move the current nonempty paragraph buffer into ``paragraphs``.

        Returns:
            ``None`` after clearing the buffer and, when nonempty, appending one
            normalized paragraph to the enclosing list.
        """

        if not buffer:
            return
        normalized = " ".join(part.strip() for part in buffer if part.strip())
        buffer.clear()
        if normalized:
            paragraphs.append(
                {
                    "section": section,
                    "page_index": None,
                    "printed_page": "",
                    "paragraph_id": f"p-{len(paragraphs) + 1:04d}",
                    "text": normalized,
                }
            )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip() or "UNSPECIFIED"
        elif not line:
            flush()
        else:
            buffer.append(line)
    flush()
    if not paragraphs:
        raise ContractError("document text did not contain any nonempty paragraph")
    return paragraphs


def _context_type(section: str, document_type: str) -> str:
    """Map a free-text section name onto the controlled context vocabulary.

    Args:
        section: Parsed section heading.
        document_type: ``MAIN`` or ``SUPPLEMENT``.

    Returns:
        Controlled context type used by the classification schema.
    """

    if document_type == "SUPPLEMENT":
        return "SUPPLEMENT"
    lowered = section.lower()
    for token, label in (
        ("intro", "INTRODUCTION"),
        ("method", "METHODS"),
        ("result", "RESULTS"),
        ("discussion", "DISCUSSION"),
        ("reference", "REFERENCES"),
        ("figure", "FIGURE_TABLE"),
        ("table", "FIGURE_TABLE"),
    ):
        if token in lowered:
            return label
    return "OTHER"


def _alias_markers(text: str, aliases: Sequence[str]) -> list[tuple[int, int, str]]:
    """Find nonoverlapping target-method markers in one paragraph.

    Args:
        text: Paragraph text to inspect.
        aliases: Frozen target aliases. Longer aliases win when matches overlap.

    Returns:
        Ordered ``(start, end, marker)`` tuples. A short following bracketed
        citation, such as ``[12]``, is included in the marker span.
    """

    candidates: list[tuple[int, int]] = []
    for alias in aliases:
        pattern = re.compile(re.escape(alias), flags=re.IGNORECASE)
        candidates.extend((match.start(), match.end()) for match in pattern.finditer(text))
    selected: list[tuple[int, int, str]] = []
    occupied_until = -1
    for start, end in sorted(candidates, key=lambda item: (item[0], -(item[1] - item[0]))):
        if start < occupied_until:
            continue
        suffix = re.match(r"\s*\[[^\]]{1,40}\]", text[end:])
        marker_end = end + (suffix.end() if suffix else 0)
        selected.append((start, marker_end, text[start:marker_end]))
        occupied_until = marker_end
    return selected


def build_capsule(
    *,
    project_root: Path,
    study: Mapping[str, Any],
    target_method: Mapping[str, Any],
    document_specs: Sequence[Mapping[str, Any]],
    codebook: Mapping[str, Any],
    evidence_complete: bool = True,
    coverage_risk_codes: Sequence[str] = (),
) -> dict[str, Any]:
    """Build and validate one evidence capsule from local plain-text documents.

    Args:
        project_root: Root used to resolve document paths.
        study: Study metadata with ``study_id``, ``title``, and ``identifiers``.
        target_method: Method metadata with canonical name, aliases, and seed IDs.
        document_specs: Ordered rights/provenance records. Every record references
            one UTF-8 text file and explicitly permits or rejects cloud processing.
        codebook: Frozen scientific codebook.
        evidence_complete: Whether the supplied versions and supplements are complete.
        coverage_risk_codes: Codebook risks explaining incomplete coverage.

    Returns:
        A validated one-study capsule containing parsed paragraphs and a physical
        occurrence for every alias match.

    Raises:
        ContractError: If a path escapes the project, a file is unreadable, rights
            are not approved, or the resulting capsule violates its contract.
    """

    root = project_root.resolve()
    aliases = target_method.get("aliases") if isinstance(target_method, Mapping) else None
    if not isinstance(aliases, list) or not aliases:
        raise ContractError("target method must define at least one alias")
    documents: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    occurrences: list[dict[str, Any]] = []
    seed_values = [str(value) for value in target_method.get("seed_identifiers", {}).values() if str(value)]
    reference_id = seed_values[0] if seed_values else ""
    seen_versions: set[str] = set()
    for document_index, spec in enumerate(document_specs):
        if not isinstance(spec, Mapping):
            raise ContractError(f"document spec {document_index} must be an object")
        required = {"path", "source_file", "document_type", "version_id", "version_type", "license", "cloud_processing_allowed"}
        if set(spec) != required:
            raise ContractError(f"document spec {document_index} fields must be {sorted(required)}")
        candidate = Path(str(spec["path"]))
        document_path = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            document_path.relative_to(root)
        except ValueError as error:
            raise ContractError(f"document path escapes project root: {candidate}") from error
        if spec["cloud_processing_allowed"] is not True:
            raise ContractError(f"cloud processing is not approved for {spec['source_file']}")
        if not str(spec["license"]).strip():
            raise ContractError(f"license evidence is missing for {spec['source_file']}")
        try:
            raw = document_path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise ContractError(f"cannot read UTF-8 document {document_path}: {error}") from error
        sections = _paragraphs_from_text(text)
        source_file = str(spec["source_file"])
        document_type = str(spec["document_type"]).upper()
        version_id = str(spec["version_id"])
        if version_id not in seen_versions:
            coverage_rows.append(
                {
                    "version_id": version_id,
                    "version_type": str(spec["version_type"]).upper(),
                    "included": True,
                    "reason": "Rights-approved text included in the capsule.",
                }
            )
            seen_versions.add(version_id)
        documents.append(
            {
                "source_file": source_file,
                "document_type": document_type,
                "version_id": version_id,
                "license": str(spec["license"]),
                "cloud_processing_allowed": True,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "sections": sections,
            }
        )
        for paragraph in sections:
            for _start, _end, marker in _alias_markers(paragraph["text"], aliases):
                occurrences.append(
                    {
                        "occurrence_id": f"occ-{len(occurrences) + 1:04d}",
                        "citation_marker": marker,
                        "reference_id": reference_id,
                        "source_file": source_file,
                        "section": paragraph["section"],
                        "page_index": paragraph["page_index"],
                        "printed_page": paragraph["printed_page"],
                        "paragraph_id": paragraph["paragraph_id"],
                        "quote": paragraph["text"],
                    }
                )
    capsule = {
        "capsule_version": "1.0.0",
        "study": dict(study),
        "target_method": dict(target_method),
        "evidence_complete": evidence_complete,
        "coverage_risk_codes": list(coverage_risk_codes),
        "version_coverage": coverage_rows,
        "documents": documents,
        "physical_target_occurrences": occurrences,
    }
    return validate_capsule(capsule, codebook)


__all__ = ["build_capsule", "_context_type"]
