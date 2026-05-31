"""
Abstraction evaluator.

Compares abstracted results against ground truth derived from PatientProfile
objects and reports:
  - per-field accuracy (exact match after normalization)
  - precision / recall / F1 for list fields
  - macro-averaged accuracy across fields
  - field-level miss rate (present in GT but returned None)
  - confusion matrices for egfr_status, histology, ecog

Notes for a patient are merged into one consolidated extraction before
comparison (a field is correct if any of the patient's notes recovered it),
because no single note carries every field.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from abstraction.types import AbstractedFields, AbstractionResult

# Scalar fields evaluated by exact-match (after normalization).
SCALAR_FIELDS = [
    "histology",
    "stage",
    "egfr_status",
    "egfr_mutation",
    "alk_status",
    "ros1_status",
    "kras_status",
    "kras_variant",
    "braf_status",
    "pdl1_status",
    "ecog",
    "progression_mentioned",
    "progression_date",
]

# Numeric field compared with a tolerance.
NUMERIC_FIELDS = ["pdl1_tps"]
NUMERIC_TOLERANCE = 0.5

# List fields evaluated by set precision/recall.
LIST_FIELDS = ["new_metastatic_sites", "treatments_mentioned"]

CONFUSION_FIELDS = ["egfr_status", "histology", "ecog"]


def normalize_scalar(value: Any) -> Any:
    """Normalize a scalar for exact-match comparison."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_")
    return value


def normalize_set(values: list[str]) -> set[str]:
    """Normalize a list field into a comparable set."""
    return {str(v).strip().lower().replace(" ", "_") for v in values if str(v).strip()}


def merge_results(results: list[AbstractionResult]) -> AbstractedFields:
    """Merge a patient's per-note extractions into one consolidated record.

    First non-None wins for scalars; lists are unioned; progression_mentioned
    is OR-ed across notes.
    """
    merged = AbstractedFields()
    sites: set[str] = set()
    treatments: list[str] = []
    treat_seen: set[str] = set()
    progression = False
    prog_date: str | None = None

    for r in results:
        f = r.fields
        for field in SCALAR_FIELDS + NUMERIC_FIELDS:
            if field in ("progression_mentioned", "progression_date"):
                continue
            if getattr(merged, field) is None and getattr(f, field) is not None:
                setattr(merged, field, getattr(f, field))
        progression = progression or f.progression_mentioned
        if prog_date is None and f.progression_date is not None:
            prog_date = f.progression_date
        sites.update(normalize_set(f.new_metastatic_sites))
        for t in f.treatments_mentioned:
            norm = t.strip().lower()
            if norm not in treat_seen:
                treat_seen.add(norm)
                treatments.append(t)

    merged.progression_mentioned = progression
    merged.progression_date = prog_date
    merged.new_metastatic_sites = sorted(sites)
    merged.treatments_mentioned = treatments
    return merged


class ListFieldMetrics(BaseModel):
    field: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


class EvalReport(BaseModel):
    n_patients: int
    macro_accuracy: float
    scalar_accuracy: dict[str, float] = Field(default_factory=dict)
    scalar_miss_rate: dict[str, float] = Field(default_factory=dict)
    numeric_accuracy: dict[str, float] = Field(default_factory=dict)
    list_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    confusion: dict[str, dict[str, dict[str, int]]] = Field(default_factory=dict)


class AbstractionEvaluator:
    """Computes accuracy metrics for abstracted results vs. ground truth."""

    def evaluate(
        self,
        ground_truth: dict[str, AbstractedFields],
        cohort_results: dict[str, list[AbstractionResult]],
    ) -> EvalReport:
        patient_ids = [pid for pid in ground_truth if pid in cohort_results]

        scalar_correct: dict[str, int] = defaultdict(int)
        scalar_total: dict[str, int] = defaultdict(int)
        scalar_present: dict[str, int] = defaultdict(int)
        scalar_misses: dict[str, int] = defaultdict(int)

        numeric_correct: dict[str, int] = defaultdict(int)
        numeric_total: dict[str, int] = defaultdict(int)

        list_metrics = {f: ListFieldMetrics(field=f) for f in LIST_FIELDS}
        confusion: dict[str, dict[str, dict[str, int]]] = {
            f: defaultdict(lambda: defaultdict(int)) for f in CONFUSION_FIELDS
        }

        for pid in patient_ids:
            gt = ground_truth[pid]
            pred = merge_results(cohort_results[pid])

            for field in SCALAR_FIELDS:
                gt_v = normalize_scalar(getattr(gt, field))
                pred_v = normalize_scalar(getattr(pred, field))
                scalar_total[field] += 1
                if gt_v == pred_v:
                    scalar_correct[field] += 1
                if gt_v is not None:
                    scalar_present[field] += 1
                    if pred_v is None:
                        scalar_misses[field] += 1
                if field in CONFUSION_FIELDS:
                    gk = "None" if gt_v is None else str(gt_v)
                    pk = "None" if pred_v is None else str(pred_v)
                    confusion[field][gk][pk] += 1

            for field in NUMERIC_FIELDS:
                gt_v = getattr(gt, field)
                pred_v = getattr(pred, field)
                numeric_total[field] += 1
                both_none = gt_v is None and pred_v is None
                both_close = (
                    gt_v is not None
                    and pred_v is not None
                    and abs(float(gt_v) - float(pred_v)) <= NUMERIC_TOLERANCE
                )
                if both_none or both_close:
                    numeric_correct[field] += 1

            for field in LIST_FIELDS:
                gt_set = normalize_set(getattr(gt, field))
                pred_set = normalize_set(getattr(pred, field))
                m = list_metrics[field]
                m.tp += len(gt_set & pred_set)
                m.fp += len(pred_set - gt_set)
                m.fn += len(gt_set - pred_set)

        scalar_accuracy = {
            f: (scalar_correct[f] / scalar_total[f] if scalar_total[f] else 0.0)
            for f in SCALAR_FIELDS
        }
        scalar_miss_rate = {
            f: (scalar_misses[f] / scalar_present[f] if scalar_present[f] else 0.0)
            for f in SCALAR_FIELDS
        }
        numeric_accuracy = {
            f: (numeric_correct[f] / numeric_total[f] if numeric_total[f] else 0.0)
            for f in NUMERIC_FIELDS
        }
        list_out = {
            f: {
                "precision": m.precision,
                "recall": m.recall,
                "f1": m.f1,
            }
            for f, m in list_metrics.items()
        }

        # Macro accuracy across all scalar + numeric fields + list F1s.
        components = (
            list(scalar_accuracy.values())
            + list(numeric_accuracy.values())
            + [list_out[f]["f1"] for f in LIST_FIELDS]
        )
        macro = sum(components) / len(components) if components else 0.0

        confusion_plain = {
            f: {gk: dict(pv) for gk, pv in rows.items()}
            for f, rows in confusion.items()
        }

        return EvalReport(
            n_patients=len(patient_ids),
            macro_accuracy=macro,
            scalar_accuracy=scalar_accuracy,
            scalar_miss_rate=scalar_miss_rate,
            numeric_accuracy=numeric_accuracy,
            list_metrics=list_out,
            confusion=confusion_plain,
        )


def write_report(report: EvalReport, out_path: Path) -> None:
    """Write the eval report as JSON."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")


def format_summary(report: EvalReport) -> str:
    """Render a human-readable summary table."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"ABSTRACTION EVAL  |  patients={report.n_patients}")
    lines.append(f"Macro accuracy:   {report.macro_accuracy:.3f}")
    lines.append("=" * 60)
    lines.append(f"{'field':<24}{'accuracy':>10}{'miss_rate':>12}")
    lines.append("-" * 60)
    for field, acc in report.scalar_accuracy.items():
        miss = report.scalar_miss_rate.get(field, 0.0)
        lines.append(f"{field:<24}{acc:>10.3f}{miss:>12.3f}")
    for field, acc in report.numeric_accuracy.items():
        lines.append(f"{field:<24}{acc:>10.3f}{'-':>12}")
    lines.append("-" * 60)
    lines.append(f"{'list field':<24}{'precision':>10}{'recall':>10}{'f1':>8}")
    lines.append("-" * 60)
    for field, m in report.list_metrics.items():
        lines.append(
            f"{field:<24}{m['precision']:>10.3f}{m['recall']:>10.3f}{m['f1']:>8.3f}"
        )
    lines.append("=" * 60)
    return "\n".join(lines)
