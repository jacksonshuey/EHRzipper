# EHRzipper Snowflake canonical store (P3)

This directory contains the Snowflake schema and migration tooling for the
EHRzipper canonical data store. The Storage implementation that uses it lives
at `ehrzipper/storage_snowflake.py`.

## Layout

```
snowflake/
├── ddl/
│   ├── 00_database.sql   # DB + warehouse + schemas (RAW, STAGING, CORE, MARTS, META)
│   ├── 01_raw.sql        # Raw landing tables (FHIR_BUNDLE, HL7_MESSAGE, CSV_ROW)
│   ├── 02_staging.sql    # Per-source × resource staging views
│   ├── 03_meta.sql       # Zippering meta tables (port of 001_zippering_tables.sql)
│   ├── 04_core.sql       # Canonical patient + event tables
│   └── 05_marts.sql      # Analytic mart views (cohort, LoT, rwOS) — stubs
├── migrate.py            # CLI runner
└── README.md / ARCHITECTURE.md
```

## Set up

1. **Sign up for the Snowflake free trial.** Standard Edition is fine.
   Free trial includes $400 in credits over 30 days.
   https://signup.snowflake.com/

2. **Export connection env vars** (`.env` is loaded by `python-dotenv` in the engine):

   ```bash
   export SNOWFLAKE_ACCOUNT=<account-locator>      # e.g. abcd-xyz123
   export SNOWFLAKE_USER=<your-user>
   export SNOWFLAKE_PASSWORD=<password-or-PAT>
   export SNOWFLAKE_WAREHOUSE=EHRZIPPER_WH
   export SNOWFLAKE_DATABASE=EHRZIPPER
   export SNOWFLAKE_SCHEMA=META
   export SNOWFLAKE_ROLE=ACCOUNTADMIN              # for bootstrap; downgrade later
   ```

3. **Install the optional dep group.**

   ```bash
   uv sync --extra snowflake
   ```

4. **Run migrations.**

   ```bash
   python snowflake/migrate.py --up
   ```

   To tear down (destructive):

   ```bash
   python snowflake/migrate.py --down
   ```

## Cortex CLI hints

If you have the Cortex CLI installed, the migrate runner is unrelated to it —
use whichever you prefer. Useful Cortex queries against this schema:

```sql
-- Sanity check the seed
SELECT name FROM META.GLOBAL_CANONICAL_COLUMNS ORDER BY name;

-- A small fact table for cohort eligibility (stub)
SELECT COUNT(*) FROM MARTS.ANSCLC_COHORT_V1 WHERE is_eligible;
```

## Cost notes

- The XSMALL warehouse `EHRZIPPER_WH` auto-suspends after **60 seconds** of
  idle time and auto-resumes on demand. Queries pay only for active seconds.
- A full migration run uses < 1 credit-minute on the free trial.
- Staging models are **views**, not materialized tables — no storage cost.
- CORE tables are clustered on `patient_id` (and `(patient_id,
  advanced_diagnosis_date_iso)` for `CORE.PATIENT`). This is free at our
  size; Snowflake auto-clustering activates only on tables > 1 TB.

## Append-only invariant

`META.ZIPPERING_DECISIONS` is **append-only** per `CLAUDE.md`. Snowflake has
no row triggers, so enforcement is layered:

1. **DDL comment + module-level comment.** The table comment and the
   `storage_snowflake.py` docstring both call out the invariant.
2. **Application code.** `SnowflakeStorage.insert_decision` uses `INSERT`
   only. Never `UPDATE`/`MERGE`/`DELETE`. Covered by
   `tests/test_storage_snowflake_unit.py::test_insert_decision_uses_insert_not_update`.
3. **Future (P4): role grants.** The application role will hold `INSERT`
   only on `META.ZIPPERING_DECISIONS`; `UPDATE`/`DELETE` denied at the
   Snowflake RBAC layer. (Recorded as an open task; see
   `snowflake/ARCHITECTURE.md`.)

If you ever need to "redact" a decision row, follow the Zippering pattern:
**insert a new row** with `decided_by` set and `reason` explaining the
override. Never mutate the original.
