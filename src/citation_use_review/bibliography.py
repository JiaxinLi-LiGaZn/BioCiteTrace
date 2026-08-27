"""Normalize provider records into citing works and study-level clusters."""

from __future__ import annotations

# Standard-library imports provide deterministic hashes, text normalization,
# conservative similarity scoring, and typed collection contracts.
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from difflib import SequenceMatcher
from typing import Any


STRONG_IDENTIFIER_TYPES = ("doi", "pmid", "pmcid", "openalex", "europe_pmc")


def normalize_doi(value: str | None) -> str:
    """Normalize a DOI for equality matching.

    Args:
        value: DOI, DOI URL, or empty value.

    Returns:
        Lowercase DOI without resolver or namespace prefixes.
    """

    raw = str(value or "").strip().lower()
    raw = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw)
    raw = re.sub(r"^doi:\s*", "", raw)
    return raw.strip().rstrip(".,;)")


def normalize_identifier(kind: str, value: str | None) -> str:
    """Normalize a strong bibliographic identifier.

    Args:
        kind: Identifier namespace such as ``doi`` or ``openalex``.
        value: Provider value, optionally expressed as a URL.

    Returns:
        Namespace-free canonical value, or an empty string.
    """

    namespace = kind.strip().lower().replace("-", "_")
    if namespace == "doi":
        return normalize_doi(value)
    raw = str(value or "").strip()
    lowered = raw.lower()
    prefixes = {
        "pmid": ("pmid:", "https://pubmed.ncbi.nlm.nih.gov/"),
        "pmcid": ("pmcid:", "https://www.ncbi.nlm.nih.gov/pmc/articles/", "https://pmc.ncbi.nlm.nih.gov/articles/"),
        "openalex": ("openalex:", "https://openalex.org/"),
        "europe_pmc": ("europe_pmc:",),
    }
    for prefix in prefixes.get(namespace, (f"{namespace}:",)):
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    raw = raw.strip().rstrip("/.,;)")
    return raw.upper() if namespace in {"pmcid", "openalex"} else raw


def normalize_title(value: str | None) -> str:
    """Normalize a title or author name for conservative comparison.

    Args:
        value: Display text or empty value.

    Returns:
        Lowercase ASCII-like alphanumeric tokens separated by single spaces.
    """

    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks.lower()))


def stable_id(prefix: str, *values: Any) -> str:
    """Build a deterministic identifier from canonical JSON values.

    Args:
        prefix: Human-readable identifier prefix.
        values: JSON-compatible identity components.

    Returns:
        Prefix followed by the first 20 hexadecimal SHA-256 characters.
    """

    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def canonicalize_identifiers(value: Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize and retain supported identifiers from one source record.

    Args:
        value: Raw identifier mapping.

    Returns:
        Sorted mapping containing only nonempty normalized identifiers.
    """

    source = value if isinstance(value, Mapping) else {}
    result = {
        kind: normalize_identifier(kind, source.get(kind))
        for kind in STRONG_IDENTIFIER_TYPES
        if normalize_identifier(kind, source.get(kind))
    }
    return dict(sorted(result.items()))


class _DisjointSet:
    """Maintain deterministic connected components for record reconciliation."""

    def __init__(self, values: Sequence[str]):
        """Initialize singleton components.

        Args:
            values: Unique scalar node identifiers.

        Returns:
            ``None``; component state is stored on the instance.
        """

        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        """Return and path-compress one component root.

        Args:
            value: Existing node identifier.

        Returns:
            Lexically deterministic root identifier.
        """

        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, first: str, second: str) -> None:
        """Join two components using the lexical root as their representative.

        Args:
            first: First existing node identifier.
            second: Second existing node identifier.

        Returns:
            ``None`` after joining the components.
        """

        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            low, high = sorted((first_root, second_root))
            self.parent[high] = low


def _record_identity(record: Mapping[str, Any], index: int) -> str:
    """Return a stable node key for one provider record.

    Args:
        record: Normalized provider record.
        index: Stable position used only when provider identity is missing.

    Returns:
        Deterministic record identifier.
    """

    return stable_id(
        "record_",
        record.get("source", ""),
        record.get("source_record_id", ""),
        canonicalize_identifiers(record.get("identifiers")),
        index,
    )


def _first_nonempty(records: Sequence[Mapping[str, Any]], field: str) -> Any:
    """Select the first nonempty field from priority-ordered records.

    Args:
        records: Provider records already sorted by source priority.
        field: Field name to inspect.

    Returns:
        First nonempty value, or an empty string.
    """

    for record in records:
        value = record.get(field)
        if value not in (None, "", [], {}):
            return value
    return ""


def _source_priority(source: str) -> tuple[int, str]:
    """Rank providers for deterministic metadata selection.

    Args:
        source: Stable provider label.

    Returns:
        Numeric priority and label tie-breaker; lower values win.
    """

    ranks = {
        "openalex": 0,
        "europe_pmc": 1,
        "pubmed": 2,
        "crossref": 3,
        "opencitations": 4,
    }
    return ranks.get(source, 50), source


def reconcile_provider_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse provider records that share any strong identifier.

    Args:
        records: Normalized citation records from enabled source adapters.

    Returns:
        Deterministically ordered version-level works with source provenance.
        Late identifier bridges are resolved transitively, preventing two works
        from retaining the same DOI or other strong identifier.
    """

    record_values = [dict(record) for record in records]
    node_ids = [_record_identity(record, index) for index, record in enumerate(record_values)]
    components = _DisjointSet(node_ids)
    owner: dict[tuple[str, str], str] = {}
    for node_id, record in zip(node_ids, record_values, strict=True):
        for kind, identifier in canonicalize_identifiers(record.get("identifiers")).items():
            key = (kind, identifier)
            if key in owner:
                components.union(node_id, owner[key])
            else:
                owner[key] = node_id
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, record in zip(node_ids, record_values, strict=True):
        grouped[components.find(node_id)].append(record)

    works: list[dict[str, Any]] = []
    for group_records in grouped.values():
        ordered = sorted(
            group_records,
            key=lambda item: (_source_priority(str(item.get("source") or "")), str(item.get("source_record_id") or "")),
        )
        identifiers: dict[str, str] = {}
        for record in ordered:
            for kind, identifier in canonicalize_identifiers(record.get("identifiers")).items():
                existing = identifiers.get(kind)
                if existing and existing != identifier:
                    # Conflicting values from records bridged by another strong
                    # identifier remain visible instead of being overwritten.
                    continue
                identifiers[kind] = identifier
        identity = sorted(f"{kind}:{value}" for kind, value in identifiers.items())
        if not identity:
            identity = sorted(
                f"{record.get('source', '')}:{record.get('source_record_id', '')}"
                for record in ordered
            )
        authors: list[str] = []
        for record in ordered:
            for author in record.get("authors") or []:
                text = str(author).strip()
                if text and text not in authors:
                    authors.append(text)
        work_id = stable_id("work_", identity)
        works.append(
            {
                "work_id": work_id,
                "title": str(_first_nonempty(ordered, "title") or ""),
                "normalized_title": normalize_title(_first_nonempty(ordered, "title")),
                "authors": authors,
                "publication_date": str(_first_nonempty(ordered, "publication_date") or ""),
                "publication_year": _first_nonempty(ordered, "publication_year") or None,
                "work_type": str(_first_nonempty(ordered, "work_type") or ""),
                "venue": str(_first_nonempty(ordered, "venue") or ""),
                "identifiers": dict(sorted(identifiers.items())),
                "source_records": [
                    {
                        "source": str(record.get("source") or ""),
                        "source_record_id": str(record.get("source_record_id") or ""),
                        "raw_response_id": str(record.get("raw_response_id") or ""),
                    }
                    for record in ordered
                ],
                "sources": sorted({str(record.get("source") or "") for record in ordered}),
                "citation_sources": sorted(
                    {
                        str(record.get("source") or "")
                        for record in ordered
                        if record.get("cited_seed_ids")
                    }
                ),
                "cited_seed_ids": sorted(
                    {
                        str(seed_id)
                        for record in ordered
                        for seed_id in record.get("cited_seed_ids") or []
                        if str(seed_id)
                    }
                ),
                "retrieval_candidates": sorted(
                    {
                        json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        for record in ordered
                        for candidate in record.get("retrieval_candidates") or []
                        if isinstance(candidate, Mapping)
                    }
                ),
                "explicit_relations": [
                    relation
                    for record in ordered
                    for relation in record.get("explicit_relations") or []
                    if isinstance(relation, Mapping)
                ],
                "provider_identifier_hints": [
                    hint
                    for record in ordered
                    for hint in record.get("provider_identifier_hints") or []
                    if isinstance(hint, Mapping)
                ],
            }
        )
    for work in works:
        work["retrieval_candidates"] = [json.loads(value) for value in work["retrieval_candidates"]]
    return sorted(works, key=lambda item: item["work_id"])


def _work_identifier_index(works: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    """Index each strong identifier to exactly one reconciled work.

    Args:
        works: Reconciled version-level work dictionaries.

    Returns:
        Mapping from ``(namespace, value)`` to work ID.

    Raises:
        ValueError: If one normalized identifier remains assigned to two works.
    """

    result: dict[tuple[str, str], str] = {}
    for work in works:
        for kind, value in canonicalize_identifiers(work.get("identifiers")).items():
            key = (kind, value)
            prior = result.get(key)
            if prior and prior != work["work_id"]:
                raise ValueError(f"strong identifier collision survived reconciliation: {kind}:{value}")
            result[key] = str(work["work_id"])
    return result


def _candidate_pairs(works: Sequence[Mapping[str, Any]], study_by_work: Mapping[str, str]) -> list[dict[str, Any]]:
    """Find conservative title/author version or duplicate candidates.

    Args:
        works: Reconciled version-level works.
        study_by_work: Current automatic study assignment by work ID.

    Returns:
        Pending candidate rows; no returned pair is automatically merged.
    """

    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for work in works:
        title = str(work.get("normalized_title") or "")
        if title:
            buckets[" ".join(title.split()[:6])].append(work)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        reason: str,
        score: float,
        shared_authors: Sequence[str],
    ) -> None:
        """Append one unique cross-study candidate.

        Args:
            left: First version-level work.
            right: Second version-level work.
            reason: Auditable candidate-generation rule.
            score: Rule-specific similarity score.
            shared_authors: Normalized author overlap.

        Returns:
            ``None``; a new row is appended only once per work pair.
        """

        left_id, right_id = sorted((str(left["work_id"]), str(right["work_id"])))
        if study_by_work[left_id] == study_by_work[right_id] or (left_id, right_id) in seen:
            return
        seen.add((left_id, right_id))
        left_value, right_value = (left, right) if str(left["work_id"]) == left_id else (right, left)
        rows.append(
            {
                "candidate_id": stable_id("candidate_", left_id, right_id, reason),
                "work_id_a": left_id,
                "work_id_b": right_id,
                "study_id_a": study_by_work[left_id],
                "study_id_b": study_by_work[right_id],
                "title_a": str(left_value.get("title") or ""),
                "title_b": str(right_value.get("title") or ""),
                "doi_a": str((left_value.get("identifiers") or {}).get("doi") or ""),
                "doi_b": str((right_value.get("identifiers") or {}).get("doi") or ""),
                "reason": reason,
                "score": round(score, 6),
                "shared_authors": list(shared_authors),
                "recommendation": "",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            }
        )

    for bucket in buckets.values():
        for left_index, left in enumerate(bucket):
            for right in bucket[left_index + 1 :]:
                left_title = str(left.get("normalized_title") or "")
                right_title = str(right.get("normalized_title") or "")
                similarity = SequenceMatcher(None, left_title, right_title).ratio()
                left_authors = {normalize_title(value) for value in left.get("authors") or [] if normalize_title(value)}
                right_authors = {normalize_title(value) for value in right.get("authors") or [] if normalize_title(value)}
                shared_authors = sorted(left_authors & right_authors)
                exact_title = left_title == right_title and bool(left_title)
                if not exact_title and not (similarity >= 0.94 and shared_authors):
                    continue
                reason = "exact_normalized_title" if exact_title else "high_title_author_similarity"
                add_candidate(
                    left,
                    right,
                    reason=reason,
                    score=similarity,
                    shared_authors=shared_authors,
                )
    identifier_index = _work_identifier_index(works)
    work_by_id = {str(work["work_id"]): work for work in works}
    for work in works:
        for hint in work.get("provider_identifier_hints") or []:
            kind = str(hint.get("identifier_type") or "").lower().replace("-", "_")
            value = normalize_identifier(kind, hint.get("identifier"))
            target_id = identifier_index.get((kind, value))
            if target_id and target_id != work["work_id"]:
                add_candidate(
                    work,
                    work_by_id[target_id],
                    reason="provider_cross_version_hint",
                    score=1.0,
                    shared_authors=(),
                )
    return sorted(rows, key=lambda item: item["candidate_id"])


def cluster_studies(
    works: Sequence[Mapping[str, Any]],
    *,
    first_public_date: str = "",
    reviewed_merges: Sequence[tuple[str, str]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cluster explicit versions and surface uncertain pairs for review.

    Args:
        works: Reconciled version-level work dictionaries.
        first_public_date: Earliest public date of the target method, used only
            to flag temporally impossible citation metadata.
        reviewed_merges: Human-approved work-ID pairs to join in a derivative
            reviewed snapshot.

    Returns:
        ``(studies, pending_candidates)`` in deterministic order.
    """

    work_values = [dict(work) for work in works]
    work_ids = [str(work["work_id"]) for work in work_values]
    by_id = {str(work["work_id"]): work for work in work_values}
    identifiers = _work_identifier_index(work_values)
    components = _DisjointSet(work_ids)
    for work in work_values:
        for relation in work.get("explicit_relations") or []:
            kind = str(relation.get("identifier_type") or "").lower().replace("-", "_")
            value = normalize_identifier(kind, relation.get("identifier"))
            target = identifiers.get((kind, value))
            if target and str(relation.get("relation_type") or "") in {
                "is-preprint-of",
                "is-version-of",
                "has-version",
                "corrected-by",
                "corrects",
            }:
                components.union(str(work["work_id"]), target)
    for left, right in reviewed_merges:
        if left not in by_id or right not in by_id:
            raise ValueError(f"reviewed merge references unknown work: {left}, {right}")
        components.union(left, right)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for work in work_values:
        groups[components.find(str(work["work_id"]))].append(work)
    studies: list[dict[str, Any]] = []
    study_by_work: dict[str, str] = {}
    threshold = date.fromisoformat(first_public_date) if first_public_date else None
    for members in groups.values():
        members = sorted(members, key=lambda item: str(item["work_id"]))
        canonical = min(
            members,
            key=lambda item: (
                0 if str(item.get("work_type") or "").lower() not in {"preprint", "posted-content"} else 1,
                str(item.get("publication_date") or "9999-99-99"),
                str(item["work_id"]),
            ),
        )
        study_id = stable_id("study_", sorted(str(item["work_id"]) for item in members))
        for member in members:
            study_by_work[str(member["work_id"])] = study_id
        temporal_impossible = False
        temporal_reasons: list[str] = []
        if threshold:
            for member in members:
                raw_date = str(member.get("publication_date") or "")
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) and date.fromisoformat(raw_date) < threshold:
                    temporal_impossible = True
                    temporal_reasons.append(f"{member['work_id']} publication_date {raw_date} predates {first_public_date}")
        studies.append(
            {
                "study_id": study_id,
                "canonical_work_id": canonical["work_id"],
                "title": canonical.get("title", ""),
                "identifiers": canonical.get("identifiers", {}),
                "publication_date": canonical.get("publication_date", ""),
                "publication_year": canonical.get("publication_year"),
                "work_type": canonical.get("work_type", ""),
                "venue": canonical.get("venue", ""),
                "version_count": len(members),
                "versions": members,
                "citation_sources": sorted({source for member in members for source in member.get("citation_sources") or []}),
                "cited_seed_ids": sorted({seed for member in members for seed in member.get("cited_seed_ids") or []}),
                "temporal_impossible": temporal_impossible,
                "temporal_reasons": temporal_reasons,
                "cluster_method": "explicit_or_reviewed_version_relation" if len(members) > 1 else "singleton",
            }
        )
    candidates = _candidate_pairs(work_values, study_by_work)
    for study in studies:
        study["pending_cluster_candidate_count"] = sum(
            1
            for candidate in candidates
            if study["study_id"] in {candidate["study_id_a"], candidate["study_id_b"]}
        )
    studies.sort(
        key=lambda item: (
            str(item.get("publication_date") or "9999-99-99"),
            normalize_title(item.get("title")),
            str(item["study_id"]),
        )
    )
    return studies, candidates
