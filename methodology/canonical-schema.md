# EHRzipper Canonical Schema (aNSCLC v0.1)

This document defines the canonical fields the EHRzipper reconciliation engine
targets. The schema has two layers:

- **§A. Global patient-level fields** — scalar, one row per patient. These are the columns of the wide patient cohort table.
- **§B. Longitudinal event fields** — many rows per patient. These are the long-format event tables.

The schema is the contract for everything downstream — derived variables,
dbt models, the Streamlit UI, the data dictionary. Type discipline matters:
an `ecog_at_advanced_diagnosis` field that is sometimes `0`, sometimes `"0"`,
sometimes `"ECOG 0"` is the kind of mess EHRzipper exists to fix.

## Conventions

- **Names:** snake_case, ASCII, no abbreviations except universally understood ones (ECOG, PD-L1, EGFR, ALK).
- **Dates:** all dates are either `timestamp` (full datetime with timezone, UTC at rest) or `partial_date` (object: `{ value, precision }` where `precision ∈ {day, month, year, unknown}`). Date-of-birth and date-of-death are often only known to month or year; the schema accepts that natively rather than forcing a fake day.
- **Quantities:** lab and vital values are `quantity_with_unit` (object: `{ value: numeric, unit: string }`). Each canonical lab has a declared canonical unit; the engine converts at write time (e.g., hemoglobin → g/dL).
- **Coded values:** every coded categorical field declares its controlled vocabulary inline. Sentinel for missing: `unknown`. The vocabulary always includes `unknown`.
- **FHIR alignment:** where a field maps cleanly to FHIR R4, the resource type and field path are given. Not all fields map (e.g., `practice_type`); those carry no FHIR pointer.

## Data type vocabulary

| Type | Description | Example |
|---|---|---|
| `text` | Free-text string. | `"Adenocarcinoma of the right upper lobe"` |
| `integer` | Whole number. | `67` |
| `numeric` | Real number. | `12.4` |
| `boolean` | true/false (no nulls — use a coded_value with explicit `unknown` instead when nullability matters). | `true` |
| `timestamp` | ISO 8601 UTC datetime. | `"2024-03-14T13:22:00Z"` |
| `partial_date` | Object `{ value, precision }` where precision ∈ `day`/`month`/`year`/`unknown`. | `{ "value": "1952-08", "precision": "month" }` |
| `quantity_with_unit` | Object `{ value: numeric, unit: string }` with canonical unit declared per field. | `{ "value": 12.4, "unit": "g/dL" }` |
| `coded_value` | Object `{ code, system, display }` for ICD-10/LOINC/RxNorm/SNOMED-coded fields, or a simple string drawn from a declared controlled vocabulary. | `{ "code": "C34.31", "system": "icd10cm", "display": "Right lower lobe lung cancer" }` |
| `jsonb` | Structured but open-ended; used for source provenance and rare nested structures. | `{ "source": "epic_fhir", "raw_field": "..." }` |

---

## §A. Global patient-level fields (~30)

One row per patient. These are scalar — one value per patient at the time the cohort was extracted.

Legend for "Scope":
- **G** = globally shared across all EHRzipper cohorts (would be present in a breast cancer cohort too)
- **N** = NSCLC-specific

| # | Canonical name | Type | Scope | Description | Vocabulary / Unit / Notes | Example | FHIR mapping |
|---|---|---|---|---|---|---|---|
| A1 | `patient_id` | text | G | Stable opaque patient identifier (synthetic; in real data, post-MPI). | UUIDv4 or hash. Never carries PHI. | `"pat_8f3e9c1a"` | `Patient.id` |
| A2 | `date_of_birth` | partial_date | G | Patient's date of birth, precision-aware. | Real data often only known to year/month. | `{ "value": "1952-08", "precision": "month" }` | `Patient.birthDate` |
| A3 | `sex` | coded_value | G | Sex assigned at birth (per Flatiron convention; gender identity is a separate field, deferred). | `male` \| `female` \| `unknown`. Cannot be missing per I6. | `"female"` | `Patient.gender` |
| A4 | `race` | coded_value | G | Race per US Census categories used by Flatiron. | `white` \| `black_or_african_american` \| `asian` \| `american_indian_or_alaska_native` \| `native_hawaiian_or_pacific_islander` \| `other` \| `unknown` | `"white"` | `Patient.extension[us-core-race]` |
| A5 | `ethnicity` | coded_value | G | Hispanic/Latino origin. | `hispanic_or_latino` \| `not_hispanic_or_latino` \| `unknown` | `"not_hispanic_or_latino"` | `Patient.extension[us-core-ethnicity]` |
| A6 | `vital_status` | coded_value | G | Composite vital status at data cutoff. | `alive` \| `deceased` \| `unknown` | `"deceased"` | `Patient.deceasedBoolean` |
| A7 | `date_of_death` | partial_date | G | Date of death if `vital_status = deceased`. Composite per Flatiron mortality methodology [Curtis 2018]. Null for living patients. | Precision often month or year in real data. | `{ "value": "2024-11", "precision": "month" }` | `Patient.deceasedDateTime` |
| A8 | `last_known_alive_date` | partial_date | G | Most recent date with evidence the patient was alive (last encounter, lab, med admin). Used for censoring in survival analyses. | Always populated. | `{ "value": "2025-01-14", "precision": "day" }` | (derived) |
| A9 | `state_of_residence` | coded_value | G | US state abbreviation. | `AL`..`WY` \| `unknown`. (Sub-state geography excluded for de-id.) | `"PA"` | `Patient.address.state` |
| A10 | `practice_type` | coded_value | G | Practice setting of primary oncology care. Flatiron's network is ~85% community, ~15% academic. | `community` \| `academic` \| `mixed` \| `unknown` | `"community"` | (no native FHIR) |
| A11 | `practice_id` | text | G | Opaque practice identifier. Used for site-level analyses; never identifies a real practice. | | `"prac_0042"` | `Organization.id` |
| A12 | `smoking_status` | coded_value | G | Most recent recorded smoking status. | `current` \| `former` \| `never` \| `unknown`. (Pack-years captured separately as longitudinal observation.) | `"former"` | `Observation` LOINC 72166-2 |
| A13 | `initial_nsclc_diagnosis_date` | partial_date | N | Date of first NSCLC diagnosis (any stage). | | `{ "value": "2022-03-10", "precision": "day" }` | `Condition.onsetDateTime` |
| A14 | `advanced_diagnosis_date` | partial_date | N | Index date. Earliest of: (a) NSCLC dx date if stage IIIB+; (b) progression-to-advanced date if earlier stage at initial dx. See cohort definition §5. | Always populated for cohort members. | `{ "value": "2023-06-22", "precision": "day" }` | (derived; no single FHIR field) |
| A15 | `advanced_diagnosis_pathway` | coded_value | N | How the patient entered advanced disease. | `de_novo_stage_iiib_plus` \| `progression_from_earlier_stage` \| `metastatic_recurrence_after_ned` | `"de_novo_stage_iiib_plus"` | (derived) |
| A16 | `histology` | coded_value | N | Primary NSCLC histology. ICD-O-3 morphology with display. | `adenocarcinoma` \| `squamous_cell_carcinoma` \| `large_cell_carcinoma` \| `adenosquamous_carcinoma` \| `sarcomatoid_carcinoma` \| `nsclc_nos` | `"adenocarcinoma"` | `Condition.code` (ICD-O-3) |
| A17 | `histology_icdo3_code` | coded_value | N | ICD-O-3 morphology code. | e.g., `8140/3` (adenocarcinoma), `8070/3` (squamous), `8046/3` (NSCLC NOS) | `{ "code": "8140/3", "system": "icd-o-3" }` | `Condition.code` |
| A18 | `stage_at_initial_diagnosis` | coded_value | N | AJCC stage at initial NSCLC diagnosis. | `I` \| `IA` \| `IB` \| `II` \| `IIA` \| `IIB` \| `III` \| `IIIA` \| `IIIB` \| `IIIC` \| `IV` \| `IVA` \| `IVB` \| `unknown` | `"IIIA"` | `Condition.stage` |
| A19 | `stage_at_advanced_diagnosis` | coded_value | N | AJCC stage at the advanced diagnosis date (always IIIB or later by definition). | `IIIB` \| `IIIC` \| `IVA` \| `IVB` | `"IVA"` | `Condition.stage` |
| A20 | `ajcc_edition` | coded_value | N | AJCC staging edition used. | `7` \| `8` | `"8"` | (no FHIR) |
| A21 | `ecog_at_advanced_diagnosis` | integer | N | ECOG performance status nearest to advanced diagnosis date (±30 days). Range 0–4. Null if no recording in window. | 0 = fully active; 4 = completely disabled. | `1` | `Observation` LOINC 89247-1 |
| A22 | `age_at_advanced_diagnosis` | integer | N | Age in years at advanced diagnosis date. Derived. | | `67` | (derived) |
| A23 | `egfr_status` | coded_value | N | Aggregated EGFR mutation status across all biomarker tests on file. | `positive` \| `negative` \| `equivocal` \| `not_tested` \| `pending` \| `unknown` | `"positive"` | `Observation` LOINC 53041-0 |
| A24 | `alk_status` | coded_value | N | Aggregated ALK rearrangement status. | `positive` \| `negative` \| `equivocal` \| `not_tested` \| `pending` \| `unknown` | `"negative"` | `Observation` LOINC 76042-8 |
| A25 | `ros1_status` | coded_value | N | Aggregated ROS1 rearrangement status. | same vocabulary as ALK | `"negative"` | `Observation` LOINC 81202-7 |
| A26 | `kras_status` | coded_value | N | Aggregated KRAS mutation status (any KRAS, including G12C). | `positive` \| `negative` \| `equivocal` \| `not_tested` \| `pending` \| `unknown` | `"negative"` | `Observation` LOINC 21704-5 |
| A27 | `braf_status` | coded_value | N | Aggregated BRAF mutation status (V600E and others). | same vocabulary as KRAS | `"not_tested"` | `Observation` LOINC 21702-9 |
| A28 | `pdl1_status` | coded_value | N | Aggregated PD-L1 IHC status. | `high` (TPS ≥50%) \| `low` (TPS 1–49%) \| `negative` (TPS <1%) \| `equivocal` \| `not_tested` \| `pending` \| `unknown`. Distinct from EGFR/ALK because PD-L1 is continuous and binned, not mutational. | `"high"` | `Observation` LOINC 85318-4 |
| A29 | `pdl1_tps_value` | numeric | N | PD-L1 tumor proportion score (TPS), 0–100, if available. | Percentage. | `65` | `Observation.valueQuantity` |
| A30 | `data_cutoff_date` | timestamp | G | Date this cohort row was extracted. Used as right-censoring boundary. | | `"2026-05-27T00:00:00Z"` | (extraction metadata) |

**Count: 30 global patient-level fields** (12 global-scope + 18 NSCLC-specific).

Open clinical question: should `gender_identity` be a separate field from `sex` per modern FHIR US Core? Flatiron historically uses `sex` only. Flagging for the user — see end of doc.

---

## §B. Longitudinal event fields (~10 event types)

Many rows per patient. Each event type is its own table.

### B1. `encounter`

Every clinical encounter (visit) in the EHR.

| Field | Type | Description | Vocabulary / Notes | Example | FHIR |
|---|---|---|---|---|---|
| `encounter_id` | text | Opaque encounter ID. | | `"enc_8a1c"` | `Encounter.id` |
| `patient_id` | text | FK to patient. | | | `Encounter.subject` |
| `encounter_date` | partial_date | Visit date. | | `{"value":"2024-03-14","precision":"day"}` | `Encounter.period.start` |
| `encounter_type` | coded_value | Kind of visit. | `office_visit` \| `infusion` \| `inpatient` \| `emergency` \| `telehealth` \| `other` | `"infusion"` | `Encounter.class` |
| `practice_id` | text | Site of care. | | `"prac_0042"` | `Encounter.location` |
| `provider_specialty` | coded_value | Specialty of attending. | `medical_oncology` \| `radiation_oncology` \| `surgical_oncology` \| `pulmonology` \| `primary_care` \| `other` \| `unknown` | `"medical_oncology"` | `Encounter.participant` |

### B2. `condition`

Diagnoses recorded against the patient. Includes the NSCLC diagnosis itself and comorbidities.

| Field | Type | Description | Vocabulary / Notes | Example | FHIR |
|---|---|---|---|---|---|
| `condition_id` | text | Opaque ID. | | | `Condition.id` |
| `patient_id` | text | FK. | | | `Condition.subject` |
| `condition_code` | coded_value | ICD-10 (preferred) or ICD-9, with system tag. | system ∈ `icd10cm` \| `icd9cm` \| `snomed` | `{"code":"C34.31","system":"icd10cm","display":"Malignant neoplasm of lower lobe, right bronchus or lung"}` | `Condition.code` |
| `onset_date` | partial_date | When the condition began. | Often year-precision in real data. | `{"value":"2023-06","precision":"month"}` | `Condition.onsetDateTime` |
| `resolution_date` | partial_date | When resolved, if applicable. Null for chronic. | | | `Condition.abatementDateTime` |
| `is_primary_cancer` | boolean | True iff this row is the NSCLC primary diagnosis. | | `true` | (derived flag) |

### B3. `observation`

Labs, vitals, ECOG over time, smoking history snapshots, anything that is "a measurement at a time."

| Field | Type | Description | Vocabulary / Notes | Example | FHIR |
|---|---|---|---|---|---|
| `observation_id` | text | Opaque ID. | | | `Observation.id` |
| `patient_id` | text | FK. | | | `Observation.subject` |
| `observation_code` | coded_value | LOINC code preferred. | system ∈ `loinc` \| `snomed` \| `custom` | `{"code":"718-7","system":"loinc","display":"Hemoglobin"}` | `Observation.code` |
| `observation_date` | timestamp | When the measurement was taken (preferred) or resulted. | Full datetime when available. | `"2024-04-02T09:14:00Z"` | `Observation.effectiveDateTime` |
| `value` | quantity_with_unit \| coded_value \| text | Result. Type depends on observation. | Canonical units enforced (e.g., hemoglobin g/dL, creatinine mg/dL, ECOG integer 0-4, smoking status enum). | `{"value":12.4,"unit":"g/dL"}` | `Observation.valueQuantity` / `.valueCodeableConcept` / `.valueString` |
| `reference_range_low` | numeric | Low end of normal, if applicable. | | `12.0` | `Observation.referenceRange.low` |
| `reference_range_high` | numeric | High end of normal. | | `15.5` | `Observation.referenceRange.high` |
| `source_system` | text | Originating EHR/lab system. | | `"epic_fhir"` | (provenance) |

Canonical observation list seeded for v0.1: hemoglobin (LOINC 718-7, g/dL), platelet count (LOINC 777-3, 10^9/L), absolute neutrophil count (LOINC 751-8, 10^9/L), serum creatinine (LOINC 2160-0, mg/dL), albumin (LOINC 1751-7, g/dL), LDH (LOINC 14804-9, U/L), ECOG (LOINC 89247-1, integer 0-4), height (LOINC 8302-2, cm), weight (LOINC 29463-7, kg), BMI (LOINC 39156-5, kg/m²), pack-years (LOINC 8663-7, integer).

### B4. `medication_administration`

Every administration of an antineoplastic agent or relevant supportive med. Distinct from prescriptions — this is "drug actually given."

| Field | Type | Description | Vocabulary / Notes | Example | FHIR |
|---|---|---|---|---|---|
| `medication_id` | text | Opaque ID per administration. | | | `MedicationAdministration.id` |
| `patient_id` | text | FK. | | | `MedicationAdministration.subject` |
| `medication_code` | coded_value | RxNorm preferred, then NDC, then text. | system ∈ `rxnorm` \| `ndc` \| `text` | `{"code":"1719765","system":"rxnorm","display":"pembrolizumab"}` | `MedicationAdministration.medicationCodeableConcept` |
| `drug_class` | coded_value | Normalized drug class. | `chemotherapy_platinum` \| `chemotherapy_taxane` \| `chemotherapy_pemetrexed` \| `io_pd1` \| `io_pdl1` \| `io_ctla4` \| `tki_egfr` \| `tki_alk` \| `tki_ros1` \| `tki_kras_g12c` \| `tki_other` \| `antiangiogenic` \| `radiation` \| `supportive` \| `other` | `"io_pd1"` | (derived) |
| `start_date` | partial_date | Start of administration. | | `{"value":"2024-04-02","precision":"day"}` | `.effectivePeriod.start` |
| `end_date` | partial_date | End of administration. Null if ongoing. | | `{"value":"2024-04-02","precision":"day"}` | `.effectivePeriod.end` |
| `dose` | quantity_with_unit | Administered dose. | Canonical units: mg, mg/kg, mg/m², or g. | `{"value":200,"unit":"mg"}` | `.dosage.dose` |
| `route` | coded_value | Route of administration. | `intravenous` \| `oral` \| `subcutaneous` \| `intramuscular` \| `other` \| `unknown` | `"intravenous"` | `.dosage.route` |
| `regimen_id` | text | FK to the line-of-therapy regimen this admin belongs to (assigned by the LoT derivation, not source data). | | `"reg_8f3e_l1"` | (derived) |

### B5. `procedure`

Surgeries, biopsies, radiation events, ports, thoracenteses.

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `procedure_id` | text | Opaque ID. | | | `Procedure.id` |
| `patient_id` | text | FK. | | | `Procedure.subject` |
| `procedure_code` | coded_value | CPT / HCPCS / SNOMED. | system ∈ `cpt` \| `hcpcs` \| `snomed` | `{"code":"32480","system":"cpt","display":"Lobectomy"}` | `Procedure.code` |
| `procedure_date` | partial_date | Date performed. | | | `Procedure.performedDateTime` |
| `procedure_category` | coded_value | Normalized category. | `surgery` \| `biopsy` \| `radiation` \| `vascular_access` \| `imaging_guided` \| `other` | `"surgery"` | (derived) |
| `body_site` | coded_value | Anatomic site if relevant. | SNOMED preferred. | `"lung_upper_lobe_right"` | `Procedure.bodySite` |

### B6. `biomarker_result`

Discrete biomarker test results. One row per gene per test (EGFR positive on date X, ALK negative on date X, PD-L1 TPS 65% on date Y, etc.).

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `biomarker_id` | text | Opaque ID. | | | `Observation.id` |
| `patient_id` | text | FK. | | | `Observation.subject` |
| `biomarker_name` | coded_value | Which gene/protein tested. | `egfr` \| `alk` \| `ros1` \| `kras` \| `kras_g12c` \| `braf` \| `met` \| `ret` \| `erbb2` \| `ntrk` \| `pdl1` \| `tmb` \| `msi` \| `other` | `"egfr"` | `Observation.code` |
| `result` | coded_value | Result categorical. | `positive` \| `negative` \| `equivocal` \| `pending` \| `unsuccessful` \| `unknown`. For PD-L1, also accepts `high`/`low`/`negative` binning. | `"positive"` | `Observation.valueCodeableConcept` |
| `result_value` | text \| numeric | Specific variant (e.g., "EGFR exon 19 deletion") or numeric TPS for PD-L1. | Free text for variant nomenclature; numeric for TPS/TMB. | `"EGFR exon 19 deletion"` | `Observation.valueString` / `.valueQuantity` |
| `result_date` | partial_date | Date the result was finalized. Required (no missing date) per Flatiron exclusion E-biomarker. | | `{"value":"2023-07-05","precision":"day"}` | `Observation.effectiveDateTime` |
| `test_method` | coded_value | Assay technology. | `ngs` \| `pcr` \| `fish` \| `ihc` \| `sanger` \| `other` \| `unknown` | `"ngs"` | (custom) |
| `specimen_type` | coded_value | Tissue or liquid. | `tissue` \| `liquid_biopsy` \| `cytology` \| `other` \| `unknown` | `"tissue"` | `Specimen.type` |
| `lab_vendor` | text | Vendor (Foundation, Caris, Guardant, etc.). Free text — controlled list deferred. | | `"Foundation Medicine"` | (custom) |

### B7. `imaging_study`

CT, MRI, PET, X-ray studies. Carries a pointer to a (possibly unstructured) report; the structured fields are limited.

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `imaging_id` | text | Opaque ID. | | | `ImagingStudy.id` |
| `patient_id` | text | FK. | | | `ImagingStudy.subject` |
| `study_date` | partial_date | When scan was performed. | | | `ImagingStudy.started` |
| `modality` | coded_value | Imaging type. | `ct` \| `mri` \| `pet` \| `pet_ct` \| `xray` \| `ultrasound` \| `bone_scan` \| `other` | `"ct"` | `ImagingStudy.modality` |
| `body_region` | coded_value | Region scanned. | `chest` \| `abdomen_pelvis` \| `brain` \| `whole_body` \| `bone` \| `other` | `"chest"` | (custom) |
| `report_text_id` | text | Pointer to the unstructured `pathology_report` table row (poorly named; renaming to `clinical_document` planned — open question §4). | | | `DiagnosticReport.id` |

### B8. `pathology_report`

Unstructured or semi-structured pathology and imaging interpretation reports. The abstraction layer's primary input.

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `report_id` | text | Opaque ID. | | | `DiagnosticReport.id` |
| `patient_id` | text | FK. | | | `DiagnosticReport.subject` |
| `report_date` | partial_date | Date report was finalized. | | | `DiagnosticReport.effectiveDateTime` |
| `report_type` | coded_value | Kind of report. | `pathology` \| `radiology` \| `genomics` \| `clinical_note` \| `discharge_summary` \| `other` | `"pathology"` | `DiagnosticReport.category` |
| `report_text` | text | Full free-text body of the report. PHI-free (synthetic). | | (long string) | `DiagnosticReport.presentedForm` |
| `source_system` | text | Originating EHR. | | `"epic_fhir"` | (provenance) |

### B9. `progression_event`

Real-world progression events. Distinguishes the cohort-anchoring transition to advanced disease (`to_advanced`) from in-cohort progressions used in TTNT and downstream rwPFS analyses.

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `progression_id` | text | Opaque ID. | | | (no native FHIR — custom) |
| `patient_id` | text | FK. | | | |
| `event_date` | partial_date | Date progression was documented. | | | |
| `progression_type` | coded_value | Kind of progression event. | `to_advanced` (earlier-stage → advanced; defines advanced_diagnosis_date for non-de-novo patients) \| `on_treatment_progression` (in-cohort progression while on a regimen) \| `metastatic_recurrence` (recurrence after NED) | `"on_treatment_progression"` | |
| `evidence_source` | coded_value | How progression was established (per Griffith et al. 2019 methodology). | `radiology_anchored` \| `clinician_anchored` \| `recist_documented` \| `pathology_confirmed` \| `mixed` | `"clinician_anchored"` | |
| `new_metastatic_sites` | coded_value[] | New sites of disease at this event. | array of: `brain` \| `bone` \| `liver` \| `adrenal` \| `lung_contralateral` \| `lymph_node_distant` \| `other` | `["brain"]` | |

### B10. `response_assessment`

Clinician-assessed response per encounter. Optional (not all patients have explicit response documentation outside of trials). Mirrors RECIST categories but does not require true RECIST measurement.

| Field | Type | Description | Vocabulary | Example | FHIR |
|---|---|---|---|---|---|
| `response_id` | text | Opaque ID. | | | |
| `patient_id` | text | FK. | | | |
| `assessment_date` | partial_date | Date of assessment. | | | |
| `response` | coded_value | Response category. | `complete_response` \| `partial_response` \| `stable_disease` \| `progressive_disease` \| `not_evaluable` \| `unknown` | `"partial_response"` | |
| `regimen_id` | text | Regimen the response was assessed against. | FK to LoT regimen. | `"reg_8f3e_l1"` | |
| `assessment_basis` | coded_value | What the assessment was based on. | `recist_1_1` \| `imaging_clinician_interpretation` \| `clinician_overall_assessment` \| `unknown` | `"imaging_clinician_interpretation"` | |

---

## Summary counts

- **Global patient-level fields (§A): 30** — 12 global-scope, 18 NSCLC-specific
- **Longitudinal event types (§B): 10** — `encounter`, `condition`, `observation`, `medication_administration`, `procedure`, `biomarker_result`, `imaging_study`, `pathology_report`, `progression_event`, `response_assessment`

## Open clinical questions (flagged for user)

1. **`sex` vs. `gender_identity`.** Modern FHIR US Core distinguishes `sex` (assigned at birth) from `gender_identity`. Flatiron historically uses one `sex` field. Recommendation: keep one field as `sex` for v0.1, document the limitation, plan a `gender_identity` extension in v0.2. Confirm with user.
2. **AJCC edition handling.** Real Flatiron data includes both 7th and 8th edition staging depending on year. EHRzipper generates synthetic data exclusively in 8th edition for v0.1. Should the engine demonstrate 7th-to-8th edition mapping? Adds value as a reconciliation showcase; adds scope.
3. **Real-world progression endpoint.** Two valid abstraction approaches per Griffith et al. 2019 [8]: radiology-anchored vs. clinician-anchored. Currently the schema supports both via `evidence_source`. The derived-variable layer needs a policy decision on which is authoritative when both exist. Suggest: clinician-anchored as primary, radiology-anchored as supporting.
4. **`pathology_report` table is misnamed** — it now houses pathology, radiology, genomics, and clinical notes. Recommend renaming to `clinical_document` in v0.2 with a `report_type` discriminator (already present in the schema).
5. **PD-L1 binning thresholds.** v0.1 uses Flatiron-aligned bins (high ≥50%, low 1–49%, negative <1%). Some sponsors use different thresholds (e.g., 22C3 vs. SP263 assay differences). Holding to TPS-based bins for v0.1; assay-specific binning deferred.
6. **`drug_class` taxonomy.** The list in B4 is hand-curated to cover NSCLC 1L/2L+ regimens through 2026. Will need expansion for KRAS G12C combos, bispecifics, antibody-drug conjugates as they enter standard of care. Schema is open to additions; no breaking change.
