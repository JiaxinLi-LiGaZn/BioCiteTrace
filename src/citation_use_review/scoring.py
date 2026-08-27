"""Category-wise scoring against an adjudicated human consensus."""

# Standard-library imports read tabular data, reject nonfinite numbers, group categories, and describe typed rows.
import csv
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ContractError


def _binary(value: str, label: str) -> bool:
    """Parse a strict binary CSV field.

    Args:
        value: Text value such as ``1``, ``0``, ``YES``, or ``NO``.
        label: Field name used in errors.

    Returns:
        Parsed Boolean.
    """

    normalized = value.strip().upper()
    if normalized in {"1", "YES", "TRUE"}:
        return True
    if normalized in {"0", "NO", "FALSE"}:
        return False
    raise ContractError(f"{label} must be binary, observed {value!r}")


def _divide(numerator: float, denominator: float) -> float | None:
    """Return a ratio or ``None`` for a zero denominator.

    Args:
        numerator: Ratio numerator.
        denominator: Ratio denominator.

    Returns:
        Floating-point ratio, or ``None`` when undefined.
    """

    return numerator / denominator if denominator else None


def _metrics(tp: float, fp: float, fn: float, tn: float) -> dict[str, float | None]:
    """Calculate standard binary metrics from one confusion matrix.

    Args:
        tp: True positives.
        fp: False positives.
        fn: False negatives.
        tn: True negatives.

    Returns:
        Precision, recall, F1, specificity, and accuracy.
    """

    precision = _divide(tp, tp + fp)
    recall = _divide(tp, tp + fn)
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": _divide(tn, tn + fp),
        "accuracy": _divide(tp + tn, tp + fp + fn + tn),
    }


def _confusion(rows: Iterable[Mapping[str, Any]], *, weighted: bool) -> dict[str, Any]:
    """Aggregate one set of evaluable study-category rows.

    Args:
        rows: Parsed rows containing machine and human binary labels and weight.
        weighted: Use ``sample_weight`` rather than unit counts.

    Returns:
        Confusion counts plus derived metrics.
    """

    counts = {"true_positive": 0.0, "false_positive": 0.0, "false_negative": 0.0, "true_negative": 0.0}
    for row in rows:
        weight = float(row["sample_weight"]) if weighted else 1.0
        machine = bool(row["machine_positive"])
        human = bool(row["human_consensus"])
        if machine and human:
            counts["true_positive"] += weight
        elif machine and not human:
            counts["false_positive"] += weight
        elif not machine and human:
            counts["false_negative"] += weight
        else:
            counts["true_negative"] += weight
    if not weighted:
        counts = {key: int(value) for key, value in counts.items()}
    counts["metrics"] = _metrics(
        float(counts["true_positive"]),
        float(counts["false_positive"]),
        float(counts["false_negative"]),
        float(counts["true_negative"]),
    )
    return counts


def _precision_recall_curve(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Build a weighted PR curve when scores and both reference classes exist.

    Args:
        rows: Parsed evaluable rows for one category.

    Returns:
        Threshold points and step-integrated average precision, or ``None`` when
        any row lacks a score or either human reference class is absent.
    """

    if not rows or any(row["machine_score"] is None for row in rows):
        return None
    total_positive = sum(float(row["sample_weight"]) for row in rows if row["human_consensus"])
    total_negative = sum(float(row["sample_weight"]) for row in rows if not row["human_consensus"])
    if not total_positive or not total_negative:
        return None
    scores = sorted({float(row["machine_score"]) for row in rows}, reverse=True)
    points: list[dict[str, float | None]] = [{"threshold": None, "precision": 1.0, "recall": 0.0}]
    average_precision = 0.0
    previous_recall = 0.0
    for threshold in scores:
        predicted = [row for row in rows if float(row["machine_score"]) >= threshold]
        tp = sum(float(row["sample_weight"]) for row in predicted if row["human_consensus"])
        fp = sum(float(row["sample_weight"]) for row in predicted if not row["human_consensus"])
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / total_positive if total_positive else 0.0
        average_precision += max(0.0, recall - previous_recall) * precision
        previous_recall = recall
        points.append({"threshold": threshold, "precision": precision, "recall": recall})
    return {"weighted": True, "average_precision": average_precision, "points": points}


def _weighted_roc_auc(rows: list[Mapping[str, Any]]) -> float | None:
    """Calculate weighted ROC AUC from all positive-negative score pairs.

    Args:
        rows: Evaluable category rows with optional frozen machine scores.

    Returns:
        Weighted probability that a human-positive study has a higher score than
        a human-negative study, with ties worth one half; ``None`` when scores or
        either reference class are absent.
    """

    if not rows or any(row["machine_score"] is None for row in rows):
        return None
    positives = [row for row in rows if row["human_consensus"]]
    negatives = [row for row in rows if not row["human_consensus"]]
    positive_weight = sum(float(row["sample_weight"]) for row in positives)
    negative_weight = sum(float(row["sample_weight"]) for row in negatives)
    if not positive_weight or not negative_weight:
        return None
    concordance = 0.0
    for positive in positives:
        for negative in negatives:
            pair_weight = float(positive["sample_weight"]) * float(negative["sample_weight"])
            positive_score = float(positive["machine_score"])
            negative_score = float(negative["machine_score"])
            if positive_score > negative_score:
                concordance += pair_weight
            elif positive_score == negative_score:
                concordance += 0.5 * pair_weight
    return concordance / (positive_weight * negative_weight)


def load_scoring_rows(path: Path | str) -> list[dict[str, Any]]:
    """Read and validate a long-format machine-versus-human CSV.

    Args:
        path: CSV using the columns in ``blank_category_scoring_template.csv``.

    Returns:
        Parsed rows with typed binary values, optional score, and positive weight.
    """

    required = {"record_id", "study_id", "category", "machine_score", "machine_positive", "human_consensus", "human_evaluable", "sample_weight", "true_positive", "false_positive", "false_negative", "true_negative", "notes"}
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if set(reader.fieldnames or []) != required:
                raise ContractError("scoring CSV columns do not match the blank template")
            raw_rows = list(reader)
    except OSError as error:
        raise ContractError(f"cannot read scoring CSV: {error}") from error
    if not raw_rows:
        raise ContractError("scoring CSV contains no study-category rows")
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(raw_rows, start=2):
        study_id = row["study_id"].strip()
        category = row["category"].strip()
        if not study_id or not category:
            raise ContractError(f"row {index} requires study_id and category")
        key = (study_id, category)
        if key in seen:
            raise ContractError(f"duplicate study-category row: {key}")
        seen.add(key)
        evaluable = _binary(row["human_evaluable"], f"row {index} human_evaluable")
        score_text = row["machine_score"].strip()
        score = None if not score_text else float(score_text)
        if score is not None and (not math.isfinite(score) or not 0.0 <= score <= 1.0):
            raise ContractError(f"row {index} machine_score must be in [0, 1]")
        weight_text = row["sample_weight"].strip()
        weight = 1.0 if not weight_text else float(weight_text)
        if not math.isfinite(weight) or weight <= 0:
            raise ContractError(f"row {index} sample_weight must be finite and positive")
        parsed.append(
            {
                "record_id": row["record_id"].strip(),
                "study_id": study_id,
                "category": category,
                "machine_score": score,
                "machine_positive": _binary(row["machine_positive"], f"row {index} machine_positive"),
                "human_consensus": _binary(row["human_consensus"], f"row {index} human_consensus") if evaluable else None,
                "human_evaluable": evaluable,
                "sample_weight": weight,
                "notes": row["notes"],
            }
        )
    return parsed


def score_categories(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Score each non-exclusive category against human consensus independently.

    Args:
        rows: Parsed long-format study-category rows.

    Returns:
        Per-category denominators, unweighted and weighted metrics, and optional
        weighted precision-recall curves.
    """

    categories = sorted({str(row["category"]) for row in rows})
    output: dict[str, Any] = {"scoring_version": "1.0.0", "categories": {}}
    for category in categories:
        category_rows = [row for row in rows if row["category"] == category]
        evaluable = [row for row in category_rows if row["human_evaluable"]]
        output["categories"][category] = {
            "n_rows": len(category_rows),
            "n_evaluable": len(evaluable),
            "n_human_positive": sum(1 for row in evaluable if row["human_consensus"]),
            "n_human_negative": sum(1 for row in evaluable if not row["human_consensus"]),
            "unweighted": _confusion(evaluable, weighted=False),
            "weighted": _confusion(evaluable, weighted=True),
            "precision_recall_curve": _precision_recall_curve(evaluable),
            "weighted_roc_auc": _weighted_roc_auc(evaluable),
        }
    output["notes"] = [
        "Human consensus is treated as the reference standard.",
        "Each category is scored one-vs-rest; multi-purpose studies may be positive in several categories.",
        "Unevaluable rows are excluded and reported in the denominator rather than counted as negatives.",
        "A precision-recall curve is emitted only when every evaluable row has a frozen score and both human reference classes are present.",
        "Weighted ROC AUC is emitted only when frozen scores and both human reference classes are present.",
    ]
    return output
