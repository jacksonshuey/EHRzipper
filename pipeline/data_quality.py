"""
Population-level data-quality checks for synthetic aNSCLC cohorts.

Generates a canonical seed-42 cohort (n=50) via
``synthetic.profiles.generate_profiles`` and asserts clinical invariants.
Prints a PASS/FAIL table and exits non-zero if any check fails.

Usage::

    uv run python pipeline/data_quality.py

Importable::

    from pipeline.data_quality import run_checks
    result = run_checks(profiles)   # returns True if all pass
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from derived.lot import compute_lot
from synthetic.profiles import PatientProfile, generate_profiles

# ---------------------------------------------------------------------------
# Allowed vocabularies
# ---------------------------------------------------------------------------

_ALLOWED_BIOMARKER_RESULTS: frozenset[str] = frozenset(
    {
        "positive",
        "negative",
        "equivocal",
        "not_tested",
        "pending",
        "unknown",
        # PD-L1 expression levels (TPS-based): clinically standard for IHC reporting.
        "high",
        "low",
    }
)

_ALLOWED_STAGES: frozenset[str] = frozenset({"IIIB", "IIIC", "IVA", "IVB"})

# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

CheckFn = Callable[[list[PatientProfile]], list[str]]


def _check_non_null_ids(profiles: list[PatientProfile]) -> list[str]:
    """Every patient has a non-null patient_id and advanced_diagnosis_date."""
    failures: list[str] = []
    for p in profiles:
        if not p.patient_id:
            failures.append("patient_id is null/empty for a record")
        if p.advanced_diagnosis_date is None:
            failures.append(f"{p.patient_id}: advanced_diagnosis_date is null")
    return failures


def _check_initial_before_advanced(profiles: list[PatientProfile]) -> list[str]:
    """initial_nsclc_diagnosis_date <= advanced_diagnosis_date for every patient."""
    failures: list[str] = []
    for p in profiles:
        if p.initial_nsclc_diagnosis_date > p.advanced_diagnosis_date:
            failures.append(
                f"{p.patient_id}: initial_dx={p.initial_nsclc_diagnosis_date} "
                f"> advanced_dx={p.advanced_diagnosis_date}"
            )
    return failures


def _check_progressions_after_advanced(profiles: list[PatientProfile]) -> list[str]:
    """No progression event precedes advanced_diagnosis_date."""
    failures: list[str] = []
    for p in profiles:
        for pe in p.progression_events:
            if pe.event_date < p.advanced_diagnosis_date:
                failures.append(
                    f"{p.patient_id}: progression {pe.progression_id} "
                    f"event_date={pe.event_date} < advanced_dx={p.advanced_diagnosis_date}"
                )
    return failures


def _check_death_after_diagnosis(profiles: list[PatientProfile]) -> list[str]:
    """For deceased patients, date_of_death >= advanced_diagnosis_date."""
    failures: list[str] = []
    for p in profiles:
        if (
            p.vital_status == "deceased"
            and p.date_of_death is not None
            and p.date_of_death < p.advanced_diagnosis_date
        ):
            failures.append(
                f"{p.patient_id}: date_of_death={p.date_of_death} "
                f"< advanced_dx={p.advanced_diagnosis_date}"
            )
    return failures


def _check_biomarker_vocab(profiles: list[PatientProfile]) -> list[str]:
    """Every biomarker result is in the allowed vocabulary."""
    failures: list[str] = []
    for p in profiles:
        for bm in p.biomarker_results:
            if bm.result not in _ALLOWED_BIOMARKER_RESULTS:
                failures.append(
                    f"{p.patient_id}: biomarker {bm.biomarker_name} "
                    f"result={bm.result!r} not in allowed vocab"
                )
    return failures


def _check_stage_vocab(profiles: list[PatientProfile]) -> list[str]:
    """stage_at_advanced_diagnosis is one of IIIB|IIIC|IVA|IVB."""
    failures: list[str] = []
    for p in profiles:
        if p.stage_at_advanced_diagnosis not in _ALLOWED_STAGES:
            failures.append(
                f"{p.patient_id}: stage_at_advanced_diagnosis="
                f"{p.stage_at_advanced_diagnosis!r} not in {sorted(_ALLOWED_STAGES)}"
            )
    return failures


def _check_lot_ordering(profiles: list[PatientProfile]) -> list[str]:
    """
    For patients with >= 2 derived therapy lines, each later line starts
    on or after the prior line's last administration date.
    """
    failures: list[str] = []
    for p in profiles:
        if not p.drug_administrations:
            continue
        med_events = [
            {
                "display": da.display,
                "start_date": da.start_date,
                "end_date": da.end_date or da.start_date,
                "drug_class": da.drug_class,
            }
            for da in p.drug_administrations
        ]
        prog_events = [
            {
                "event_date": pe.event_date,
                "progression_type": pe.progression_type,
            }
            for pe in p.progression_events
        ]
        lines = compute_lot(
            med_events,
            prog_events,
            deceased_date=p.date_of_death,
        )
        for i in range(1, len(lines)):
            prev = lines[i - 1]
            curr = lines[i]
            if prev.end_date is not None and curr.start_date < prev.start_date:
                failures.append(
                    f"{p.patient_id}: line {curr.line_number} starts "
                    f"{curr.start_date} before line {prev.line_number} "
                    f"start {prev.start_date}"
                )
    return failures


# ---------------------------------------------------------------------------
# Registry and runner
# ---------------------------------------------------------------------------

@dataclass
class _CheckSpec:
    name: str
    description: str
    fn: CheckFn


_CHECKS: list[_CheckSpec] = [
    _CheckSpec(
        name="non_null_ids",
        description="patient_id and advanced_diagnosis_date are non-null",
        fn=_check_non_null_ids,
    ),
    _CheckSpec(
        name="initial_before_advanced",
        description="initial_nsclc_diagnosis_date <= advanced_diagnosis_date",
        fn=_check_initial_before_advanced,
    ),
    _CheckSpec(
        name="progressions_after_advanced",
        description="No progression event precedes advanced_diagnosis_date",
        fn=_check_progressions_after_advanced,
    ),
    _CheckSpec(
        name="death_after_diagnosis",
        description="Deceased: date_of_death >= advanced_diagnosis_date",
        fn=_check_death_after_diagnosis,
    ),
    _CheckSpec(
        name="biomarker_vocab",
        description="Biomarker results use allowed vocabulary",
        fn=_check_biomarker_vocab,
    ),
    _CheckSpec(
        name="stage_vocab",
        description="stage_at_advanced_diagnosis in {IIIB, IIIC, IVA, IVB}",
        fn=_check_stage_vocab,
    ),
    _CheckSpec(
        name="lot_ordering",
        description="Therapy lines are temporally ordered (LoT engine)",
        fn=_check_lot_ordering,
    ),
]


def run_checks(
    profiles: list[PatientProfile],
    *,
    verbose: bool = False,
) -> bool:
    """
    Run all population-level DQ checks against *profiles*.

    Prints a PASS/FAIL table to stdout.  Returns ``True`` if every check
    passes, ``False`` otherwise.
    """
    col_w = max(len(c.description) for c in _CHECKS) + 2
    header = f"{'Check':<{col_w}}  {'Status':<6}  Failures"
    print(header)
    print("-" * len(header))

    all_passed = True
    for spec in _CHECKS:
        failures = spec.fn(profiles)
        status = "PASS" if not failures else "FAIL"
        if failures:
            all_passed = False
        n_fail = len(failures)
        print(f"{spec.description:<{col_w}}  {status:<6}  {n_fail}")
        if verbose and failures:
            for msg in failures[:10]:
                print(f"    {msg}")
            if n_fail > 10:
                print(f"    ... and {n_fail - 10} more")

    print()
    summary = "ALL CHECKS PASSED" if all_passed else "ONE OR MORE CHECKS FAILED"
    print(summary)
    return all_passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Generate seed-42 cohort (n=50) and run all DQ checks."""
    profiles = generate_profiles(n=50, seed=42)
    passed = run_checks(profiles, verbose=True)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
