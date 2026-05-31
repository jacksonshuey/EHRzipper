"""
Curated vocabulary: RxNorm, LOINC, ICD-10, SNOMED, ICD-O-3 codes used by the
synthetic aNSCLC patient generator.

~50 hand-curated codes covering the major NSCLC oncology concepts.
"""

from typing import Final

# ---------------------------------------------------------------------------
# ICD-10-CM — NSCLC primary diagnoses
# ---------------------------------------------------------------------------
ICD10_NSCLC: Final[dict[str, str]] = {
    "C34.10": "Malignant neoplasm of upper lobe, bronchus or lung, unspecified",
    "C34.11": "Malignant neoplasm of upper lobe, right bronchus or lung",
    "C34.12": "Malignant neoplasm of upper lobe, left bronchus or lung",
    "C34.30": "Malignant neoplasm of lower lobe, bronchus or lung, unspecified",
    "C34.31": "Malignant neoplasm of lower lobe, right bronchus or lung",
    "C34.32": "Malignant neoplasm of lower lobe, left bronchus or lung",
    "C34.90": "Malignant neoplasm of bronchus or lung, unspecified",
    "C34.91": "Malignant neoplasm of right bronchus or lung, unspecified",
    "C34.92": "Malignant neoplasm of left bronchus or lung, unspecified",
    "C78.00": "Secondary malignant neoplasm of unspecified lung",
    "C78.01": "Secondary malignant neoplasm of right lung",
    "C78.02": "Secondary malignant neoplasm of left lung",
}

ICD10_NSCLC_CODES: Final[list[str]] = list(ICD10_NSCLC.keys())

# ---------------------------------------------------------------------------
# ICD-O-3 morphology codes
# ---------------------------------------------------------------------------
ICDO3: Final[dict[str, str]] = {
    "8140/3": "Adenocarcinoma, NOS",
    "8255/3": "Adenocarcinoma with mixed subtypes",
    "8260/3": "Papillary adenocarcinoma, NOS",
    "8070/3": "Squamous cell carcinoma, NOS",
    "8071/3": "Squamous cell carcinoma, keratinizing, NOS",
    "8012/3": "Large cell carcinoma, NOS",
    "8046/3": "Non-small cell carcinoma",
    "8560/3": "Adenosquamous carcinoma",
    "8033/3": "Pseudosarcomatous carcinoma",
}

HISTOLOGY_TO_ICDO3: Final[dict[str, str]] = {
    "adenocarcinoma": "8140/3",
    "squamous_cell_carcinoma": "8070/3",
    "large_cell_carcinoma": "8012/3",
    "adenosquamous_carcinoma": "8560/3",
    "sarcomatoid_carcinoma": "8033/3",
    "nsclc_nos": "8046/3",
}

# ---------------------------------------------------------------------------
# LOINC codes
# ---------------------------------------------------------------------------
LOINC: Final[dict[str, dict[str, str]]] = {
    # CBC
    "26464-8": {"display": "Leukocytes [#/volume] in Blood", "unit": "10*3/uL"},
    "26515-7": {"display": "Platelets [#/volume] in Blood", "unit": "10*3/uL"},
    "718-7": {"display": "Hemoglobin [Mass/volume] in Blood", "unit": "g/dL"},
    "751-8": {"display": "Neutrophils [#/volume] in Blood by Automated count", "unit": "10*3/uL"},
    "777-3": {"display": "Platelets [#/volume] in Blood by Automated count", "unit": "10*3/uL"},
    # CMP
    "2160-0": {"display": "Creatinine [Mass/volume] in Serum or Plasma", "unit": "mg/dL"},
    "1742-6": {
        "display": "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma",
        "unit": "U/L",
    },
    "1751-7": {"display": "Albumin [Mass/volume] in Serum or Plasma", "unit": "g/dL"},
    "14804-9": {
        "display": "Lactate dehydrogenase [Enzymatic activity/volume] in Serum or Plasma",
        "unit": "U/L",
    },
    # Biomarkers
    "85337-4": {"display": "PD-L1 (CD274) [Presence] in Tissue by Immune stain", "unit": ""},
    "85318-4": {"display": "PD-L1 [Interpretation] in Tissue by Immune stain", "unit": ""},
    "53041-0": {
        "display": "EGFR gene mutations found [Identifier] in Blood or Tissue",
        "unit": "",
    },
    "76042-8": {"display": "ALK gene rearrangements [Presence] in Tissue by FISH", "unit": ""},
    "81202-7": {"display": "ROS1 gene rearrangements [Presence] in Tissue by FISH", "unit": ""},
    "21704-5": {
        "display": "KRAS gene mutations found [Identifier] in Blood or Tissue",
        "unit": "",
    },
    "21702-9": {
        "display": "BRAF gene mutations found [Identifier] in Blood or Tissue",
        "unit": "",
    },
    # Clinical
    "89247-1": {"display": "ECOG performance status score", "unit": ""},
    "72166-2": {"display": "Tobacco smoking status", "unit": ""},
    "8302-2": {"display": "Body height", "unit": "cm"},
    "29463-7": {"display": "Body weight", "unit": "kg"},
    "39156-5": {"display": "Body mass index (BMI) [Ratio]", "unit": "kg/m2"},
    "8663-7": {"display": "Cigarette pack-years", "unit": "{PackYears}"},
}

# ---------------------------------------------------------------------------
# RxNorm CUIs — antineoplastic agents used in NSCLC
# ---------------------------------------------------------------------------
RXNORM: Final[dict[str, dict[str, str]]] = {
    # TKIs
    "1860487": {"display": "osimertinib", "drug_class": "tki_egfr"},
    "1946821": {"display": "alectinib", "drug_class": "tki_alk"},
    "2103181": {"display": "lorlatinib", "drug_class": "tki_alk"},
    "1726289": {"display": "entrectinib", "drug_class": "tki_ros1"},
    "613391":  {"display": "crizotinib", "drug_class": "tki_ros1"},
    "2370592": {"display": "sotorasib", "drug_class": "tki_kras_g12c"},
    "2389953": {"display": "adagrasib", "drug_class": "tki_kras_g12c"},
    "704259":  {"display": "erlotinib", "drug_class": "tki_egfr"},
    "1147220": {"display": "afatinib", "drug_class": "tki_egfr"},
    # IO / checkpoint inhibitors
    "1719765": {"display": "pembrolizumab", "drug_class": "io_pd1"},
    "1812189": {"display": "nivolumab", "drug_class": "io_pd1"},
    "1791578": {"display": "atezolizumab", "drug_class": "io_pdl1"},
    "1876366": {"display": "durvalumab", "drug_class": "io_pdl1"},
    # Platinum-based chemotherapy
    "2555":    {"display": "carboplatin", "drug_class": "chemotherapy_platinum"},
    "40048":   {"display": "cisplatin", "drug_class": "chemotherapy_platinum"},
    # Taxanes
    "56946":   {"display": "paclitaxel", "drug_class": "chemotherapy_taxane"},
    "134350":  {"display": "docetaxel", "drug_class": "chemotherapy_taxane"},
    "1153654": {"display": "nab-paclitaxel", "drug_class": "chemotherapy_taxane"},
    # Pemetrexed
    "358274":  {"display": "pemetrexed", "drug_class": "chemotherapy_pemetrexed"},
    # Gemcitabine
    "72626":   {"display": "gemcitabine", "drug_class": "chemotherapy_other"},
    # Bevacizumab
    "318350":  {"display": "bevacizumab", "drug_class": "antiangiogenic"},
    # Ramucirumab (anti-angiogenic, used with docetaxel in 2L)
    "1535996": {"display": "ramucirumab", "drug_class": "antiangiogenic"},
    # Supportive
    "1008":    {"display": "dexamethasone", "drug_class": "supportive"},
    "41493":   {"display": "ondansetron", "drug_class": "supportive"},
    "41549":   {"display": "filgrastim", "drug_class": "supportive"},
}

# Drug display name → RxNorm CUI
DRUG_NAME_TO_RXNORM: Final[dict[str, str]] = {
    v["display"]: k for k, v in RXNORM.items()
}

# ---------------------------------------------------------------------------
# SNOMED CT — procedures and body sites
# ---------------------------------------------------------------------------
SNOMED_PROCEDURES: Final[dict[str, str]] = {
    "173171007": "Lobectomy of lung",
    "173171008": "Wedge resection of lung",
    "396487001": "CT-guided biopsy",
    "71388002":  "Endobronchial ultrasound-guided transbronchial needle aspiration",
    "363680008": "Radiographic imaging procedure",
    "169069000": "Radiation therapy",
}

SNOMED_BODY_SITES: Final[dict[str, str]] = {
    "44029006":  "Left lung structure",
    "3341006":   "Right lung structure",
    "368209003": "Right upper lobe of lung",
    "31094006":  "Right lower lobe of lung",
    "266005":    "Right middle lobe of lung",
    "41224006":  "Left upper lobe of lung",
    "20303001":  "Left lower lobe of lung",
    "256704008": "Mediastinum",
    "119187002": "Bone structure",
    "10200004":  "Liver structure",
    "12738006":  "Brain structure",
    "68171009":  "Adrenal gland structure",
}

# ---------------------------------------------------------------------------
# CPT — procedure codes
# ---------------------------------------------------------------------------
CPT: Final[dict[str, str]] = {
    "32480": "Lobectomy, with or without skeletonization of hilar structures",
    "32505": "Thoracotomy; with therapeutic wedge resection",
    "32408": "Core needle biopsy, lung or mediastinum, percutaneous",
    "31625": "Bronchoscopy with bronchial or endobronchial biopsy",
    "77263": "Radiation treatment planning",
    "77300": "Radiation dosimetry calculation",
    "96409": (
        "Chemotherapy administration; intravenous push technique, single or initial substance/drug"
    ),
    "96413": "Chemotherapy administration, intravenous infusion technique; up to 1 hour",
    "96415": "Chemotherapy administration, intravenous infusion technique; each additional hour",
    "99213": "Office or other outpatient visit, established patient, low complexity",
    "99214": "Office or other outpatient visit, established patient, moderate complexity",
    "99215": "Office or other outpatient visit, established patient, high complexity",
    "71250": "Computed tomography, thorax; without contrast material",
    "71260": "Computed tomography, thorax; with contrast material",
    "78816": "Positron emission tomography (PET) imaging; whole body",
    "70553": "MRI brain with and without contrast",
}

# ---------------------------------------------------------------------------
# Stage → ICD-10 secondary / metastasis codes
# ---------------------------------------------------------------------------
METASTASIS_SITES: Final[dict[str, str]] = {
    "brain": "C79.31",
    "bone": "C79.51",
    "liver": "C78.7",
    "adrenal": "C79.71",
    "lung_contralateral": "C78.02",
    "lymph_node_distant": "C77.9",
    "other": "C79.89",
}
