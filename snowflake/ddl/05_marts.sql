-- 05_marts.sql — analytic mart views.
--
-- These are PLACEHOLDERS. Full methodology lives in methodology/ and the
-- complete implementations land in P5. Each view selects the structural
-- skeleton so downstream tooling (Streamlit cohort builder, dbt-style
-- testing) can reference them today.
--
-- All views are CREATE OR REPLACE — re-running migrate is safe.

USE DATABASE EHRZIPPER;
USE SCHEMA MARTS;

-- ===========================================================================
-- MARTS.ANSCLC_COHORT_V1 — eligibility flags per methodology/cohort-definition.md
--
-- Each row is one patient with boolean inclusion/exclusion flags. The final
-- `is_eligible` column is the AND of all inclusions and the negation of all
-- exclusions. Placeholder logic — refined in P5.
-- ===========================================================================

CREATE OR REPLACE VIEW MARTS.ANSCLC_COHORT_V1 AS
SELECT
    p.patient_id,
    p.advanced_diagnosis_date_iso,
    p.histology,
    p.stage_at_advanced_diagnosis,
    -- Inclusions (placeholders)
    (p.histology IN (
        'adenocarcinoma', 'squamous_cell_carcinoma', 'large_cell_carcinoma',
        'adenosquamous_carcinoma', 'sarcomatoid_carcinoma', 'nsclc_nos'
    ))                                                       AS inc_nsclc_histology,
    (p.stage_at_advanced_diagnosis IN ('IIIB', 'IIIC', 'IVA', 'IVB'))
                                                             AS inc_advanced_stage,
    (p.advanced_diagnosis_date IS NOT NULL)                  AS inc_has_index_date,
    -- Exclusions (placeholders — extend in P5)
    FALSE                                                    AS exc_no_post_index_followup,
    FALSE                                                    AS exc_clinical_trial_only,
    -- Final eligibility (refined in P5)
    (
        p.histology IS NOT NULL
        AND p.stage_at_advanced_diagnosis IN ('IIIB', 'IIIC', 'IVA', 'IVB')
        AND p.advanced_diagnosis_date IS NOT NULL
    )                                                        AS is_eligible
FROM CORE.PATIENT p;

-- ===========================================================================
-- MARTS.LINES_OF_THERAPY — derived regimen lines.
--
-- STUB. Real logic (per Flatiron LoT methodology) requires gap rules,
-- regimen-equivalence rules, and progression-anchoring. Lives in P5.
-- For now: one row per (patient, drug_class, start_date) so downstream
-- code can reference the table shape.
--
-- Implements methodology/derived-variables.md §1. CORE date columns are
-- precision-aware VARIANT partial_dates ({value, precision}); MARTS.RESOLVE_DATE
-- (below) collapses them to a DATE using the same day-15 / July-1 assumptions
-- as the Python engine.
--
-- The authoritative, fully-featured derivation (maintenance detection,
-- progression anchoring, end-reason attribution) lives in the Python engine
-- (derived/lot.py), which is intended to materialize regimen_id back onto
-- CORE.MEDICATION_ADMINISTRATION. This SQL view implements the same line/gap/
-- combination logic at warehouse scale using a window-function sessionization:
--   1. resolve each administration to a DATE;
--   2. order administrations per patient;
--   3. open a new line when the gap to the prior administration exceeds
--      gap_threshold_days AND a not-previously-seen drug is introduced, or a
--      progression event sits between the prior admin and this one;
--   4. number the resulting sessions 1..n per patient.
-- ===========================================================================

-- Helper: resolve a partial_date VARIANT to a DATE with documented assumptions.
CREATE OR REPLACE FUNCTION MARTS.RESOLVE_DATE("PD" VARIANT)
RETURNS DATE
LANGUAGE SQL
COMMENT = 'Collapse a partial_date {value, precision} to a DATE. month→day 15, year→Jul 1.'
AS
$$
    CASE
        WHEN PD IS NULL OR PD:value IS NULL THEN NULL
        WHEN LENGTH(PD:value::STRING) >= 10 THEN TRY_TO_DATE(LEFT(PD:value::STRING, 10))
        WHEN LENGTH(PD:value::STRING) = 7  THEN TRY_TO_DATE(PD:value::STRING || '-15', 'YYYY-MM-DD')
        WHEN LENGTH(PD:value::STRING) = 4  THEN TRY_TO_DATE(PD:value::STRING || '-07-01', 'YYYY-MM-DD')
        ELSE TRY_TO_DATE(PD:value::STRING)
    END
$$;

CREATE OR REPLACE VIEW MARTS.LINES_OF_THERAPY AS
WITH admin AS (
    SELECT
        m.patient_id,
        m.medication_id,
        m.medication_code:display::STRING               AS drug_name,
        m.drug_class,
        MARTS.RESOLVE_DATE(m.start_date)                AS start_dt,
        COALESCE(MARTS.RESOLVE_DATE(m.end_date),
                 MARTS.RESOLVE_DATE(m.start_date))      AS end_dt
    FROM CORE.MEDICATION_ADMINISTRATION m
    WHERE MARTS.RESOLVE_DATE(m.start_date) IS NOT NULL
),
prog AS (
    SELECT patient_id, MARTS.RESOLVE_DATE(event_date) AS prog_dt
    FROM CORE.PROGRESSION_EVENT
    WHERE progression_type <> 'to_advanced'
      AND MARTS.RESOLVE_DATE(event_date) IS NOT NULL
),
lagged AS (
    -- Materialize the LAG first; a window function cannot live inside the
    -- correlated subquery below (Snowflake rejects window+correlation).
    SELECT
        a.*,
        LAG(a.start_dt) OVER (PARTITION BY a.patient_id ORDER BY a.start_dt, a.drug_name)
            AS prev_start,
        -- New drug not seen earlier in this patient's timeline?
        CASE WHEN a.drug_name NOT IN (
                SELECT b.drug_name FROM admin b
                WHERE b.patient_id = a.patient_id AND b.start_dt < a.start_dt
             ) THEN 1 ELSE 0 END                         AS is_new_drug
    FROM admin a
),
flagged AS (
    SELECT
        l.*,
        -- Any progression between the prior admin (plain column now) and this one?
        CASE WHEN EXISTS (
                SELECT 1 FROM prog p
                WHERE p.patient_id = l.patient_id
                  AND p.prog_dt <= l.start_dt
                  AND p.prog_dt > COALESCE(l.prev_start, DATE '1900-01-01')
             ) THEN 1 ELSE 0 END                         AS progressed_since_prev
    FROM lagged l
),
sessionized AS (
    SELECT
        f.*,
        -- A new line opens when: progression precedes a new drug, OR a >90d
        -- gap precedes a new drug (rules 1 & 3 of the methodology).
        CASE
            WHEN f.prev_start IS NULL THEN 1
            WHEN f.is_new_drug = 1 AND f.progressed_since_prev = 1 THEN 1
            WHEN f.is_new_drug = 1 AND DATEDIFF('day', f.prev_start, f.start_dt) > 90 THEN 1
            ELSE 0
        END                                              AS line_break
    FROM flagged f
),
numbered AS (
    SELECT
        s.*,
        SUM(s.line_break) OVER (
            PARTITION BY s.patient_id ORDER BY s.start_dt, s.drug_name
            ROWS UNBOUNDED PRECEDING)                    AS line_number
    FROM sessionized s
)
SELECT
    patient_id,
    line_number,
    MIN(start_dt)                                        AS line_start_date,
    MAX(end_dt)                                          AS line_end_date,
    ARRAY_AGG(DISTINCT drug_name) WITHIN GROUP (ORDER BY drug_name) AS drugs,
    ARRAY_AGG(DISTINCT drug_class) WITHIN GROUP (ORDER BY drug_class) AS drug_classes,
    COUNT(*)                                             AS n_administrations
FROM numbered
GROUP BY patient_id, line_number;

-- ===========================================================================
-- MARTS.RWOS — real-world overall survival.
--
-- Implements methodology/derived-variables.md §2. Index = advanced diagnosis
-- date; event = death (date_of_death); censor = last_known_alive_date.
-- os_days is the basis for the Kaplan-Meier fit (computed client-side in
-- derived/km.py or by a downstream SQL/Snowpark step).
-- ===========================================================================

CREATE OR REPLACE VIEW MARTS.RWOS AS
WITH resolved AS (
    SELECT
        p.patient_id,
        p.vital_status,
        MARTS.RESOLVE_DATE(p.advanced_diagnosis_date)    AS index_dt,
        MARTS.RESOLVE_DATE(p.date_of_death)              AS death_dt,
        MARTS.RESOLVE_DATE(p.last_known_alive_date)      AS last_alive_dt,
        p.advanced_diagnosis_date:precision::STRING      AS index_precision,
        p.age_at_advanced_diagnosis
    FROM CORE.PATIENT p
)
SELECT
    patient_id,
    index_dt                                             AS index_date,
    index_precision,
    vital_status,
    age_at_advanced_diagnosis                            AS age_at_index,
    CASE WHEN vital_status = 'deceased' AND death_dt IS NOT NULL
         THEN death_dt ELSE last_alive_dt END            AS event_date,
    CASE WHEN vital_status = 'deceased' AND death_dt IS NOT NULL
         THEN 1 ELSE 0 END                               AS event,
    GREATEST(
        DATEDIFF('day', index_dt,
            CASE WHEN vital_status = 'deceased' AND death_dt IS NOT NULL
                 THEN death_dt ELSE last_alive_dt END),
        0)                                               AS os_days,
    ROUND(GREATEST(
        DATEDIFF('day', index_dt,
            CASE WHEN vital_status = 'deceased' AND death_dt IS NOT NULL
                 THEN death_dt ELSE last_alive_dt END),
        0) / 30.4375, 2)                                 AS rwos_months,
    (vital_status = 'deceased' AND death_dt IS NOT NULL) AS event_observed
FROM resolved
WHERE index_dt IS NOT NULL
  AND (CASE WHEN vital_status = 'deceased' AND death_dt IS NOT NULL
            THEN death_dt ELSE last_alive_dt END) IS NOT NULL;
