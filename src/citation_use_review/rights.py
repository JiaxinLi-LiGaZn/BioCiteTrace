"""Prepare human rights review, retrieve approved files, and build handoffs."""

from __future__ import annotations

# Standard-library imports provide bounded parallel downloads, binary/text
# inspection, deterministic review tables, and URL/content-type handling.
import io
import json
import re
import time
import csv
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from .bibliography import normalize_doi, normalize_title, stable_id
from .capsule import build_capsule
from .errors import ContractError
from .sources import HTTPResult, HTTPTransport, UrllibTransport
from .upstream import snapshot_paths, snapshot_summary
from .util import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_jsonl,
    load_json,
    load_jsonl,
    sha256_bytes,
    sha256_file,
    utc_now,
)


RIGHTS_QUEUE_VERSION = "rights-review-v1"
RETRIEVAL_VERSION = "human-approved-retrieval-v1"


def _snapshot_studies(project_root: Path, snapshot_id: str) -> list[dict[str, Any]]:
    """Load studies after verifying the snapshot manifest and file hashes.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Existing reviewed snapshot label.

    Returns:
        Ordered study dictionaries.
    """

    summary = snapshot_summary(project_root, snapshot_id)
    if summary.get("pending_cluster_candidate_count"):
        raise ContractError("rights review requires a snapshot with no pending cluster candidates")
    if not summary.get("production_eligible"):
        raise ContractError("snapshot is not eligible for downstream promotion")
    paths = snapshot_paths(project_root, snapshot_id)
    studies_file = paths["artifact_dir"] / str(summary["files"]["studies"]["path"])
    return load_jsonl(studies_file)


def _rights_paths(project_root: Path, snapshot_id: str) -> dict[str, Path]:
    """Resolve rights-review and retrieval paths for one snapshot.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Existing reviewed snapshot label.

    Returns:
        Stable path mapping.
    """

    base = project_root.resolve() / "artifacts" / "upstream" / "rights" / snapshot_id
    retrieval = project_root.resolve() / "artifacts" / "upstream" / "retrieval" / snapshot_id
    return {
        "rights_dir": base,
        "queue": base / "rights_review_queue.jsonl",
        "queue_csv": base / "rights_review_queue.csv",
        "queue_manifest": base / "manifest.json",
        "retrieval_dir": retrieval,
        "checkpoint_dir": retrieval / "checkpoints",
        "approval_snapshot": retrieval / "rights_review_completed.jsonl",
        "retrieval_manifest": retrieval / "manifest.jsonl",
        "retrieval_summary": retrieval / "summary.json",
        "duplicate_queue": retrieval / "post_retrieval_duplicate_candidates.jsonl",
        "coverage_queue": retrieval / "evidence_coverage_review_queue.jsonl",
    }


def _candidate_rows(studies: Sequence[Mapping[str, Any]], snapshot_id: str) -> list[dict[str, Any]]:
    """Flatten version-level OA locations into a human review queue.

    Args:
        studies: Ordered reviewed study records.
        snapshot_id: Source snapshot label.

    Returns:
        Candidate rows in study/version/provider priority order.
    """

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for order, study in enumerate(studies, start=1):
        for version in study.get("versions") or []:
            if not isinstance(version, Mapping):
                continue
            for candidate in version.get("retrieval_candidates") or []:
                if not isinstance(candidate, Mapping):
                    continue
                url = str(candidate.get("url") or "").strip()
                if not url.lower().startswith("https://"):
                    continue
                key = (str(study["study_id"]), str(version["work_id"]), url)
                if key in seen:
                    continue
                seen.add(key)
                candidate_id = stable_id("document_", snapshot_id, *key)
                identifiers = dict(version.get("identifiers") or {})
                rows.append(
                    {
                        "queue_version": RIGHTS_QUEUE_VERSION,
                        "snapshot_id": snapshot_id,
                        "corpus_order": order,
                        "candidate_id": candidate_id,
                        "study_id": str(study["study_id"]),
                        "work_id": str(version["work_id"]),
                        "title": str(version.get("title") or study.get("title") or ""),
                        "doi": str(identifiers.get("doi") or ""),
                        "pmid": str(identifiers.get("pmid") or ""),
                        "pmcid": str(identifiers.get("pmcid") or ""),
                        "source": str(candidate.get("source") or ""),
                        "url": url,
                        "landing_page_url": str(candidate.get("landing_page_url") or ""),
                        "document_role": str(candidate.get("document_role") or "MAIN").upper(),
                        "version": str(candidate.get("version") or ""),
                        "provider_reports_open_access": bool(candidate.get("is_oa")),
                        "provider_reported_license": str(candidate.get("reported_license") or ""),
                        "decision": "",
                        "cloud_processing_allowed": "",
                        "permission_basis": "",
                        "reviewer": "",
                        "reviewed_at": "",
                        "notes": "",
                    }
                )
    return rows


def prepare_rights_review(*, project_root: Path, snapshot_id: str) -> dict[str, Any]:
    """Create a blank human rights-review queue for direct OA candidates.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Reviewed production-eligible corpus snapshot.

    Returns:
        Queue manifest with candidate count and hash bindings.
    """

    studies = _snapshot_studies(project_root, snapshot_id)
    paths = _rights_paths(project_root, snapshot_id)
    if paths["queue_manifest"].exists():
        raise FileExistsError(f"rights queue already exists for {snapshot_id}")
    rows = _candidate_rows(studies, snapshot_id)
    atomic_write_jsonl(paths["queue"], rows)
    csv_fields = list(rows[0]) if rows else [
        "queue_version", "snapshot_id", "corpus_order", "candidate_id", "study_id", "work_id", "title", "doi", "pmid", "pmcid", "source", "url", "landing_page_url", "document_role", "version", "provider_reports_open_access", "provider_reported_license", "decision", "cloud_processing_allowed", "permission_basis", "reviewer", "reviewed_at", "notes"
    ]
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=csv_fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(paths["queue_csv"], buffer.getvalue().encode("utf-8"))
    snapshot_manifest = snapshot_paths(project_root, snapshot_id)["artifact_dir"] / "manifest.json"
    manifest = {
        "schema_version": RIGHTS_QUEUE_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "candidate_count": len(rows),
        "study_count": len(studies),
        "snapshot_manifest_sha256": sha256_file(snapshot_manifest),
        "queue": {"path": paths["queue"].name, "sha256": sha256_file(paths["queue"])},
        "queue_csv": {"path": paths["queue_csv"].name, "sha256": sha256_file(paths["queue_csv"])},
        "instruction": "A human reviewer must complete every row. Provider OA or license metadata is evidence to inspect, not an automatic permission decision.",
    }
    atomic_write_json(paths["queue_manifest"], manifest)
    return manifest


def _load_approved_decisions(
    project_root: Path,
    snapshot_id: str,
    approval_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate a completed rights review against its blank frozen queue.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Reviewed corpus snapshot.
        approval_path: Completed JSONL copied from the blank queue.

    Returns:
        Validated decision rows in frozen queue order and queue manifest.
    """

    paths = _rights_paths(project_root, snapshot_id)
    queue_manifest = load_json(paths["queue_manifest"])
    if sha256_file(paths["queue"]) != queue_manifest["queue"]["sha256"]:
        raise ContractError("frozen rights queue hash mismatch")
    queue = load_jsonl(paths["queue"])
    approvals = load_jsonl(approval_path)
    by_id = {str(row.get("candidate_id") or ""): row for row in approvals}
    if "" in by_id or len(by_id) != len(approvals):
        raise ContractError("rights approval has blank or duplicate candidate IDs")
    if set(by_id) != {str(row["candidate_id"]) for row in queue}:
        raise ContractError("rights approval must cover every candidate exactly once")
    immutable_fields = {
        "queue_version", "snapshot_id", "corpus_order", "candidate_id", "study_id", "work_id", "title", "doi", "pmid", "pmcid", "source", "url", "landing_page_url", "document_role", "version", "provider_reports_open_access", "provider_reported_license"
    }
    ordered: list[dict[str, Any]] = []
    approved_slots: set[tuple[str, str, str]] = set()
    for frozen in queue:
        value = dict(by_id[str(frozen["candidate_id"])])
        for field in immutable_fields:
            if value.get(field) != frozen.get(field):
                raise ContractError(f"rights approval changed frozen field {field} for {frozen['candidate_id']}")
        decision = str(value.get("decision") or "").upper()
        if decision not in {"APPROVE", "DENY", "DEFER"}:
            raise ContractError(f"invalid rights decision for {frozen['candidate_id']}: {decision}")
        if not str(value.get("reviewer") or "").strip() or not str(value.get("reviewed_at") or "").strip():
            raise ContractError(f"rights decision requires reviewer and reviewed_at for {frozen['candidate_id']}")
        allowed = value.get("cloud_processing_allowed")
        if decision == "APPROVE":
            if allowed is not True:
                raise ContractError(f"APPROVE requires explicit cloud_processing_allowed=true for {frozen['candidate_id']}")
            if not str(value.get("permission_basis") or "").strip():
                raise ContractError(f"APPROVE requires a permission basis for {frozen['candidate_id']}")
            slot = (str(value["study_id"]), str(value["work_id"]), str(value["document_role"]))
            if slot in approved_slots:
                raise ContractError(f"more than one candidate approved for one study/version/role: {slot}")
            approved_slots.add(slot)
        elif allowed is not False:
            raise ContractError(f"non-APPROVE row requires explicit cloud_processing_allowed=false for {frozen['candidate_id']}")
        value["decision"] = decision
        ordered.append(value)
    return ordered, queue_manifest


def _format_from_response(url: str, headers: Mapping[str, str], body: bytes) -> tuple[str, str]:
    """Identify a supported article format from signature, headers, and URL.

    Args:
        url: Requested direct URL.
        headers: Response headers.
        body: Complete response bytes.

    Returns:
        Lowercase format name and safe file suffix.

    Raises:
        ContractError: If the response is not PDF, XML, HTML, or plain text.
    """

    content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "").lower()
    stripped = body.lstrip()[:200].lower()
    if body.startswith(b"%PDF-"):
        return "pdf", ".pdf"
    if "xml" in content_type or stripped.startswith(b"<?xml") or b"<article" in stripped:
        return "xml", ".xml"
    if "html" in content_type or stripped.startswith((b"<!doctype html", b"<html")):
        return "html", ".html"
    if content_type.startswith("text/plain") or Path(urlparse(url).path).suffix.lower() == ".txt":
        return "text", ".txt"
    raise ContractError(f"approved URL did not return a supported article format: {content_type or 'unknown'}")


def _extract_text(body: bytes, format_name: str) -> str:
    """Extract plain text from one supported article document.

    Args:
        body: Complete validated document bytes.
        format_name: ``pdf``, ``xml``, ``html``, or ``text``.

    Returns:
        UTF-8 Python text suitable for one-study capsule construction.
    """

    if format_name == "text":
        return body.decode("utf-8")
    if format_name == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise ContractError("PDF retrieval requires the optional upstream dependency pypdf") from error
        reader = PdfReader(io.BytesIO(body))
        return "\n\n".join(str(page.extract_text() or "") for page in reader.pages)
    try:
        from lxml import etree, html
    except ImportError as error:
        raise ContractError("XML/HTML retrieval requires the optional upstream dependency lxml") from error
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True, huge_tree=False)
    if format_name == "xml":
        root = etree.fromstring(body, parser=parser)
        return "\n\n".join(part.strip() for part in root.itertext() if part.strip())
    root = html.fromstring(body)
    return "\n\n".join(part.strip() for part in root.itertext() if part.strip())


def _validate_identity(text: str, title: str, doi: str) -> dict[str, Any]:
    """Require a DOI or strong title match in extracted document text.

    Args:
        text: Extracted full text.
        title: Expected citing-work title.
        doi: Expected normalized DOI, when available.

    Returns:
        Identity evidence mapping.

    Raises:
        ContractError: If neither expected DOI nor title is supported.
    """

    normalized_doi = normalize_doi(doi)
    doi_found = bool(normalized_doi and normalized_doi in text.lower().replace("https://doi.org/", ""))
    normalized_expected = normalize_title(title)
    normalized_head = normalize_title(text[:30000])
    title_found = bool(normalized_expected and normalized_expected in normalized_head)
    if not doi_found and not title_found:
        raise ContractError("downloaded document identity does not match expected DOI or title")
    return {"doi_found": doi_found, "title_found": title_found, "expected_doi": normalized_doi, "expected_title": title}


def _validate_retrieval_checkpoint(
    checkpoint: Mapping[str, Any],
    row: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Validate an existing terminal retrieval before resume.

    Args:
        checkpoint: Decoded terminal record.
        row: Current validated rights decision.
        output_root: Snapshot retrieval directory.

    Returns:
        Defensive copy of the validated terminal record.

    Raises:
        ContractError: If identity, approval binding, paths, or hashes differ.
    """

    approval_sha = sha256_bytes(json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for field in ("candidate_id", "study_id", "work_id"):
        if checkpoint.get(field) != row.get(field):
            raise ContractError(f"retrieval checkpoint identity mismatch for {row['candidate_id']}: {field}")
    if checkpoint.get("approval_identity_sha256") != approval_sha:
        raise ContractError(f"stale retrieval checkpoint collides for {row['candidate_id']}")
    if checkpoint.get("status") == "RETRIEVED":
        for path_field, hash_field in (("binary_path", "sha256"), ("text_path", "text_sha256")):
            path = Path(str(checkpoint.get(path_field) or "")).resolve()
            try:
                path.relative_to(output_root.resolve())
            except ValueError as error:
                raise ContractError(f"retrieval checkpoint path escapes output root: {path}") from error
            if not path.is_file() or sha256_file(path) != checkpoint.get(hash_field):
                raise ContractError(f"retrieval checkpoint file is missing or stale: {path}")
        if checkpoint.get("identity_verified") is not True:
            raise ContractError(f"retrieved checkpoint lacks identity verification: {row['candidate_id']}")
        approval = checkpoint.get("human_rights_approval")
        if not isinstance(approval, Mapping) or approval.get("cloud_processing_allowed") is not True:
            raise ContractError(f"retrieved checkpoint lacks explicit human rights approval: {row['candidate_id']}")
    return dict(checkpoint)


def _download_approved(
    row: Mapping[str, Any],
    *,
    output_root: Path,
    transport: HTTPTransport,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    """Download, validate, and checkpoint one explicitly approved candidate.

    Args:
        row: Validated human rights decision.
        output_root: Snapshot retrieval directory.
        transport: Live or fixture HTTP transport.
        timeout_seconds: Per-attempt timeout.
        max_retries: Retry count after the first attempt.
        retry_backoff_seconds: Base exponential backoff.
        max_bytes: Hard response-size cap.

    Returns:
        Terminal retrieval record.
    """

    candidate_id = str(row["candidate_id"])
    checkpoint = output_root / "checkpoints" / f"{candidate_id}.json"
    if checkpoint.is_file():
        return _validate_retrieval_checkpoint(load_json(checkpoint), row, output_root)
    approval_sha = sha256_bytes(json.dumps(dict(row), sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if row["decision"] != "APPROVE":
        result = {
            "schema_version": RETRIEVAL_VERSION,
            "candidate_id": candidate_id,
            "study_id": row["study_id"],
            "work_id": row["work_id"],
            "status": "EXCLUDED_RIGHTS_NOT_APPROVED",
            "decision": row["decision"],
            "approval_identity_sha256": approval_sha,
        }
        atomic_write_json(checkpoint, result)
        return result

    response: HTTPResult | None = None
    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        try:
            response = transport.fetch(
                str(row["url"]),
                {},
                {"User-Agent": "fulltext-citation-use-review/0.2", "Accept": "application/pdf, application/xml, text/html, text/plain"},
                timeout_seconds,
            )
            if response.status >= 400:
                raise HTTPError(str(row["url"]), response.status, "HTTP error", dict(response.headers), None)
            break
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            status = int(getattr(error, "code", 0) or 0)
            if attempt >= max_retries or (status and status not in {429, 500, 502, 503, 504}):
                break
            time.sleep(max(0.0, retry_backoff_seconds) * (2**attempt))
    if response is None:
        result = {
            "schema_version": RETRIEVAL_VERSION,
            "candidate_id": candidate_id,
            "study_id": row["study_id"],
            "work_id": row["work_id"],
            "status": "UNRESOLVED_FULLTEXT",
            "error_type": type(last_error).__name__ if last_error else "NO_RESPONSE",
            "attempts": attempts,
            "approval_identity_sha256": approval_sha,
        }
        atomic_write_json(checkpoint, result)
        return result
    if len(response.body) > max_bytes:
        raise ContractError(f"approved document exceeds max_bytes: {candidate_id}")
    format_name, suffix = _format_from_response(str(row["url"]), response.headers, response.body)
    text = _extract_text(response.body, format_name)
    if len(text.strip()) < 200:
        raise ContractError(f"approved document yielded too little text: {candidate_id}")
    identity = _validate_identity(text, str(row["title"]), str(row["doi"]))
    study_dir = output_root / "files" / str(row["study_id"])
    binary_path = study_dir / f"{candidate_id}{suffix}"
    text_path = study_dir / f"{candidate_id}.txt"
    atomic_write_bytes(binary_path, response.body)
    atomic_write_bytes(text_path, ("# Full text\n\n" + text.strip() + "\n").encode("utf-8"))
    result = {
        "schema_version": RETRIEVAL_VERSION,
        "candidate_id": candidate_id,
        "study_id": row["study_id"],
        "work_id": row["work_id"],
        "status": "RETRIEVED",
        "source": row["source"],
        "url": row["url"],
        "document_role": row["document_role"],
        "version": row["version"],
        "format": format_name,
        "binary_path": str(binary_path),
        "text_path": str(text_path),
        "sha256": sha256_bytes(response.body),
        "text_sha256": sha256_file(text_path),
        "bytes": len(response.body),
        "identity_verified": True,
        "identity_evidence": identity,
        "human_rights_approval": {
            "cloud_processing_allowed": True,
            "permission_basis": row["permission_basis"],
            "reviewer": row["reviewer"],
            "reviewed_at": row["reviewed_at"],
            "notes": row.get("notes", ""),
        },
        "attempts": attempts,
        "retrieved_at": utc_now(),
        "approval_identity_sha256": approval_sha,
    }
    atomic_write_json(checkpoint, result)
    return result


def _duplicate_candidates(records: Sequence[Mapping[str, Any]], studies: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Detect cross-study DOI or byte-identical document collisions.

    Args:
        records: Ordered terminal retrieval records.
        studies: Frozen citing studies.

    Returns:
        Manual post-retrieval duplicate candidate rows.
    """

    doi_by_study = {
        str(study["study_id"]): normalize_doi((study.get("identifiers") or {}).get("doi"))
        for study in studies
    }
    retrieved = [record for record in records if record.get("status") == "RETRIEVED"]
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for index, left in enumerate(retrieved):
        for right in retrieved[index + 1 :]:
            if left["study_id"] == right["study_id"]:
                continue
            reasons: set[str] = set()
            left_doi, right_doi = doi_by_study.get(str(left["study_id"]), ""), doi_by_study.get(str(right["study_id"]), "")
            if left_doi and left_doi == right_doi:
                reasons.add("SAME_NORMALIZED_DOI")
            if left.get("sha256") and left.get("sha256") == right.get("sha256"):
                reasons.add("BYTE_IDENTICAL_FULLTEXT")
            if reasons:
                pair = tuple(sorted((str(left["study_id"]), str(right["study_id"]))))
                pairs[pair].update(reasons)
    return [
        {
            "collision_id": stable_id("collision_", pair, sorted(reasons)),
            "study_id_a": pair[0],
            "study_id_b": pair[1],
            "reasons": sorted(reasons),
            "decision": "",
            "keep_study_id": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        }
        for pair, reasons in sorted(pairs.items())
    ]


def _coverage_review_rows(
    records: Sequence[Mapping[str, Any]],
    studies: Sequence[Mapping[str, Any]],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    """Prepare one frozen evidence-coverage decision row per retrieved study.

    Args:
        records: Ordered terminal retrieval records.
        studies: Frozen citing-study records.
        snapshot_id: Reviewed corpus snapshot label.

    Returns:
        Blank human coverage-review rows for studies with retrieved text.
    """

    retrieved_by_study: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("status") == "RETRIEVED":
            retrieved_by_study[str(record["study_id"])].append(record)
    rows: list[dict[str, Any]] = []
    for study in studies:
        study_id = str(study["study_id"])
        retrieved = retrieved_by_study.get(study_id, [])
        if not retrieved:
            continue
        known_work_ids = sorted(str(version["work_id"]) for version in study.get("versions") or [])
        retrieved_work_ids = sorted({str(record["work_id"]) for record in retrieved})
        rows.append(
            {
                "coverage_review_version": "evidence-coverage-review-v1",
                "snapshot_id": snapshot_id,
                "study_id": study_id,
                "title": str(study.get("title") or ""),
                "known_version_work_ids": known_work_ids,
                "retrieved_work_ids": retrieved_work_ids,
                "retrieved_candidate_ids": sorted(str(record["candidate_id"]) for record in retrieved),
                "evidence_complete": "",
                "supplement_coverage": "",
                "missing_version_work_ids": sorted(set(known_work_ids) - set(retrieved_work_ids)),
                "coverage_risk_codes": [],
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            }
        )
    return rows


def retrieve_approved(
    *,
    project_root: Path,
    snapshot_id: str,
    approval_path: Path,
    config: Mapping[str, Any],
    transport: HTTPTransport | None = None,
) -> dict[str, Any]:
    """Retrieve only human-approved candidates with resumable checkpoints.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Reviewed corpus snapshot.
        approval_path: Completed rights-review JSONL.
        config: Upstream configuration with retrieval limits.
        transport: Optional fixture-backed HTTP transport.

    Returns:
        Retrieval summary with status and duplicate-audit counts.
    """

    approval_sha256 = sha256_file(approval_path)
    decisions, queue_manifest = _load_approved_decisions(project_root, snapshot_id, approval_path)
    studies = _snapshot_studies(project_root, snapshot_id)
    snapshot_manifest_path = snapshot_paths(project_root, snapshot_id)["artifact_dir"] / "manifest.json"
    if sha256_file(snapshot_manifest_path) != queue_manifest["snapshot_manifest_sha256"]:
        raise ContractError("citation snapshot changed after the rights queue was prepared")
    paths = _rights_paths(project_root, snapshot_id)
    if paths["approval_snapshot"].is_file():
        if load_jsonl(paths["approval_snapshot"]) != decisions:
            raise ContractError("a different completed rights review already exists for this retrieval namespace")
    else:
        atomic_write_jsonl(paths["approval_snapshot"], decisions)
    frozen_approval_sha256 = sha256_file(paths["approval_snapshot"])
    retrieval = (config.get("upstream") or {}).get("retrieval") or {}
    workers = max(1, min(int(retrieval.get("concurrency", 4)), 32))
    ordered: list[dict[str, Any] | None] = [None] * len(decisions)
    transport_value = transport or UrllibTransport()

    def job(index: int, row: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        """Retrieve one indexed rights decision.

        Args:
            index: Frozen queue position.
            row: Validated human decision.

        Returns:
            Original index and terminal record.
        """

        return index, _download_approved(
            row,
            output_root=paths["retrieval_dir"],
            transport=transport_value,
            timeout_seconds=float(retrieval.get("timeout_seconds", 120)),
            max_retries=int(retrieval.get("max_retries", 5)),
            retry_backoff_seconds=float(retrieval.get("retry_backoff_seconds", 1)),
            max_bytes=int(retrieval.get("max_bytes_per_file", 100_000_000)),
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(job, index, row) for index, row in enumerate(decisions)]
        for future in as_completed(futures):
            index, result = future.result()
            ordered[index] = result
    if sha256_file(approval_path) != approval_sha256:
        raise ContractError("rights approval changed during retrieval")
    records = [record for record in ordered if record is not None]
    atomic_write_jsonl(paths["retrieval_manifest"], records)
    collisions = _duplicate_candidates(records, studies)
    atomic_write_jsonl(paths["duplicate_queue"], collisions)
    coverage_rows = _coverage_review_rows(records, studies, snapshot_id)
    atomic_write_jsonl(paths["coverage_queue"], coverage_rows)
    status_counts = {
        status: sum(1 for record in records if record.get("status") == status)
        for status in sorted({str(record.get("status") or "") for record in records})
    }
    summary = {
        "schema_version": RETRIEVAL_VERSION,
        "snapshot_id": snapshot_id,
        "completed_at": utc_now(),
        "rights_queue_manifest_sha256": sha256_file(paths["queue_manifest"]),
        "rights_queue_sha256": queue_manifest["queue"]["sha256"],
        "approval_path": str(approval_path),
        "approval_sha256": approval_sha256,
        "frozen_approval_path": str(paths["approval_snapshot"]),
        "frozen_approval_sha256": frozen_approval_sha256,
        "config_sha256": sha256_bytes(json.dumps(dict(config), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "candidate_count": len(records),
        "status_counts": status_counts,
        "post_retrieval_duplicate_candidate_count": len(collisions),
        "manifest_sha256": sha256_file(paths["retrieval_manifest"]),
        "duplicate_queue_sha256": sha256_file(paths["duplicate_queue"]),
        "coverage_review_candidate_count": len(coverage_rows),
        "coverage_queue_sha256": sha256_file(paths["coverage_queue"]),
    }
    atomic_write_json(paths["retrieval_summary"], summary)
    return summary


def _duplicate_exclusions(
    collision_rows: Sequence[Mapping[str, Any]],
    review_path: Path | None,
) -> set[str]:
    """Validate duplicate resolutions and return study IDs to exclude.

    Args:
        collision_rows: Frozen post-retrieval candidate rows.
        review_path: Completed JSONL when collisions exist.

    Returns:
        Study IDs removed from the final downstream denominator.
    """

    if not collision_rows:
        if review_path is not None:
            raise ContractError("duplicate review was supplied but the frozen collision queue is empty")
        return set()
    if review_path is None:
        raise ContractError("post-retrieval duplicate candidates require a completed review")
    reviews = load_jsonl(review_path)
    by_id = {str(row.get("collision_id") or ""): row for row in reviews}
    expected = {str(row["collision_id"]): row for row in collision_rows}
    if set(by_id) != set(expected) or len(by_id) != len(reviews):
        raise ContractError("duplicate review must resolve every collision exactly once")
    excluded: set[str] = set()
    kept: set[str] = set()
    for collision_id, frozen in expected.items():
        value = by_id[collision_id]
        if {value.get("study_id_a"), value.get("study_id_b")} != {frozen["study_id_a"], frozen["study_id_b"]}:
            raise ContractError(f"duplicate review changed study identities for {collision_id}")
        decision = str(value.get("decision") or "").upper()
        if not str(value.get("reviewer") or "").strip() or not str(value.get("reviewed_at") or "").strip():
            raise ContractError(f"duplicate decision requires reviewer and reviewed_at: {collision_id}")
        if decision == "DISTINCT_STUDIES":
            continue
        if decision != "SAME_STUDY":
            raise ContractError(f"invalid duplicate decision for {collision_id}: {decision}")
        keep = str(value.get("keep_study_id") or "")
        pair = {str(frozen["study_id_a"]), str(frozen["study_id_b"])}
        if keep not in pair:
            raise ContractError(f"SAME_STUDY requires keep_study_id from the collision pair: {collision_id}")
        kept.add(keep)
        excluded.update(pair - {keep})
    if kept & excluded:
        raise ContractError("duplicate review contains inconsistent keep_study_id decisions across a collision component")
    return excluded


def _load_coverage_review(
    frozen_rows: Sequence[Mapping[str, Any]],
    review_path: Path,
) -> dict[str, dict[str, Any]]:
    """Validate human evidence-coverage decisions against the frozen queue.

    Args:
        frozen_rows: Retrieval-bound blank coverage-review rows.
        review_path: Completed coverage-review JSONL.

    Returns:
        Validated decisions keyed by study ID.

    Raises:
        ContractError: If coverage, identity, or decision semantics differ.
    """

    reviews = load_jsonl(review_path)
    by_study = {str(row.get("study_id") or ""): row for row in reviews}
    expected = {str(row["study_id"]): row for row in frozen_rows}
    if "" in by_study or len(by_study) != len(reviews) or set(by_study) != set(expected):
        raise ContractError("evidence coverage review must resolve every retrieved study exactly once")
    immutable_fields = {
        "coverage_review_version",
        "snapshot_id",
        "study_id",
        "title",
        "known_version_work_ids",
        "retrieved_work_ids",
        "retrieved_candidate_ids",
    }
    result: dict[str, dict[str, Any]] = {}
    for study_id, frozen in expected.items():
        value = dict(by_study[study_id])
        for field in immutable_fields:
            if value.get(field) != frozen.get(field):
                raise ContractError(f"evidence coverage review changed frozen field {field} for {study_id}")
        if not str(value.get("reviewer") or "").strip() or not str(value.get("reviewed_at") or "").strip():
            raise ContractError(f"evidence coverage review requires reviewer and reviewed_at for {study_id}")
        if not isinstance(value.get("evidence_complete"), bool):
            raise ContractError(f"evidence_complete must be a JSON Boolean for {study_id}")
        supplement_coverage = str(value.get("supplement_coverage") or "").upper()
        if supplement_coverage not in {"COMPLETE", "NONE_IDENTIFIED", "INCOMPLETE", "NOT_ASSESSED"}:
            raise ContractError(f"invalid supplement_coverage for {study_id}: {supplement_coverage}")
        missing_versions = value.get("missing_version_work_ids")
        risks = value.get("coverage_risk_codes")
        if not isinstance(missing_versions, list) or not all(isinstance(item, str) for item in missing_versions):
            raise ContractError(f"missing_version_work_ids must be a string list for {study_id}")
        if not isinstance(risks, list) or not all(isinstance(item, str) and item.strip() for item in risks):
            raise ContractError(f"coverage_risk_codes must be a nonblank string list for {study_id}")
        known_missing = set(frozen.get("known_version_work_ids") or []) - set(frozen.get("retrieved_work_ids") or [])
        if set(missing_versions) != known_missing:
            raise ContractError(f"missing_version_work_ids disagrees with retrieval state for {study_id}")
        if value["evidence_complete"] is True:
            if missing_versions or supplement_coverage not in {"COMPLETE", "NONE_IDENTIFIED"} or risks:
                raise ContractError(f"evidence_complete=true conflicts with coverage gaps for {study_id}")
        elif not risks:
            raise ContractError(f"evidence_complete=false requires at least one coverage_risk_code for {study_id}")
        value["supplement_coverage"] = supplement_coverage
        result[study_id] = value
    return result


def build_agent_handoff(
    *,
    project_root: Path,
    snapshot_id: str,
    config: Mapping[str, Any],
    codebook_path: Path,
    coverage_review_path: Path,
    duplicate_review_path: Path | None = None,
) -> dict[str, Any]:
    """Build validated one-study capsules from retrieved approved documents.

    Args:
        project_root: Repository or analysis project root.
        snapshot_id: Reviewed corpus snapshot.
        config: Upstream and method configuration.
        codebook_path: Frozen citation-use codebook.
        coverage_review_path: Completed human evidence-coverage review for
            every study with retrieved approved text.
        duplicate_review_path: Required completed review when the final file
            audit found cross-study collisions.

    Returns:
        Handoff manifest accepted by the existing ordered batch runner.
    """

    paths = _rights_paths(project_root, snapshot_id)
    handoff_dir = project_root.resolve() / "artifacts" / "upstream" / "handoff" / snapshot_id
    handoff_manifest_path = handoff_dir / "manifest.json"
    if handoff_manifest_path.exists():
        raise FileExistsError(f"immutable agent handoff already exists for {snapshot_id}")
    summary = load_json(paths["retrieval_summary"])
    if sha256_file(paths["approval_snapshot"]) != summary["frozen_approval_sha256"]:
        raise ContractError("frozen completed rights review hash mismatch")
    if sha256_file(paths["retrieval_manifest"]) != summary["manifest_sha256"]:
        raise ContractError("retrieval manifest hash mismatch")
    if sha256_file(paths["duplicate_queue"]) != summary["duplicate_queue_sha256"]:
        raise ContractError("frozen post-retrieval duplicate queue hash mismatch")
    if sha256_file(paths["coverage_queue"]) != summary["coverage_queue_sha256"]:
        raise ContractError("frozen evidence coverage queue hash mismatch")
    current_config_sha256 = sha256_bytes(
        json.dumps(dict(config), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if summary.get("config_sha256") != current_config_sha256:
        raise ContractError("upstream configuration changed after retrieval")
    records = load_jsonl(paths["retrieval_manifest"])
    collisions = load_jsonl(paths["duplicate_queue"])
    coverage_review_rows = load_jsonl(coverage_review_path)
    coverage = _load_coverage_review(load_jsonl(paths["coverage_queue"]), coverage_review_path)
    excluded = _duplicate_exclusions(collisions, duplicate_review_path)
    studies = _snapshot_studies(project_root, snapshot_id)
    by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("status") == "RETRIEVED" and str(record["study_id"]) not in excluded:
            for path_field, hash_field in (("binary_path", "sha256"), ("text_path", "text_sha256")):
                record_path = Path(str(record.get(path_field) or "")).resolve()
                try:
                    record_path.relative_to(paths["retrieval_dir"].resolve())
                except ValueError as error:
                    raise ContractError(f"retrieved handoff path escapes retrieval root: {record_path}") from error
                if not record_path.is_file() or sha256_file(record_path) != record.get(hash_field):
                    raise ContractError(f"retrieved handoff file is missing or stale: {record_path}")
            by_study[str(record["study_id"])].append(record)
    upstream = config.get("upstream") if isinstance(config.get("upstream"), Mapping) else {}
    method_config = upstream.get("method") if isinstance(upstream.get("method"), Mapping) else {}
    seeds = load_json(snapshot_paths(project_root, snapshot_id)["artifact_dir"] / "seed_versions.json")
    seed_identifiers = {
        f"{seed['seed_id']}_{kind}": value
        for seed in seeds
        for kind, value in seed.get("identifiers", {}).items()
    }
    target_method = {
        "canonical_name": str(method_config.get("canonical_name") or ""),
        "aliases": list(method_config.get("aliases") or []),
        "seed_identifiers": seed_identifiers,
    }
    codebook = load_json(codebook_path)
    method_path = handoff_dir / "method.json"
    atomic_write_json(method_path, target_method)
    frozen_coverage_review_path = handoff_dir / "evidence_coverage_review.jsonl"
    atomic_write_jsonl(frozen_coverage_review_path, coverage_review_rows)
    frozen_duplicate_review_path: Path | None = None
    if duplicate_review_path is not None:
        frozen_duplicate_review_path = handoff_dir / "post_retrieval_duplicate_review.jsonl"
        atomic_write_jsonl(frozen_duplicate_review_path, load_jsonl(duplicate_review_path))
    capsule_rows: list[dict[str, Any]] = []
    disposition_rows: list[dict[str, Any]] = []
    for study in studies:
        study_id = str(study["study_id"])
        study_records = by_study.get(study_id, [])
        if not study_records:
            disposition_rows.append({"study_id": study_id, "status": "NO_RIGHTS_APPROVED_RETRIEVED_TEXT"})
            continue
        coverage_decision = coverage[study_id]
        study_value = {
            "study_id": study_id,
            "title": str(study.get("title") or ""),
            "identifiers": {str(key): str(value) for key, value in (study.get("identifiers") or {}).items()},
        }
        document_specs = []
        for record in study_records:
            approval = record["human_rights_approval"]
            text_path = Path(str(record["text_path"])).resolve()
            try:
                relative_path = text_path.relative_to(project_root.resolve())
            except ValueError as error:
                raise ContractError(f"retrieved text escapes project root: {text_path}") from error
            version_text = str(record.get("version") or "").lower()
            version_type = "PREPRINT" if "preprint" in version_text else "PUBLISHED" if "publish" in version_text else "OTHER"
            document_specs.append(
                {
                    "path": str(relative_path),
                    "source_file": text_path.name,
                    "document_type": str(record.get("document_role") or "MAIN").upper(),
                    "version_id": str(record["work_id"]),
                    "version_type": version_type,
                    "license": str(approval["permission_basis"]),
                    "cloud_processing_allowed": True,
                }
            )
        study_path = handoff_dir / "studies" / f"{study_id}.json"
        documents_path = handoff_dir / "documents" / f"{study_id}.json"
        atomic_write_json(study_path, study_value)
        atomic_write_json(documents_path, document_specs)
        capsule = build_capsule(
            project_root=project_root,
            study=study_value,
            target_method=target_method,
            document_specs=document_specs,
            codebook=codebook,
            evidence_complete=bool(coverage_decision["evidence_complete"]),
            coverage_risk_codes=tuple(coverage_decision["coverage_risk_codes"]),
        )
        capsule_path = handoff_dir / "capsules" / f"{study_id}.json"
        atomic_write_json(capsule_path, capsule)
        capsule_rows.append(
            {
                "study_id": study_id,
                "method_path": str(method_path),
                "study_path": str(study_path),
                "documents_path": str(documents_path),
                "capsule_path": str(capsule_path),
            }
        )
        disposition_rows.append({"study_id": study_id, "status": "CAPSULE_READY"})
    manifest_path = handoff_dir / "capsules.jsonl"
    atomic_write_jsonl(manifest_path, capsule_rows)
    atomic_write_jsonl(handoff_dir / "study_dispositions.jsonl", disposition_rows)
    handoff = {
        "schema_version": "agent-handoff-v1",
        "snapshot_id": snapshot_id,
        "created_at": utc_now(),
        "source_study_count": len(studies),
        "capsule_count": len(capsule_rows),
        "excluded_duplicate_study_count": len(excluded),
        "capsule_manifest": str(manifest_path),
        "capsule_manifest_sha256": sha256_file(manifest_path),
        "method_manifest": str(method_path),
        "method_manifest_sha256": sha256_file(method_path),
        "retrieval_manifest_sha256": summary["manifest_sha256"],
        "duplicate_queue_sha256": summary["duplicate_queue_sha256"],
        "duplicate_review_path": str(frozen_duplicate_review_path) if frozen_duplicate_review_path else "",
        "duplicate_review_sha256": sha256_file(frozen_duplicate_review_path) if frozen_duplicate_review_path else "",
        "coverage_review_path": str(frozen_coverage_review_path),
        "coverage_review_sha256": sha256_file(frozen_coverage_review_path),
        "coverage_queue_sha256": summary["coverage_queue_sha256"],
        "codebook_sha256": sha256_file(codebook_path),
        "machine_processing_permission_source": "explicit completed human rights-review rows",
    }
    atomic_write_json(handoff_manifest_path, handoff)
    return handoff
