"""Command-line interface for the public citation-use review starter."""

# Standard-library imports parse CLI arguments, print JSON, and resolve paths.
import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .capsule import build_capsule
from .comparison import compare_classifications
from .contracts import validate_capsule, validate_classification
from .errors import CitationReviewError, ContractError
from .pipeline import run_batch, run_one_study
from .prompting import assemble_prompt, load_contract_files
from .rights import build_agent_handoff, prepare_rights_review, retrieve_approved
from .scoring import load_scoring_rows, score_categories
from .upstream import derive_reviewed_snapshot, discover_snapshot, snapshot_summary
from .util import atomic_write_json, atomic_write_text, load_json


def _path(value: str) -> Path:
    """Convert a CLI string to an expanded path.

    Args:
        value: User-supplied path string.

    Returns:
        Expanded ``Path`` without requiring it to exist yet.
    """

    return Path(value).expanduser()


def _write_or_print(value: object, output: Path | None) -> None:
    """Publish JSON to a file or standard output.

    Args:
        value: JSON-compatible result.
        output: Optional destination path.

    Returns:
        ``None`` after publication.
    """

    if output is None:
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        atomic_write_json(output, value)


def build_parser() -> argparse.ArgumentParser:
    """Construct the complete command-line parser.

    Returns:
        Configured top-level parser with all workflow subcommands.
    """

    parser = argparse.ArgumentParser(prog="citation-use-review")
    parser.add_argument("--project-root", type=_path, default=Path("."), help="Repository root; defaults to the current directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build-capsule", help="Build one capsule from rights-approved UTF-8 text.")
    build.add_argument("--study", type=_path, required=True)
    build.add_argument("--method", type=_path, required=True)
    build.add_argument("--documents", type=_path, required=True)
    build.add_argument("--codebook", type=_path, default=Path("codebook/citation_use_codebook.json"))
    build.add_argument("--output", type=_path, required=True)
    build.add_argument("--incomplete", action="store_true")
    build.add_argument("--coverage-risk", action="append", default=[])

    validate_capsule_parser = subparsers.add_parser("validate-capsule", help="Validate one capsule and its rights/evidence invariants.")
    validate_capsule_parser.add_argument("--capsule", type=_path, required=True)
    validate_capsule_parser.add_argument("--codebook", type=_path, default=Path("codebook/citation_use_codebook.json"))

    assemble = subparsers.add_parser("assemble-prompt", help="Render one prompt without calling Codex.")
    assemble.add_argument("--config", type=_path, required=True)
    assemble.add_argument("--capsule", type=_path, required=True)
    assemble.add_argument("--role", choices=["classifier", "reviewer", "adjudicator"], required=True)
    assemble.add_argument("--adjudication-context", type=_path)
    assemble.add_argument("--output", type=_path, required=True)

    validate_output = subparsers.add_parser("validate-output", help="Validate one agent JSON against a capsule.")
    validate_output.add_argument("--config", type=_path, required=True)
    validate_output.add_argument("--capsule", type=_path, required=True)
    validate_output.add_argument("--result", type=_path, required=True)
    validate_output.add_argument("--output", type=_path)

    compare = subparsers.add_parser("compare-reviews", help="Compare two validated blind-review results.")
    compare.add_argument("--config", type=_path, required=True)
    compare.add_argument("--capsule", type=_path, required=True)
    compare.add_argument("--first", type=_path, required=True)
    compare.add_argument("--second", type=_path, required=True)
    compare.add_argument("--output", type=_path)

    run_one = subparsers.add_parser("run-one", help="Run or resume A/B and conditional C for one study.")
    run_one.add_argument("--config", type=_path, required=True)
    run_one.add_argument("--capsule", type=_path, required=True)
    run_one.add_argument("--output-root", type=_path, default=Path("artifacts/reviews"))

    run_many = subparsers.add_parser("run-batch", help="Run ordered one-study pipelines from a JSONL manifest.")
    run_many.add_argument("--config", type=_path, required=True)
    run_many.add_argument("--manifest", type=_path, required=True)
    run_many.add_argument("--output-root", type=_path, default=Path("artifacts/reviews"))
    run_many.add_argument("--workers", type=int)

    scoring = subparsers.add_parser("score-human", help="Score categories against adjudicated human consensus.")
    scoring.add_argument("--input", type=_path, required=True)
    scoring.add_argument("--output", type=_path)

    discover = subparsers.add_parser("discover-citations", help="Discover citations and freeze an immutable source snapshot.")
    discover.add_argument("--config", type=_path, required=True)
    discover.add_argument("--snapshot-id", required=True)

    cluster_review = subparsers.add_parser("apply-cluster-review", help="Create a reviewed snapshot from all duplicate/version decisions.")
    cluster_review.add_argument("--parent-snapshot", required=True)
    cluster_review.add_argument("--review", type=_path, required=True)
    cluster_review.add_argument("--derived-snapshot", required=True)
    cluster_review.add_argument("--allow-incomplete-sources", action="store_true")

    inspect_snapshot = subparsers.add_parser("inspect-snapshot", help="Verify and summarize one immutable citation snapshot.")
    inspect_snapshot.add_argument("--snapshot-id", required=True)

    rights_review = subparsers.add_parser("prepare-rights-review", help="Create a blank human rights-review queue.")
    rights_review.add_argument("--snapshot-id", required=True)

    retrieve = subparsers.add_parser("retrieve-approved", help="Retrieve only candidates explicitly approved by a human.")
    retrieve.add_argument("--config", type=_path, required=True)
    retrieve.add_argument("--snapshot-id", required=True)
    retrieve.add_argument("--approval", type=_path, required=True)

    handoff = subparsers.add_parser("build-agent-handoff", help="Build ordered one-study capsules from approved retrieved text.")
    handoff.add_argument("--config", type=_path, required=True)
    handoff.add_argument("--snapshot-id", required=True)
    handoff.add_argument("--codebook", type=_path, default=Path("codebook/citation_use_codebook.json"))
    handoff.add_argument("--coverage-review", type=_path, required=True)
    handoff.add_argument("--duplicate-review", type=_path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI subcommand.

    Args:
        argv: Optional argument sequence excluding the program name.

    Returns:
        Process exit code: zero for success, two for a typed workflow failure.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    try:
        if args.command == "build-capsule":
            capsule = build_capsule(
                project_root=root,
                study=load_json(args.study),
                target_method=load_json(args.method),
                document_specs=load_json(args.documents),
                codebook=load_json(args.codebook),
                evidence_complete=not args.incomplete,
                coverage_risk_codes=args.coverage_risk,
            )
            atomic_write_json(args.output, capsule)
        elif args.command == "validate-capsule":
            capsule = validate_capsule(load_json(args.capsule), load_json(args.codebook))
            print(json.dumps({"status": "VALID", "study_id": capsule["study"]["study_id"]}, sort_keys=True))
        elif args.command == "assemble-prompt":
            config = load_json(args.config)
            context = load_json(args.adjudication_context) if args.adjudication_context else None
            prompt = assemble_prompt(project_root=root, config=config, capsule=load_json(args.capsule), role=args.role, adjudication_context=context)
            atomic_write_text(args.output, prompt)
        elif args.command == "validate-output":
            config = load_json(args.config)
            codebook, _schema = load_contract_files(root, config)
            capsule = validate_capsule(load_json(args.capsule), codebook)
            result = validate_classification(load_json(args.result), capsule, codebook)
            _write_or_print(result, args.output)
        elif args.command == "compare-reviews":
            config = load_json(args.config)
            codebook, _schema = load_contract_files(root, config)
            capsule = validate_capsule(load_json(args.capsule), codebook)
            first = validate_classification(load_json(args.first), capsule, codebook)
            second = validate_classification(load_json(args.second), capsule, codebook)
            _write_or_print(compare_classifications(first, second), args.output)
        elif args.command == "run-one":
            result = run_one_study(project_root=root, config_path=args.config, capsule_path=args.capsule, output_root=args.output_root)
            print(json.dumps({"study_id": result["study_id"], "terminal_status": result["terminal_status"]}, sort_keys=True))
        elif args.command == "run-batch":
            results = run_batch(project_root=root, config_path=args.config, manifest_path=args.manifest, output_root=args.output_root, max_workers=args.workers)
            print(json.dumps({"study_count": len(results), "output": str(args.output_root / "batch_results.jsonl")}, sort_keys=True))
        elif args.command == "score-human":
            _write_or_print(score_categories(load_scoring_rows(args.input)), args.output)
        elif args.command == "discover-citations":
            config = load_json(args.config)
            if not isinstance(config, dict):
                raise ContractError("configuration must be a JSON object")
            _write_or_print(discover_snapshot(project_root=root, config=config, snapshot_id=args.snapshot_id), None)
        elif args.command == "apply-cluster-review":
            _write_or_print(
                derive_reviewed_snapshot(
                    project_root=root,
                    parent_snapshot_id=args.parent_snapshot,
                    review_path=args.review,
                    derived_snapshot_id=args.derived_snapshot,
                    allow_incomplete_sources=args.allow_incomplete_sources,
                ),
                None,
            )
        elif args.command == "inspect-snapshot":
            _write_or_print(snapshot_summary(root, args.snapshot_id), None)
        elif args.command == "prepare-rights-review":
            _write_or_print(prepare_rights_review(project_root=root, snapshot_id=args.snapshot_id), None)
        elif args.command == "retrieve-approved":
            config = load_json(args.config)
            if not isinstance(config, dict):
                raise ContractError("configuration must be a JSON object")
            _write_or_print(
                retrieve_approved(
                    project_root=root,
                    snapshot_id=args.snapshot_id,
                    approval_path=args.approval,
                    config=config,
                ),
                None,
            )
        elif args.command == "build-agent-handoff":
            config = load_json(args.config)
            if not isinstance(config, dict):
                raise ContractError("configuration must be a JSON object")
            _write_or_print(
                build_agent_handoff(
                    project_root=root,
                    snapshot_id=args.snapshot_id,
                    config=config,
                    codebook_path=args.codebook,
                    coverage_review_path=args.coverage_review,
                    duplicate_review_path=args.duplicate_review,
                ),
                None,
            )
        else:
            raise ContractError(f"unimplemented command: {args.command}")
    except (CitationReviewError, OSError, ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
