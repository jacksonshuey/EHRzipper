"""
Tests for the synthetic aNSCLC patient generator.

Tests:
  1. Seed determinism — same seed produces identical profiles
  2. Biomarker prevalence within tolerance over 200 patients
  3. Every patient validates against canonical schema fields
  4. No PHI tokens (real celebrity names not present)
  5. FHIR bundle structure validation
  6. HL7v2 file structure validation
  7. CSV file integrity (all patients present, patient_id consistency)
  8. Notes generation (template mode)
  9. Date ordering invariants
  10. Format distribution
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from synthetic.profiles import DATA_CUTOFF, PatientProfile, generate_profiles

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fifty_profiles() -> list[PatientProfile]:
    return generate_profiles(n=50, seed=42)


@pytest.fixture(scope="module")
def two_hundred_profiles() -> list[PatientProfile]:
    return generate_profiles(n=200, seed=99)


@pytest.fixture(scope="module")
def tmp_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("synth_output")


# ---------------------------------------------------------------------------
# 1. Seed determinism
# ---------------------------------------------------------------------------


def test_seed_determinism() -> None:
    """Same seed must produce byte-identical profiles."""
    p1 = generate_profiles(n=10, seed=123)
    p2 = generate_profiles(n=10, seed=123)
    for a, b in zip(p1, p2, strict=True):
        assert a.model_dump() == b.model_dump(), f"Profile {a.patient_id} not deterministic"


def test_different_seeds_differ() -> None:
    """Different seeds should produce different profiles."""
    p1 = generate_profiles(n=5, seed=1)
    p2 = generate_profiles(n=5, seed=2)
    ids1 = {p.patient_id for p in p1}
    ids2 = {p.patient_id for p in p2}
    # Very unlikely to be identical
    assert ids1 != ids2 or [p.advanced_diagnosis_date for p in p1] != [
        p.advanced_diagnosis_date for p in p2
    ]


# ---------------------------------------------------------------------------
# 2. Biomarker prevalence (within ±10 percentage points over 200 patients)
# ---------------------------------------------------------------------------


def test_egfr_prevalence(two_hundred_profiles: list[PatientProfile]) -> None:
    """EGFR positive prevalence: target ~15%, tolerance 5-25%."""
    pos = sum(1 for p in two_hundred_profiles if p.egfr_status == "positive")
    rate = pos / len(two_hundred_profiles)
    assert 0.05 <= rate <= 0.25, f"EGFR prevalence {rate:.1%} out of [5%, 25%]"


def test_alk_prevalence(two_hundred_profiles: list[PatientProfile]) -> None:
    """ALK positive prevalence: target ~5%, tolerance 1-12%."""
    pos = sum(1 for p in two_hundred_profiles if p.alk_status == "positive")
    rate = pos / len(two_hundred_profiles)
    assert 0.01 <= rate <= 0.12, f"ALK prevalence {rate:.1%} out of [1%, 12%]"


def test_kras_prevalence(two_hundred_profiles: list[PatientProfile]) -> None:
    """KRAS positive prevalence: target ~25%, tolerance 15-35%."""
    pos = sum(1 for p in two_hundred_profiles if p.kras_status == "positive")
    rate = pos / len(two_hundred_profiles)
    assert 0.15 <= rate <= 0.35, f"KRAS prevalence {rate:.1%} out of [15%, 35%]"


def test_pdl1_high_prevalence(two_hundred_profiles: list[PatientProfile]) -> None:
    """PD-L1 high prevalence: target ~30%, tolerance 15-45%."""
    high = sum(1 for p in two_hundred_profiles if p.pdl1_status == "high")
    rate = high / len(two_hundred_profiles)
    assert 0.15 <= rate <= 0.45, f"PD-L1 high prevalence {rate:.1%} out of [15%, 45%]"


def test_treatment_rate(two_hundred_profiles: list[PatientProfile]) -> None:
    """~70% of patients should receive at least one systemic therapy."""
    treated = sum(1 for p in two_hundred_profiles if p.drug_administrations)
    rate = treated / len(two_hundred_profiles)
    assert 0.55 <= rate <= 0.85, f"Treatment rate {rate:.1%} out of [55%, 85%]"


def test_deceased_rate(two_hundred_profiles: list[PatientProfile]) -> None:
    """~30% deceased at data cutoff, tolerance 20-40%."""
    deceased = sum(1 for p in two_hundred_profiles if p.vital_status == "deceased")
    rate = deceased / len(two_hundred_profiles)
    assert 0.20 <= rate <= 0.40, f"Deceased rate {rate:.1%} out of [20%, 40%]"


def test_histology_mix(two_hundred_profiles: list[PatientProfile]) -> None:
    """Adenocarcinoma ~60%, squamous ~25%."""
    adeno = sum(1 for p in two_hundred_profiles if p.histology == "adenocarcinoma")
    squamous = sum(1 for p in two_hundred_profiles if p.histology == "squamous_cell_carcinoma")
    n = len(two_hundred_profiles)
    assert 0.50 <= adeno / n <= 0.72, f"Adenocarcinoma {adeno / n:.1%} out of [50%, 72%]"
    assert 0.15 <= squamous / n <= 0.35, f"Squamous {squamous / n:.1%} out of [15%, 35%]"


# ---------------------------------------------------------------------------
# 3. Canonical schema validation
# ---------------------------------------------------------------------------

_REQUIRED_PATIENT_FIELDS = [
    "patient_id", "date_of_birth", "sex", "race", "ethnicity",
    "vital_status", "last_known_alive_date", "state_of_residence",
    "practice_type", "practice_id", "smoking_status",
    "initial_nsclc_diagnosis_date", "advanced_diagnosis_date",
    "advanced_diagnosis_pathway", "histology", "histology_icdo3_code",
    "stage_at_initial_diagnosis", "stage_at_advanced_diagnosis",
    "ajcc_edition", "ecog_at_advanced_diagnosis", "age_at_advanced_diagnosis",
    "egfr_status", "alk_status", "ros1_status", "kras_status",
    "braf_status", "pdl1_status", "data_cutoff_date",
]

_VALID_SEX = {"male", "female"}
_VALID_HISTOLOGY = {
    "adenocarcinoma", "squamous_cell_carcinoma", "large_cell_carcinoma",
    "adenosquamous_carcinoma", "sarcomatoid_carcinoma", "nsclc_nos",
}
_VALID_STAGE_ADV = {"IIIB", "IIIC", "IVA", "IVB"}
_VALID_ECOG = {0, 1, 2, 3, 4}
_VALID_BIOMARKER_STATUS = {"positive", "negative", "equivocal", "not_tested", "pending", "unknown"}
_VALID_PDL1_STATUS = {"high", "low", "negative", "equivocal", "not_tested", "pending", "unknown"}
_VALID_VITAL = {"alive", "deceased", "unknown"}
_VALID_PATHWAY = {
    "de_novo_stage_iiib_plus",
    "progression_from_earlier_stage",
    "metastatic_recurrence_after_ned",
}


def test_all_required_fields_present(fifty_profiles: list[PatientProfile]) -> None:
    """All canonical schema fields must be present and non-None."""
    for p in fifty_profiles:
        d = p.model_dump()
        for field in _REQUIRED_PATIENT_FIELDS:
            assert field in d and d[field] is not None, (
                f"Patient {p.patient_id}: field '{field}' is missing or None"
            )


def test_sex_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.sex in _VALID_SEX, f"Patient {p.patient_id}: invalid sex '{p.sex}'"


def test_histology_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.histology in _VALID_HISTOLOGY, (
            f"Patient {p.patient_id}: invalid histology '{p.histology}'"
        )


def test_stage_at_advanced_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.stage_at_advanced_diagnosis in _VALID_STAGE_ADV, (
            f"Patient {p.patient_id}: invalid adv stage '{p.stage_at_advanced_diagnosis}'"
        )


def test_ecog_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.ecog_at_advanced_diagnosis in _VALID_ECOG, (
            f"Patient {p.patient_id}: invalid ECOG {p.ecog_at_advanced_diagnosis}"
        )


def test_biomarker_status_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        for bm_name, status in [
            ("egfr", p.egfr_status), ("alk", p.alk_status),
            ("ros1", p.ros1_status), ("kras", p.kras_status),
            ("braf", p.braf_status),
        ]:
            assert status in _VALID_BIOMARKER_STATUS, (
                f"Patient {p.patient_id}: {bm_name} status '{status}' not in vocabulary"
            )
        assert p.pdl1_status in _VALID_PDL1_STATUS, (
            f"Patient {p.patient_id}: pdl1 status '{p.pdl1_status}' not in vocabulary"
        )


def test_vital_status_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.vital_status in _VALID_VITAL


def test_pathway_valid(fifty_profiles: list[PatientProfile]) -> None:
    for p in fifty_profiles:
        assert p.advanced_diagnosis_pathway in _VALID_PATHWAY


def test_data_cutoff_consistent(fifty_profiles: list[PatientProfile]) -> None:
    """All patients must share the same data_cutoff_date."""
    for p in fifty_profiles:
        assert p.data_cutoff_date == DATA_CUTOFF, (
            f"Patient {p.patient_id}: data_cutoff_date {p.data_cutoff_date} != {DATA_CUTOFF}"
        )


# ---------------------------------------------------------------------------
# 4. No PHI tokens / celebrity names
# ---------------------------------------------------------------------------

# A small set of well-known public figures to make sure Faker isn't generating them
_CELEBRITY_NAMES = {
    "elon musk", "donald trump", "joe biden", "taylor swift", "beyonce",
    "oprah winfrey", "kim kardashian", "barack obama", "michelle obama",
    "jeff bezos", "mark zuckerberg", "bill gates", "steve jobs",
}


def test_no_celebrity_names(fifty_profiles: list[PatientProfile]) -> None:
    """Generated names must not match known celebrity names."""
    for p in fifty_profiles:
        full_name = f"{p.first_name} {p.last_name}".lower()
        for celeb in _CELEBRITY_NAMES:
            assert celeb not in full_name, (
                f"Patient {p.patient_id} name '{full_name}' matches celebrity '{celeb}'"
            )


def test_patient_ids_are_opaque(fifty_profiles: list[PatientProfile]) -> None:
    """Patient IDs should not contain real names (just hex-ish codes)."""
    for p in fifty_profiles:
        # pat_ prefix + 8 hex chars
        assert re.match(r"^pat_[0-9a-f]{8}$", p.patient_id), (
            f"Unexpected patient_id format: {p.patient_id}"
        )


def test_no_real_ssn_pattern(fifty_profiles: list[PatientProfile]) -> None:
    """No SSN-like patterns (NNN-NN-NNNN) in any serialized patient data."""
    ssn_re = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    for p in fifty_profiles:
        dumped = json.dumps(p.model_dump(), default=str)
        assert not ssn_re.search(dumped), f"SSN pattern found in patient {p.patient_id}"


# ---------------------------------------------------------------------------
# 5. FHIR bundle structure
# ---------------------------------------------------------------------------


def test_fhir_bundle_written(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    """FHIR bundles are valid JSON with correct resource types."""
    from synthetic.fhir_writer import write_fhir_bundle

    fhir_patients = [p for p in fifty_profiles if p.source_format == "fhir"]
    assert len(fhir_patients) > 0, "Expected at least one FHIR-format patient"

    p = fhir_patients[0]
    bundle_path = write_fhir_bundle(p, tmp_out / "fhir")

    bundle = json.loads(bundle_path.read_text())
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "transaction"
    assert len(bundle["entry"]) > 0

    resource_types = {e["resource"]["resourceType"] for e in bundle["entry"]}
    assert "Patient" in resource_types
    assert "Condition" in resource_types
    assert "Observation" in resource_types


def test_fhir_patient_has_correct_id(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    from synthetic.fhir_writer import write_fhir_bundle

    fhir_patients = [p for p in fifty_profiles if p.source_format == "fhir"]
    p = fhir_patients[0]
    bundle_path = write_fhir_bundle(p, tmp_out / "fhir")
    bundle = json.loads(bundle_path.read_text())

    patient_entry = next(e for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient")
    assert patient_entry["resource"]["id"] == p.patient_id


# ---------------------------------------------------------------------------
# 6. HL7v2 file structure
# ---------------------------------------------------------------------------


def test_hl7_file_written(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    from synthetic.hl7_writer import write_hl7_messages

    hl7_patients = [p for p in fifty_profiles if p.source_format == "hl7v2"]
    assert len(hl7_patients) > 0, "Expected at least one HL7v2-format patient"

    p = hl7_patients[0]
    hl7_path = write_hl7_messages(p, tmp_out / "hl7v2")

    content = hl7_path.read_text()
    assert hl7_path.suffix == ".hl7"
    assert "MSH|" in content
    assert "PID|" in content
    assert "DG1|" in content


def test_hl7_pid_contains_patient_id(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    from synthetic.hl7_writer import write_hl7_messages

    hl7_patients = [p for p in fifty_profiles if p.source_format == "hl7v2"]
    p = hl7_patients[0]
    hl7_path = write_hl7_messages(p, tmp_out / "hl7v2")
    content = hl7_path.read_text()
    assert p.patient_id in content


# ---------------------------------------------------------------------------
# 7. CSV integrity
# ---------------------------------------------------------------------------


def test_csv_patients_all_present(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    import csv

    from synthetic.csv_writer import write_csv_files

    write_csv_files(fifty_profiles, tmp_out)

    csv_path = tmp_out / "csv" / "patients.csv"
    assert csv_path.exists(), "patients.csv not written"

    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        written_ids = {row["patient_id"] for row in reader}

    csv_patients = {p.patient_id for p in fifty_profiles if p.source_format == "csv"}
    assert csv_patients == written_ids, (
        f"CSV patient IDs mismatch: missing={csv_patients - written_ids}"
    )


def test_csv_observations_patient_ids(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    """All patient_ids in observations.csv must reference a known CSV patient."""
    import csv

    obs_path = tmp_out / "csv" / "observations.csv"
    if not obs_path.exists():
        pytest.skip("No CSV observations file (no CSV-format patients with labs)")

    csv_patients = {p.patient_id for p in fifty_profiles if p.source_format == "csv"}

    with obs_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            assert row["patient_id"] in csv_patients, (
                f"observations.csv has unknown patient_id: {row['patient_id']}"
            )


# ---------------------------------------------------------------------------
# 8. Notes generation (template mode)
# ---------------------------------------------------------------------------


def test_notes_written(tmp_out: Path, fifty_profiles: list[PatientProfile]) -> None:
    from synthetic.notes import generate_notes

    p = fifty_profiles[0]
    paths = generate_notes(p, tmp_out, use_llm=False, seed=42)

    assert len(paths) >= 2, f"Expected at least 2 notes, got {len(paths)}"
    for path in paths:
        assert path.exists()
        content = path.read_text()
        assert len(content) > 100, f"Note too short: {path}"


def test_notes_contain_clinical_keywords(
    tmp_out: Path, fifty_profiles: list[PatientProfile]
) -> None:
    from synthetic.notes import generate_notes

    p = fifty_profiles[0]
    paths = generate_notes(p, tmp_out, use_llm=False, seed=42)
    all_text = " ".join(path.read_text() for path in paths).lower()

    # Each note must reference the stage somewhere across the note set
    assert p.stage_at_advanced_diagnosis.lower() in all_text, (
        f"Stage {p.stage_at_advanced_diagnosis} not mentioned in notes"
    )
    assert "ecog" in all_text, "ECOG not mentioned in notes"


def test_notes_with_progression_mention_it(
    tmp_out: Path, fifty_profiles: list[PatientProfile]
) -> None:
    from synthetic.notes import generate_notes

    # Find a patient with progression
    prg_patients = [p for p in fifty_profiles if any(
        e.progression_type == "on_treatment_progression" for e in p.progression_events
    )]
    if not prg_patients:
        pytest.skip("No patients with on-treatment progression in this cohort")

    p = prg_patients[0]
    paths = generate_notes(p, tmp_out, use_llm=False, seed=42)
    all_text = " ".join(path.read_text() for path in paths).lower()
    assert "progression" in all_text, (
        "Progression not mentioned in notes for patient with progression event"
    )


# ---------------------------------------------------------------------------
# 9. Date ordering invariants
# ---------------------------------------------------------------------------


def test_advanced_date_after_or_equal_initial(fifty_profiles: list[PatientProfile]) -> None:
    """advanced_diagnosis_date >= initial_nsclc_diagnosis_date."""
    for p in fifty_profiles:
        assert p.advanced_diagnosis_date >= p.initial_nsclc_diagnosis_date, (
            f"Patient {p.patient_id}: advanced_diagnosis_date {p.advanced_diagnosis_date} "
            f"< initial_nsclc_diagnosis_date {p.initial_nsclc_diagnosis_date}"
        )


def test_death_before_or_at_cutoff(fifty_profiles: list[PatientProfile]) -> None:
    """Date of death must be ≤ data_cutoff_date."""
    for p in fifty_profiles:
        if p.vital_status == "deceased" and p.date_of_death:
            assert p.date_of_death <= DATA_CUTOFF, (
                f"Patient {p.patient_id}: date_of_death {p.date_of_death} > cutoff {DATA_CUTOFF}"
            )


def test_last_known_alive_valid(fifty_profiles: list[PatientProfile]) -> None:
    """last_known_alive_date must be ≤ data_cutoff_date for deceased patients
    and = data_cutoff_date for alive patients."""
    for p in fifty_profiles:
        if p.vital_status == "alive":
            assert p.last_known_alive_date == DATA_CUTOFF, (
                f"Patient {p.patient_id}: alive but last_known_alive "
                f"{p.last_known_alive_date} != cutoff"
            )
        elif p.vital_status == "deceased":
            assert p.last_known_alive_date <= DATA_CUTOFF, (
                f"Patient {p.patient_id}: last_known_alive_date {p.last_known_alive_date} > cutoff"
            )


def test_drug_admin_dates_after_adv_dx(fifty_profiles: list[PatientProfile]) -> None:
    """Drug administration start dates must be after advanced_diagnosis_date."""
    for p in fifty_profiles:
        for admin in p.drug_administrations:
            assert admin.start_date >= p.advanced_diagnosis_date, (
                f"Patient {p.patient_id}: drug admin {admin.medication_id} starts "
                f"{admin.start_date} before advanced_dx {p.advanced_diagnosis_date}"
            )


def test_age_at_advanced_diagnosis_consistent(fifty_profiles: list[PatientProfile]) -> None:
    """age_at_advanced_diagnosis must be ≥ 18."""
    for p in fifty_profiles:
        assert p.age_at_advanced_diagnosis >= 18, (
            f"Patient {p.patient_id}: age {p.age_at_advanced_diagnosis} < 18"
        )


# ---------------------------------------------------------------------------
# 10. Format distribution
# ---------------------------------------------------------------------------


def test_format_distribution(fifty_profiles: list[PatientProfile]) -> None:
    """All three formats must be represented."""
    fhir_n = sum(1 for p in fifty_profiles if p.source_format == "fhir")
    hl7_n = sum(1 for p in fifty_profiles if p.source_format == "hl7v2")
    csv_n = sum(1 for p in fifty_profiles if p.source_format == "csv")

    assert fhir_n >= 10, f"Too few FHIR patients: {fhir_n}"
    assert hl7_n >= 10, f"Too few HL7v2 patients: {hl7_n}"
    assert csv_n >= 10, f"Too few CSV patients: {csv_n}"
    assert fhir_n + hl7_n + csv_n == 50


def test_patient_count(fifty_profiles: list[PatientProfile]) -> None:
    assert len(fifty_profiles) == 50


# ---------------------------------------------------------------------------
# 11. Multi-line therapy (2L / 3L)
# ---------------------------------------------------------------------------


def _regimens_in_order(p: PatientProfile) -> list[tuple[str, set[str], date, date]]:
    """Return per-regimen (regimen_id, drug displays, first_start, last_start)
    ordered by first administration date."""
    by_reg: dict[str, list[date]] = {}
    drugs: dict[str, set[str]] = {}
    for a in p.drug_administrations:
        by_reg.setdefault(a.regimen_id, []).append(a.start_date)
        drugs.setdefault(a.regimen_id, set()).add(a.display)
    out = [
        (rid, drugs[rid], min(dts), max(dts)) for rid, dts in by_reg.items()
    ]
    out.sort(key=lambda r: r[2])
    return out


def test_meaningful_fraction_reach_second_line(
    two_hundred_profiles: list[PatientProfile],
) -> None:
    """Over treated patients, >25% should have >=2 distinct regimen_ids."""
    treated = [p for p in two_hundred_profiles if p.drug_administrations]
    assert treated, "Expected some treated patients"
    multi = [
        p for p in treated
        if len({a.regimen_id for a in p.drug_administrations}) >= 2
    ]
    frac = len(multi) / len(treated)
    assert frac > 0.25, f"Only {frac:.1%} of treated patients reach 2L (want >25%)"


def test_at_least_one_patient_reaches_third_line(
    two_hundred_profiles: list[PatientProfile],
) -> None:
    """At least one patient must reach 3 lines."""
    three_line = [
        p for p in two_hundred_profiles
        if len({a.regimen_id for a in p.drug_administrations}) >= 3
    ]
    assert three_line, "Expected at least one patient with >=3 lines of therapy"


def test_later_lines_use_distinct_anchor_drugs(
    two_hundred_profiles: list[PatientProfile],
) -> None:
    """Each later line's anchor regimen must introduce a drug not in any prior
    line (so the LoT engine opens a genuinely new line)."""
    for p in two_hundred_profiles:
        regs = _regimens_in_order(p)
        if len(regs) < 2:
            continue
        seen: set[str] = set(regs[0][1])
        for _rid, line_drugs, _start, _end in regs[1:]:
            assert line_drugs - seen, (
                f"Patient {p.patient_id}: later line drugs {line_drugs} "
                f"are all reused from prior lines {seen}"
            )
            seen |= line_drugs


def test_multiline_date_ordering(two_hundred_profiles: list[PatientProfile]) -> None:
    """Each later line starts strictly after the prior line's last admin, with a
    progression event recorded between them, and stays within the death/cutoff
    boundary."""
    for p in two_hundred_profiles:
        regs = _regimens_in_order(p)
        if len(regs) < 2:
            continue
        prog_dates = sorted(
            e.event_date for e in p.progression_events
            if e.progression_type == "on_treatment_progression"
        )
        boundary = p.date_of_death or p.data_cutoff_date
        for i in range(1, len(regs)):
            prev_last = regs[i - 1][3]
            cur_first = regs[i][2]
            assert cur_first > prev_last, (
                f"Patient {p.patient_id}: line {i + 1} starts {cur_first} "
                f"not after prior line last admin {prev_last}"
            )
            assert any(prev_last <= d <= cur_first for d in prog_dates), (
                f"Patient {p.patient_id}: no progression between line {i} end "
                f"{prev_last} and line {i + 1} start {cur_first}"
            )
        last_admin = max(a.start_date for a in p.drug_administrations)
        assert last_admin <= boundary, (
            f"Patient {p.patient_id}: admin {last_admin} after boundary {boundary}"
        )


def test_multiline_determinism() -> None:
    """Multi-line journeys are reproducible under the same seed."""
    a = generate_profiles(n=60, seed=7)
    b = generate_profiles(n=60, seed=7)
    for pa, pb in zip(a, b, strict=True):
        admins_a = [
            (d.regimen_id, d.display, d.start_date) for d in pa.drug_administrations
        ]
        admins_b = [
            (d.regimen_id, d.display, d.start_date) for d in pb.drug_administrations
        ]
        assert admins_a == admins_b, f"Non-deterministic journey for {pa.patient_id}"
