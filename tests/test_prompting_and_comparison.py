"""Test prompt isolation and deterministic review comparison rules."""

# Standard-library imports copy fixtures, locate paths, and provide unittest assertions.
import copy
from pathlib import Path
import unittest

# Package imports render prompts and apply comparison/adjudication contracts.
from citation_use_review.comparison import adjudication_acceptance, compare_classifications
from citation_use_review.errors import ContractError
from citation_use_review.prompting import assemble_prompt
from citation_use_review.util import load_json


ROOT = Path(__file__).resolve().parents[1]


class PromptingAndComparisonTests(unittest.TestCase):
    """Verify one-study prompt boundaries and bounded conflict handling."""

    def setUp(self) -> None:
        """Load one synthetic capsule, classification, and workflow config."""

        self.config = load_json(ROOT / "config/example_config.json")
        self.capsule = load_json(ROOT / "examples/example_study_capsule.json")
        self.result = load_json(ROOT / "examples/example_classification.json")

    def test_classifier_prompt_is_complete_and_one_study(self) -> None:
        """Rendered prompts should replace every placeholder and preserve trust boundaries."""

        prompt = assemble_prompt(project_root=ROOT, config=self.config, capsule=self.capsule, role="classifier")
        self.assertNotIn("{{", prompt)
        self.assertIn("CellMapFM", prompt)
        self.assertIn("BEGIN_UNTRUSTED_ONE_STUDY_CAPSULE_JSON", prompt)
        self.assertIn('"study_id": "synthetic-study-001"', prompt)

    def test_exact_agreement_does_not_trigger_third_review(self) -> None:
        """Identical validated decisions should be a nonmaterial agreement."""

        comparison = compare_classifications(self.result, self.result)
        self.assertEqual(comparison["comparison_tier"], "EXACT_AGREEMENT")
        self.assertFalse(comparison["material_conflict"])

    def test_adjudicator_rejects_answer_bearing_context(self) -> None:
        """Agent C may receive only the exact generic context, never an earlier answer."""

        with self.assertRaises(ContractError):
            assemble_prompt(
                project_root=ROOT,
                config=self.config,
                capsule=self.capsule,
                role="adjudicator",
                adjudication_context={"mode": "BLIND_INDEPENDENT_REVIEW", "primary_label": "APPLY_BIOLOGICAL"},
            )

    def test_multi_label_difference_is_material(self) -> None:
        """Dropping a genuine secondary use label should be a decision conflict."""

        second = copy.deepcopy(self.result)
        second["use_labels"] = ["APPLY_BIOLOGICAL"]
        second["use_evidence"][0]["supports_labels"] = ["APPLY_BIOLOGICAL"]
        comparison = compare_classifications(self.result, second)
        self.assertEqual(comparison["comparison_tier"], "DECISION_CONFLICT")
        self.assertTrue(comparison["material_conflict"])

    def test_third_review_must_match_exactly_one_conflicting_baseline(self) -> None:
        """Agent C resolves a conflict only by supporting one side, never by recursive voting."""

        second = copy.deepcopy(self.result)
        second["biological_insight"] = "NO"
        second["insight_role"] = "NONE"
        second["insight_evidence"] = []
        second["attribution_bridge"] = ""
        outcome = adjudication_acceptance(
            trigger="DECISION_CONFLICT",
            primary=self.result,
            secondary=second,
            adjudicator=self.result,
        )
        self.assertEqual(outcome, "MACHINE_ADJUDICATED")


if __name__ == "__main__":
    unittest.main()
