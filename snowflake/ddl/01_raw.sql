-- 01_raw.sql — RAW landing zone.
--
-- Source-format-faithful. No transformations beyond optional pre-parsing into
-- VARIANT for JSON-ish payloads. Bytes-in / bytes-out fidelity.
--
-- Cluster keys on (patient_id) because virtually every downstream extract
-- filters by patient. loaded_at is a secondary filter for incremental loads.

USE DATABASE EHRZIPPER;
USE SCHEMA RAW;

-- ---------------------------------------------------------------------------
-- FHIR Bundle landing — Epic, Cerner, Synthea FHIR R4 exports.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS RAW.FHIR_BUNDLE (
    patient_id    STRING       NOT NULL,
    bundle        VARIANT      NOT NULL,
    source_file   STRING,
    source_system STRING,
    loaded_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (patient_id)
COMMENT = 'Raw FHIR R4 Bundle resources. bundle is the entire Bundle JSON in VARIANT.';

-- ---------------------------------------------------------------------------
-- HL7v2 landing — pipe-delimited messages, optionally pre-parsed.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS RAW.HL7_MESSAGE (
    patient_id    STRING       NOT NULL,
    message_type  STRING       NOT NULL,                -- ADT_A01, ORU_R01, etc.
    raw_text      STRING       NOT NULL,                -- original pipe-delimited body
    parsed        VARIANT,                              -- optional pre-parsed structure
    source_system STRING,
    loaded_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (patient_id)
COMMENT = 'Raw HL7v2 messages with optional pre-parsed VARIANT for cheap downstream access.';

-- ---------------------------------------------------------------------------
-- Generic CSV row landing — flat-file extracts from legacy/registry systems.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS RAW.CSV_ROW (
    patient_id    STRING       NOT NULL,
    source_table  STRING       NOT NULL,                -- logical table name in the source
    row_data      VARIANT      NOT NULL,                -- column_name → value ("row" is reserved)
    source_system STRING,
    loaded_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (patient_id, source_table)
COMMENT = 'Raw CSV rows as VARIANT objects keyed by column name. One row per source CSV row.';
