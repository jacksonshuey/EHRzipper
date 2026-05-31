"""
End-to-end derived-variable pipeline over synthetic output.

Reads a synthetic batch directory (as produced by ``synthetic.generator``),
runs the lines-of-therapy engine per patient and the rwOS / Kaplan-Meier
engines across the cohort, and returns summary statistics.

The synthetic generator emits three source *formats* (FHIR, HL7v2, CSV) plus a
combined ``csv/`` directory that carries every patient's full structured record
(patients, medication_administrations, progression_events, ...). The CSV layer
is the complete canonical projection, so the pipeline reads from ``csv/`` —
this mirrors how the production pipeline would read CORE tables rather than raw
source payloads.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from derived.dates import resolve_date
from derived.km import KMResult, kaplan_meier
from derived.lot import TherapyLine, compute_lot
from derived.lot_validator import LotWarning, validate_lot
from derived.rwos import SurvivalRecord, compute_rwos


def _find_csv_dir(patients_dir: Path) -> Path:
    """Locate the combined CSV directory under a batch dir (or accept it directly)."""
    if (patients_dir / "patients.csv").exists():
        return patients_dir
    if (patients_dir / "csv" / "patients.csv").exists():
        return patients_dir / "csv"
    raise FileNotFoundError(
        f"No patients.csv found under {patients_dir} or {patients_dir}/csv"
    )


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _group_by_patient(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.get("patient_id", ""), []).append(r)
    return out


def run_derived_variables(patients_dir: Path | str) -> dict[str, Any]:
    """
    Run all derived variables over a synthetic batch directory.

    Returns a summary dict:
      {
        "n_patients", "n_treated",
        "lines_of_therapy": {patient_id: [TherapyLine, ...]},
        "lot_warnings": {patient_id: [LotWarning, ...]},
        "survival_records": [SurvivalRecord, ...],
        "km": KMResult,
        "summary": {
            "median_os_days", "median_os_ci",
            "pct_reaching_line_2", "pct_reaching_line_3",
            "line1_drug_class_distribution",
        },
      }
    """
    base = Path(patients_dir)
    csv_dir = _find_csv_dir(base)

    patients = _read_csv(csv_dir / "patients.csv")
    meds_by_pat = _group_by_patient(_read_csv(csv_dir / "medication_administrations.csv"))
    prog_by_pat = _group_by_patient(_read_csv(csv_dir / "progression_events.csv"))

    lot_by_patient: dict[str, list[TherapyLine]] = {}
    warnings_by_patient: dict[str, list[LotWarning]] = {}
    n_treated = 0
    line1_classes: Counter[str] = Counter()
    reached_2 = 0
    reached_3 = 0

    for p in patients:
        pid = p.get("patient_id", "")
        meds = meds_by_pat.get(pid, [])
        progs = prog_by_pat.get(pid, [])
        deceased = (
            resolve_date(p.get("date_of_death"))
            if (p.get("vital_status") or "").lower() == "deceased"
            else None
        )
        lines = compute_lot(meds, progs, deceased_date=deceased)
        lot_by_patient[pid] = lines
        warnings_by_patient[pid] = validate_lot(
            lines, resolve_date(p.get("advanced_diagnosis_date"))
        )
        if lines:
            n_treated += 1
            line1_classes[lines[0].drug_class] += 1
            if len(lines) >= 2:
                reached_2 += 1
            if len(lines) >= 3:
                reached_3 += 1

    survival_records: list[SurvivalRecord] = compute_rwos(patients)
    km: KMResult = kaplan_meier(survival_records)

    treated_denom = n_treated or 1
    summary = {
        "median_os_days": km.median_os_days,
        "median_os_ci": [km.ci_lower, km.ci_upper],
        "pct_reaching_line_2": round(100.0 * reached_2 / treated_denom, 1),
        "pct_reaching_line_3": round(100.0 * reached_3 / treated_denom, 1),
        "line1_drug_class_distribution": dict(line1_classes),
    }

    return {
        "n_patients": len(patients),
        "n_treated": n_treated,
        "lines_of_therapy": lot_by_patient,
        "lot_warnings": warnings_by_patient,
        "survival_records": survival_records,
        "km": km,
        "summary": summary,
    }
