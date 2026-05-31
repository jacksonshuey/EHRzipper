-- 04_core.sql — CORE canonical patient + event store.
--
-- This is the unified Flatiron-style model. The Zippering engine writes here
-- after merging across sources. Every wide CORE.PATIENT row is one patient.
-- Event tables are long-format (many rows per patient).
--
-- Type strategy:
--   - Composite/precision-aware fields (partial_date, coded_value,
--     quantity_with_unit) are stored as VARIANT to preserve their shape
--     verbatim per methodology/canonical-schema.md.
--   - Simple scalars (integer, numeric, boolean, text, timestamp) use
--     native Snowflake types.
--
-- Cluster keys:
--   - Event tables: (patient_id) — virtually every analytic filters by patient.
--   - CORE.PATIENT: (patient_id, advanced_diagnosis_date) — common cohort
--     filters slice by index date; advanced_diagnosis_date is the index.
--
-- _meta_ columns: every CORE row carries provenance for the Zippering layer.
--   _meta_data_cutoff_date: when this row was extracted/zippered.
--   _meta_zippered_at:      when the Zippering engine wrote this row.
--   _meta_source_records:   list of contributing source records (audit trail).
--
-- Note: per methodology agent (open question §4), the v0.2 rename of
-- pathology_report → clinical_document is adopted here as CORE.CLINICAL_DOCUMENT.

USE DATABASE EHRZIPPER;
USE SCHEMA CORE;

-- ===========================================================================
-- CORE.PATIENT — 30 canonical patient-level fields + meta provenance
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.PATIENT (
    -- A1. Identity ---------------------------------------------------------
    patient_id                        STRING       NOT NULL,
    -- A2. Date of birth (partial_date) -------------------------------------
    date_of_birth                     VARIANT,            -- {value, precision}
    -- A3-A5. Demographics --------------------------------------------------
    sex                               STRING,             -- coded_value (enum string)
    race                              STRING,
    ethnicity                         STRING,
    -- A6-A8. Vital status / mortality --------------------------------------
    vital_status                      STRING,             -- alive | deceased | unknown
    date_of_death                     VARIANT,            -- partial_date | null
    last_known_alive_date             VARIANT,            -- partial_date
    -- A9-A11. Geography / practice -----------------------------------------
    state_of_residence                STRING,
    practice_type                     STRING,             -- community | academic | mixed | unknown
    practice_id                       STRING,
    -- A12. Smoking ---------------------------------------------------------
    smoking_status                    STRING,
    -- A13-A15. Diagnosis dates & pathway -----------------------------------
    initial_nsclc_diagnosis_date      VARIANT,            -- partial_date
    advanced_diagnosis_date           VARIANT,            -- partial_date (cluster on this)
    advanced_diagnosis_date_iso       DATE,               -- denormalized for cluster key
    advanced_diagnosis_pathway        STRING,
    -- A16-A20. Histology / stage ------------------------------------------
    histology                         STRING,
    histology_icdo3_code              VARIANT,            -- coded_value
    stage_at_initial_diagnosis        STRING,
    stage_at_advanced_diagnosis       STRING,
    ajcc_edition                      STRING,
    -- A21-A22. PS / age ----------------------------------------------------
    ecog_at_advanced_diagnosis        NUMBER(2, 0),
    age_at_advanced_diagnosis         NUMBER(3, 0),
    -- A23-A29. Biomarkers (aggregate status; per-test rows in BIOMARKER_RESULT)
    egfr_status                       STRING,
    alk_status                        STRING,
    ros1_status                       STRING,
    kras_status                       STRING,
    braf_status                       STRING,
    pdl1_status                       STRING,
    pdl1_tps_value                    NUMBER(5, 2),
    -- A30. Extraction metadata --------------------------------------------
    data_cutoff_date                  TIMESTAMP_TZ,
    -- Zippering provenance ------------------------------------------------
    _meta_data_cutoff_date            TIMESTAMP_TZ NOT NULL,
    _meta_zippered_at                 TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records              VARIANT,            -- array of {source, external_id}
    CONSTRAINT pk_core_patient PRIMARY KEY (patient_id)
)
CLUSTER BY (patient_id, advanced_diagnosis_date_iso)
COMMENT = 'Canonical wide patient row — 30 fields per methodology/canonical-schema.md §A.';

-- ===========================================================================
-- CORE.ENCOUNTER — B1
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.ENCOUNTER (
    encounter_id          STRING       NOT NULL,
    patient_id            STRING       NOT NULL,
    encounter_date        VARIANT,
    encounter_type        STRING,
    practice_id           STRING,
    provider_specialty    STRING,
    _meta_zippered_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records  VARIANT,
    CONSTRAINT pk_core_encounter PRIMARY KEY (encounter_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Canonical encounter rows. patient_id-clustered for cohort scans.';

-- ===========================================================================
-- CORE.CONDITION — B2
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.CONDITION (
    condition_id          STRING       NOT NULL,
    patient_id            STRING       NOT NULL,
    condition_code        VARIANT,     -- coded_value {code, system, display}
    onset_date            VARIANT,
    resolution_date       VARIANT,
    is_primary_cancer     BOOLEAN      NOT NULL DEFAULT FALSE,
    _meta_zippered_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records  VARIANT,
    CONSTRAINT pk_core_condition PRIMARY KEY (condition_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Canonical conditions. is_primary_cancer flags the NSCLC index dx.';

-- ===========================================================================
-- CORE.OBSERVATION — B3
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.OBSERVATION (
    observation_id           STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    observation_code         VARIANT,     -- coded_value (LOINC preferred)
    observation_date         TIMESTAMP_TZ,
    value                    VARIANT,     -- quantity_with_unit | coded_value | text
    reference_range_low      NUMBER(20, 6),
    reference_range_high     NUMBER(20, 6),
    source_system            STRING,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_observation PRIMARY KEY (observation_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Labs, vitals, ECOG, smoking snapshots. Value is VARIANT to carry quantity_with_unit.';

-- ===========================================================================
-- CORE.MEDICATION_ADMINISTRATION — B4
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.MEDICATION_ADMINISTRATION (
    medication_id            STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    medication_code          VARIANT,     -- coded_value (rxnorm | ndc | text)
    drug_class               STRING,
    start_date               VARIANT,     -- partial_date
    end_date                 VARIANT,
    dose                     VARIANT,     -- quantity_with_unit
    route                    STRING,
    regimen_id               STRING,      -- derived by LoT logic (P5)
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_medadmin PRIMARY KEY (medication_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Drug administrations. regimen_id populated by MARTS.LINES_OF_THERAPY (P5).';

-- ===========================================================================
-- CORE.PROCEDURE — B5
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.PROCEDURE (
    procedure_id             STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    procedure_code           VARIANT,
    procedure_date           VARIANT,
    procedure_category       STRING,
    body_site                VARIANT,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_procedure PRIMARY KEY (procedure_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Surgeries, biopsies, radiation events.';

-- ===========================================================================
-- CORE.BIOMARKER_RESULT — B6
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.BIOMARKER_RESULT (
    biomarker_id             STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    biomarker_name           STRING       NOT NULL,
    result                   STRING,
    result_value             VARIANT,     -- text | numeric (variant nomenclature or TPS)
    result_date              VARIANT,
    test_method              STRING,
    specimen_type            STRING,
    lab_vendor               STRING,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_biomarker PRIMARY KEY (biomarker_id)
)
CLUSTER BY (patient_id)
COMMENT = 'One row per gene per test. Aggregated into CORE.PATIENT.*_status.';

-- ===========================================================================
-- CORE.IMAGING_STUDY — B7
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.IMAGING_STUDY (
    imaging_id               STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    study_date               VARIANT,
    modality                 STRING,
    body_region              STRING,
    report_text_id           STRING,      -- FK to CORE.CLINICAL_DOCUMENT
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_imaging PRIMARY KEY (imaging_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Imaging studies. report_text_id points to a CORE.CLINICAL_DOCUMENT row.';

-- ===========================================================================
-- CORE.CLINICAL_DOCUMENT — B8 (renamed from pathology_report per methodology v0.2)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.CLINICAL_DOCUMENT (
    document_id              STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    document_date            VARIANT,
    document_type            STRING,      -- pathology | radiology | genomics | clinical_note | discharge_summary | other
    document_text            STRING,
    source_system            STRING,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_clinical_document PRIMARY KEY (document_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Unstructured/semi-structured documents — pathology, radiology, genomics, notes. (B8 renamed.)';

-- ===========================================================================
-- CORE.PROGRESSION_EVENT — B9
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.PROGRESSION_EVENT (
    progression_id           STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    event_date               VARIANT,
    progression_type         STRING,      -- to_advanced | on_treatment_progression | metastatic_recurrence
    evidence_source          STRING,      -- per Griffith et al. 2019
    new_metastatic_sites     ARRAY,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_progression PRIMARY KEY (progression_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Real-world progression events. Per Griffith et al. 2019 abstraction methodology.';

-- ===========================================================================
-- CORE.RESPONSE_ASSESSMENT — B10
-- ===========================================================================

CREATE TABLE IF NOT EXISTS CORE.RESPONSE_ASSESSMENT (
    response_id              STRING       NOT NULL,
    patient_id               STRING       NOT NULL,
    assessment_date          VARIANT,
    response                 STRING,
    regimen_id               STRING,
    assessment_basis         STRING,
    _meta_zippered_at        TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _meta_source_records     VARIANT,
    CONSTRAINT pk_core_response PRIMARY KEY (response_id)
)
CLUSTER BY (patient_id)
COMMENT = 'Clinician/RECIST response. Optional — not all patients have explicit documentation.';
