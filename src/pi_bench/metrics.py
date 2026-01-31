"""
Inter-annotator agreement metrics for PolicyBeats benchmark calibration.

Per SPEC.md §13 item 6: Cohen's kappa (2 annotators) or Fleiss' kappa (3+)
for human baseline calibration.

Usage:
    # Compare golden labels vs one human annotator
    from pi_bench.metrics import cohens_kappa
    k = cohens_kappa(
        labels_a=["violation", "no_violation", "violation"],
        labels_b=["violation", "violation", "violation"],
    )

    # Compare golden labels vs multiple annotators
    from pi_bench.metrics import fleiss_kappa
    k = fleiss_kappa(
        annotations=[
            ["violation", "no_violation", "violation"],   # annotator 1
            ["violation", "violation", "violation"],       # annotator 2
            ["no_violation", "no_violation", "violation"], # annotator 3
        ]
    )

    # Full calibration report
    from pi_bench.metrics import calibration_report
    report = calibration_report(
        golden=["violation", "no_violation", "violation", "no_violation"],
        annotators=[
            ["violation", "no_violation", "violation", "no_violation"],
            ["violation", "violation", "violation", "no_violation"],
        ]
    )
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KappaResult:
    """Result of a kappa computation."""
    kappa: float
    observed_agreement: float
    expected_agreement: float
    n_items: int
    interpretation: str


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Full calibration report for benchmark golden labels."""
    n_items: int
    n_annotators: int
    golden_vs_annotator: dict[int, KappaResult]  # annotator index -> kappa
    inter_annotator: KappaResult | None  # Fleiss' kappa across all annotators
    mean_kappa: float
    category_agreement: dict[str, float]  # per-category agreement rates
    confusion_matrix: dict[str, dict[str, int]]  # predicted -> actual counts


def _interpret_kappa(k: float) -> str:
    """Landis & Koch (1977) interpretation scale."""
    if k < 0:
        return "poor"
    if k < 0.20:
        return "slight"
    if k < 0.40:
        return "fair"
    if k < 0.60:
        return "moderate"
    if k < 0.80:
        return "substantial"
    return "almost_perfect"


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> KappaResult:
    """
    Cohen's kappa for two annotators.

    Args:
        labels_a: Labels from annotator A (or golden labels)
        labels_b: Labels from annotator B

    Returns:
        KappaResult with kappa statistic and interpretation
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(f"Label lists must be same length: {len(labels_a)} != {len(labels_b)}")

    n = len(labels_a)
    if n == 0:
        return KappaResult(kappa=1.0, observed_agreement=1.0, expected_agreement=1.0,
                           n_items=0, interpretation="almost_perfect")

    # Observed agreement
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    p_o = agree / n

    # Expected agreement (by chance)
    categories = sorted(set(labels_a) | set(labels_b))
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    p_e = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)

    # Kappa
    if p_e == 1.0:
        kappa = 1.0  # perfect agreement by definition
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)

    return KappaResult(
        kappa=kappa,
        observed_agreement=p_o,
        expected_agreement=p_e,
        n_items=n,
        interpretation=_interpret_kappa(kappa),
    )


def fleiss_kappa(annotations: list[list[str]]) -> KappaResult:
    """
    Fleiss' kappa for 3+ annotators (also works for 2).

    Args:
        annotations: List of label lists, one per annotator.
                     All lists must be same length.

    Returns:
        KappaResult with kappa statistic and interpretation
    """
    if len(annotations) < 2:
        raise ValueError("Need at least 2 annotators")

    n_annotators = len(annotations)
    n_items = len(annotations[0])
    if any(len(a) != n_items for a in annotations):
        raise ValueError("All annotator label lists must be same length")
    if n_items == 0:
        return KappaResult(kappa=1.0, observed_agreement=1.0, expected_agreement=1.0,
                           n_items=0, interpretation="almost_perfect")

    # Collect all categories
    categories = sorted({label for ann in annotations for label in ann})

    # Build count matrix: n_items × n_categories
    # counts[i][j] = number of annotators who assigned category j to item i
    counts: list[dict[str, int]] = []
    for i in range(n_items):
        item_counts: dict[str, int] = {c: 0 for c in categories}
        for ann in annotations:
            item_counts[ann[i]] += 1
        counts.append(item_counts)

    # P_i = proportion of agreeing pairs for item i
    # P_i = (1 / (n*(n-1))) * (sum(n_ij^2) - n)
    n = n_annotators
    p_items = []
    for item_counts in counts:
        sum_sq = sum(v * v for v in item_counts.values())
        p_i = (sum_sq - n) / (n * (n - 1)) if n > 1 else 1.0
        p_items.append(p_i)

    p_o = sum(p_items) / n_items

    # P_e = sum of (proportion of all assignments to category j)^2
    total_assignments = n_items * n_annotators
    p_e = sum(
        (sum(counts[i][c] for i in range(n_items)) / total_assignments) ** 2
        for c in categories
    )

    if p_e == 1.0:
        kappa = 1.0
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)

    return KappaResult(
        kappa=kappa,
        observed_agreement=p_o,
        expected_agreement=p_e,
        n_items=n_items,
        interpretation=_interpret_kappa(kappa),
    )


def calibration_report(
    golden: list[str],
    annotators: list[list[str]],
    annotator_names: list[str] | None = None,  # noqa: ARG001 — reserved for future reporting
) -> CalibrationReport:
    """
    Full calibration report: golden labels vs human annotators.

    Args:
        golden: Golden (benchmark) labels
        annotators: List of annotator label lists
        annotator_names: Optional names for annotators

    Returns:
        CalibrationReport with per-annotator kappa, inter-annotator kappa,
        confusion matrix, and per-category agreement rates
    """
    n_items = len(golden)
    n_annotators = len(annotators)

    # Golden vs each annotator
    golden_vs = {}
    for i, ann in enumerate(annotators):
        golden_vs[i] = cohens_kappa(golden, ann)

    # Inter-annotator (Fleiss' kappa across all annotators + golden)
    all_annotations = [golden] + annotators
    inter = fleiss_kappa(all_annotations) if len(all_annotations) >= 2 else None

    # Mean kappa
    mean_k = sum(r.kappa for r in golden_vs.values()) / n_annotators if n_annotators else 0.0

    # Per-category agreement rates
    categories = sorted(set(golden))
    category_agreement: dict[str, float] = {}
    for cat in categories:
        cat_indices = [i for i, g in enumerate(golden) if g == cat]
        if not cat_indices:
            continue
        agrees = 0
        total = 0
        for idx in cat_indices:
            for ann in annotators:
                total += 1
                if ann[idx] == golden[idx]:
                    agrees += 1
        category_agreement[cat] = agrees / total if total else 0.0

    # Confusion matrix (aggregated across all annotators)
    all_labels = sorted(set(golden) | {l for ann in annotators for l in ann})
    confusion: dict[str, dict[str, int]] = {g: {p: 0 for p in all_labels} for g in all_labels}
    for ann in annotators:
        for g, p in zip(golden, ann):
            confusion[g][p] += 1

    return CalibrationReport(
        n_items=n_items,
        n_annotators=n_annotators,
        golden_vs_annotator=golden_vs,
        inter_annotator=inter,
        mean_kappa=mean_k,
        category_agreement=category_agreement,
        confusion_matrix=confusion,
    )
