"""Offline tests for reproducible discovery, rights review, and handoff."""

# Standard-library imports create isolated projects, copy review rows, and
# serialize exact fixture responses for injectable network tests.
import json
from pathlib import Path
import tempfile
import unittest
from typing import Any, Mapping

from citation_use_review.bibliography import cluster_studies, reconcile_provider_records
from citation_use_review.errors import ContractError
from citation_use_review.rights import (
    _duplicate_candidates,
    _duplicate_exclusions,
    _load_coverage_review,
    build_agent_handoff,
    prepare_rights_review,
    retrieve_approved,
)
from citation_use_review.sources import EuropePMCAdapter, HTTPResult, OpenCitationsAdapter, ProvenanceFetcher
from citation_use_review.upstream import derive_reviewed_snapshot, discover_snapshot, snapshot_paths, snapshot_summary
from citation_use_review.util import atomic_write_jsonl, load_jsonl, sha256_file


class FixtureTransport:
    """Return deterministic JSON or article bytes keyed by URL."""

    def __init__(self, responses: Mapping[str, list[HTTPResult] | HTTPResult]):
        """Initialize ordered fixture responses.

        Args:
            responses: URL-to-response or URL-to-response-sequence mapping.

        Returns:
            ``None``; copies are retained for deterministic consumption.
        """

        self.responses = {
            url: list(value) if isinstance(value, list) else [value]
            for url, value in responses.items()
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def fetch(
        self,
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HTTPResult:
        """Pop one configured response.

        Args:
            url: Requested endpoint.
            params: Public query parameters.
            headers: Public request headers.
            timeout_seconds: Requested timeout.

        Returns:
            Next exact fixture response.

        Raises:
            OSError: If no response remains for the URL.
        """

        del headers, timeout_seconds
        self.calls.append((url, dict(params)))
        values = self.responses.get(url)
        if not values:
            raise OSError(f"unexpected fixture request: {url}")
        return values.pop(0)


def json_result(value: Any, status: int = 200) -> HTTPResult:
    """Serialize one JSON fixture as an HTTP result.

    Args:
        value: JSON-compatible payload.
        status: HTTP status.

    Returns:
        Exact UTF-8 JSON response.
    """

    return HTTPResult(status=status, headers={"Content-Type": "application/json"}, body=json.dumps(value).encode("utf-8"))


def upstream_config(*, opencitations: bool = False) -> dict[str, Any]:
    """Build a complete method-agnostic test configuration.

    Args:
        opencitations: Whether to enable the optional adapter.

    Returns:
        Configuration dictionary.
    """

    return {
        "upstream": {
            "method": {"canonical_name": "TestMethod", "aliases": ["TestMethod"]},
            "seed_versions": [
                {
                    "seed_id": "testmethod-published",
                    "version_type": "PUBLISHED",
                    "title": "TestMethod",
                    "identifiers": {"doi": "10.1000/seed", "openalex": "WSEED"},
                }
            ],
            "first_public_date": "2024-01-01",
            "sources": {
                "openalex": {"enabled": True, "per_page": 200},
                "europe_pmc": {"enabled": False},
                "opencitations": {"enabled": opencitations},
                "crossref": {"enabled": False},
                "pubmed": {"enabled": False},
            },
            "http": {"minimum_delay_seconds": 0, "max_retries": 0},
            "retrieval": {"concurrency": 2, "max_retries": 0, "max_bytes_per_file": 1_000_000},
        }
    }


def openalex_payload() -> dict[str, Any]:
    """Return two same-title works that require manual study review.

    Returns:
        Cursor-complete OpenAlex fixture payload.
    """

    return {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "display_name": "A biological analysis with TestMethod",
                "publication_date": "2025-01-10",
                "publication_year": 2025,
                "type": "article",
                "ids": {"doi": "https://doi.org/10.1000/article-a"},
                "authorships": [{"author": {"display_name": "Ada Researcher"}}],
                "referenced_works": ["https://openalex.org/WSEED"],
                "locations": [
                    {
                        "is_oa": True,
                        "landing_page_url": "https://example.test/article-a.xml",
                        "license": "cc-by",
                        "version": "publishedVersion",
                    }
                ],
            },
            {
                "id": "https://openalex.org/W2",
                "display_name": "A biological analysis with TestMethod",
                "publication_date": "2025-01-01",
                "publication_year": 2025,
                "type": "preprint",
                "ids": {"doi": "https://doi.org/10.1000/article-a-preprint"},
                "authorships": [{"author": {"display_name": "Ada Researcher"}}],
                "referenced_works": ["https://openalex.org/WSEED"],
                "locations": [
                    {
                        "is_oa": True,
                        "landing_page_url": "https://example.test/article-a-preprint.xml",
                        "license": "cc-by",
                        "version": "submittedVersion",
                    }
                ],
            },
        ],
        "meta": {"next_cursor": None},
    }


def article_xml(title: str, doi: str, result: str) -> bytes:
    """Build a small identity-bearing article XML fixture.

    Args:
        title: Expected article title.
        doi: Expected DOI.
        result: Version-specific result sentence.

    Returns:
        UTF-8 XML bytes with enough text for capsule construction.
    """

    filler = " ".join(["This paragraph provides biological context and methodological detail."] * 12)
    return (
        f"<article><front><article-title>{title}</article-title><article-id pub-id-type='doi'>{doi}</article-id></front>"
        f"<body><sec><title>Methods</title><p>We applied TestMethod [7] to single-cell biological data. {filler}</p>"
        f"<sec><title>Results</title><p>{result}</p></sec></sec></body></article>"
    ).encode("utf-8")


class UpstreamWorkflowTests(unittest.TestCase):
    """Exercise the public scGPT-derived upstream contract without network use."""

    def setUp(self) -> None:
        """Create an isolated project and discovery fixture.

        Returns:
            ``None``; paths are stored on the instance.
        """

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.config = upstream_config()
        self.discovery_transport = FixtureTransport(
            {"https://api.openalex.org/works": json_result(openalex_payload())}
        )

    def tearDown(self) -> None:
        """Remove the isolated test project.

        Returns:
            ``None``.
        """

        self.temporary_directory.cleanup()

    def _discover_and_review(self) -> str:
        """Create a source snapshot and merge its one candidate pair.

        Returns:
            Derived reviewed snapshot ID.
        """

        manifest = discover_snapshot(
            project_root=self.root,
            config=self.config,
            snapshot_id="source-v1",
            transport=self.discovery_transport,
        )
        self.assertEqual(manifest["study_count"], 2)
        self.assertEqual(manifest["pending_cluster_candidate_count"], 1)
        self.assertEqual(manifest["citation_edge_count"], 2)
        self.assertEqual(manifest["citation_source_counts"], {"openalex": 2})
        self.assertEqual(manifest["source_record_counts"], {"openalex": 2})
        source_files = snapshot_paths(self.root, "source-v1")
        candidates = load_jsonl(source_files["artifact_dir"] / "cluster_candidates.jsonl")
        review = [
            {
                **candidates[0],
                "recommendation": "MERGE",
                "reviewer": "reviewer-1",
                "reviewed_at": "2026-08-27T12:00:00+00:00",
                "notes": "Same study, preprint and article.",
            }
        ]
        review_path = self.root / "cluster_review.jsonl"
        atomic_write_jsonl(review_path, review)
        parent_hash = sha256_file(source_files["artifact_dir"] / "manifest.json")
        derived = derive_reviewed_snapshot(
            project_root=self.root,
            parent_snapshot_id="source-v1",
            review_path=review_path,
            derived_snapshot_id="reviewed-v1",
        )
        self.assertEqual(derived["study_count"], 1)
        self.assertEqual(derived["pending_cluster_candidate_count"], 0)
        self.assertTrue(derived["production_eligible"])
        self.assertIn("cluster_review", derived["files"])
        self.assertTrue((snapshot_paths(self.root, "reviewed-v1")["artifact_dir"] / "cluster_review.jsonl").is_file())
        self.assertEqual(sha256_file(source_files["artifact_dir"] / "manifest.json"), parent_hash)
        return "reviewed-v1"

    def test_discovery_review_rights_retrieval_and_handoff(self) -> None:
        """The complete upstream flow ends in a batch-compatible capsule manifest."""

        snapshot_id = self._discover_and_review()
        queue_manifest = prepare_rights_review(project_root=self.root, snapshot_id=snapshot_id)
        self.assertEqual(queue_manifest["candidate_count"], 2)
        queue_path = self.root / "artifacts" / "upstream" / "rights" / snapshot_id / "rights_review_queue.jsonl"
        queue = load_jsonl(queue_path)
        approvals = []
        for row in queue:
            approvals.append(
                {
                    **row,
                    "decision": "APPROVE",
                    "cloud_processing_allowed": True,
                    "permission_basis": "Human reviewed CC BY provider and document evidence.",
                    "reviewer": "reviewer-1",
                    "reviewed_at": "2026-08-27T12:00:00+00:00",
                    "notes": "Approved for this test workflow.",
                }
            )
        approval_path = self.root / "rights_approved.jsonl"
        atomic_write_jsonl(approval_path, approvals)
        retrieval_transport = FixtureTransport(
            {
                "https://example.test/article-a.xml": HTTPResult(
                    200,
                    {"Content-Type": "application/xml"},
                    article_xml("A biological analysis with TestMethod", "10.1000/article-a", "The treated cells showed an immune-state transition."),
                ),
                "https://example.test/article-a-preprint.xml": HTTPResult(
                    200,
                    {"Content-Type": "application/xml"},
                    article_xml("A biological analysis with TestMethod", "10.1000/article-a-preprint", "The preprint reported the same immune-state transition."),
                ),
            }
        )
        retrieval = retrieve_approved(
            project_root=self.root,
            snapshot_id=snapshot_id,
            approval_path=approval_path,
            config=self.config,
            transport=retrieval_transport,
        )
        self.assertEqual(retrieval["status_counts"], {"RETRIEVED": 2})
        self.assertEqual(retrieval["post_retrieval_duplicate_candidate_count"], 0)
        self.assertEqual(retrieval["coverage_review_candidate_count"], 1)
        self.assertTrue(Path(retrieval["frozen_approval_path"]).is_file())
        self.assertEqual(sha256_file(retrieval["frozen_approval_path"]), retrieval["frozen_approval_sha256"])
        coverage_queue_path = (
            self.root
            / "artifacts"
            / "upstream"
            / "retrieval"
            / snapshot_id
            / "evidence_coverage_review_queue.jsonl"
        )
        coverage_review_path = self.root / "evidence_coverage_completed.jsonl"
        coverage_rows = load_jsonl(coverage_queue_path)
        atomic_write_jsonl(
            coverage_review_path,
            [
                {
                    **coverage_rows[0],
                    "evidence_complete": True,
                    "supplement_coverage": "NONE_IDENTIFIED",
                    "coverage_risk_codes": [],
                    "reviewer": "reviewer-1",
                    "reviewed_at": "2026-08-27T13:00:00+00:00",
                    "notes": "All known versions retrieved; no supplements identified.",
                }
            ],
        )
        repository_root = Path(__file__).resolve().parents[1]
        handoff = build_agent_handoff(
            project_root=self.root,
            snapshot_id=snapshot_id,
            config=self.config,
            codebook_path=repository_root / "codebook" / "citation_use_codebook.json",
            coverage_review_path=coverage_review_path,
        )
        self.assertEqual(handoff["capsule_count"], 1)
        capsule_rows = load_jsonl(Path(handoff["capsule_manifest"]))
        self.assertEqual(len(capsule_rows), 1)
        self.assertTrue(Path(capsule_rows[0]["method_path"]).is_file())
        self.assertTrue(Path(capsule_rows[0]["study_path"]).is_file())
        self.assertTrue(Path(capsule_rows[0]["documents_path"]).is_file())
        capsule = json.loads(Path(capsule_rows[0]["capsule_path"]).read_text(encoding="utf-8"))
        self.assertEqual(capsule["target_method"]["canonical_name"], "TestMethod")
        self.assertEqual(len(capsule["documents"]), 2)
        self.assertGreaterEqual(len(capsule["physical_target_occurrences"]), 2)
        with self.assertRaisesRegex(FileExistsError, "immutable agent handoff"):
            build_agent_handoff(
                project_root=self.root,
                snapshot_id=snapshot_id,
                config=self.config,
                codebook_path=repository_root / "codebook" / "citation_use_codebook.json",
                coverage_review_path=coverage_review_path,
            )

    def test_approval_cannot_be_inferred_from_provider_metadata(self) -> None:
        """A provider-reported CC license never substitutes for explicit approval."""

        snapshot_id = self._discover_and_review()
        prepare_rights_review(project_root=self.root, snapshot_id=snapshot_id)
        queue_path = self.root / "artifacts" / "upstream" / "rights" / snapshot_id / "rights_review_queue.jsonl"
        rows = load_jsonl(queue_path)
        for row in rows:
            row.update({"decision": "APPROVE", "permission_basis": "CC BY", "reviewer": "r", "reviewed_at": "now"})
        approval_path = self.root / "invalid_approval.jsonl"
        atomic_write_jsonl(approval_path, rows)
        with self.assertRaisesRegex(ContractError, "explicit cloud_processing_allowed=true"):
            retrieve_approved(
                project_root=self.root,
                snapshot_id=snapshot_id,
                approval_path=approval_path,
                config=self.config,
                transport=FixtureTransport({}),
            )

    def test_optional_source_failure_requires_explicit_promotion(self) -> None:
        """Optional source failures are frozen and require an explicit exception."""

        config = upstream_config(opencitations=True)
        manifest = discover_snapshot(
            project_root=self.root,
            config=config,
            snapshot_id="partial-v1",
            transport=FixtureTransport({"https://api.openalex.org/works": json_result(openalex_payload())}),
        )
        self.assertFalse(manifest["source_complete"])
        self.assertIn("opencitations", manifest["source_errors"])
        candidates = load_jsonl(snapshot_paths(self.root, "partial-v1")["artifact_dir"] / "cluster_candidates.jsonl")
        review_path = self.root / "partial_review.jsonl"
        atomic_write_jsonl(
            review_path,
            [
                {
                    **candidates[0],
                    "recommendation": "KEEP_SEPARATE",
                    "reviewer": "reviewer-1",
                    "reviewed_at": "2026-08-27T12:00:00+00:00",
                }
            ],
        )
        with self.assertRaisesRegex(ContractError, "allow-incomplete-sources"):
            derive_reviewed_snapshot(
                project_root=self.root,
                parent_snapshot_id="partial-v1",
                review_path=review_path,
                derived_snapshot_id="partial-reviewed-v1",
            )
        derived = derive_reviewed_snapshot(
            project_root=self.root,
            parent_snapshot_id="partial-v1",
            review_path=review_path,
            derived_snapshot_id="partial-reviewed-v2",
            allow_incomplete_sources=True,
        )
        self.assertTrue(derived["production_eligible"])
        self.assertFalse(derived["source_complete"])

    def test_opencitations_keeps_raw_response_and_supported_identifiers(self) -> None:
        """OMIDs stay in raw provenance while strong tokens enter reconciliation."""

        raw_root = self.root / "raw"
        transport = FixtureTransport(
            {
                "https://api.opencitations.net/index/v2/citations/doi:10.1000/seed": json_result(
                    [{"oci": "1-2", "citing": "omid:br/1 doi:10.1000/citing pmid:123", "creation": "2025-01-01"}]
                )
            }
        )
        fetcher = ProvenanceFetcher(raw_root, transport=transport, minimum_delay_seconds=0, max_retries=0)
        records = OpenCitationsAdapter().discover(
            [{"seed_id": "seed", "identifiers": {"doi": "10.1000/seed"}}],
            fetcher,
            {},
        )
        self.assertEqual(records[0]["identifiers"], {"doi": "10.1000/citing"})
        self.assertEqual(
            records[0]["provider_identifier_hints"],
            [{"identifier_type": "pmid", "identifier": "123"}],
        )
        self.assertEqual(len(fetcher.provenance_records()), 1)
        self.assertTrue(next((raw_root / "responses" / "opencitations").glob("*.json")).is_file())

    def test_opencitations_cross_version_hint_requires_manual_review(self) -> None:
        """A multi-token provider hint must not silently merge two versions."""

        records = [
            {
                "source": "opencitations",
                "source_record_id": "oc-1",
                "raw_response_id": "raw-1",
                "title": "A preprint record",
                "authors": [],
                "publication_date": "2025-01-01",
                "publication_year": 2025,
                "work_type": "preprint",
                "venue": "",
                "identifiers": {"doi": "10.1000/preprint"},
                "cited_seed_ids": ["seed"],
                "retrieval_candidates": [],
                "explicit_relations": [],
                "provider_identifier_hints": [{"identifier_type": "pmid", "identifier": "123"}],
            },
            {
                "source": "pubmed",
                "source_record_id": "123",
                "raw_response_id": "raw-2",
                "title": "Published article record",
                "authors": [],
                "publication_date": "2025-02-01",
                "publication_year": 2025,
                "work_type": "article",
                "venue": "Journal",
                "identifiers": {"pmid": "123"},
                "cited_seed_ids": [],
                "retrieval_candidates": [],
                "explicit_relations": [],
            },
        ]
        works = reconcile_provider_records(records)
        studies, candidates = cluster_studies(works)
        self.assertEqual(len(works), 2)
        self.assertEqual(len(studies), 2)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["reason"], "provider_cross_version_hint")

    def test_raw_response_resume_and_retry_are_deterministic(self) -> None:
        """A retryable page is cached once and reused without a network call."""

        raw_root = self.root / "retry_raw"
        endpoint = "https://example.test/api"
        first_transport = FixtureTransport(
            {
                endpoint: [
                    json_result({"error": "rate limited"}, status=429),
                    json_result({"results": [{"id": 1}]}),
                ]
            }
        )
        first = ProvenanceFetcher(raw_root, transport=first_transport, minimum_delay_seconds=0, max_retries=1)
        payload, response_id = first.request_json(
            source="fixture",
            seed_id="seed",
            url=endpoint,
            params={"page": 1},
            page_token="1",
        )
        self.assertEqual(payload["results"][0]["id"], 1)
        self.assertEqual(len(first_transport.calls), 2)
        second_transport = FixtureTransport({})
        second = ProvenanceFetcher(raw_root, transport=second_transport, minimum_delay_seconds=0, max_retries=0)
        resumed_payload, resumed_id = second.request_json(
            source="fixture",
            seed_id="seed",
            url=endpoint,
            params={"page": 1},
            page_token="1",
        )
        self.assertEqual(resumed_payload, payload)
        self.assertEqual(resumed_id, response_id)
        self.assertEqual(second_transport.calls, [])

    def test_openalex_cannot_be_disabled(self) -> None:
        """The required primary citation graph fails before snapshot publication."""

        config = upstream_config()
        config["upstream"]["sources"]["openalex"]["enabled"] = False
        with self.assertRaisesRegex(ContractError, "required primary citation source"):
            discover_snapshot(
                project_root=self.root,
                config=config,
                snapshot_id="no-openalex",
                transport=FixtureTransport({}),
            )

    def test_europe_pmc_enriches_preprint_and_published_version(self) -> None:
        """PPR CORE relations hydrate and cluster an absent MED target."""

        citations_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/PPR/PPRSEED/citations"
        search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        transport = FixtureTransport(
            {
                citations_url: json_result(
                    {
                        "hitCount": 1,
                        "citationList": {
                            "citation": [
                                {
                                    "source": "PPR",
                                    "id": "PPR100",
                                    "title": "A citing preprint",
                                    "authorString": "A Researcher",
                                    "pubYear": 2025,
                                }
                            ]
                        },
                    }
                ),
                search_url: [
                    json_result(
                        {
                            "resultList": {
                                "result": [
                                    {
                                        "source": "PPR",
                                        "id": "PPR100",
                                        "doi": "10.1000/preprint-100",
                                        "title": "A citing preprint",
                                        "pubYear": 2025,
                                        "commentCorrectionList": {
                                            "commentCorrection": [
                                                {"type": "Preprint of", "source": "MED", "id": "123"}
                                            ]
                                        },
                                    }
                                ]
                            }
                        }
                    ),
                    json_result(
                        {
                            "resultList": {
                                "result": [
                                    {
                                        "source": "MED",
                                        "id": "123",
                                        "pmid": "123",
                                        "doi": "10.1000/published-100",
                                        "title": "A citing article",
                                        "pubYear": 2025,
                                    }
                                ]
                            }
                        }
                    ),
                ],
            }
        )
        fetcher = ProvenanceFetcher(self.root / "epmc_raw", transport=transport, minimum_delay_seconds=0, max_retries=0)
        records = EuropePMCAdapter().discover(
            [
                {
                    "seed_id": "seed-ppr",
                    "identifiers": {"doi": "10.1000/seed"},
                    "europe_pmc_source": "PPR",
                    "europe_pmc_id": "PPR:PPRSEED",
                }
            ],
            fetcher,
            {"page_size": 1000, "enrichment_batch_size": 50},
        )
        works = reconcile_provider_records(records)
        studies, candidates = cluster_studies(works)
        self.assertEqual(len(records), 3)
        self.assertEqual(len(works), 2)
        self.assertEqual(len(studies), 1)
        self.assertEqual(candidates, [])
        self.assertEqual(studies[0]["version_count"], 2)

    def test_snapshot_hash_verification_rejects_tampering(self) -> None:
        """Frozen artifacts fail closed when one byte changes."""

        self._discover_and_review()
        paths = snapshot_paths(self.root, "reviewed-v1")
        studies = paths["artifact_dir"] / "citing_studies.jsonl"
        studies.write_bytes(studies.read_bytes() + b"\n")
        with self.assertRaisesRegex(ContractError, "missing or stale"):
            snapshot_summary(self.root, "reviewed-v1")

    def test_snapshot_verification_rejects_raw_response_tampering(self) -> None:
        """A frozen snapshot also binds the exact cached provider response."""

        self._discover_and_review()
        paths = snapshot_paths(self.root, "reviewed-v1")
        raw_record = load_jsonl(paths["artifact_dir"] / "raw_responses.jsonl")[0]
        body_path = (
            self.root
            / "state"
            / "upstream"
            / "snapshots"
            / "source-v1"
            / "raw"
            / raw_record["body_relative_path"]
        )
        body_path.write_bytes(body_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ContractError, "raw response body is missing or stale"):
            snapshot_summary(self.root, "reviewed-v1")

    def test_post_retrieval_duplicate_gate_requires_complete_resolution(self) -> None:
        """Cross-study DOI/file collisions block handoff until reviewed."""

        studies = [
            {"study_id": "study-a", "identifiers": {"doi": "10.1000/same"}},
            {"study_id": "study-b", "identifiers": {"doi": "https://doi.org/10.1000/same"}},
        ]
        records = [
            {"status": "RETRIEVED", "study_id": "study-a", "sha256": "a" * 64},
            {"status": "RETRIEVED", "study_id": "study-b", "sha256": "a" * 64},
        ]
        collisions = _duplicate_candidates(records, studies)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(
            collisions[0]["reasons"],
            ["BYTE_IDENTICAL_FULLTEXT", "SAME_NORMALIZED_DOI"],
        )
        with self.assertRaisesRegex(ContractError, "completed review"):
            _duplicate_exclusions(collisions, None)
        review_path = self.root / "duplicate_review.jsonl"
        atomic_write_jsonl(
            review_path,
            [
                {
                    **collisions[0],
                    "decision": "SAME_STUDY",
                    "keep_study_id": "study-a",
                    "reviewer": "reviewer-1",
                    "reviewed_at": "2026-08-27T12:00:00+00:00",
                    "notes": "Same DOI and byte-identical full text.",
                }
            ],
        )
        self.assertEqual(_duplicate_exclusions(collisions, review_path), {"study-b"})

    def test_coverage_review_cannot_claim_complete_with_known_gaps(self) -> None:
        """Evidence completeness must agree with version and supplement state."""

        frozen = {
            "coverage_review_version": "evidence-coverage-review-v1",
            "snapshot_id": "reviewed-v1",
            "study_id": "study-a",
            "title": "A study",
            "known_version_work_ids": ["work-a", "work-b"],
            "retrieved_work_ids": ["work-a"],
            "retrieved_candidate_ids": ["document-a"],
            "evidence_complete": "",
            "supplement_coverage": "",
            "missing_version_work_ids": ["work-b"],
            "coverage_risk_codes": [],
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        }
        review_path = self.root / "coverage_invalid.jsonl"
        atomic_write_jsonl(
            review_path,
            [
                {
                    **frozen,
                    "evidence_complete": True,
                    "supplement_coverage": "COMPLETE",
                    "reviewer": "reviewer-1",
                    "reviewed_at": "2026-08-27T12:00:00+00:00",
                }
            ],
        )
        with self.assertRaisesRegex(ContractError, "conflicts with coverage gaps"):
            _load_coverage_review([frozen], review_path)


if __name__ == "__main__":
    unittest.main()
