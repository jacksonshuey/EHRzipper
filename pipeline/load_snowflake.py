"""Load synthetic aNSCLC data into the live Snowflake canonical store.

Two jobs:

1. **RAW landing** — push the on-disk FHIR bundles, HL7v2 messages, and flat
   CSV rows into RAW.* exactly as generated. This demonstrates heterogeneous
   multi-source ingestion (the whole point of the reconciliation engine).

2. **CORE population** — regenerate the canonical ``PatientProfile`` objects
   (deterministic from the same seed the files were generated with) and load the
   mart-critical CORE tables: PATIENT, MEDICATION_ADMINISTRATION,
   PROGRESSION_EVENT, BIOMARKER_RESULT. The marts (cohort, lines of therapy,
   rwOS) read from these.

Dates are stored as precision-aware partial_date VARIANTs ({value, precision})
to match MARTS.RESOLVE_DATE. Run:

    python pipeline/load_snowflake.py --seed 42 --n 50
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ehrzipper.sf_connect import connect  # noqa: E402
from synthetic.profiles import PatientProfile, generate_profiles  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    from snowflake.connector.cursor import SnowflakeCursor

_OUTPUT = _ROOT / "synthetic" / "output"
_CUTOFF = dt.datetime(2024, 12, 31, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# VARIANT helpers
# ---------------------------------------------------------------------------
def _pd(d: dt.date | None) -> str | None:
    """Serialize a date as a day-precision partial_date VARIANT payload."""
    if d is None:
        return None
    return json.dumps({"value": d.isoformat(), "precision": "day"})


def _exec_rows(cur: SnowflakeCursor, sql: str, rows: list[Any]) -> None:
    """Execute an INSERT...SELECT once per row.

    ``executemany`` only batches the plain ``INSERT...VALUES`` form; our inserts
    wrap VARIANT columns in PARSE_JSON via INSERT...SELECT, so we loop.
    """
    for r in rows:
        cur.execute(sql, r)


def _coded(code: str, system: str, display: str) -> str:
    return json.dumps({"code": code, "system": system, "display": display})


def _qty(value: float, unit: str) -> str:
    return json.dumps({"value": value, "unit": unit})


# ---------------------------------------------------------------------------
# CORE loaders
# ---------------------------------------------------------------------------
def _load_patients(cur: SnowflakeCursor, profiles: list[PatientProfile]) -> int:
    cur.execute("TRUNCATE TABLE IF EXISTS CORE.PATIENT")
    sql = """
        INSERT INTO CORE.PATIENT (
            patient_id, date_of_birth, sex, race, ethnicity, vital_status,
            date_of_death, last_known_alive_date, state_of_residence,
            practice_type, practice_id, smoking_status,
            initial_nsclc_diagnosis_date, advanced_diagnosis_date,
            advanced_diagnosis_date_iso, advanced_diagnosis_pathway, histology,
            stage_at_initial_diagnosis, stage_at_advanced_diagnosis, ajcc_edition,
            ecog_at_advanced_diagnosis, age_at_advanced_diagnosis,
            egfr_status, alk_status, ros1_status, kras_status, braf_status,
            pdl1_status, pdl1_tps_value, data_cutoff_date, _meta_data_cutoff_date,
            _meta_source_records
        )
        SELECT
            ?, PARSE_JSON(?), ?, ?, ?, ?, PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, ?,
            PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, PARSE_JSON(?)
    """
    rows = [
        (
            p.patient_id, _pd(p.date_of_birth), p.sex, p.race, p.ethnicity,
            p.vital_status, _pd(p.date_of_death), _pd(p.last_known_alive_date),
            p.state_of_residence, p.practice_type, p.practice_id, p.smoking_status,
            _pd(p.initial_nsclc_diagnosis_date), _pd(p.advanced_diagnosis_date),
            p.advanced_diagnosis_date, p.advanced_diagnosis_pathway, p.histology,
            p.stage_at_initial_diagnosis, p.stage_at_advanced_diagnosis,
            p.ajcc_edition, p.ecog_at_advanced_diagnosis, p.age_at_advanced_diagnosis,
            p.egfr_status, p.alk_status, p.ros1_status, p.kras_status, p.braf_status,
            p.pdl1_status, p.pdl1_tps_value, _CUTOFF, _CUTOFF,
            json.dumps([{"source": p.source_format, "external_id": p.patient_id}]),
        )
        for p in profiles
    ]
    _exec_rows(cur, sql, rows)
    return len(rows)


def _load_medications(cur: SnowflakeCursor, profiles: list[PatientProfile]) -> int:
    cur.execute("TRUNCATE TABLE IF EXISTS CORE.MEDICATION_ADMINISTRATION")
    sql = """
        INSERT INTO CORE.MEDICATION_ADMINISTRATION (
            medication_id, patient_id, medication_code, drug_class,
            start_date, end_date, dose, route, regimen_id
        )
        SELECT ?, ?, PARSE_JSON(?), ?, PARSE_JSON(?), PARSE_JSON(?),
               PARSE_JSON(?), ?, ?
    """
    rows = [
        (
            m.medication_id, p.patient_id,
            _coded(m.rxnorm_code, "rxnorm", m.display), m.drug_class,
            _pd(m.start_date), _pd(m.end_date), _qty(m.dose_value, m.dose_unit),
            m.route, m.regimen_id,
        )
        for p in profiles
        for m in p.drug_administrations
    ]
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


def _load_progression(cur: SnowflakeCursor, profiles: list[PatientProfile]) -> int:
    cur.execute("TRUNCATE TABLE IF EXISTS CORE.PROGRESSION_EVENT")
    sql = """
        INSERT INTO CORE.PROGRESSION_EVENT (
            progression_id, patient_id, event_date, progression_type,
            evidence_source, new_metastatic_sites
        )
        SELECT ?, ?, PARSE_JSON(?), ?, ?, TO_ARRAY(PARSE_JSON(?))
    """
    rows = [
        (
            e.progression_id, p.patient_id, _pd(e.event_date), e.progression_type,
            e.evidence_source, json.dumps(e.new_metastatic_sites),
        )
        for p in profiles
        for e in p.progression_events
    ]
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


def _load_biomarkers(cur: SnowflakeCursor, profiles: list[PatientProfile]) -> int:
    cur.execute("TRUNCATE TABLE IF EXISTS CORE.BIOMARKER_RESULT")
    sql = """
        INSERT INTO CORE.BIOMARKER_RESULT (
            biomarker_id, patient_id, biomarker_name, result, result_date, test_method
        )
        SELECT ?, ?, ?, ?, PARSE_JSON(?), ?
    """
    rows = [
        (
            b.biomarker_id, p.patient_id, b.biomarker_name, b.result,
            _pd(b.result_date), b.test_method,
        )
        for p in profiles
        for b in p.biomarker_results
    ]
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# RAW loaders
# ---------------------------------------------------------------------------
def _load_raw_fhir(cur: SnowflakeCursor) -> int:
    d = _OUTPUT / "fhir"
    if not d.exists():
        return 0
    cur.execute("TRUNCATE TABLE IF EXISTS RAW.FHIR_BUNDLE")
    sql = (
        "INSERT INTO RAW.FHIR_BUNDLE (patient_id, bundle, source_file, source_system) "
        "SELECT ?, PARSE_JSON(?), ?, ?"
    )
    rows = [
        (f.stem, f.read_text(encoding="utf-8"), f.name, "synthetic_fhir")
        for f in sorted(d.glob("*.json"))
    ]
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


def _load_raw_hl7(cur: SnowflakeCursor) -> int:
    d = _OUTPUT / "hl7v2"
    if not d.exists():
        return 0
    cur.execute("TRUNCATE TABLE IF EXISTS RAW.HL7_MESSAGE")
    sql = (
        "INSERT INTO RAW.HL7_MESSAGE (patient_id, message_type, raw_text, source_system) "
        "VALUES (?, ?, ?, ?)"
    )
    rows = [
        (f.stem, "MIXED", f.read_text(encoding="utf-8"), "synthetic_hl7")
        for f in sorted(d.glob("*.hl7"))
    ]
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


def _load_raw_csv(cur: SnowflakeCursor) -> int:
    d = _OUTPUT / "csv"
    if not d.exists():
        return 0
    cur.execute("TRUNCATE TABLE IF EXISTS RAW.CSV_ROW")
    sql = (
        "INSERT INTO RAW.CSV_ROW (patient_id, source_table, row_data, source_system) "
        "SELECT ?, ?, PARSE_JSON(?), ?"
    )
    rows: list[tuple[str, str, str, str]] = []
    for f in sorted(d.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            for record in csv.DictReader(fh):
                pid = record.get("patient_id", "")
                rows.append((pid, f.stem, json.dumps(record), "synthetic_csv"))
    if rows:
        _exec_rows(cur, sql, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load synthetic data into Snowflake")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n", type=int, default=50)
    args = p.parse_args(argv)

    profiles = generate_profiles(n=args.n, seed=args.seed)
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute("USE DATABASE EHRZIPPER")
            print("== RAW landing ==")
            print(f"  RAW.FHIR_BUNDLE   {_load_raw_fhir(cur):>5}")
            print(f"  RAW.HL7_MESSAGE   {_load_raw_hl7(cur):>5}")
            print(f"  RAW.CSV_ROW       {_load_raw_csv(cur):>5}")
            print("== CORE population ==")
            print(f"  CORE.PATIENT                  {_load_patients(cur, profiles):>5}")
            print(f"  CORE.MEDICATION_ADMINISTRATION{_load_medications(cur, profiles):>5}")
            print(f"  CORE.PROGRESSION_EVENT        {_load_progression(cur, profiles):>5}")
            print(f"  CORE.BIOMARKER_RESULT         {_load_biomarkers(cur, profiles):>5}")
            conn.commit()
            print("== done ==")
        finally:
            cur.close()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
