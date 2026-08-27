"""Test one-vs-rest human-reference scoring for non-exclusive labels."""

# Standard-library imports write temporary CSV fixtures and provide unittest assertions.
import csv
from pathlib import Path
import tempfile
import unittest

# Package imports parse and score the method-agnostic human-validation table.
from citation_use_review.scoring import load_scoring_rows, score_categories


HEADER = [
    "record_id", "study_id", "category", "machine_score", "machine_positive", "human_consensus",
    "human_evaluable", "sample_weight", "true_positive", "false_positive", "false_negative",
    "true_negative", "notes",
]


class ScoringTests(unittest.TestCase):
    """Verify multi-label studies and sampling weights are scored independently."""

    def test_category_metrics_and_precision_recall_curve(self) -> None:
        """Each category should use its own weighted one-vs-rest confusion matrix."""

        rows = [
            ["R1", "S1", "APPLY_BIOLOGICAL", "0.9", "1", "1", "1", "2", "", "", "", "", ""],
            ["R2", "S2", "APPLY_BIOLOGICAL", "0.2", "0", "1", "1", "1", "", "", "", "", ""],
            ["R5", "S3", "APPLY_BIOLOGICAL", "0.1", "0", "0", "1", "1", "", "", "", "", ""],
            ["R3", "S1", "EXTEND_DEVELOP", "0.8", "1", "1", "1", "2", "", "", "", "", "same study, second label"],
            ["R4", "S2", "EXTEND_DEVELOP", "0.1", "0", "0", "1", "1", "", "", "", "", ""],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scores.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(HEADER)
                writer.writerows(rows)
            output = score_categories(load_scoring_rows(path))
        apply = output["categories"]["APPLY_BIOLOGICAL"]
        extend = output["categories"]["EXTEND_DEVELOP"]
        self.assertEqual(apply["unweighted"]["true_positive"], 1)
        self.assertEqual(apply["unweighted"]["false_negative"], 1)
        self.assertEqual(apply["weighted"]["true_positive"], 2.0)
        self.assertEqual(extend["unweighted"]["true_positive"], 1)
        self.assertEqual(extend["unweighted"]["true_negative"], 1)
        self.assertIsNotNone(apply["precision_recall_curve"])
        self.assertIsNone(apply["precision_recall_curve"]["points"][0]["threshold"])
        self.assertEqual(apply["weighted_roc_auc"], 1.0)
        self.assertEqual(extend["weighted_roc_auc"], 1.0)


if __name__ == "__main__":
    unittest.main()
