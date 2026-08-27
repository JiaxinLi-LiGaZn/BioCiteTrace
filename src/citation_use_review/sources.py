"""Citation-source adapters with immutable raw-response provenance."""

from __future__ import annotations

# Standard-library imports define injectable protocols, encode HTTP queries,
# implement bounded retries, persist exact response bytes, and parse metadata.
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .bibliography import normalize_identifier, normalize_title, stable_id
from .errors import ContractError
from .util import atomic_write_bytes, atomic_write_json, load_json, sha256_bytes, utc_now


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
EUROPE_PMC_REST_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OPENCITATIONS_INDEX_URL = "https://api.opencitations.net/index/v2/citations"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@dataclass(frozen=True, slots=True)
class HTTPResult:
    """Represent one complete HTTP response.

    Args:
        status: Numeric HTTP status.
        headers: Response headers without credentials.
        body: Exact response bytes.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes


class HTTPTransport(Protocol):
    """Protocol for live or fixture-backed HTTP access."""

    def fetch(
        self,
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HTTPResult:
        """Fetch one URL.

        Args:
            url: Endpoint without query parameters.
            params: Public query parameters.
            headers: Public request headers.
            timeout_seconds: Per-request timeout.

        Returns:
            Complete status, headers, and exact response body.
        """


class UrllibTransport:
    """Small standard-library implementation of :class:`HTTPTransport`."""

    def fetch(
        self,
        url: str,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HTTPResult:
        """Perform one GET request without internal retries.

        Args:
            url: Endpoint without query parameters.
            params: Public query parameters.
            headers: Public request headers.
            timeout_seconds: Per-request timeout.

        Returns:
            Complete response bytes and non-secret headers.

        Raises:
            HTTPError: For an HTTP error response.
            URLError: For a transport failure.
        """

        query = urlencode([(key, value) for key, value in params.items() if value not in (None, "")])
        request_url = f"{url}?{query}" if query else url
        request = Request(request_url, headers=dict(headers), method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:
            return HTTPResult(
                status=int(response.status),
                headers={str(key): str(value) for key, value in response.headers.items()},
                body=response.read(),
            )


class ProvenanceFetcher:
    """Fetch JSON with retry, exact-byte persistence, and resumable caching."""

    def __init__(
        self,
        raw_root: Path,
        *,
        transport: HTTPTransport | None = None,
        timeout_seconds: float = 60.0,
        minimum_delay_seconds: float = 0.2,
        max_retries: int = 5,
        user_agent: str = "fulltext-citation-use-review/0.2",
    ):
        """Configure one snapshot-scoped raw-response store.

        Args:
            raw_root: Private directory for response bytes and metadata.
            transport: Optional fixture or live transport.
            timeout_seconds: Per-attempt timeout.
            minimum_delay_seconds: Lower bound for retry and page delays.
            max_retries: Retry count after the first attempt.
            user_agent: Public User-Agent value.

        Returns:
            ``None``; settings are stored on the instance.
        """

        self.raw_root = raw_root
        self.transport = transport or UrllibTransport()
        self.timeout_seconds = float(timeout_seconds)
        self.minimum_delay_seconds = max(0.0, float(minimum_delay_seconds))
        self.max_retries = max(0, int(max_retries))
        self.user_agent = user_agent
        self._records: dict[str, dict[str, Any]] = {}
        self._last_live_request_at: float | None = None

    def _wait_for_request_slot(self) -> None:
        """Enforce the configured minimum interval between live requests.

        Returns:
            ``None`` after waiting, if necessary, and recording the start time
            of the next request.
        """

        if self._last_live_request_at is not None and self.minimum_delay_seconds:
            elapsed = time.monotonic() - self._last_live_request_at
            if elapsed < self.minimum_delay_seconds:
                time.sleep(self.minimum_delay_seconds - elapsed)
        self._last_live_request_at = time.monotonic()

    def request_json(
        self,
        *,
        source: str,
        seed_id: str,
        url: str,
        params: Mapping[str, Any],
        page_token: str,
    ) -> tuple[Any, str]:
        """Fetch or resume one JSON response and register exact provenance.

        Args:
            source: Stable source adapter name.
            seed_id: Seed version identifier or ``combined``.
            url: Public endpoint.
            params: Public request parameters.
            page_token: Stable cursor/page label.

        Returns:
            Decoded JSON value and deterministic raw-response ID.
        """

        request_id = stable_id("request_", source, seed_id, url, dict(sorted(params.items())), page_token)
        metadata_path = self.raw_root / "index" / f"{request_id}.json"
        if metadata_path.is_file():
            metadata = load_json(metadata_path)
            body_path = self.raw_root / str(metadata["body_relative_path"])
            body = body_path.read_bytes()
            if sha256_bytes(body) != metadata["body_sha256"]:
                raise ContractError(f"cached raw response hash mismatch: {body_path}")
            self._records[str(metadata["response_id"])] = dict(metadata)
            try:
                return json.loads(body), str(metadata["response_id"])
            except json.JSONDecodeError as error:
                raise ContractError(f"cached response is invalid JSON: {body_path}") from error

        result: HTTPResult | None = None
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self._wait_for_request_slot()
                result = self.transport.fetch(
                    url,
                    params,
                    {"User-Agent": self.user_agent, "Accept": "application/json"},
                    self.timeout_seconds,
                )
                if result.status >= 400:
                    raise HTTPError(url, result.status, "HTTP error", dict(result.headers), None)
                break
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                last_error = error
                status = int(getattr(error, "code", 0) or 0)
                retryable = not status or status in {429, 500, 502, 503, 504}
                if attempt >= self.max_retries or not retryable:
                    raise
                retry_after = ""
                if isinstance(error, HTTPError) and error.headers:
                    retry_after = str(error.headers.get("Retry-After") or "")
                try:
                    delay = float(retry_after) if retry_after else min(2**attempt, 30)
                except ValueError:
                    delay = min(2**attempt, 30)
                time.sleep(max(self.minimum_delay_seconds, delay))
        if result is None:
            raise ContractError(f"no response returned for {source}: {last_error}")
        try:
            payload = json.loads(result.body)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ContractError(f"invalid JSON returned by {source}: {url}") from error
        digest = sha256_bytes(result.body)
        response_id = stable_id("raw_", source, url, dict(sorted(params.items())), page_token, digest)
        body_relative = Path("responses") / source / f"{response_id}.json"
        atomic_write_bytes(self.raw_root / body_relative, result.body)
        safe_headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower() not in {"authorization", "cookie", "set-cookie"}
        }
        metadata = {
            "response_id": response_id,
            "source": source,
            "seed_id": seed_id,
            "request_url": url,
            "request_params": dict(sorted(params.items())),
            "page_token": page_token,
            "fetched_at": utc_now(),
            "http_status": result.status,
            "response_headers": safe_headers,
            "body_sha256": digest,
            "body_relative_path": str(body_relative),
        }
        atomic_write_json(metadata_path, metadata)
        self._records[response_id] = metadata
        return payload, response_id

    def provenance_records(self) -> list[dict[str, Any]]:
        """Return all response metadata observed by this fetcher.

        Returns:
            Response dictionaries sorted by response ID.
        """

        return [self._records[key] for key in sorted(self._records)]


class CitationSourceAdapter(Protocol):
    """Interface implemented by citation-discovery providers."""

    name: str

    def discover(
        self,
        seeds: Sequence[Mapping[str, Any]],
        fetcher: ProvenanceFetcher,
        source_config: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Return normalized citing records for a seed version cluster.

        Args:
            seeds: Configured target-method seed versions.
            fetcher: Snapshot-scoped provenance fetcher.
            source_config: Adapter-specific settings.

        Returns:
            Normalized provider record dictionaries.
        """


def _openalex_authors(record: Mapping[str, Any]) -> list[str]:
    """Extract author display names from an OpenAlex work.

    Args:
        record: OpenAlex work mapping.

    Returns:
        Author names in provider order.
    """

    authors: list[str] = []
    for authorship in record.get("authorships") or []:
        if not isinstance(authorship, Mapping) or not isinstance(authorship.get("author"), Mapping):
            continue
        name = str(authorship["author"].get("display_name") or "").strip()
        if name:
            authors.append(name)
    return authors


def _compact_openalex_candidate(location: Any) -> dict[str, Any] | None:
    """Convert one OpenAlex location into a rights-review candidate.

    Args:
        location: Provider location mapping.

    Returns:
        Compact candidate mapping, or ``None`` without a direct article URL.
    """

    if not isinstance(location, Mapping):
        return None
    url = str(location.get("pdf_url") or location.get("url_for_pdf") or "")
    if not url and bool(location.get("is_oa")):
        possible = str(location.get("landing_page_url") or location.get("url") or "")
        if re.search(r"\.(?:pdf|xml|html?)(?:[?#]|$)", possible, flags=re.IGNORECASE):
            url = possible
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    public_repository = any(
        marker in host
        for marker in (
            "ncbi.nlm.nih.gov",
            "europepmc.org",
            "ebi.ac.uk",
            "biorxiv.org",
            "medrxiv.org",
            "zenodo.org",
            "figshare.com",
            "osf.io",
            "hal.science",
            "repository.",
        )
    )
    if not bool(location.get("is_oa")) and not str(location.get("license") or "").strip() and not public_repository:
        return None
    return {
        "source": "openalex",
        "url": url,
        "landing_page_url": str(location.get("landing_page_url") or ""),
        "reported_license": str(location.get("license") or ""),
        "version": str(location.get("version") or ""),
        "is_oa": bool(location.get("is_oa")),
        "document_role": "MAIN",
    }


class OpenAlexAdapter:
    """Discover incoming citations through the OpenAlex citation graph."""

    name = "openalex"

    def discover(
        self,
        seeds: Sequence[Mapping[str, Any]],
        fetcher: ProvenanceFetcher,
        source_config: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Query all seed OpenAlex IDs with one cursor-paginated OR filter.

        Args:
            seeds: Seed version dictionaries with stable ``seed_id`` values.
            fetcher: Snapshot raw-response manager.
            source_config: Optional ``mailto`` and ``per_page`` settings.

        Returns:
            Normalized citing work records.
        """

        seed_by_openalex = {
            normalize_identifier("openalex", seed.get("identifiers", {}).get("openalex")): str(seed["seed_id"])
            for seed in seeds
            if normalize_identifier("openalex", seed.get("identifiers", {}).get("openalex"))
        }
        if not seed_by_openalex:
            raise ContractError("OpenAlex discovery requires at least one seed OpenAlex ID")
        records: list[dict[str, Any]] = []
        cursor = "*"
        seen: set[str] = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            params: dict[str, Any] = {
                "filter": "cites:" + "|".join(sorted(seed_by_openalex)),
                "cursor": cursor,
                "per-page": int(source_config.get("per_page", 200)),
            }
            if source_config.get("mailto"):
                params["mailto"] = str(source_config["mailto"])
            payload, response_id = fetcher.request_json(
                source=self.name,
                seed_id="combined",
                url=OPENALEX_WORKS_URL,
                params=params,
                page_token=cursor,
            )
            if not isinstance(payload, Mapping):
                raise ContractError("OpenAlex response must be a JSON object")
            for value in payload.get("results") or []:
                if not isinstance(value, Mapping):
                    continue
                ids = value.get("ids") if isinstance(value.get("ids"), Mapping) else {}
                referenced = {
                    normalize_identifier("openalex", item)
                    for item in value.get("referenced_works") or []
                }
                cited = sorted(seed_by_openalex[item] for item in referenced if item in seed_by_openalex)
                if not cited:
                    raise ContractError(
                        "OpenAlex returned a work from the seed-cluster filter "
                        "without a matching referenced_works edge"
                    )
                candidates: list[dict[str, Any]] = []
                locations = list(value.get("locations") or [])
                locations.extend([value.get("best_oa_location"), value.get("primary_location")])
                for location in locations:
                    candidate = _compact_openalex_candidate(location)
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                primary = value.get("primary_location") if isinstance(value.get("primary_location"), Mapping) else {}
                source = primary.get("source") if isinstance(primary.get("source"), Mapping) else {}
                records.append(
                    {
                        "source": self.name,
                        "source_record_id": normalize_identifier("openalex", value.get("id") or ids.get("openalex")),
                        "raw_response_id": response_id,
                        "title": str(value.get("display_name") or value.get("title") or ""),
                        "authors": _openalex_authors(value),
                        "publication_date": str(value.get("publication_date") or ""),
                        "publication_year": value.get("publication_year"),
                        "work_type": str(value.get("type") or ""),
                        "venue": str(source.get("display_name") or ""),
                        "identifiers": {
                            "openalex": value.get("id") or ids.get("openalex"),
                            "doi": ids.get("doi") or value.get("doi"),
                            "pmid": ids.get("pmid"),
                            "pmcid": ids.get("pmcid"),
                        },
                        "cited_seed_ids": cited,
                        "retrieval_candidates": candidates,
                        "explicit_relations": [],
                    }
                )
            meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
            cursor = str(meta.get("next_cursor") or "")
            if cursor and fetcher.minimum_delay_seconds:
                time.sleep(fetcher.minimum_delay_seconds)
        return records


def _europe_pmc_authors(record: Mapping[str, Any]) -> list[str]:
    """Extract Europe PMC author names.

    Args:
        record: Europe PMC citation or CORE record.

    Returns:
        Author names in provider order.
    """

    author_list = record.get("authorList") if isinstance(record.get("authorList"), Mapping) else {}
    values: list[str] = []
    for author in author_list.get("author") or []:
        if not isinstance(author, Mapping):
            continue
        name = str(author.get("fullName") or "").strip()
        if name:
            values.append(name)
    if not values:
        values = [item.strip() for item in re.split(r"[,;]", str(record.get("authorString") or "")) if item.strip()]
    return values


def _europe_pmc_relations(record: Mapping[str, Any]) -> list[dict[str, str]]:
    """Extract only explicit published-version relations from Europe PMC.

    Args:
        record: Europe PMC CORE-compatible mapping.

    Returns:
        Conservative relation dictionaries suitable for automatic clustering.
    """

    corrections = record.get("commentCorrectionList")
    values = corrections.get("commentCorrection") if isinstance(corrections, Mapping) else []
    if isinstance(values, Mapping):
        values = [values]
    result: list[dict[str, str]] = []
    type_map = {"preprint of": "is-preprint-of", "published version": "has-version"}
    namespace_map = {"MED": "pmid", "PMC": "pmcid", "PPR": "europe_pmc"}
    for value in values or []:
        if not isinstance(value, Mapping):
            continue
        relation_type = type_map.get(normalize_title(value.get("type")))
        relation_source = str(value.get("source") or "").upper()
        namespace = namespace_map.get(relation_source)
        identifier = str(value.get("id") or "")
        if relation_source == "PPR" and identifier and not identifier.upper().startswith("PPR:"):
            identifier = f"PPR:{identifier}"
        if relation_type and namespace and identifier:
            result.append({"relation_type": relation_type, "identifier_type": namespace, "identifier": identifier})
    return result


def _normalize_europe_pmc_record(
    value: Mapping[str, Any],
    *,
    response_id: str,
    cited_seed_ids: Sequence[str],
) -> dict[str, Any]:
    """Normalize a Europe PMC citation or CORE record.

    Args:
        value: Provider record mapping.
        response_id: Exact raw-response provenance identifier.
        cited_seed_ids: Seed IDs directly cited by this record. Metadata-only
            enrichment records use an empty sequence.

    Returns:
        Normalized provider record compatible with reconciliation.
    """

    provider_source = str(value.get("source") or "").upper()
    provider_id = str(value.get("id") or value.get("pmid") or value.get("pmcid") or "")
    pmcid = normalize_identifier("pmcid", value.get("pmcid"))
    candidates = []
    if pmcid:
        candidates.append(
            {
                "source": "europe_pmc",
                "url": f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                "landing_page_url": f"https://europepmc.org/articles/{pmcid}",
                "reported_license": str(value.get("license") or value.get("licence") or ""),
                "version": "published",
                "is_oa": str(value.get("isOpenAccess") or "").upper() in {"Y", "YES", "TRUE"},
                "document_role": "MAIN",
            }
        )
    return {
        "source": "europe_pmc",
        "source_record_id": f"{provider_source}:{provider_id}" if provider_source and provider_id else stable_id("epmc_", value),
        "raw_response_id": response_id,
        "title": str(value.get("title") or ""),
        "authors": _europe_pmc_authors(value),
        "publication_date": str(value.get("firstPublicationDate") or value.get("dateOfPublication") or ""),
        "publication_year": value.get("pubYear"),
        "work_type": str(value.get("pubType") or provider_source),
        "venue": str(value.get("journalTitle") or ""),
        "identifiers": {
            "doi": value.get("doi"),
            "pmid": value.get("pmid") or (provider_id if provider_source == "MED" else ""),
            "pmcid": value.get("pmcid") or (provider_id if provider_source == "PMC" else ""),
            "europe_pmc": f"{provider_source}:{provider_id}" if provider_source and provider_id else "",
        },
        "cited_seed_ids": list(cited_seed_ids),
        "retrieval_candidates": candidates,
        "explicit_relations": _europe_pmc_relations(value),
    }


class EuropePMCAdapter:
    """Discover citations through Europe PMC seed citation endpoints."""

    name = "europe_pmc"

    def discover(
        self,
        seeds: Sequence[Mapping[str, Any]],
        fetcher: ProvenanceFetcher,
        source_config: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Retrieve citation pages for every seed with Europe PMC identity.

        Args:
            seeds: Seed version dictionaries.
            fetcher: Snapshot raw-response manager.
            source_config: Optional ``page_size`` setting.

        Returns:
            Normalized citing work records.
        """

        output: list[dict[str, Any]] = []
        unresolved_ppr_ids: set[str] = set()
        page_size = int(source_config.get("page_size", 1000))
        for seed in seeds:
            identifiers = seed.get("identifiers") if isinstance(seed.get("identifiers"), Mapping) else {}
            source_name = str(seed.get("europe_pmc_source") or "").upper()
            source_id = str(seed.get("europe_pmc_id") or identifiers.get("europe_pmc") or "")
            if source_name and source_id.upper().startswith(f"{source_name}:"):
                source_id = source_id.split(":", 1)[1]
            if not source_name or not source_id:
                continue
            page = 1
            while True:
                url = f"{EUROPE_PMC_REST_URL}/{quote(source_name)}/{quote(source_id)}/citations"
                payload, response_id = fetcher.request_json(
                    source=self.name,
                    seed_id=str(seed["seed_id"]),
                    url=url,
                    params={"page": page, "pageSize": page_size, "format": "json"},
                    page_token=str(page),
                )
                if not isinstance(payload, Mapping):
                    raise ContractError("Europe PMC response must be a JSON object")
                citation_list = payload.get("citationList") if isinstance(payload.get("citationList"), Mapping) else {}
                records = citation_list.get("citation") or []
                for value in records:
                    if not isinstance(value, Mapping):
                        continue
                    provider_source = str(value.get("source") or "").upper()
                    provider_id = str(value.get("id") or "").upper()
                    if provider_source == "PPR" and re.fullmatch(r"PPR\d+", provider_id) and not normalize_identifier("doi", value.get("doi")):
                        unresolved_ppr_ids.add(provider_id)
                    output.append(
                        _normalize_europe_pmc_record(
                            value,
                            response_id=response_id,
                            cited_seed_ids=[str(seed["seed_id"])],
                        )
                    )
                hit_count = int(payload.get("hitCount") or len(records))
                if not records or page * page_size >= hit_count:
                    break
                page += 1
                if fetcher.minimum_delay_seconds:
                    time.sleep(fetcher.minimum_delay_seconds)
        enrichment_batch_size = max(1, min(int(source_config.get("enrichment_batch_size", 50)), 50))
        for offset in range(0, len(unresolved_ppr_ids), enrichment_batch_size):
            batch = sorted(unresolved_ppr_ids)[offset : offset + enrichment_batch_size]
            query = "(" + " OR ".join(f"EXT_ID:{value}" for value in batch) + ") AND SRC:PPR"
            payload, response_id = fetcher.request_json(
                source="europe_pmc_enrichment",
                seed_id="combined",
                url=f"{EUROPE_PMC_REST_URL}/search",
                params={"query": query, "resultType": "core", "pageSize": 1000, "format": "json"},
                page_token=f"ppr_batch_{offset // enrichment_batch_size + 1}",
            )
            result_list = payload.get("resultList") if isinstance(payload, Mapping) else None
            if not isinstance(result_list, Mapping):
                raise ContractError("Europe PMC PPR enrichment response lacks resultList")
            for value in result_list.get("result") or []:
                if isinstance(value, Mapping) and str(value.get("id") or "").upper() in batch:
                    output.append(_normalize_europe_pmc_record(value, response_id=response_id, cited_seed_ids=[]))

        present_pmids = {
            normalize_identifier("pmid", (record.get("identifiers") or {}).get("pmid"))
            for record in output
            if normalize_identifier("pmid", (record.get("identifiers") or {}).get("pmid"))
        }
        target_pmids = sorted(
            {
                normalize_identifier("pmid", relation.get("identifier"))
                for record in output
                for relation in record.get("explicit_relations") or []
                if relation.get("identifier_type") == "pmid"
                and normalize_identifier("pmid", relation.get("identifier"))
                not in present_pmids
            }
        )
        for offset in range(0, len(target_pmids), enrichment_batch_size):
            batch = target_pmids[offset : offset + enrichment_batch_size]
            query = "(" + " OR ".join(f"EXT_ID:{value}" for value in batch) + ") AND SRC:MED"
            payload, response_id = fetcher.request_json(
                source="europe_pmc_version_enrichment",
                seed_id="combined",
                url=f"{EUROPE_PMC_REST_URL}/search",
                params={"query": query, "resultType": "core", "pageSize": 1000, "format": "json"},
                page_token=f"published_batch_{offset // enrichment_batch_size + 1}",
            )
            result_list = payload.get("resultList") if isinstance(payload, Mapping) else None
            if not isinstance(result_list, Mapping):
                raise ContractError("Europe PMC published-version enrichment response lacks resultList")
            for value in result_list.get("result") or []:
                if not isinstance(value, Mapping):
                    continue
                pmid = normalize_identifier("pmid", value.get("pmid") or value.get("id"))
                if pmid in batch:
                    output.append(_normalize_europe_pmc_record(value, response_id=response_id, cited_seed_ids=[]))
        return output


def _identifiers_from_opencitations(value: Any) -> dict[str, str]:
    """Parse strong identifiers from an OpenCitations Meta string.

    Args:
        value: Space-separated identifier tokens.

    Returns:
        Normalized identifier mapping; unsupported OMIDs are omitted.
    """

    result: dict[str, str] = {}
    aliases = {"doi": "doi", "pmid": "pmid", "pmcid": "pmcid", "openalex": "openalex"}
    for token in str(value or "").split():
        if ":" not in token:
            continue
        prefix, raw = token.split(":", 1)
        kind = aliases.get(prefix.lower())
        if kind and normalize_identifier(kind, raw):
            result[kind] = normalize_identifier(kind, raw)
    return result


class OpenCitationsAdapter:
    """Discover DOI citation edges through OpenCitations Index v2."""

    name = "opencitations"

    def discover(
        self,
        seeds: Sequence[Mapping[str, Any]],
        fetcher: ProvenanceFetcher,
        source_config: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Query each DOI-bearing seed and retain supported citing identifiers.

        Args:
            seeds: Seed version dictionaries.
            fetcher: Snapshot raw-response manager.
            source_config: Reserved adapter settings.

        Returns:
            Identifier-first normalized records for later hydration.
        """

        del source_config
        output: list[dict[str, Any]] = []
        for seed in seeds:
            doi = normalize_identifier("doi", (seed.get("identifiers") or {}).get("doi"))
            if not doi:
                continue
            payload, response_id = fetcher.request_json(
                source=self.name,
                seed_id=str(seed["seed_id"]),
                url=f"{OPENCITATIONS_INDEX_URL}/doi:{quote(doi, safe='/')}",
                params={},
                page_token="all",
            )
            if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
                raise ContractError("OpenCitations response must be a JSON list")
            for value in payload:
                if not isinstance(value, Mapping):
                    continue
                identifiers = _identifiers_from_opencitations(value.get("citing"))
                if not identifiers:
                    continue
                primary_kind = next(
                    kind for kind in ("doi", "pmid", "pmcid", "openalex") if identifiers.get(kind)
                )
                primary_identifiers = {primary_kind: identifiers[primary_kind]}
                provider_hints = [
                    {"identifier_type": kind, "identifier": identifier}
                    for kind, identifier in identifiers.items()
                    if kind != primary_kind
                ]
                creation = str(value.get("creation") or "")
                year_match = re.match(r"(\d{4})", creation)
                output.append(
                    {
                        "source": self.name,
                        "source_record_id": str(value.get("oci") or stable_id("oci_", value)),
                        "raw_response_id": response_id,
                        "title": "",
                        "authors": [],
                        "publication_date": creation,
                        "publication_year": int(year_match.group(1)) if year_match else None,
                        "work_type": "",
                        "venue": "",
                        "identifiers": primary_identifiers,
                        "cited_seed_ids": [str(seed["seed_id"])],
                        "retrieval_candidates": [],
                        "explicit_relations": [],
                        "provider_identifier_hints": provider_hints,
                    }
                )
        return output


ADAPTERS: dict[str, CitationSourceAdapter] = {
    "openalex": OpenAlexAdapter(),
    "europe_pmc": EuropePMCAdapter(),
    "opencitations": OpenCitationsAdapter(),
}


def enabled_adapters(source_config: Mapping[str, Any]) -> list[CitationSourceAdapter]:
    """Instantiate citation adapters enabled by configuration.

    Args:
        source_config: Mapping keyed by stable provider name.

    Returns:
        Adapters in scGPT-compatible source order.
    """

    result: list[CitationSourceAdapter] = []
    for name in ("openalex", "europe_pmc", "opencitations"):
        settings = source_config.get(name)
        enabled = name == "openalex" if settings is None else bool((settings or {}).get("enabled", True))
        if enabled:
            result.append(ADAPTERS[name])
    return result


def _crossref_date(record: Mapping[str, Any]) -> tuple[str, int | None]:
    """Extract the first available Crossref publication date.

    Args:
        record: Crossref work ``message`` mapping.

    Returns:
        ISO-like date text and optional year.
    """

    for field in ("published-print", "published-online", "published", "issued"):
        container = record.get(field)
        parts = container.get("date-parts") if isinstance(container, Mapping) else []
        if not parts or not isinstance(parts[0], list) or not parts[0]:
            continue
        values = [int(value) for value in parts[0][:3]]
        text = "-".join(f"{value:04d}" if index == 0 else f"{value:02d}" for index, value in enumerate(values))
        return text, values[0]
    return "", None


def enrich_titleless_records(
    records: Sequence[Mapping[str, Any]],
    fetcher: ProvenanceFetcher,
    source_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Hydrate identifier-only citation records through exact metadata lookups.

    Args:
        records: Normalized records returned by citation adapters.
        fetcher: Snapshot raw-response manager.
        source_config: ``crossref`` and ``pubmed`` adapter settings.

    Returns:
        Original records followed by metadata records that share a strong
        identifier and therefore reconcile deterministically. Crossref is used
        for DOI records; PubMed ESummary is used for PMID-only records.
    """

    output = [dict(record) for record in records]
    titled_identifiers = {
        (kind, normalize_identifier(kind, value))
        for record in output
        if str(record.get("title") or "").strip()
        for kind, value in (record.get("identifiers") or {}).items()
        if kind in {"doi", "pmid"} and normalize_identifier(kind, value)
    }
    titleless_dois = sorted(
        {
            normalize_identifier("doi", (record.get("identifiers") or {}).get("doi"))
            for record in output
            if not str(record.get("title") or "").strip()
            and normalize_identifier("doi", (record.get("identifiers") or {}).get("doi"))
            and ("doi", normalize_identifier("doi", (record.get("identifiers") or {}).get("doi"))) not in titled_identifiers
        }
    )
    crossref_settings = source_config.get("crossref") if isinstance(source_config.get("crossref"), Mapping) else {}
    if bool(crossref_settings.get("enabled", False)):
        for index, doi in enumerate(titleless_dois, start=1):
            payload, response_id = fetcher.request_json(
                source="crossref",
                seed_id="titleless",
                url=f"{CROSSREF_WORKS_URL}/{quote(doi, safe='')}",
                params={},
                page_token=f"doi_{index}",
            )
            message = payload.get("message") if isinstance(payload, Mapping) else None
            if not isinstance(message, Mapping):
                raise ContractError(f"Crossref exact response lacks message for DOI {doi}")
            returned_doi = normalize_identifier("doi", message.get("DOI") or message.get("doi"))
            if returned_doi != doi:
                raise ContractError(f"Crossref exact response DOI mismatch: {doi} != {returned_doi}")
            title_value = message.get("title") or []
            title = str(title_value[0]) if isinstance(title_value, list) and title_value else str(title_value or "")
            publication_date, publication_year = _crossref_date(message)
            authors = [
                " ".join(filter(None, (str(author.get("given") or ""), str(author.get("family") or "")))).strip()
                for author in message.get("author") or []
                if isinstance(author, Mapping)
            ]
            container = message.get("container-title") or []
            venue = str(container[0]) if isinstance(container, list) and container else str(container or "")
            output.append(
                {
                    "source": "crossref",
                    "source_record_id": doi,
                    "raw_response_id": response_id,
                    "title": title,
                    "authors": [author for author in authors if author],
                    "publication_date": publication_date,
                    "publication_year": publication_year,
                    "work_type": str(message.get("type") or ""),
                    "venue": venue,
                    "identifiers": {"doi": doi},
                    "cited_seed_ids": [],
                    "retrieval_candidates": [],
                    "explicit_relations": [],
                }
            )

    titleless_pmids = sorted(
        {
            normalize_identifier("pmid", (record.get("identifiers") or {}).get("pmid"))
            for record in output
            if not str(record.get("title") or "").strip()
            and not normalize_identifier("doi", (record.get("identifiers") or {}).get("doi"))
            and normalize_identifier("pmid", (record.get("identifiers") or {}).get("pmid"))
            and ("pmid", normalize_identifier("pmid", (record.get("identifiers") or {}).get("pmid"))) not in titled_identifiers
        }
    )
    pubmed_settings = source_config.get("pubmed") if isinstance(source_config.get("pubmed"), Mapping) else {}
    if bool(pubmed_settings.get("enabled", False)):
        batch_size = max(1, min(int(pubmed_settings.get("batch_size", 200)), 200))
        for offset in range(0, len(titleless_pmids), batch_size):
            batch = titleless_pmids[offset : offset + batch_size]
            payload, response_id = fetcher.request_json(
                source="pubmed",
                seed_id="titleless",
                url=PUBMED_ESUMMARY_URL,
                params={"db": "pubmed", "id": ",".join(batch), "retmode": "json", "version": "2.0"},
                page_token=f"batch_{offset // batch_size + 1}",
            )
            result = payload.get("result") if isinstance(payload, Mapping) else None
            if not isinstance(result, Mapping):
                raise ContractError("PubMed ESummary response lacks result mapping")
            for pmid in batch:
                value = result.get(pmid)
                if not isinstance(value, Mapping):
                    continue
                article_ids = value.get("articleids") or []
                identifiers: dict[str, str] = {"pmid": pmid}
                for article_id in article_ids:
                    if not isinstance(article_id, Mapping):
                        continue
                    kind = str(article_id.get("idtype") or "").lower()
                    if kind in {"doi", "pmc"}:
                        identifiers["pmcid" if kind == "pmc" else "doi"] = str(article_id.get("value") or "")
                author_values = value.get("authors") or []
                authors = [str(author.get("name") or "") for author in author_values if isinstance(author, Mapping)]
                publication_date = str(value.get("pubdate") or "")
                year_match = re.search(r"\b(\d{4})\b", publication_date)
                output.append(
                    {
                        "source": "pubmed",
                        "source_record_id": pmid,
                        "raw_response_id": response_id,
                        "title": str(value.get("title") or ""),
                        "authors": [author for author in authors if author],
                        "publication_date": publication_date,
                        "publication_year": int(year_match.group(1)) if year_match else None,
                        "work_type": str(value.get("pubtype") or ""),
                        "venue": str(value.get("fulljournalname") or value.get("source") or ""),
                        "identifiers": identifiers,
                        "cited_seed_ids": [],
                        "retrieval_candidates": [],
                        "explicit_relations": [],
                    }
                )
    return output
