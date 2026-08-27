"""Test capsule construction and evidence-grounded output validation."""

# Standard-library imports copy fixtures, locate the repository, and provide unittest assertions.
import copy
from pathlib import Path
import unittest

# Package imports exercise the public builder, validators, and typed contract error.
from citation_use_review.capsule import _alias_markers, build_capsule
from citation_use_review.contracts import validate_capsule, validate_classification
from citation_use_review.errors import ContractError
from citation_use_review.util import load_json


ROOT = Path(__file__).resolve().parents[1]


class CapsuleContractTests(unittest.TestCase):
    """Verify deterministic construction and strict scientific invariants."""

    def setUp(self) -> None:
        """Load the frozen synthetic fixtures used by each test."""

        self.codebook = load_json(ROOT / "codebook/citation_use_codebook.json")
        self.capsule = load_json(ROOT / "examples/example_study_capsule.json")
        self.classification = load_json(ROOT / "examples/example_classification.json")

    def test_builder_reproduces_committed_capsule(self) -> None:
        """The transparent plain-text builder should reproduce the example exactly."""

        built = build_capsule(
            project_root=ROOT,
            study=load_json(ROOT / "examples/example_study.json"),
            target_method=load_json(ROOT / "examples/example_method.json"),
            document_specs=load_json(ROOT / "examples/example_documents.json"),
            codebook=self.codebook,
        )
        self.assertEqual(built, self.capsule)
        self.assertEqual(len(built["physical_target_occurrences"]), 3)

    def test_multi_label_classification_is_valid(self) -> None:
        """One study may validly apply and extend a method at the same time."""

        validated = validate_classification(self.classification, self.capsule, self.codebook)
        self.assertEqual(validated["use_labels"], ["APPLY_BIOLOGICAL", "EXTEND_DEVELOP"])

    def test_tampered_quote_is_rejected(self) -> None:
        """A quotation absent from its declared paragraph must fail closed."""

        candidate = copy.deepcopy(self.classification)
        candidate["use_evidence"][0]["quote"] = "This sentence was never in the article."
        with self.assertRaises(ContractError):
            validate_classification(candidate, self.capsule, self.codebook)

    def test_every_label_requires_direct_evidence(self) -> None:
        """Removing support for one assigned label must invalidate the record."""

        candidate = copy.deepcopy(self.classification)
        candidate["use_evidence"][0]["supports_labels"] = ["APPLY_BIOLOGICAL"]
        with self.assertRaises(ContractError):
            validate_classification(candidate, self.capsule, self.codebook)

    def test_occurrence_registry_must_be_complete(self) -> None:
        """A classified result cannot silently omit a physical citation occurrence."""

        candidate = copy.deepcopy(self.classification)
        candidate["citation_instances"].pop()
        with self.assertRaises(ContractError):
            validate_classification(candidate, self.capsule, self.codebook)

    def test_capsule_rights_gate_is_enforced(self) -> None:
        """A document without explicit cloud-processing permission is ineligible."""

        candidate = copy.deepcopy(self.capsule)
        candidate["documents"][0]["cloud_processing_allowed"] = False
        with self.assertRaises(ContractError):
            validate_capsule(candidate, self.codebook)

    def test_overlapping_aliases_produce_one_physical_marker(self) -> None:
        """A shorter alias inside a longer alias must not double-count one mention."""

        markers = _alias_markers("CellMapFM [12] was used.", ["CellMapFM", "CellMap"])
        self.assertEqual(markers, [(0, 14, "CellMapFM [12]")])


if __name__ == "__main__":
    unittest.main()
