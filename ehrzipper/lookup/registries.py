"""
Static healthcare-vocabulary registries used by the deterministic lookup tier.

These are deliberately small, oncology-relevant slices — not full LOINC /
RxNorm / ICD-10 tables. The aim is a defensible match rate for the demo
(advanced NSCLC cohort) while keeping the codebase reviewable.

Schema
------
LOINC  — labs and IHC.
    Each entry: loinc_code, display, canonical_field_name, canonical_unit,
    value_type, name_aliases (substrings we'll match column names against).

RxNorm — NSCLC drugs we expect to see in `drug` columns.
    Each entry: rxnorm_cui, drug_name (generic), brand_names,
    drug_class, canonical_field_name.

ICD-10 — diagnosis codes (lung cancer + common comorbidities).
    Each entry: icd10_code, display, canonical_field_name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ehrzipper.types import ZipperingDataType


@dataclass(frozen=True)
class LoincEntry:
    loinc_code: str
    display: str
    canonical_field_name: str
    canonical_unit: str | None
    value_type: ZipperingDataType
    name_aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RxNormEntry:
    rxnorm_cui: str
    drug_name: str
    drug_class: str
    canonical_field_name: str
    brand_names: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Icd10Entry:
    icd10_code: str
    display: str
    canonical_field_name: str


# ---------------------------------------------------------------------------
# LOINC — ~25 entries covering CBC, CMP, oncology biomarkers
# ---------------------------------------------------------------------------

LOINC_REGISTRY: tuple[LoincEntry, ...] = (
    # CBC
    LoincEntry("26464-8", "White blood cell count", "wbc_count",
               "10*3/uL", "quantity_with_unit", ("wbc", "white blood")),
    LoincEntry("718-7", "Hemoglobin", "hemoglobin",
               "g/dL", "quantity_with_unit", ("hgb", "hemoglobin")),
    LoincEntry("4544-3", "Hematocrit", "hematocrit",
               "%", "quantity_with_unit", ("hct", "hematocrit")),
    LoincEntry("777-3", "Platelets", "platelet_count",
               "10*3/uL", "quantity_with_unit", ("plt", "platelet")),
    LoincEntry("751-8", "Neutrophils", "absolute_neutrophil_count",
               "10*3/uL", "quantity_with_unit", ("anc", "neutrophil")),
    LoincEntry("731-0", "Lymphocytes", "lymphocyte_count",
               "10*3/uL", "quantity_with_unit", ("lymphocyte",)),
    # CMP
    LoincEntry("2345-7", "Glucose", "glucose",
               "mg/dL", "quantity_with_unit", ("glucose",)),
    LoincEntry("2160-0", "Creatinine", "creatinine",
               "mg/dL", "quantity_with_unit", ("creatinine",)),
    LoincEntry("3094-0", "BUN", "bun",
               "mg/dL", "quantity_with_unit", ("bun",)),
    LoincEntry("2951-2", "Sodium", "sodium",
               "mEq/L", "quantity_with_unit", ("sodium", "na")),
    LoincEntry("2823-3", "Potassium", "potassium",
               "mEq/L", "quantity_with_unit", ("potassium",)),
    LoincEntry("2075-0", "Chloride", "chloride",
               "mEq/L", "quantity_with_unit", ("chloride",)),
    LoincEntry("2028-9", "CO2", "co2",
               "mEq/L", "quantity_with_unit", ("co2", "bicarbonate")),
    LoincEntry("17861-6", "Calcium", "calcium",
               "mg/dL", "quantity_with_unit", ("calcium",)),
    LoincEntry("1751-7", "Albumin", "albumin",
               "g/dL", "quantity_with_unit", ("albumin",)),
    LoincEntry("1742-6", "ALT", "alt",
               "U/L", "quantity_with_unit", ("alt", "sgpt")),
    LoincEntry("1920-8", "AST", "ast",
               "U/L", "quantity_with_unit", ("ast", "sgot")),
    LoincEntry("1975-2", "Total bilirubin", "total_bilirubin",
               "mg/dL", "quantity_with_unit", ("bilirubin",)),
    # Oncology biomarkers
    LoincEntry("85319-2", "PD-L1 tumor proportion score by IHC",
               "pdl1_tps_value", "%", "quantity_with_unit",
               ("pdl1", "pd-l1", "tps")),
    LoincEntry("48676-1", "EGFR gene mutations found", "egfr_status",
               None, "coded_value", ("egfr",)),
    LoincEntry("48570-6", "ALK gene rearrangements", "alk_status",
               None, "coded_value", ("alk",)),
    LoincEntry("82115-7", "ROS1 gene rearrangements", "ros1_status",
               None, "coded_value", ("ros1",)),
    LoincEntry("21667-1", "KRAS gene mutations", "kras_status",
               None, "coded_value", ("kras",)),
    LoincEntry("62862-8", "BRAF gene mutations", "braf_status",
               None, "coded_value", ("braf",)),
    LoincEntry("89243-0", "ECOG performance status", "ecog_at_advanced_diagnosis",
               None, "integer", ("ecog",)),
)


# ---------------------------------------------------------------------------
# RxNorm — ~30 NSCLC therapeutics + supportive agents
# ---------------------------------------------------------------------------

RXNORM_REGISTRY: tuple[RxNormEntry, ...] = (
    # EGFR TKIs
    RxNormEntry("1721560", "osimertinib", "EGFR_TKI", "drug_name", ("Tagrisso",)),
    RxNormEntry("450821",  "gefitinib",   "EGFR_TKI", "drug_name", ("Iressa",)),
    RxNormEntry("711442",  "erlotinib",   "EGFR_TKI", "drug_name", ("Tarceva",)),
    RxNormEntry("1430438", "afatinib",    "EGFR_TKI", "drug_name", ("Gilotrif",)),
    RxNormEntry("1995158", "dacomitinib", "EGFR_TKI", "drug_name", ("Vizimpro",)),
    # ALK/ROS1 TKIs
    RxNormEntry("1535467", "crizotinib",  "ALK_TKI", "drug_name", ("Xalkori",)),
    RxNormEntry("1727444", "alectinib",   "ALK_TKI", "drug_name", ("Alecensa",)),
    RxNormEntry("1925188", "lorlatinib",  "ALK_TKI", "drug_name", ("Lorbrena",)),
    RxNormEntry("1855581", "brigatinib",  "ALK_TKI", "drug_name", ("Alunbrig",)),
    RxNormEntry("1996189", "entrectinib", "ROS1_TKI", "drug_name", ("Rozlytrek",)),
    # KRAS G12C
    RxNormEntry("2569878", "sotorasib",   "KRAS_INHIBITOR", "drug_name", ("Lumakras",)),
    RxNormEntry("2641288", "adagrasib",   "KRAS_INHIBITOR", "drug_name", ("Krazati",)),
    # Immunotherapy
    RxNormEntry("1547545", "pembrolizumab", "IO", "drug_name", ("Keytruda",)),
    RxNormEntry("1597876", "nivolumab",     "IO", "drug_name", ("Opdivo",)),
    RxNormEntry("1792776", "atezolizumab",  "IO", "drug_name", ("Tecentriq",)),
    RxNormEntry("1919505", "durvalumab",    "IO", "drug_name", ("Imfinzi",)),
    RxNormEntry("1657797", "ipilimumab",    "IO", "drug_name", ("Yervoy",)),
    # Platinum doublets / chemo
    RxNormEntry("40048",   "carboplatin",   "PLATINUM", "drug_name", ("Paraplatin",)),
    RxNormEntry("2555",    "cisplatin",     "PLATINUM", "drug_name", ("Platinol",)),
    RxNormEntry("482311",  "pemetrexed",    "CHEMO", "drug_name", ("Alimta",)),
    RxNormEntry("56946",   "paclitaxel",    "CHEMO", "drug_name", ("Taxol",)),
    RxNormEntry("72962",   "docetaxel",     "CHEMO", "drug_name", ("Taxotere",)),
    RxNormEntry("12574",   "gemcitabine",   "CHEMO", "drug_name", ("Gemzar",)),
    RxNormEntry("53557",   "vinorelbine",   "CHEMO", "drug_name", ("Navelbine",)),
    # Anti-angiogenic / other
    RxNormEntry("253337",  "bevacizumab",   "VEGF", "drug_name", ("Avastin",)),
    RxNormEntry("1535996", "ramucirumab",   "VEGF", "drug_name", ("Cyramza",)),
    # BRAF + MEK combo
    RxNormEntry("1424911", "dabrafenib",    "BRAF_INHIBITOR", "drug_name", ("Tafinlar",)),
    RxNormEntry("1425099", "trametinib",    "MEK_INHIBITOR",  "drug_name", ("Mekinist",)),
    # RET / MET / EGFR-MET
    RxNormEntry("2378728", "selpercatinib", "RET_INHIBITOR", "drug_name", ("Retevmo",)),
    RxNormEntry("2374727", "capmatinib",    "MET_INHIBITOR", "drug_name", ("Tabrecta",)),
    RxNormEntry("2569870", "amivantamab",   "EGFR_MET_BISPECIFIC", "drug_name",
                ("Rybrevant",)),
)


# ---------------------------------------------------------------------------
# ICD-10 — lung cancer + common comorbidities
# ---------------------------------------------------------------------------

ICD10_REGISTRY: tuple[Icd10Entry, ...] = (
    Icd10Entry("C34.00", "Malignant neoplasm, unspecified main bronchus", "diagnosis_code"),
    Icd10Entry("C34.01", "Malignant neoplasm, right main bronchus",       "diagnosis_code"),
    Icd10Entry("C34.02", "Malignant neoplasm, left main bronchus",        "diagnosis_code"),
    Icd10Entry("C34.10", "Malignant neoplasm, upper lobe, unspecified",   "diagnosis_code"),
    Icd10Entry("C34.11", "Malignant neoplasm, upper lobe, right bronchus","diagnosis_code"),
    Icd10Entry("C34.12", "Malignant neoplasm, upper lobe, left bronchus", "diagnosis_code"),
    Icd10Entry("C34.2",  "Malignant neoplasm, middle lobe, right",        "diagnosis_code"),
    Icd10Entry("C34.3",  "Malignant neoplasm, lower lobe",                "diagnosis_code"),
    Icd10Entry("C34.90", "Malignant neoplasm, unspecified lung",          "diagnosis_code"),
    Icd10Entry("C34.91", "Malignant neoplasm, unspecified part right lung", "diagnosis_code"),
    Icd10Entry("C34.92", "Malignant neoplasm, unspecified part left lung",  "diagnosis_code"),
    # Comorbidities
    Icd10Entry("I10",    "Essential (primary) hypertension",              "comorbidity_code"),
    Icd10Entry("E11",    "Type 2 diabetes mellitus",                       "comorbidity_code"),
    Icd10Entry("J44",    "Chronic obstructive pulmonary disease (COPD)",   "comorbidity_code"),
    Icd10Entry("F32",    "Major depressive disorder, single episode",      "comorbidity_code"),
)
