-- 02_staging.sql — STAGING per source × resource.
--
-- One model per (source format, resource type). Still carries per-source
-- semantics — codes, dates, units have not been canonicalized yet. The CORE
-- layer is where the Zippering engine merges these into the unified schema.
--
-- All staging models are VIEWS over RAW. The pattern is:
--   1. LATERAL FLATTEN bundle entries (FHIR) or parsed segments (HL7).
--   2. Project the resource-shaped columns with light coercion.
--
-- Keep one staging model per (source format) × (resource type) so the
-- Zippering layer can reason about source provenance per column.

USE DATABASE EHRZIPPER;
USE SCHEMA STAGING;

-- ===========================================================================
-- FHIR staging (Patient, Condition, Observation, MedicationAdministration,
-- Procedure, Encounter, DiagnosticReport).
-- ===========================================================================

CREATE OR REPLACE VIEW STAGING.FHIR_PATIENT AS
SELECT
    rb.patient_id                                        AS patient_id,
    entry.value:resource:id::STRING                      AS fhir_id,
    entry.value:resource:birthDate::STRING               AS birth_date,
    entry.value:resource:gender::STRING                  AS gender,
    entry.value:resource:deceasedBoolean::BOOLEAN        AS deceased_boolean,
    entry.value:resource:deceasedDateTime::STRING        AS deceased_datetime,
    entry.value:resource:address[0]:state::STRING        AS state_of_residence,
    entry.value:resource:extension                       AS extensions,
    rb.source_system                                     AS source_system,
    rb.loaded_at                                         AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'Patient';

CREATE OR REPLACE VIEW STAGING.FHIR_CONDITION AS
SELECT
    rb.patient_id                                                  AS patient_id,
    entry.value:resource:id::STRING                                AS fhir_id,
    entry.value:resource:code:coding[0]:code::STRING               AS condition_code,
    entry.value:resource:code:coding[0]:system::STRING             AS condition_system,
    entry.value:resource:code:coding[0]:display::STRING            AS condition_display,
    entry.value:resource:onsetDateTime::STRING                     AS onset_datetime,
    entry.value:resource:abatementDateTime::STRING                 AS abatement_datetime,
    entry.value:resource:stage                                     AS stage,
    rb.source_system                                               AS source_system,
    rb.loaded_at                                                   AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'Condition';

CREATE OR REPLACE VIEW STAGING.FHIR_OBSERVATION AS
SELECT
    rb.patient_id                                                  AS patient_id,
    entry.value:resource:id::STRING                                AS fhir_id,
    entry.value:resource:code:coding[0]:code::STRING               AS observation_code,
    entry.value:resource:code:coding[0]:system::STRING             AS observation_system,
    entry.value:resource:code:coding[0]:display::STRING            AS observation_display,
    entry.value:resource:effectiveDateTime::STRING                 AS effective_datetime,
    entry.value:resource:valueQuantity:value::FLOAT                AS value_quantity_value,
    entry.value:resource:valueQuantity:unit::STRING                AS value_quantity_unit,
    entry.value:resource:valueCodeableConcept:coding[0]:code::STRING AS value_code,
    entry.value:resource:valueString::STRING                       AS value_string,
    entry.value:resource:referenceRange[0]:low:value::FLOAT        AS reference_range_low,
    entry.value:resource:referenceRange[0]:high:value::FLOAT       AS reference_range_high,
    rb.source_system                                               AS source_system,
    rb.loaded_at                                                   AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'Observation';

CREATE OR REPLACE VIEW STAGING.FHIR_MEDICATION_ADMINISTRATION AS
SELECT
    rb.patient_id                                                       AS patient_id,
    entry.value:resource:id::STRING                                     AS fhir_id,
    entry.value:resource:medicationCodeableConcept:coding[0]:code::STRING   AS medication_code,
    entry.value:resource:medicationCodeableConcept:coding[0]:system::STRING AS medication_system,
    entry.value:resource:medicationCodeableConcept:coding[0]:display::STRING AS medication_display,
    entry.value:resource:effectivePeriod:start::STRING                  AS effective_start,
    entry.value:resource:effectivePeriod:end::STRING                    AS effective_end,
    entry.value:resource:dosage:dose:value::FLOAT                       AS dose_value,
    entry.value:resource:dosage:dose:unit::STRING                       AS dose_unit,
    entry.value:resource:dosage:route:coding[0]:code::STRING            AS route_code,
    rb.source_system                                                    AS source_system,
    rb.loaded_at                                                        AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'MedicationAdministration';

CREATE OR REPLACE VIEW STAGING.FHIR_PROCEDURE AS
SELECT
    rb.patient_id                                              AS patient_id,
    entry.value:resource:id::STRING                            AS fhir_id,
    entry.value:resource:code:coding[0]:code::STRING           AS procedure_code,
    entry.value:resource:code:coding[0]:system::STRING         AS procedure_system,
    entry.value:resource:code:coding[0]:display::STRING        AS procedure_display,
    entry.value:resource:performedDateTime::STRING             AS performed_datetime,
    entry.value:resource:bodySite[0]:coding[0]:code::STRING    AS body_site_code,
    rb.source_system                                           AS source_system,
    rb.loaded_at                                               AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'Procedure';

CREATE OR REPLACE VIEW STAGING.FHIR_ENCOUNTER AS
SELECT
    rb.patient_id                                              AS patient_id,
    entry.value:resource:id::STRING                            AS fhir_id,
    entry.value:resource:class:code::STRING                    AS encounter_class,
    entry.value:resource:period:start::STRING                  AS period_start,
    entry.value:resource:period:end::STRING                    AS period_end,
    entry.value:resource:location[0]:location:reference::STRING AS location_ref,
    rb.source_system                                           AS source_system,
    rb.loaded_at                                               AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'Encounter';

CREATE OR REPLACE VIEW STAGING.FHIR_DIAGNOSTIC_REPORT AS
SELECT
    rb.patient_id                                                 AS patient_id,
    entry.value:resource:id::STRING                               AS fhir_id,
    entry.value:resource:category[0]:coding[0]:code::STRING       AS category_code,
    entry.value:resource:effectiveDateTime::STRING                AS effective_datetime,
    entry.value:resource:presentedForm[0]:data::STRING            AS report_text_b64,
    rb.source_system                                              AS source_system,
    rb.loaded_at                                                  AS loaded_at
FROM RAW.FHIR_BUNDLE rb,
LATERAL FLATTEN(input => rb.bundle:entry) entry
WHERE entry.value:resource:resourceType::STRING = 'DiagnosticReport';

-- ===========================================================================
-- HL7v2 staging — uses the optional `parsed` VARIANT.
-- For unparsed messages, downstream tools must parse on read.
-- ===========================================================================

CREATE OR REPLACE VIEW STAGING.HL7_PATIENT AS
SELECT
    patient_id                              AS patient_id,
    parsed:PID:PID_5::STRING                AS patient_name,
    parsed:PID:PID_7::STRING                AS birth_date,
    parsed:PID:PID_8::STRING                AS administrative_sex,
    parsed:PID:PID_11:XAD_4::STRING         AS state_of_residence,
    source_system                           AS source_system,
    loaded_at                               AS loaded_at
FROM RAW.HL7_MESSAGE
WHERE message_type LIKE 'ADT%' AND parsed IS NOT NULL;

CREATE OR REPLACE VIEW STAGING.HL7_OBSERVATION AS
SELECT
    hl7.patient_id                                  AS patient_id,
    obx.value:OBX_3:CE_1::STRING                    AS observation_code,
    obx.value:OBX_3:CE_3::STRING                    AS observation_system,
    obx.value:OBX_5::STRING                         AS value_string,
    obx.value:OBX_6:CE_1::STRING                    AS value_units,
    obx.value:OBX_14::STRING                        AS effective_datetime,
    hl7.source_system                               AS source_system,
    hl7.loaded_at                                   AS loaded_at
FROM RAW.HL7_MESSAGE hl7,
LATERAL FLATTEN(input => hl7.parsed:OBX) obx
WHERE hl7.message_type LIKE 'ORU%' AND hl7.parsed IS NOT NULL;

-- ===========================================================================
-- CSV staging — projects VARIANT row payloads with the standard column names.
-- ===========================================================================

CREATE OR REPLACE VIEW STAGING.CSV_PATIENT AS
SELECT
    patient_id                          AS patient_id,
    row_data:date_of_birth::STRING           AS date_of_birth,
    row_data:sex::STRING                     AS sex,
    row_data:race::STRING                    AS race,
    row_data:ethnicity::STRING               AS ethnicity,
    row_data:state::STRING                   AS state_of_residence,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'patient';

CREATE OR REPLACE VIEW STAGING.CSV_CONDITION AS
SELECT
    patient_id                          AS patient_id,
    row_data:condition_code::STRING          AS condition_code,
    row_data:code_system::STRING             AS condition_system,
    row_data:condition_display::STRING       AS condition_display,
    row_data:onset_date::STRING              AS onset_date,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'condition';

CREATE OR REPLACE VIEW STAGING.CSV_OBSERVATION AS
SELECT
    patient_id                          AS patient_id,
    row_data:observation_code::STRING        AS observation_code,
    row_data:code_system::STRING             AS observation_system,
    row_data:value::STRING                   AS value_string,
    row_data:value_numeric::FLOAT            AS value_numeric,
    row_data:unit::STRING                    AS unit,
    row_data:observation_date::STRING        AS observation_date,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'observation';

CREATE OR REPLACE VIEW STAGING.CSV_MEDICATION_ADMINISTRATION AS
SELECT
    patient_id                          AS patient_id,
    row_data:medication_code::STRING         AS medication_code,
    row_data:code_system::STRING             AS medication_system,
    row_data:drug_name::STRING               AS drug_name,
    row_data:start_date::STRING              AS start_date,
    row_data:end_date::STRING                AS end_date,
    row_data:dose_value::FLOAT               AS dose_value,
    row_data:dose_unit::STRING               AS dose_unit,
    row_data:route::STRING                   AS route,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'medication_administration';

CREATE OR REPLACE VIEW STAGING.CSV_PROCEDURE AS
SELECT
    patient_id                          AS patient_id,
    row_data:procedure_code::STRING          AS procedure_code,
    row_data:code_system::STRING             AS procedure_system,
    row_data:procedure_date::STRING          AS procedure_date,
    row_data:body_site::STRING               AS body_site,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'procedure';

CREATE OR REPLACE VIEW STAGING.CSV_ENCOUNTER AS
SELECT
    patient_id                          AS patient_id,
    row_data:encounter_date::STRING          AS encounter_date,
    row_data:encounter_type::STRING          AS encounter_type,
    row_data:provider_specialty::STRING      AS provider_specialty,
    row_data:practice_id::STRING             AS practice_id,
    source_system                       AS source_system,
    loaded_at                           AS loaded_at
FROM RAW.CSV_ROW
WHERE source_table = 'encounter';
