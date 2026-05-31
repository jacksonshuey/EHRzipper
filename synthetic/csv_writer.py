"""
Flat CSV writer.

Emits one CSV file per resource type, all joined by patient_id.
Files produced:
  patients.csv              — one row per patient (§A patient-level fields)
  encounters.csv            — one row per encounter
  conditions.csv            — one row per condition (just the primary NSCLC dx)
  observations.csv          — labs + ECOG + smoking (one row per observation)
  medication_administrations.csv — one row per drug administration
  biomarker_results.csv     — one row per biomarker test
  progression_events.csv    — one row per progression event
  imaging_studies.csv       — one row per imaging study
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

from synthetic.profiles import PatientProfile

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _opt_date(d: date | None) -> str:
    return d.isoformat() if d else ""


def _opt_val(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _patient_row(p: PatientProfile) -> dict[str, Any]:
    return {
        "patient_id": p.patient_id,
        "practice_id": p.practice_id,
        "practice_type": p.practice_type,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "date_of_birth": p.date_of_birth.strftime("%Y-%m"),
        "sex": p.sex,
        "race": p.race,
        "ethnicity": p.ethnicity,
        "state_of_residence": p.state_of_residence,
        "street_address": p.street_address,
        "city": p.city,
        "zip_code": p.zip_code,
        "smoking_status": p.smoking_status,
        "pack_years": _opt_val(p.pack_years),
        "initial_nsclc_diagnosis_date": p.initial_nsclc_diagnosis_date.isoformat(),
        "advanced_diagnosis_date": p.advanced_diagnosis_date.isoformat(),
        "advanced_diagnosis_pathway": p.advanced_diagnosis_pathway,
        "histology": p.histology,
        "histology_icdo3_code": p.histology_icdo3_code,
        "icd10_code": p.icd10_code,
        "stage_at_initial_diagnosis": p.stage_at_initial_diagnosis,
        "stage_at_advanced_diagnosis": p.stage_at_advanced_diagnosis,
        "ajcc_edition": p.ajcc_edition,
        "ecog_at_advanced_diagnosis": str(p.ecog_at_advanced_diagnosis),
        "age_at_advanced_diagnosis": str(p.age_at_advanced_diagnosis),
        "egfr_status": p.egfr_status,
        "alk_status": p.alk_status,
        "ros1_status": p.ros1_status,
        "kras_status": p.kras_status,
        "braf_status": p.braf_status,
        "pdl1_status": p.pdl1_status,
        "pdl1_tps_value": _opt_val(p.pdl1_tps_value),
        "vital_status": p.vital_status,
        "date_of_death": _opt_date(p.date_of_death),
        "last_known_alive_date": p.last_known_alive_date.isoformat(),
        "data_cutoff_date": p.data_cutoff_date.isoformat(),
        "source_format": p.source_format,
    }


PATIENT_FIELDS = [
    "patient_id", "practice_id", "practice_type",
    "first_name", "last_name", "date_of_birth", "sex", "race", "ethnicity",
    "state_of_residence", "street_address", "city", "zip_code",
    "smoking_status", "pack_years",
    "initial_nsclc_diagnosis_date", "advanced_diagnosis_date",
    "advanced_diagnosis_pathway", "histology", "histology_icdo3_code",
    "icd10_code", "stage_at_initial_diagnosis", "stage_at_advanced_diagnosis",
    "ajcc_edition", "ecog_at_advanced_diagnosis", "age_at_advanced_diagnosis",
    "egfr_status", "alk_status", "ros1_status", "kras_status", "braf_status",
    "pdl1_status", "pdl1_tps_value",
    "vital_status", "date_of_death", "last_known_alive_date",
    "data_cutoff_date", "source_format",
]

ENCOUNTER_FIELDS = [
    "encounter_id", "patient_id", "encounter_date", "encounter_type", "provider_specialty",
]

CONDITION_FIELDS = [
    "condition_id", "patient_id", "condition_code", "onset_date",
    "histology", "stage_at_advanced_diagnosis", "is_primary_cancer",
]

OBSERVATION_FIELDS = [
    "observation_id", "patient_id", "loinc_code", "display",
    "observation_date", "value", "unit", "ref_low", "ref_high",
]

MED_ADMIN_FIELDS = [
    "medication_id", "patient_id", "rxnorm_code", "display", "drug_class",
    "start_date", "end_date", "dose_value", "dose_unit", "route",
    "regimen_id", "cycle",
]

BIOMARKER_FIELDS = [
    "biomarker_id", "patient_id", "biomarker_name", "result", "result_value",
    "result_date", "test_method", "specimen_type", "lab_vendor", "loinc_code",
]

PROGRESSION_FIELDS = [
    "progression_id", "patient_id", "event_date", "progression_type",
    "evidence_source", "new_metastatic_sites",
]

IMAGING_FIELDS = [
    "imaging_id", "patient_id", "study_date", "modality", "body_region",
]


# ---------------------------------------------------------------------------
# Main CSV write function
# ---------------------------------------------------------------------------


def write_csv_files(profiles: list[PatientProfile], out_dir: Path) -> list[Path]:
    """Write all CSV files for CSV-format profiles to *out_dir*/csv/."""
    csv_dir = out_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    # Collect rows
    patient_rows: list[dict[str, Any]] = []
    encounter_rows: list[dict[str, Any]] = []
    condition_rows: list[dict[str, Any]] = []
    observation_rows: list[dict[str, Any]] = []
    med_rows: list[dict[str, Any]] = []
    biomarker_rows: list[dict[str, Any]] = []
    progression_rows: list[dict[str, Any]] = []
    imaging_rows: list[dict[str, Any]] = []

    for p in profiles:
        if p.source_format != "csv":
            continue

        patient_rows.append(_patient_row(p))

        condition_rows.append({
            "condition_id": f"cond_{p.patient_id}",
            "patient_id": p.patient_id,
            "condition_code": p.icd10_code,
            "onset_date": p.initial_nsclc_diagnosis_date.isoformat(),
            "histology": p.histology,
            "stage_at_advanced_diagnosis": p.stage_at_advanced_diagnosis,
            "is_primary_cancer": "true",
        })

        for enc in p.encounters:
            encounter_rows.append({
                "encounter_id": enc.encounter_id,
                "patient_id": p.patient_id,
                "encounter_date": enc.encounter_date.isoformat(),
                "encounter_type": enc.encounter_type,
                "provider_specialty": enc.provider_specialty,
            })

        for lab in p.lab_observations:
            observation_rows.append({
                "observation_id": lab.observation_id,
                "patient_id": p.patient_id,
                "loinc_code": lab.loinc_code,
                "display": lab.display,
                "observation_date": lab.observation_date.isoformat(),
                "value": str(lab.value),
                "unit": lab.unit,
                "ref_low": _opt_val(lab.ref_low),
                "ref_high": _opt_val(lab.ref_high),
            })

        for admin in p.drug_administrations:
            med_rows.append({
                "medication_id": admin.medication_id,
                "patient_id": p.patient_id,
                "rxnorm_code": admin.rxnorm_code,
                "display": admin.display,
                "drug_class": admin.drug_class,
                "start_date": admin.start_date.isoformat(),
                "end_date": _opt_date(admin.end_date),
                "dose_value": str(admin.dose_value),
                "dose_unit": admin.dose_unit,
                "route": admin.route,
                "regimen_id": admin.regimen_id,
                "cycle": str(admin.cycle),
            })

        for bm in p.biomarker_results:
            biomarker_rows.append({
                "biomarker_id": bm.biomarker_id,
                "patient_id": p.patient_id,
                "biomarker_name": bm.biomarker_name,
                "result": bm.result,
                "result_value": _opt_val(bm.result_value),
                "result_date": bm.result_date.isoformat(),
                "test_method": bm.test_method,
                "specimen_type": bm.specimen_type,
                "lab_vendor": bm.lab_vendor,
                "loinc_code": bm.loinc_code,
            })

        for prg in p.progression_events:
            progression_rows.append({
                "progression_id": prg.progression_id,
                "patient_id": p.patient_id,
                "event_date": prg.event_date.isoformat(),
                "progression_type": prg.progression_type,
                "evidence_source": prg.evidence_source,
                "new_metastatic_sites": "|".join(prg.new_metastatic_sites),
            })

        for img in p.imaging_studies:
            imaging_rows.append({
                "imaging_id": img.imaging_id,
                "patient_id": p.patient_id,
                "study_date": img.study_date.isoformat(),
                "modality": img.modality,
                "body_region": img.body_region,
            })

    files: list[Path] = []

    if patient_rows:
        p_path = csv_dir / "patients.csv"
        _write_csv(p_path, PATIENT_FIELDS, patient_rows)
        files.append(p_path)

    if encounter_rows:
        e_path = csv_dir / "encounters.csv"
        _write_csv(e_path, ENCOUNTER_FIELDS, encounter_rows)
        files.append(e_path)

    if condition_rows:
        c_path = csv_dir / "conditions.csv"
        _write_csv(c_path, CONDITION_FIELDS, condition_rows)
        files.append(c_path)

    if observation_rows:
        o_path = csv_dir / "observations.csv"
        _write_csv(o_path, OBSERVATION_FIELDS, observation_rows)
        files.append(o_path)

    if med_rows:
        m_path = csv_dir / "medication_administrations.csv"
        _write_csv(m_path, MED_ADMIN_FIELDS, med_rows)
        files.append(m_path)

    if biomarker_rows:
        b_path = csv_dir / "biomarker_results.csv"
        _write_csv(b_path, BIOMARKER_FIELDS, biomarker_rows)
        files.append(b_path)

    if progression_rows:
        pr_path = csv_dir / "progression_events.csv"
        _write_csv(pr_path, PROGRESSION_FIELDS, progression_rows)
        files.append(pr_path)

    if imaging_rows:
        i_path = csv_dir / "imaging_studies.csv"
        _write_csv(i_path, IMAGING_FIELDS, imaging_rows)
        files.append(i_path)

    return files


def write_canonical_patient_csv(profiles: list[PatientProfile], out_dir: Path) -> Path:
    """Write a flat canonical patient CSV for ALL profiles, every source format.

    ``write_csv_files`` only emits the CSV-delivered subset (to preserve the
    raw multi-source split for RAW landing). The canonical export is the
    unified patient-level view across all formats — what the cohort UI reads,
    matching what lands in CORE.PATIENT.
    """
    canon_dir = out_dir / "canonical"
    canon_dir.mkdir(parents=True, exist_ok=True)
    rows = [_patient_row(p) for p in profiles]
    path = canon_dir / "patients.csv"
    _write_csv(path, PATIENT_FIELDS, rows)
    return path
