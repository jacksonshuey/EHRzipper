"""
Patient archetype generation.

Produces a fully-specified PatientProfile (Pydantic v2 model) for each
synthetic aNSCLC patient.  All clinical decisions (stage, biomarker, ECOG,
treatment, progression, vital status) are made here so the format writers
are purely serialisation logic.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from faker import Faker
from pydantic import BaseModel, Field

from synthetic.vocab import (
    HISTOLOGY_TO_ICDO3,
    ICD10_NSCLC_CODES,
    RXNORM,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rhex(rng: random.Random, n: int = 8) -> str:
    """Generate a deterministic hex string of length n using seeded rng."""
    return "".join(f"{rng.randint(0, 255):02x}" for _ in range(n // 2 + 1))[:n]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

DATA_CUTOFF: date = date(2024, 12, 31)


class DrugAdministration(BaseModel):
    medication_id: str
    rxnorm_code: str
    display: str
    drug_class: str
    start_date: date
    end_date: date | None = None
    dose_value: float
    dose_unit: str
    route: str = "intravenous"
    regimen_id: str
    cycle: int = 1


class BiomarkerResult(BaseModel):
    biomarker_id: str
    biomarker_name: str
    result: str  # positive | negative | not_tested
    result_value: str | None = None
    result_date: date
    test_method: str = "ngs"
    specimen_type: str = "tissue"
    lab_vendor: str = "Foundation Medicine"
    loinc_code: str = ""


class LabObservation(BaseModel):
    observation_id: str
    loinc_code: str
    display: str
    observation_date: date
    value: float
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None


class ProgressionEvent(BaseModel):
    progression_id: str
    event_date: date
    progression_type: str  # to_advanced | on_treatment_progression | metastatic_recurrence
    evidence_source: str = "clinician_anchored"
    new_metastatic_sites: list[str] = Field(default_factory=list)


class ImagingStudy(BaseModel):
    imaging_id: str
    study_date: date
    modality: str  # ct | pet_ct | mri | xray
    body_region: str


class Encounter(BaseModel):
    encounter_id: str
    encounter_date: date
    encounter_type: str
    provider_specialty: str = "medical_oncology"


class PatientProfile(BaseModel):
    # Identity
    patient_id: str
    practice_id: str
    practice_type: str

    # Demographics
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    race: str
    ethnicity: str
    state_of_residence: str
    street_address: str
    city: str
    zip_code: str

    # Disease
    initial_nsclc_diagnosis_date: date
    advanced_diagnosis_date: date
    advanced_diagnosis_pathway: str
    histology: str
    histology_icdo3_code: str
    stage_at_initial_diagnosis: str
    stage_at_advanced_diagnosis: str
    ajcc_edition: str = "8"
    icd10_code: str
    ecog_at_advanced_diagnosis: int
    age_at_advanced_diagnosis: int
    smoking_status: str
    pack_years: int | None = None

    # Biomarkers
    egfr_status: str
    alk_status: str
    ros1_status: str
    kras_status: str
    braf_status: str
    pdl1_status: str
    pdl1_tps_value: float | None = None

    # Outcomes
    vital_status: str
    date_of_death: date | None = None
    last_known_alive_date: date
    data_cutoff_date: date = DATA_CUTOFF

    # Events
    biomarker_results: list[BiomarkerResult] = Field(default_factory=list)
    drug_administrations: list[DrugAdministration] = Field(default_factory=list)
    progression_events: list[ProgressionEvent] = Field(default_factory=list)
    lab_observations: list[LabObservation] = Field(default_factory=list)
    imaging_studies: list[ImagingStudy] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)

    # Extra metadata for note generation
    primary_regimen_display: str | None = None
    source_format: str = "fhir"  # fhir | hl7v2 | csv


# ---------------------------------------------------------------------------
# Prevalence tables
# ---------------------------------------------------------------------------

_HISTOLOGY_WEIGHTS = [
    ("adenocarcinoma", 0.60),
    ("squamous_cell_carcinoma", 0.25),
    ("large_cell_carcinoma", 0.07),
    ("adenosquamous_carcinoma", 0.04),
    ("sarcomatoid_carcinoma", 0.02),
    ("nsclc_nos", 0.02),
]

_STAGE_ADV_WEIGHTS = [
    ("IVA", 0.45),
    ("IVB", 0.30),
    ("IIIB", 0.15),
    ("IIIC", 0.10),
]

_ECOG_WEIGHTS = [
    (0, 0.30),
    (1, 0.50),
    (2, 0.15),
    (3, 0.04),
    (4, 0.01),
]

_RACE_WEIGHTS = [
    ("white", 0.72),
    ("black_or_african_american", 0.13),
    ("asian", 0.06),
    ("other", 0.05),
    ("american_indian_or_alaska_native", 0.02),
    ("native_hawaiian_or_pacific_islander", 0.02),
]

_STATES = [
    "CA", "TX", "NY", "FL", "PA", "OH", "IL", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
    "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
]

_PRACTICES = [f"prac_{i:04d}" for i in range(1, 8)]
_PRACTICE_TYPES = ["community"] * 6 + ["academic"]


def _weighted_choice(rng: random.Random, items: list[tuple[Any, float]]) -> Any:
    population = [x for x, _ in items]
    weights = [w for _, w in items]
    return rng.choices(population, weights=weights, k=1)[0]


def _random_date_between(rng: random.Random, start: date, end: date) -> date:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=rng.randint(0, delta))


def _make_biomarker_results(
    rng: random.Random,
    egfr: str,
    alk: str,
    ros1: str,
    kras: str,
    braf: str,
    pdl1: str,
    pdl1_tps: float | None,
    adv_date: date,
) -> list[BiomarkerResult]:
    results: list[BiomarkerResult] = []
    result_date = adv_date + timedelta(days=rng.randint(5, 21))

    biomarker_loinc = {
        "egfr": "53041-0",
        "alk": "76042-8",
        "ros1": "81202-7",
        "kras": "21704-5",
        "braf": "21702-9",
        "pdl1": "85337-4",
    }

    for bm_name, status, extra in [
        ("egfr", egfr, "EGFR exon 19 deletion" if egfr == "positive" else None),
        ("alk", alk, "ALK rearrangement detected" if alk == "positive" else None),
        ("ros1", ros1, "ROS1 rearrangement detected" if ros1 == "positive" else None),
        ("kras", kras, "KRAS G12C" if kras == "positive" else None),
        ("braf", braf, "BRAF V600E" if braf == "positive" else None),
        ("pdl1", pdl1, str(round(pdl1_tps or 0)) + "%" if pdl1 != "not_tested" else None),
    ]:
        if status == "not_tested":
            continue
        method = "ihc" if bm_name == "pdl1" else "ngs"
        results.append(
            BiomarkerResult(
                biomarker_id=f"bm_{_rhex(rng)}",
                biomarker_name=bm_name,
                result=status if bm_name != "pdl1" else pdl1,
                result_value=extra,
                result_date=result_date + timedelta(days=rng.randint(0, 3)),
                test_method=method,
                specimen_type="tissue",
                lab_vendor=rng.choice([
                    "Foundation Medicine", "Caris Life Sciences", "Guardant Health"
                ]),
                loinc_code=biomarker_loinc[bm_name],
            )
        )
    return results


def _choose_regimen(
    rng: random.Random,
    egfr: str,
    alk: str,
    ros1: str,
    kras: str,
    pdl1: str,
    histology: str,
) -> list[tuple[str, str, str]]:
    """Return list of (rxnorm_code, display, drug_class) tuples for 1L regimen."""
    # Driver-directed therapy
    if egfr == "positive":
        return [("1860487", "osimertinib", "tki_egfr")]
    if alk == "positive":
        choice = rng.choice(["1946821", "2103181"])
        info = RXNORM[choice]
        return [(choice, info["display"], info["drug_class"])]
    if ros1 == "positive":
        choice = rng.choice(["1726289", "613391"])
        info = RXNORM[choice]
        return [(choice, info["display"], info["drug_class"])]

    # PD-L1 high, no driver
    if pdl1 == "high":
        return [("1719765", "pembrolizumab", "io_pd1")]

    # No driver, PD-L1 low or negative
    non_squamous = (
        "adenocarcinoma", "large_cell_carcinoma", "adenosquamous_carcinoma", "nsclc_nos"
    )
    if histology in non_squamous:
        # Carbo + pemetrexed + pembro
        return [
            ("2555", "carboplatin", "chemotherapy_platinum"),
            ("358274", "pemetrexed", "chemotherapy_pemetrexed"),
            ("1719765", "pembrolizumab", "io_pd1"),
        ]
    else:
        # Squamous: carbo + paclitaxel + pembro
        return [
            ("2555", "carboplatin", "chemotherapy_platinum"),
            ("56946", "paclitaxel", "chemotherapy_taxane"),
            ("1719765", "pembrolizumab", "io_pd1"),
        ]


def _choose_later_regimen(
    rng: random.Random,
    line: int,
    egfr: str,
    alk: str,
    ros1: str,
    kras: str,
    histology: str,
    used_drugs: set[str],
) -> list[tuple[str, str, str]] | None:
    """
    Return a clinically appropriate later-line (2L/3L) regimen for *line*, as a
    list of (rxnorm_code, display, drug_class) tuples, or ``None`` if no
    distinct regimen is available.

    Decisions are deterministic given *rng*. The returned regimen never reuses a
    drug already present in *used_drugs* (so the LoT engine sees a genuinely new
    agent and opens a new line).
    """
    non_squamous = (
        "adenocarcinoma", "large_cell_carcinoma", "adenosquamous_carcinoma", "nsclc_nos"
    )

    def _platinum_doublet() -> list[tuple[str, str, str]]:
        # Platinum + histology-appropriate partner (no IO in later-line salvage).
        partner = (
            ("358274", "pemetrexed", "chemotherapy_pemetrexed")
            if histology in non_squamous
            else ("56946", "paclitaxel", "chemotherapy_taxane")
        )
        return [("2555", "carboplatin", "chemotherapy_platinum"), partner]

    candidates: list[list[tuple[str, str, str]]] = []

    driver_positive = egfr == "positive" or alk == "positive" or ros1 == "positive"

    if driver_positive:
        # Targeted 1L (a TKI). On progression: next-gen TKI if not used, else
        # switch to platinum-doublet chemo. 3L is platinum-doublet / docetaxel.
        if egfr == "positive" and "osimertinib" not in used_drugs:
            candidates.append([("1860487", "osimertinib", "tki_egfr")])
        if alk == "positive" and "lorlatinib" not in used_drugs:
            candidates.append([("2103181", "lorlatinib", "tki_alk")])
        candidates.append(_platinum_doublet())
        candidates.append([("134350", "docetaxel", "chemotherapy_taxane")])
    elif kras == "positive":
        # KRAS G12C: 1L was chemo/IO; 2L+ may be a G12C inhibitor (realistically
        # 2L+) or single-agent docetaxel.
        candidates.append([("2370592", "sotorasib", "tki_kras_g12c")])
        candidates.append([("2389953", "adagrasib", "tki_kras_g12c")])
        candidates.append([("134350", "docetaxel", "chemotherapy_taxane")])
    else:
        # No-driver, chemo+IO / IO 1L: 2L is single-agent docetaxel, sometimes
        # docetaxel + ramucirumab.
        candidates.append([("134350", "docetaxel", "chemotherapy_taxane")])
        candidates.append([
            ("134350", "docetaxel", "chemotherapy_taxane"),
            ("1535996", "ramucirumab", "antiangiogenic"),
        ])

    # 3L+ fallbacks: gemcitabine, then platinum-doublet, then docetaxel.
    candidates.append([("72626", "gemcitabine", "chemotherapy_other")])
    candidates.append(_platinum_doublet())
    candidates.append([("134350", "docetaxel", "chemotherapy_taxane")])

    # Keep only regimens whose drugs are all new relative to prior lines, and
    # whose anchor (first) drug is itself new (so a fresh line opens).
    viable = [
        regimen
        for regimen in candidates
        if regimen[0][1] not in used_drugs
        and not all(d[1] in used_drugs for d in regimen)
    ]
    if not viable:
        return None

    # Deterministic pick weighted toward the earliest (most preferred) option.
    idx = rng.choices(
        range(len(viable)),
        weights=[max(1, len(viable) - i) for i in range(len(viable))],
        k=1,
    )[0]
    return viable[idx]


def _make_drug_administrations(
    rng: random.Random,
    regimen_drugs: list[tuple[str, str, str]],
    start_date: date,
    n_cycles: int,
    regimen_id: str,
    max_date: date = DATA_CUTOFF,
) -> list[DrugAdministration]:
    admins: list[DrugAdministration] = []
    cycle_length = 21  # days
    cap_date = min(max_date, DATA_CUTOFF)
    dose_map: dict[str, tuple[float, str]] = {
        "osimertinib": (80.0, "mg"),
        "alectinib": (600.0, "mg"),
        "lorlatinib": (100.0, "mg"),
        "entrectinib": (600.0, "mg"),
        "crizotinib": (250.0, "mg"),
        "sotorasib": (960.0, "mg"),
        "adagrasib": (400.0, "mg"),
        "pembrolizumab": (200.0, "mg"),
        "nivolumab": (480.0, "mg"),
        "carboplatin": (450.0, "mg"),
        "pemetrexed": (500.0, "mg/m2"),
        "paclitaxel": (175.0, "mg/m2"),
        "docetaxel": (75.0, "mg/m2"),
        "cisplatin": (75.0, "mg/m2"),
        "gemcitabine": (1250.0, "mg/m2"),
        "bevacizumab": (15.0, "mg/kg"),
        "nab-paclitaxel": (100.0, "mg/m2"),
        "ramucirumab": (10.0, "mg/kg"),
    }
    for cycle in range(1, n_cycles + 1):
        cycle_date = start_date + timedelta(days=(cycle - 1) * cycle_length)
        if cycle_date > cap_date:
            break
        for rxnorm_code, display, drug_class in regimen_drugs:
            oral_classes = ("tki_egfr", "tki_alk", "tki_ros1", "tki_kras_g12c")
            route = "oral" if drug_class in oral_classes else "intravenous"
            dose_v, dose_u = dose_map.get(display, (200.0, "mg"))
            admins.append(
                DrugAdministration(
                    medication_id=f"med_{_rhex(rng)}",
                    rxnorm_code=rxnorm_code,
                    display=display,
                    drug_class=drug_class,
                    start_date=cycle_date,
                    end_date=cycle_date + timedelta(days=1) if route == "intravenous" else None,
                    dose_value=dose_v,
                    dose_unit=dose_u,
                    route=route,
                    regimen_id=regimen_id,
                    cycle=cycle,
                )
            )
    return admins


def _make_lab_observations(
    rng: random.Random,
    adv_date: date,
    n_timepoints: int = 3,
) -> list[LabObservation]:
    labs: list[LabObservation] = []
    lab_specs = [
        ("26464-8", "WBC", 3.5, 11.0, 5.0, 10.5),
        ("26515-7", "Platelets", 100.0, 400.0, 150.0, 400.0),
        ("718-7", "Hemoglobin", 8.0, 17.0, 12.0, 17.5),
        ("2160-0", "Creatinine", 0.5, 2.5, 0.6, 1.2),
        ("1742-6", "ALT", 10.0, 120.0, 7.0, 56.0),
        ("1751-7", "Albumin", 2.5, 4.5, 3.5, 5.0),
    ]
    unit_map = {
        "26464-8": "10*3/uL",
        "26515-7": "10*3/uL",
        "718-7": "g/dL",
        "2160-0": "mg/dL",
        "1742-6": "U/L",
        "1751-7": "g/dL",
    }
    for tp in range(n_timepoints):
        obs_date = adv_date + timedelta(days=tp * 42 + rng.randint(-3, 3))
        if obs_date > DATA_CUTOFF:
            break
        for loinc, display, vmin, vmax, ref_lo, ref_hi in lab_specs:
            labs.append(
                LabObservation(
                    observation_id=f"obs_{_rhex(rng)}",
                    loinc_code=loinc,
                    display=display,
                    observation_date=obs_date,
                    value=round(rng.uniform(vmin, vmax), 1),
                    unit=unit_map[loinc],
                    ref_low=ref_lo,
                    ref_high=ref_hi,
                )
            )
    return labs


def _make_imaging_studies(
    rng: random.Random,
    adv_date: date,
    has_progression: bool,
    progression_date: date | None,
) -> list[ImagingStudy]:
    studies: list[ImagingStudy] = []
    # Baseline staging scan
    studies.append(
        ImagingStudy(
            imaging_id=f"img_{_rhex(rng)}",
            study_date=adv_date - timedelta(days=rng.randint(7, 21)),
            modality="pet_ct",
            body_region="whole_body",
        )
    )
    # Follow-up CT
    f1_date = adv_date + timedelta(days=rng.randint(60, 90))
    if f1_date <= DATA_CUTOFF:
        studies.append(
            ImagingStudy(
                imaging_id=f"img_{_rhex(rng)}",
                study_date=f1_date,
                modality="ct",
                body_region="chest",
            )
        )
    if has_progression and progression_date:
        prg_img = progression_date + timedelta(days=rng.randint(-7, 7))
        if prg_img > adv_date and prg_img <= DATA_CUTOFF:
            studies.append(
                ImagingStudy(
                    imaging_id=f"img_{_rhex(rng)}",
                    study_date=prg_img,
                    modality="ct",
                    body_region="chest",
                )
            )
    return studies


def _make_encounters(
    rng: random.Random,
    adv_date: date,
    n_months_follow_up: int,
) -> list[Encounter]:
    encounters: list[Encounter] = []
    # Initial consult
    encounters.append(
        Encounter(
            encounter_id=f"enc_{_rhex(rng)}",
            encounter_date=adv_date,
            encounter_type="office_visit",
            provider_specialty="medical_oncology",
        )
    )
    # Roughly monthly follow-ups
    for m in range(1, min(n_months_follow_up, 36)):
        enc_date = adv_date + timedelta(days=m * 28 + rng.randint(-5, 5))
        if enc_date > DATA_CUTOFF:
            break
        enc_type = "infusion" if rng.random() < 0.6 else "office_visit"
        encounters.append(
            Encounter(
                encounter_id=f"enc_{_rhex(rng)}",
                encounter_date=enc_date,
                encounter_type=enc_type,
            )
        )
    return encounters


# ---------------------------------------------------------------------------
# Multi-line treatment journey
# ---------------------------------------------------------------------------

_PROGRESSION_SITES = [
    "brain", "bone", "liver", "adrenal",
    "lung_contralateral", "lymph_node_distant",
]


def _build_treatment_journey(
    rng: random.Random,
    *,
    egfr: str,
    alk: str,
    ros1: str,
    kras: str,
    pdl1: str,
    histology: str,
    adv_date: date,
    timeline_end: date,
) -> tuple[list[DrugAdministration], list[ProgressionEvent], str | None, date | None]:
    """
    Build a sequential, clinically realistic treatment journey (1L → 2L → 3L).

    Each completed line (one the patient progressed off of) emits an
    ``on_treatment_progression`` event; the final line the patient is still on /
    died on does NOT. Every date is bounded by *timeline_end* (death or cutoff).

    Returns ``(drug_administrations, progression_events, primary_regimen_display,
    first_progression_date)``.
    """
    admins: list[DrugAdministration] = []
    progression_events: list[ProgressionEvent] = []
    first_progression_date: date | None = None
    primary_regimen_display: str | None = None
    used_drugs: set[str] = set()

    # 1L regimen.
    regimen_drugs: list[tuple[str, str, str]] | None = _choose_regimen(
        rng, egfr, alk, ros1, kras, pdl1, histology
    )

    line = 1
    line_start = adv_date + timedelta(days=rng.randint(14, 45))

    while regimen_drugs is not None and line <= 3:
        if line_start > timeline_end:
            break

        regimen_id = f"reg_{_rhex(rng)}_l{line}"
        n_cycles = rng.randint(4, 12)
        line_admins = _make_drug_administrations(
            rng, regimen_drugs, line_start, n_cycles, regimen_id, max_date=timeline_end
        )
        if not line_admins:
            break
        admins.extend(line_admins)
        used_drugs.update(d[1] for d in regimen_drugs)
        if line == 1:
            primary_regimen_display = " + ".join(d[1] for d in regimen_drugs)

        last_tx = max(a.start_date for a in line_admins)

        # Decide whether this line progresses (and a later line follows).
        prog_prob = 0.55 if line == 1 else 0.50
        progresses = rng.random() < prog_prob
        if not progresses:
            break

        prg_date = last_tx + timedelta(days=rng.randint(30, 120))
        # Progression must precede the timeline end with room for a next line.
        if prg_date >= timeline_end:
            break

        # Choose the next-line regimen now; if none is distinct, this line is
        # the patient's last (no terminal progression event emitted).
        next_drugs = _choose_later_regimen(
            rng, line + 1, egfr, alk, ros1, kras, histology, used_drugs
        )

        # Probability of actually starting the next line given progression.
        start_next_prob = 0.85
        start_next = next_drugs is not None and rng.random() < start_next_prob

        next_start = prg_date + timedelta(days=rng.randint(14, 42))
        if start_next and next_start > timeline_end:
            start_next = False

        if not start_next:
            # Still record progression off the final line only if the patient
            # has time left (otherwise it reads as progression-at-death noise);
            # we keep it to give rwPFS signal but cap before timeline_end.
            progression_events.append(
                ProgressionEvent(
                    progression_id=f"prg_{_rhex(rng)}",
                    event_date=prg_date,
                    progression_type="on_treatment_progression",
                    evidence_source=rng.choice(
                        ["clinician_anchored", "radiology_anchored"]
                    ),
                    new_metastatic_sites=rng.sample(
                        _PROGRESSION_SITES, k=rng.randint(1, 3)
                    ),
                )
            )
            if first_progression_date is None:
                first_progression_date = prg_date
            break

        # Emit the progression that closes this line and opens the next.
        progression_events.append(
            ProgressionEvent(
                progression_id=f"prg_{_rhex(rng)}",
                event_date=prg_date,
                progression_type="on_treatment_progression",
                evidence_source=rng.choice(["clinician_anchored", "radiology_anchored"]),
                new_metastatic_sites=rng.sample(_PROGRESSION_SITES, k=rng.randint(1, 3)),
            )
        )
        if first_progression_date is None:
            first_progression_date = prg_date

        regimen_drugs = next_drugs
        line_start = next_start
        line += 1

    return admins, progression_events, primary_regimen_display, first_progression_date


# ---------------------------------------------------------------------------
# Main profile generator
# ---------------------------------------------------------------------------

def generate_profiles(
    n: int,
    seed: int,
    source_format_distribution: list[str] | None = None,
) -> list[PatientProfile]:
    """Generate *n* synthetic PatientProfile objects deterministically from *seed*."""
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)

    if source_format_distribution is None:
        # ~17 FHIR, ~17 HL7v2, ~16 CSV out of 50
        base = n // 3
        remainder = n % 3
        source_formats = (
            ["fhir"] * (base + (1 if remainder > 0 else 0))
            + ["hl7v2"] * (base + (1 if remainder > 1 else 0))
            + ["csv"] * base
        )
        rng.shuffle(source_formats)
    else:
        source_formats = source_format_distribution

    profiles: list[PatientProfile] = []

    for i in range(n):
        # --- Demographics ---
        sex = rng.choices(["male", "female"], weights=[0.55, 0.45])[0]
        first_name = (
            fake.first_name_male() if sex == "male" else fake.first_name_female()
        )
        last_name = fake.last_name()

        # Age distribution: median ~68, range 35-90
        age = int(rng.gauss(68, 10))
        age = max(35, min(90, age))

        race = _weighted_choice(rng, _RACE_WEIGHTS)
        ethnicity = rng.choices(
            ["hispanic_or_latino", "not_hispanic_or_latino", "unknown"],
            weights=[0.12, 0.82, 0.06],
        )[0]
        state = rng.choice(_STATES)
        practice_idx = rng.randint(0, len(_PRACTICES) - 1)
        practice_id = _PRACTICES[practice_idx]
        practice_type = _PRACTICE_TYPES[practice_idx]

        # --- Disease dates ---
        # Advanced diagnosis date: 2013-2023
        adv_year = rng.randint(2013, 2022)
        adv_month = rng.randint(1, 12)
        adv_day = rng.randint(1, 28)
        adv_date = date(adv_year, adv_month, adv_day)

        dob_year = adv_year - age
        dob = date(dob_year, rng.randint(1, 12), rng.randint(1, 28))

        # Pathway: ~60% de novo advanced, ~40% progression from earlier
        adv_pathway_r = rng.random()
        if adv_pathway_r < 0.60:
            adv_pathway = "de_novo_stage_iiib_plus"
            initial_dx_date = adv_date
            stage_initial = _weighted_choice(rng, _STAGE_ADV_WEIGHTS)
        elif adv_pathway_r < 0.90:
            adv_pathway = "progression_from_earlier_stage"
            prior_months = rng.randint(6, 36)
            initial_dx_date = adv_date - timedelta(days=prior_months * 30)
            stage_initial = rng.choice(["I", "IA", "IB", "II", "IIA", "IIB", "IIIA"])
        else:
            adv_pathway = "metastatic_recurrence_after_ned"
            prior_months = rng.randint(12, 60)
            initial_dx_date = adv_date - timedelta(days=prior_months * 30)
            stage_initial = rng.choice(["I", "II", "IIA", "IIB", "IIIA"])

        stage_adv = _weighted_choice(rng, _STAGE_ADV_WEIGHTS)

        # --- Histology ---
        histology = _weighted_choice(rng, _HISTOLOGY_WEIGHTS)
        icdo3 = HISTOLOGY_TO_ICDO3[histology]

        # ICD-10 code
        icd10 = rng.choice(ICD10_NSCLC_CODES)

        # ECOG
        ecog = _weighted_choice(rng, _ECOG_WEIGHTS)

        # Smoking
        smoking_status = rng.choices(
            ["current", "former", "never", "unknown"],
            weights=[0.20, 0.55, 0.20, 0.05],
        )[0]
        pack_years: int | None = None
        if smoking_status in ("current", "former"):
            pack_years = rng.randint(5, 80)

        # --- Biomarkers ---
        # Mutually exclusive drivers (mostly)
        r = rng.random()
        if r < 0.15 and histology in ("adenocarcinoma", "nsclc_nos", "large_cell_carcinoma"):
            egfr = "positive"
        else:
            egfr = "negative"

        if egfr == "negative" and rng.random() < 0.05:  # noqa: SIM108
            alk = "positive"
        else:
            alk = "negative"

        if egfr == "negative" and alk == "negative" and rng.random() < 0.02:
            ros1 = "positive"
        else:
            ros1 = "negative"

        if egfr == "negative" and alk == "negative" and ros1 == "negative" and rng.random() < 0.25:
            kras = "positive"
        else:
            kras = "negative"

        if egfr == "negative" and rng.random() < 0.03:  # noqa: SIM108
            braf = "positive"
        else:
            braf = "negative"

        # PDL1
        pdl1_r = rng.random()
        if pdl1_r < 0.30:
            pdl1 = "high"
            pdl1_tps: float | None = round(rng.uniform(50, 100), 1)
        elif pdl1_r < 0.60:
            pdl1 = "low"
            pdl1_tps = round(rng.uniform(1, 49), 1)
        elif pdl1_r < 0.85:
            pdl1 = "negative"
            pdl1_tps = round(rng.uniform(0, 0.9), 1)
        else:
            pdl1 = "not_tested"
            pdl1_tps = None

        # Biomarker result objects
        biomarker_results = _make_biomarker_results(
            rng, egfr, alk, ros1, kras, braf, pdl1, pdl1_tps, adv_date
        )

        # --- Vital status (computed first so treatment lines respect the
        #     death/censor boundary) ---
        vital_r = rng.random()
        date_of_death: date | None = None
        follow_up_months = int((DATA_CUTOFF - adv_date).days / 30)

        if vital_r < 0.30:
            vital_status = "deceased"
            # Death 3-30 months after advanced dx, before cutoff
            death_months = rng.randint(3, min(30, follow_up_months or 3))
            date_of_death = adv_date + timedelta(days=death_months * 30)
            if date_of_death > DATA_CUTOFF:
                date_of_death = DATA_CUTOFF - timedelta(days=rng.randint(7, 60))
            last_known_alive = date_of_death
        else:
            vital_status = "alive"
            last_known_alive = DATA_CUTOFF

        # Hard upper bound for any therapy/progression date.
        timeline_end = date_of_death if date_of_death is not None else DATA_CUTOFF

        # --- Treatment & progression (multi-line) ---
        receives_treatment = rng.random() < 0.70
        drug_admins: list[DrugAdministration] = []
        progression_events: list[ProgressionEvent] = []
        progression_date: date | None = None  # first on-treatment progression
        primary_regimen_display: str | None = None

        if receives_treatment:
            drug_admins, progression_events, primary_regimen_display, progression_date = (
                _build_treatment_journey(
                    rng,
                    egfr=egfr,
                    alk=alk,
                    ros1=ros1,
                    kras=kras,
                    pdl1=pdl1,
                    histology=histology,
                    adv_date=adv_date,
                    timeline_end=timeline_end,
                )
            )

        # For pathway = progression_from_earlier_stage, add a to_advanced event
        if adv_pathway != "de_novo_stage_iiib_plus":
            progression_events.insert(
                0,
                ProgressionEvent(
                    progression_id=f"prg_{_rhex(rng)}",
                    event_date=adv_date,
                    progression_type="to_advanced",
                    evidence_source="radiology_anchored",
                    new_metastatic_sites=[],
                ),
            )

        # --- Labs ---
        n_lab_tps = 3 if receives_treatment else 1
        lab_observations = _make_lab_observations(rng, adv_date, n_lab_tps)

        # --- Imaging ---
        imaging_studies = _make_imaging_studies(
            rng, adv_date, progression_date is not None, progression_date
        )

        # --- Encounters ---
        months_fu = int((last_known_alive - adv_date).days / 30)
        encounters = _make_encounters(rng, adv_date, months_fu)

        # --- Assemble ---
        patient_id = f"pat_{_rhex(rng)}"

        profile = PatientProfile(
            patient_id=patient_id,
            practice_id=practice_id,
            practice_type=practice_type,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=dob,
            sex=sex,
            race=race,
            ethnicity=ethnicity,
            state_of_residence=state,
            street_address=fake.street_address(),
            city=fake.city(),
            zip_code=fake.zipcode(),
            initial_nsclc_diagnosis_date=initial_dx_date,
            advanced_diagnosis_date=adv_date,
            advanced_diagnosis_pathway=adv_pathway,
            histology=histology,
            histology_icdo3_code=icdo3,
            stage_at_initial_diagnosis=stage_initial,
            stage_at_advanced_diagnosis=stage_adv,
            icd10_code=icd10,
            ecog_at_advanced_diagnosis=ecog,
            age_at_advanced_diagnosis=age,
            smoking_status=smoking_status,
            pack_years=pack_years,
            egfr_status=egfr,
            alk_status=alk,
            ros1_status=ros1,
            kras_status=kras,
            braf_status=braf,
            pdl1_status=pdl1,
            pdl1_tps_value=pdl1_tps,
            vital_status=vital_status,
            date_of_death=date_of_death,
            last_known_alive_date=last_known_alive,
            biomarker_results=biomarker_results,
            drug_administrations=drug_admins,
            progression_events=progression_events,
            lab_observations=lab_observations,
            imaging_studies=imaging_studies,
            encounters=encounters,
            primary_regimen_display=primary_regimen_display,
            source_format=source_formats[i] if i < len(source_formats) else "fhir",
        )
        profiles.append(profile)

    return profiles
