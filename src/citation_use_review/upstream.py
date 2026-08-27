"""Freeze and review reproducible upstream citation-corpus snapshots."""

from __future__ import annotations

# Standard-library imports produce portable review tables, validate immutable
# paths, and represent structured source/configuration values.
import csv
import re
from collections.abc import Mapping, Sequence
from io import StringIO
from pathlib import Path
from typing import Any

from .bibliography import cluster_studies, normalize_identifier, reconcile_provider_records, stable_id
from .errors import ContractError
from .sources import HTTPTransport, ProvenanceFetcher, enabled_adapters, enrich_titleless_records
from .util import (
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    load_json,
    load_jsonl,
    sha256_file,
    utc_now,
)


UPSTREAM_SCHEMA_VERSION = "upstream-corpus-v1"


def validate_snapshot_id(value: str) -> str:
    """Validate an immutable snapshot label as one safe path component.

    Args:
        value: User-supplied snapshot label.

    Returns:
        The unchanged validated label.

    Raises:
        ContractError: If the label is empty, ambiguous, or unsafe.
    """

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) or value in {".", ".."}:
        raise ContractError(f"unsafe snapshot ID: {value!r}")
    return value


def snapshot_paths(project_root: Path, snapshot_id: str) -> dict[str, Path]:
    """Resolve artifact and raw-state paths for one snapshot.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Valid immutable label.

    Returns:
        Mapping containing ``artifact_dir`` and ``raw_dir`` paths.
    """

    safe_id = validate_snapshot_id(snapshot_id)
    root = project_root.resolve()
    return {
        "artifact_dir": root / "artifacts" / "upstream" / "snapshots" / safe_id,
        "raw_dir": root / "state" / "upstream" / "snapshots" / safe_id / "raw",
    }


def _normalize_seed_versions(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize a target method's seed version cluster.

    Args:
        config: Complete upstream configuration.

    Returns:
        Seed dictionaries with stable IDs and normalized identifiers.

    Raises:
        ContractError: If the method identity or seed cluster is incomplete.
    """

    upstream = config.get("upstream") if isinstance(config.get("upstream"), Mapping) else {}
    method = upstream.get("method") if isinstance(upstream.get("method"), Mapping) else {}
    canonical_name = str(method.get("canonical_name") or "").strip()
    aliases = [str(value).strip() for value in method.get("aliases") or [] if str(value).strip()]
    if not canonical_name or canonical_name not in aliases:
        raise ContractError("upstream.method requires canonical_name included in aliases")
    raw_seeds = upstream.get("seed_versions")
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ContractError("upstream.seed_versions must be a nonempty list")
    seeds: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_identifiers: set[tuple[str, str]] = set()
    for index, raw_seed in enumerate(raw_seeds):
        if not isinstance(raw_seed, Mapping):
            raise ContractError(f"upstream.seed_versions[{index}] must be an object")
        identifiers = {
            kind: normalize_identifier(kind, value)
            for kind, value in (raw_seed.get("identifiers") or {}).items()
            if normalize_identifier(kind, value)
        }
        if not identifiers:
            raise ContractError(f"seed version {index} lacks a strong identifier")
        seed_id = str(raw_seed.get("seed_id") or stable_id("seed_", sorted(identifiers.items())))
        if seed_id in seen_ids:
            raise ContractError(f"duplicate seed_id: {seed_id}")
        for item in identifiers.items():
            if item in seen_identifiers:
                raise ContractError(f"seed identifier is repeated across versions: {item[0]}:{item[1]}")
            seen_identifiers.add(item)
        seen_ids.add(seed_id)
        seeds.append(
            {
                "seed_id": seed_id,
                "version_type": str(raw_seed.get("version_type") or "OTHER").upper(),
                "title": str(raw_seed.get("title") or ""),
                "identifiers": dict(sorted(identifiers.items())),
                "europe_pmc_source": str(raw_seed.get("europe_pmc_source") or ""),
                "europe_pmc_id": str(raw_seed.get("europe_pmc_id") or ""),
            }
        )
    return seeds


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    """Write a deterministic UTF-8 CSV through the atomic text helper.

    Args:
        path: Destination CSV path.
        rows: Ordered mapping rows.
        fields: Exact column order.

    Returns:
        ``None`` after atomic publication.
    """

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    atomic_write_text(path, buffer.getvalue())


def _snapshot_files(artifact_dir: Path) -> dict[str, Path]:
    """Return the canonical file layout inside one snapshot directory.

    Args:
        artifact_dir: Snapshot artifact directory.

    Returns:
        Stable file-name mapping.
    """

    return {
        "seeds": artifact_dir / "seed_versions.json",
        "source_records": artifact_dir / "source_records.jsonl",
        "citation_edges": artifact_dir / "citation_edges.jsonl",
        "works": artifact_dir / "works.jsonl",
        "studies": artifact_dir / "citing_studies.jsonl",
        "studies_csv": artifact_dir / "citing_studies.csv",
        "candidates": artifact_dir / "cluster_candidates.jsonl",
        "candidates_csv": artifact_dir / "cluster_candidates.csv",
        "cluster_review": artifact_dir / "cluster_review.jsonl",
        "raw_manifest": artifact_dir / "raw_responses.jsonl",
        "manifest": artifact_dir / "manifest.json",
    }


def _publish_snapshot(
    *,
    artifact_dir: Path,
    seeds: Sequence[Mapping[str, Any]],
    source_records: Sequence[Mapping[str, Any]],
    works: Sequence[Mapping[str, Any]],
    studies: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    raw_records: Sequence[Mapping[str, Any]],
    source_errors: Mapping[str, str],
    snapshot_id: str,
    first_public_date: str,
    parent: Mapping[str, Any] | None = None,
    cluster_review_rows: Sequence[Mapping[str, Any]] | None = None,
    allow_incomplete_sources: bool = False,
    raw_root_reference: str = "",
) -> dict[str, Any]:
    """Publish one hash-bound immutable corpus snapshot.

    Args:
        artifact_dir: New snapshot directory.
        seeds: Normalized seed version cluster.
        source_records: Normalized provider records.
        works: Reconciled version-level works.
        studies: Study-level ordered records.
        candidates: Pending manual duplicate/version candidates.
        raw_records: Exact-response provenance records.
        source_errors: Adapter failures by source.
        snapshot_id: Immutable label.
        first_public_date: Target method's earliest public date.
        parent: Optional derivative-snapshot provenance.
        cluster_review_rows: Exact completed decisions for a derivative
            snapshot; omitted for a source snapshot.
        allow_incomplete_sources: Explicit promotion exception.
        raw_root_reference: Project-relative directory containing the exact
            raw response files named in ``raw_records``.

    Returns:
        Frozen manifest dictionary.

    Raises:
        FileExistsError: If a manifest already seals this snapshot.
    """

    files = _snapshot_files(artifact_dir)
    if files["manifest"].exists():
        raise FileExistsError(f"immutable snapshot already exists: {snapshot_id}")
    atomic_write_json(files["seeds"], list(seeds))
    atomic_write_jsonl(files["source_records"], source_records)
    work_by_source_record = {
        (str(source_row.get("source") or ""), str(source_row.get("source_record_id") or "")): str(work["work_id"])
        for work in works
        for source_row in work.get("source_records") or []
    }
    citation_edges = sorted(
        [
            {
                "edge_id": stable_id("edge_", record.get("source", ""), record.get("source_record_id", ""), seed_id),
                "source": str(record.get("source") or ""),
                "source_record_id": str(record.get("source_record_id") or ""),
                "raw_response_id": str(record.get("raw_response_id") or ""),
                "seed_id": str(seed_id),
                "citing_work_id": work_by_source_record[
                    (str(record.get("source") or ""), str(record.get("source_record_id") or ""))
                ],
            }
            for record in source_records
            for seed_id in record.get("cited_seed_ids") or []
            if (str(record.get("source") or ""), str(record.get("source_record_id") or ""))
            in work_by_source_record
        ],
        key=lambda item: item["edge_id"],
    )
    atomic_write_jsonl(files["citation_edges"], citation_edges)
    atomic_write_jsonl(files["works"], works)
    atomic_write_jsonl(files["studies"], studies)
    atomic_write_jsonl(files["candidates"], candidates)
    if cluster_review_rows is not None:
        atomic_write_jsonl(files["cluster_review"], cluster_review_rows)
    atomic_write_jsonl(files["raw_manifest"], raw_records)
    study_csv_rows = [
        {
            "order": index,
            "study_id": study["study_id"],
            "title": study.get("title", ""),
            "doi": (study.get("identifiers") or {}).get("doi", ""),
            "pmid": (study.get("identifiers") or {}).get("pmid", ""),
            "pmcid": (study.get("identifiers") or {}).get("pmcid", ""),
            "openalex": (study.get("identifiers") or {}).get("openalex", ""),
            "version_count": study.get("version_count", 0),
            "citation_sources": ";".join(study.get("citation_sources") or []),
            "pending_cluster_candidate_count": study.get("pending_cluster_candidate_count", 0),
            "temporal_impossible": int(bool(study.get("temporal_impossible"))),
        }
        for index, study in enumerate(studies, start=1)
    ]
    _write_csv(
        files["studies_csv"],
        study_csv_rows,
        ("order", "study_id", "title", "doi", "pmid", "pmcid", "openalex", "version_count", "citation_sources", "pending_cluster_candidate_count", "temporal_impossible"),
    )
    candidate_csv_rows = [
        {
            **candidate,
            "shared_authors": ";".join(candidate.get("shared_authors") or []),
        }
        for candidate in candidates
    ]
    _write_csv(
        files["candidates_csv"],
        candidate_csv_rows,
        (
            "candidate_id", "work_id_a", "study_id_a", "title_a", "doi_a",
            "work_id_b", "study_id_b", "title_b", "doi_b", "reason", "score",
            "shared_authors", "recommendation", "reviewer", "reviewed_at", "notes",
        ),
    )
    hashed_files = {
        name: {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for name, path in files.items()
        if name != "manifest" and path.is_file()
    }
    manifest: dict[str, Any] = {
        "schema_version": UPSTREAM_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "first_public_date": first_public_date,
        "seed_version_count": len(seeds),
        "source_record_count": len(source_records),
        "version_work_count": len(works),
        "study_count": len(studies),
        "pending_cluster_candidate_count": len(candidates),
        "source_record_counts": {
            source: sum(1 for record in source_records if record.get("source") == source)
            for source in sorted({str(record.get("source") or "") for record in source_records})
        },
        "citation_source_counts": {
            source: sum(
                1
                for record in source_records
                if record.get("source") == source and record.get("cited_seed_ids")
            )
            for source in sorted(
                {
                    str(record.get("source") or "")
                    for record in source_records
                    if record.get("cited_seed_ids")
                }
            )
        },
        "raw_response_count": len(raw_records),
        "citation_edge_count": len(citation_edges),
        "raw_response_root": raw_root_reference,
        "source_complete": not bool(source_errors),
        "source_errors": dict(sorted(source_errors.items())),
        "allow_incomplete_sources": bool(allow_incomplete_sources),
        "production_eligible": (not candidates and (not source_errors or allow_incomplete_sources)),
        "files": hashed_files,
    }
    if parent:
        manifest["parent"] = dict(parent)
    atomic_write_json(files["manifest"], manifest)
    return manifest


def discover_snapshot(
    *,
    project_root: Path,
    config: Mapping[str, Any],
    snapshot_id: str,
    transport: HTTPTransport | None = None,
) -> dict[str, Any]:
    """Discover citations and seal a new source snapshot.

    Args:
        project_root: Repository or analysis project root.
        config: Upstream configuration.
        snapshot_id: New immutable label.
        transport: Optional fixture-backed HTTP transport.

    Returns:
        Frozen source-snapshot manifest.
    """

    paths = snapshot_paths(project_root, snapshot_id)
    files = _snapshot_files(paths["artifact_dir"])
    if files["manifest"].exists():
        raise FileExistsError(f"immutable snapshot already exists: {snapshot_id}")
    seeds = _normalize_seed_versions(config)
    upstream = config.get("upstream") if isinstance(config.get("upstream"), Mapping) else {}
    source_config = upstream.get("sources") if isinstance(upstream.get("sources"), Mapping) else {}
    http = upstream.get("http") if isinstance(upstream.get("http"), Mapping) else {}
    fetcher = ProvenanceFetcher(
        paths["raw_dir"],
        transport=transport,
        timeout_seconds=float(http.get("timeout_seconds", 60)),
        minimum_delay_seconds=float(http.get("minimum_delay_seconds", 0.2)),
        max_retries=int(http.get("max_retries", 5)),
        user_agent=str(http.get("user_agent") or "fulltext-citation-use-review/0.2"),
    )
    source_records: list[dict[str, Any]] = []
    source_errors: dict[str, str] = {}
    adapters = enabled_adapters(source_config)
    if not any(adapter.name == "openalex" for adapter in adapters):
        raise ContractError("OpenAlex is the required primary citation source and cannot be disabled")
    for adapter in adapters:
        settings = source_config.get(adapter.name) if isinstance(source_config.get(adapter.name), Mapping) else {}
        try:
            source_records.extend(adapter.discover(seeds, fetcher, settings))
        except Exception as error:
            if adapter.name == "openalex":
                raise
            source_errors[adapter.name] = f"{type(error).__name__}: {error}"
    try:
        source_records = enrich_titleless_records(source_records, fetcher, source_config)
    except Exception as error:
        source_errors["metadata_enrichment"] = f"{type(error).__name__}: {error}"
    works = reconcile_provider_records(source_records)
    studies, candidates = cluster_studies(
        works,
        first_public_date=str(upstream.get("first_public_date") or ""),
    )
    return _publish_snapshot(
        artifact_dir=paths["artifact_dir"],
        seeds=seeds,
        source_records=source_records,
        works=works,
        studies=studies,
        candidates=candidates,
        raw_records=fetcher.provenance_records(),
        source_errors=source_errors,
        snapshot_id=snapshot_id,
        first_public_date=str(upstream.get("first_public_date") or ""),
        raw_root_reference=str(paths["raw_dir"].relative_to(project_root.resolve())),
    )


def derive_reviewed_snapshot(
    *,
    project_root: Path,
    parent_snapshot_id: str,
    review_path: Path,
    derived_snapshot_id: str,
    allow_incomplete_sources: bool = False,
) -> dict[str, Any]:
    """Resolve every pending candidate into a new immutable snapshot.

    Args:
        project_root: Repository or analysis project root.
        parent_snapshot_id: Existing source snapshot.
        review_path: JSONL with one decision per pending candidate.
        derived_snapshot_id: New immutable label.
        allow_incomplete_sources: Explicitly promote a snapshot whose optional
            adapters failed; the failures remain in provenance.

    Returns:
        Frozen derived-snapshot manifest.

    Raises:
        ContractError: If review identity or coverage is not exact.
    """

    if parent_snapshot_id == derived_snapshot_id:
        raise ContractError("derived snapshot ID must differ from its parent")
    parent_paths = snapshot_paths(project_root, parent_snapshot_id)
    derived_paths = snapshot_paths(project_root, derived_snapshot_id)
    parent_files = _snapshot_files(parent_paths["artifact_dir"])
    parent_manifest = load_json(parent_files["manifest"])
    candidates = load_jsonl(parent_files["candidates"])
    reviews = load_jsonl(review_path)
    pending = {str(row["candidate_id"]): row for row in candidates}
    decisions = {str(row.get("candidate_id") or ""): row for row in reviews}
    if "" in decisions or len(decisions) != len(reviews):
        raise ContractError("cluster review has blank or duplicate candidate IDs")
    if set(decisions) != set(pending):
        raise ContractError(
            "cluster review must resolve every pending candidate exactly once; "
            f"missing={sorted(set(pending) - set(decisions))}, extra={sorted(set(decisions) - set(pending))}"
        )
    allowed = {"MERGE", "KEEP_SEPARATE", "DO_NOT_MERGE"}
    merges: list[tuple[str, str]] = []
    for candidate_id, review in decisions.items():
        parent = pending[candidate_id]
        pair = {str(review.get("work_id_a") or ""), str(review.get("work_id_b") or "")}
        if pair != {str(parent["work_id_a"]), str(parent["work_id_b"])}:
            raise ContractError(f"cluster review work IDs disagree for {candidate_id}")
        decision = str(review.get("recommendation") or "").upper()
        if decision not in allowed:
            raise ContractError(f"unsupported cluster review decision for {candidate_id}: {decision}")
        if not str(review.get("reviewer") or "").strip() or not str(review.get("reviewed_at") or "").strip():
            raise ContractError(f"cluster review requires reviewer and reviewed_at for {candidate_id}")
        if decision == "MERGE":
            merges.append((str(parent["work_id_a"]), str(parent["work_id_b"])))
    if parent_manifest.get("source_errors") and not allow_incomplete_sources:
        raise ContractError("source-incomplete snapshot requires --allow-incomplete-sources for promotion")
    seeds = load_json(parent_files["seeds"])
    source_records = load_jsonl(parent_files["source_records"])
    works = load_jsonl(parent_files["works"])
    studies, regenerated = cluster_studies(
        works,
        first_public_date=str(parent_manifest.get("first_public_date") or ""),
        reviewed_merges=merges,
    )
    reviewed_pairs = {
        tuple(sorted((str(row["work_id_a"]), str(row["work_id_b"]))))
        for row in candidates
    }
    new_candidates = [
        row
        for row in regenerated
        if tuple(sorted((str(row["work_id_a"]), str(row["work_id_b"])))) not in reviewed_pairs
    ]
    if new_candidates:
        raise ContractError("reviewed clustering unexpectedly produced new unresolved candidates")
    for study in studies:
        study["pending_cluster_candidate_count"] = 0
    raw_records = load_jsonl(parent_files["raw_manifest"])
    parent_binding = {
        "snapshot_id": parent_snapshot_id,
        "manifest_sha256": sha256_file(parent_files["manifest"]),
        "review_path": str(review_path),
        "review_sha256": sha256_file(review_path),
        "review_count": len(reviews),
        "merge_count": len(merges),
        "source_study_count": int(parent_manifest["study_count"]),
        "study_count_reduction": int(parent_manifest["study_count"]) - len(studies),
    }
    return _publish_snapshot(
        artifact_dir=derived_paths["artifact_dir"],
        seeds=seeds,
        source_records=source_records,
        works=works,
        studies=studies,
        candidates=[],
        raw_records=raw_records,
        source_errors=dict(parent_manifest.get("source_errors") or {}),
        snapshot_id=derived_snapshot_id,
        first_public_date=str(parent_manifest.get("first_public_date") or ""),
        parent=parent_binding,
        cluster_review_rows=reviews,
        allow_incomplete_sources=allow_incomplete_sources,
        raw_root_reference=str(parent_paths["raw_dir"].relative_to(project_root.resolve())),
    )


def snapshot_summary(project_root: Path, snapshot_id: str) -> dict[str, Any]:
    """Validate frozen file hashes and summarize one snapshot.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Existing immutable snapshot label.

    Returns:
        Manifest augmented with ``hashes_verified=true``.
    """

    paths = snapshot_paths(project_root, snapshot_id)
    manifest = load_json(_snapshot_files(paths["artifact_dir"])["manifest"])
    for metadata in manifest.get("files", {}).values():
        path = paths["artifact_dir"] / str(metadata["path"])
        if not path.is_file() or sha256_file(path) != metadata["sha256"]:
            raise ContractError(f"snapshot file is missing or stale: {path}")
    raw_root_value = str(manifest.get("raw_response_root") or "")
    if raw_root_value:
        raw_root_path = Path(raw_root_value)
        if raw_root_path.is_absolute():
            raise ContractError("snapshot raw_response_root must be project-relative")
        raw_root = (project_root.resolve() / raw_root_path).resolve()
        try:
            raw_root.relative_to(project_root.resolve())
        except ValueError as error:
            raise ContractError("snapshot raw_response_root escapes project root") from error
        raw_records_path = paths["artifact_dir"] / str(manifest["files"]["raw_manifest"]["path"])
        for record in load_jsonl(raw_records_path):
            body_path = raw_root / str(record["body_relative_path"])
            if not body_path.is_file() or sha256_file(body_path) != record["body_sha256"]:
                raise ContractError(f"raw response body is missing or stale: {body_path}")
    return {**manifest, "hashes_verified": True}
