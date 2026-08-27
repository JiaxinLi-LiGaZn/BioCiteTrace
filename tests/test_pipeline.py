"""Test deterministic pipeline states and all-batch preflight behavior."""

# Standard-library imports copy fixtures, create temporary manifests, and mock preflight calls.
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

# Package imports exercise pipeline state derivation and duplicate-study rejection.
from citation_use_review.errors import ContractError
from citation_use_review.pipeline import _derive_review_state, run_batch, run_one_study
from citation_use_review.util import load_json


ROOT = Path(__file__).resolve().parents[1]


def _terminal(result: dict[str, object] | None) -> dict[str, object]:
    """Create a minimal logical terminal for deterministic state tests.

    Args:
        result: Successful classification or ``None`` for terminal failure.

    Returns:
        Terminal-shaped mapping consumed by the local state reducer.
    """

    return {"terminal_status": "SUCCESS" if result is not None else "FAILED", "result": result}


class PipelineTests(unittest.TestCase):
    """Verify baseline failure branches and pre-call cohort validation."""

    def setUp(self) -> None:
        """Load one valid synthetic machine classification."""

        self.result = load_json(ROOT / "examples/example_classification.json")

    def test_both_baseline_failures_do_not_open_agent_c(self) -> None:
        """Two failed baseline roles should terminate unresolved without a third call."""

        state = _derive_review_state(
            {"classifier": _terminal(None), "reviewer": _terminal(None)},
            None,
        )
        self.assertEqual(state["adjudication_trigger"], "NOT_TRIGGERED")
        self.assertEqual(state["terminal_status"], "UNRESOLVED_BASELINE_FAILED")

    def test_single_failure_requires_consistent_third_review(self) -> None:
        """A surviving baseline plus a matching Agent C should yield machine consensus."""

        baseline = {"classifier": _terminal(self.result), "reviewer": _terminal(None)}
        pending = _derive_review_state(baseline, None)
        resolved = _derive_review_state(baseline, _terminal(self.result))
        self.assertEqual(pending["adjudication_trigger"], "SECOND_REVIEW_FAILED")
        self.assertEqual(pending["terminal_status"], "")
        self.assertEqual(resolved["terminal_status"], "MACHINE_CONSENSUS")

    def test_duplicate_study_ids_fail_before_codex_preflight(self) -> None:
        """The whole batch should reject duplicate counting units before any agent work."""

        capsule_text = (ROOT / "examples/example_study_capsule.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first = temporary_root / "first.json"
            second = temporary_root / "second.json"
            first.write_text(capsule_text, encoding="utf-8")
            second.write_text(capsule_text, encoding="utf-8")
            manifest = temporary_root / "manifest.jsonl"
            manifest.write_text(
                json.dumps({"capsule_path": str(first)}) + "\n" + json.dumps({"capsule_path": str(second)}) + "\n",
                encoding="utf-8",
            )
            with mock.patch("citation_use_review.pipeline.preflight_codex") as preflight:
                with self.assertRaises(ContractError):
                    run_batch(
                        project_root=ROOT,
                        config_path=ROOT / "config/example_config.json",
                        manifest_path=manifest,
                        output_root=temporary_root / "output",
                    )
            preflight.assert_not_called()

    def test_one_study_runs_two_blind_roles_without_unneeded_agent_c(self) -> None:
        """Agreement between A and B should publish after exactly two logical role calls."""

        def role_result(**kwargs: object) -> dict[str, object]:
            """Return the same successful classification for either baseline role.

            Args:
                **kwargs: Keyword arguments supplied to the mocked role runner.

            Returns:
                Minimal successful terminal containing the synthetic result.
            """

            self.assertIn(kwargs["role"], {"classifier", "reviewer"})
            return _terminal(self.result)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("citation_use_review.pipeline.preflight_codex"), mock.patch(
                "citation_use_review.pipeline.run_codex_role",
                side_effect=role_result,
            ) as role_runner:
                result = run_one_study(
                    project_root=ROOT,
                    config_path=ROOT / "config/example_config.json",
                    capsule_path=ROOT / "examples/example_study_capsule.json",
                    output_root=Path(temporary),
                )
        self.assertEqual(role_runner.call_count, 2)
        self.assertEqual(result["terminal_status"], "TWO_AGENT_NO_MATERIAL_CONFLICT")
        self.assertIsNone(result["adjudicator"])


if __name__ == "__main__":
    unittest.main()
