"""Tests for EHRzipper Streamlit UI — data loading and cohort filter logic.

No Streamlit rendering tests — pure Python only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ui.data.loader import (
    _MOCK_PATIENTS,
    filter_patients,
    load_fhir_bundle,
    load_patient_events,
    load_patients,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_output_dir(tmp_path: Path, patients: list[dict[str, Any]]) -> Path:
    """Create a minimal synthetic output directory in tmp_path."""
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir(parents=True)
    patients_csv = csv_dir / "patients.csv"
    if patients:
        fields = list(patients[0].keys())
        with patients_csv.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(patients)
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: load_patients returns a list of dicts
# ---------------------------------------------------------------------------


def test_load_patients_returns_list_of_dicts() -> None:
    patients = load_patients()
    assert isinstance(patients, list)
    assert len(patients) > 0
    assert all(isinstance(p, dict) for p in patients)


# ---------------------------------------------------------------------------
# Test 2: load_patients from custom output dir with real CSV
# ---------------------------------------------------------------------------


def test_load_patients_from_custom_dir(tmp_path: Path) -> None:
    sample = [
        {
            "patient_id": "test_001",
            "age_at_advanced_diagnosis": "55",
            "histology": "adenocarcinoma",
            "egfr_status": "positive",
            "vital_status": "alive",
            "practice_type": "academic",
            "stage_at_advanced_diagnosis": "IVA",
            "alk_status": "negative",
            "pdl1_status": "low",
            "ecog_at_advanced_diagnosis": "1",
        }
    ]
    out_dir = _make_output_dir(tmp_path, sample)
    patients = load_patients(out_dir)
    assert len(patients) == 1
    assert patients[0]["patient_id"] == "test_001"


# ---------------------------------------------------------------------------
# Test 3: load_patients falls back gracefully when dir missing (returns non-empty)
# ---------------------------------------------------------------------------


def test_load_patients_missing_dir_returns_nonempty() -> None:
    """When a custom dir is missing, loader falls back to _sample/ or mock data.
    Either way, it must return a non-empty list of dicts.
    """
    missing = Path("/nonexistent/path/that/should/not/exist")
    patients = load_patients(missing)
    assert isinstance(patients, list)
    assert len(patients) > 0
    assert all(isinstance(p, dict) for p in patients)


# ---------------------------------------------------------------------------
# Test 4: load_patients always returns at least mock data
# ---------------------------------------------------------------------------


def test_load_patients_always_returns_data(tmp_path: Path) -> None:
    """load_patients must always return at least mock data, never an empty list."""
    # tmp_path has no csv/ dir at all — no patients.csv anywhere
    # The loader will fall through custom → default → sample → mock
    patients = load_patients(tmp_path)
    assert len(patients) > 0


# ---------------------------------------------------------------------------
# Test 5: load_patient_events returns dict with correct keys
# ---------------------------------------------------------------------------


def test_load_patient_events_returns_correct_keys() -> None:
    events = load_patient_events("any_patient")
    expected_keys = {"encounters", "medications", "biomarkers", "conditions",
                     "progressions", "observations", "imaging"}
    assert set(events.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test 6: load_patient_events with missing dir returns empty lists
# ---------------------------------------------------------------------------


def test_load_patient_events_missing_dir_returns_empty() -> None:
    missing = Path("/nonexistent/path")
    events = load_patient_events("pat_xyz", output_dir=missing)
    assert all(len(v) == 0 for v in events.values())


# ---------------------------------------------------------------------------
# Test 7: load_fhir_bundle returns None when bundle absent
# ---------------------------------------------------------------------------


def test_load_fhir_bundle_returns_none_for_missing(tmp_path: Path) -> None:
    out_dir = _make_output_dir(tmp_path, [])
    result = load_fhir_bundle("nonexistent_patient", out_dir)
    assert result is None


# ---------------------------------------------------------------------------
# Test 8: load_fhir_bundle returns dict when bundle present
# ---------------------------------------------------------------------------


def test_load_fhir_bundle_returns_dict_when_present(tmp_path: Path) -> None:
    fhir_dir = tmp_path / "fhir"
    fhir_dir.mkdir()
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
    bundle_path = fhir_dir / "pat_test.json"
    bundle_path.write_text(json.dumps(bundle))
    # Also need csv/patients.csv
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "patients.csv").write_text("patient_id\npat_test\n")

    result = load_fhir_bundle("pat_test", tmp_path)
    assert result is not None
    assert result["resourceType"] == "Bundle"


# ---------------------------------------------------------------------------
# Test 9: filter_patients — no filters returns all
# ---------------------------------------------------------------------------


def test_filter_patients_no_filters_returns_all() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients)
    assert len(result) == len(patients)


# ---------------------------------------------------------------------------
# Test 10: filter_patients — age range excludes some patients
# ---------------------------------------------------------------------------


def test_filter_patients_age_range() -> None:
    patients = list(_MOCK_PATIENTS)
    # mock ages: 63, 68, 57, 59, 66
    result = filter_patients(patients, age_min=60, age_max=70)
    ages = [int(p["age_at_advanced_diagnosis"]) for p in result]
    assert all(60 <= a <= 70 for a in ages)
    assert len(result) < len(patients)


# ---------------------------------------------------------------------------
# Test 11: filter_patients — histology filter
# ---------------------------------------------------------------------------


def test_filter_patients_histology_filter() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients, histology=["adenocarcinoma"])
    assert all(p["histology"] == "adenocarcinoma" for p in result)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Test 12: filter_patients — EGFR status filter
# ---------------------------------------------------------------------------


def test_filter_patients_egfr_filter() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients, egfr_status=["positive"])
    assert all(p["egfr_status"] == "positive" for p in result)


# ---------------------------------------------------------------------------
# Test 13: filter_patients — vital status filter
# ---------------------------------------------------------------------------


def test_filter_patients_vital_status_filter() -> None:
    patients = list(_MOCK_PATIENTS)
    alive = filter_patients(patients, vital_status=["alive"])
    deceased = filter_patients(patients, vital_status=["deceased"])
    assert len(alive) + len(deceased) == len(patients)


# ---------------------------------------------------------------------------
# Test 14: filter_patients — combined filters AND logic
# ---------------------------------------------------------------------------


def test_filter_patients_combined_filters() -> None:
    patients = list(_MOCK_PATIENTS)
    # adenocarcinoma AND egfr positive
    result = filter_patients(patients, histology=["adenocarcinoma"], egfr_status=["positive"])
    for p in result:
        assert p["histology"] == "adenocarcinoma"
        assert p["egfr_status"] == "positive"


# ---------------------------------------------------------------------------
# Test 15: filter_patients — impossible filter returns empty list
# ---------------------------------------------------------------------------


def test_filter_patients_impossible_filter_returns_empty() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients, age_min=200, age_max=201)
    assert result == []


# ---------------------------------------------------------------------------
# Test 16: data dictionary CSV parsing works correctly
# ---------------------------------------------------------------------------


def test_data_dictionary_csv_parsing() -> None:
    """Verify canonical-schema-seed.csv loads correctly."""
    import csv as csv_mod

    schema_path = Path(__file__).parent.parent / "methodology" / "canonical-schema-seed.csv"
    assert schema_path.exists(), f"Schema CSV not found: {schema_path}"

    with schema_path.open(newline="") as fh:
        reader = csv_mod.DictReader(fh)
        rows = list(reader)

    assert len(rows) > 0
    # Must have required columns
    required_cols = {"name", "data_type", "description", "semantic_tags"}
    assert required_cols.issubset(set(rows[0].keys()))
    # patient_id must be present
    names = [r["name"] for r in rows]
    assert "patient_id" in names
    assert "egfr_status" in names


# ---------------------------------------------------------------------------
# Test 17: load_patient_events filters by patient_id correctly
# ---------------------------------------------------------------------------


def test_load_patient_events_filters_by_patient_id(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()

    # Create a biomarker_results.csv with two patients
    bm_path = csv_dir / "biomarker_results.csv"
    bm_path.write_text(
        "biomarker_id,patient_id,biomarker_name,result,result_date\n"
        "bm_001,pat_A,egfr,positive,2021-01-01\n"
        "bm_002,pat_B,alk,negative,2021-01-02\n"
    )
    # Minimal patients.csv so _find_output_dir resolves
    (csv_dir / "patients.csv").write_text("patient_id\npat_A\npat_B\n")

    events_a = load_patient_events("pat_A", output_dir=tmp_path)
    events_b = load_patient_events("pat_B", output_dir=tmp_path)

    assert len(events_a["biomarkers"]) == 1
    assert events_a["biomarkers"][0]["biomarker_name"] == "egfr"
    assert len(events_b["biomarkers"]) == 1
    assert events_b["biomarkers"][0]["biomarker_name"] == "alk"


# ---------------------------------------------------------------------------
# Test 18: filter_patients — practice_type filter
# ---------------------------------------------------------------------------


def test_filter_patients_practice_type_filter() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients, practice_type=["academic"])
    assert all(p["practice_type"] == "academic" for p in result)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Test 19: load_fhir_bundle handles malformed JSON gracefully
# ---------------------------------------------------------------------------


def test_load_fhir_bundle_handles_malformed_json(tmp_path: Path) -> None:
    fhir_dir = tmp_path / "fhir"
    fhir_dir.mkdir()
    # Write invalid JSON
    bad_bundle = fhir_dir / "bad_patient.json"
    bad_bundle.write_text("{not: valid json")
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "patients.csv").write_text("patient_id\nbad_patient\n")

    # Should return None rather than raising
    result = load_fhir_bundle("bad_patient", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# Test 20: filter_patients — ecog filter
# ---------------------------------------------------------------------------


def test_filter_patients_ecog_filter() -> None:
    patients = list(_MOCK_PATIENTS)
    result = filter_patients(patients, ecog=["1"])
    assert all(str(p["ecog_at_advanced_diagnosis"]) == "1" for p in result)
