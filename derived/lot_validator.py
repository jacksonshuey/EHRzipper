"""
Clinical sanity checks for derived lines of therapy.

These are *warnings*, not hard errors: real-world data is messy, and the LoT
engine should surface suspicious output rather than crash. Each check emits a
:class:`LotWarning` carrying the line number(s) involved and a human-readable
message a clinical analyst can triage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from derived.drugs import ONCOLOGY_DRUGS, normalize_drug_name
from derived.lot import TherapyLine

# A line lasting longer than this is almost certainly a derivation error.
MAX_LINE_DURATION_DAYS = 10 * 365


@dataclass
class LotWarning:
    """A single clinical-plausibility warning about derived LoT output."""

    code: str
    message: str
    line_number: int | None = None


def validate_lot(
    lines: list[TherapyLine],
    advanced_diagnosis_date: date | None = None,
) -> list[LotWarning]:
    """
    Run clinical sanity checks over a patient's derived lines.

    Checks:
      * Line 1 cannot start before the advanced diagnosis (index) date.
      * Line numbers are sequential starting at 1 with no gaps.
      * Every drug in every line is on the recognized oncology drug list.
      * No line has a duration longer than 10 years.
      * end_date (if present) is not before start_date.
    """
    warnings: list[LotWarning] = []
    if not lines:
        return warnings

    # 1. Line 1 vs. index date.
    if advanced_diagnosis_date is not None:
        first = lines[0]
        if first.start_date < advanced_diagnosis_date:
            warnings.append(
                LotWarning(
                    code="treatment_before_diagnosis",
                    message=(
                        f"Line 1 starts {first.start_date.isoformat()} which is "
                        f"before the advanced diagnosis date "
                        f"{advanced_diagnosis_date.isoformat()}."
                    ),
                    line_number=1,
                )
            )

    # 2. Sequential line numbers 1..n.
    expected = list(range(1, len(lines) + 1))
    actual = [ln.line_number for ln in lines]
    if actual != expected:
        warnings.append(
            LotWarning(
                code="non_sequential_line_numbers",
                message=f"Line numbers {actual} are not sequential (expected {expected}).",
            )
        )

    for ln in lines:
        # 3. Recognized drugs only.
        for drug in ln.drugs:
            if normalize_drug_name(drug) not in ONCOLOGY_DRUGS:
                warnings.append(
                    LotWarning(
                        code="unrecognized_drug",
                        message=f"Drug '{drug}' is not on the recognized oncology list.",
                        line_number=ln.line_number,
                    )
                )

        # 4 & 5. Duration sanity.
        if ln.end_date is not None:
            if ln.end_date < ln.start_date:
                warnings.append(
                    LotWarning(
                        code="end_before_start",
                        message=(
                            f"Line {ln.line_number} end_date "
                            f"{ln.end_date.isoformat()} precedes start_date "
                            f"{ln.start_date.isoformat()}."
                        ),
                        line_number=ln.line_number,
                    )
                )
            elif (ln.end_date - ln.start_date).days > MAX_LINE_DURATION_DAYS:
                warnings.append(
                    LotWarning(
                        code="implausible_duration",
                        message=(
                            f"Line {ln.line_number} duration "
                            f"{(ln.end_date - ln.start_date).days} days exceeds "
                            f"{MAX_LINE_DURATION_DAYS} days (10 years)."
                        ),
                        line_number=ln.line_number,
                    )
                )

    return warnings
