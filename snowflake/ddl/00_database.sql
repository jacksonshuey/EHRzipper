-- 00_database.sql — EHRzipper database, warehouse, and schema bootstrap.
--
-- Idempotent. Safe to re-run.
--
-- Layering (Flatiron-typical):
--   RAW     — landing zone, source-format-faithful (FHIR JSON, HL7v2, CSV)
--   STAGING — normalized per source × resource (still per-source semantics)
--   CORE    — canonical zippered patient + event store (unified model)
--   MARTS   — analytic views (cohort flags, lines of therapy, rwOS)
--   META    — Zippering decision/audit tables (the why behind core columns)

CREATE DATABASE IF NOT EXISTS EHRZIPPER
    COMMENT = 'EHRzipper canonical oncology data store (P3). Synthetic data only.';

CREATE WAREHOUSE IF NOT EXISTS EHRZIPPER_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'XSMALL warehouse, 60s auto-suspend — minimizes trial credit burn.';

USE DATABASE EHRZIPPER;

CREATE SCHEMA IF NOT EXISTS RAW
    COMMENT = 'Source-format-faithful landing zone (FHIR bundles, HL7 messages, CSV rows).';

CREATE SCHEMA IF NOT EXISTS STAGING
    COMMENT = 'Per-source × per-resource normalized models. Still per-source semantics.';

CREATE SCHEMA IF NOT EXISTS CORE
    COMMENT = 'Canonical zippered patient + event store. The unified Flatiron-style model.';

CREATE SCHEMA IF NOT EXISTS MARTS
    COMMENT = 'Analytic views: cohort eligibility, lines of therapy, rwOS.';

CREATE SCHEMA IF NOT EXISTS META
    COMMENT = 'Zippering audit tables — decisions, schema state, global canonical columns.';
