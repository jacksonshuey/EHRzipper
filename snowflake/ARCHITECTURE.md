# EHRzipper Snowflake architecture

Four logical layers, Flatiron-typical:

```
RAW       — source-format-faithful landing zone
STAGING   — per-source × per-resource normalized views
CORE      — canonical zippered patient + event store
MARTS     — analytic views (cohort, LoT, rwOS)
META      — Zippering decision/audit tables (orthogonal to the data layers)
```

## Why VARIANT for FHIR

FHIR R4 Bundles are deeply nested, polymorphic, and evolve over R4 patch
versions. Loading every Bundle into `RAW.FHIR_BUNDLE.bundle VARIANT` lets us:

1. Preserve the source bytes losslessly — useful for audit and re-run.
2. Defer schema commitment to the STAGING layer. `LATERAL FLATTEN` on
   `bundle:entry` projects per-resource staging views without ever
   materializing the unnested entries to storage.
3. Add new resource types (e.g. `MolecularSequence`) by adding a new staging
   view, not by reloading raw data.

VARIANT is also the natural fit for the methodology's composite types
(`partial_date`, `coded_value`, `quantity_with_unit`) — they're stored
verbatim in CORE so the engine can round-trip a `date_of_birth` of
`{value: "1952-08", precision: "month"}` without inventing a fake day.

## Cluster-key rationale

| Table | Cluster key | Why |
|---|---|---|
| `RAW.FHIR_BUNDLE` | `(patient_id)` | Every downstream extract filters by patient. |
| `RAW.CSV_ROW` | `(patient_id, source_table)` | Same + source-table coarseness for parallel scans. |
| `CORE.PATIENT` | `(patient_id, advanced_diagnosis_date_iso)` | Cohort cuts slice by index date; `advanced_diagnosis_date_iso` is the denormalized DATE form of the partial-date VARIANT. |
| `CORE.*` event tables | `(patient_id)` | Co-locates a patient's timeline. |
| `META.ZIPPERING_DECISIONS` | `(workspace_key, pkey, source, source_column)` | Mirrors the SQLite lookup index — the active-routing query. |
| `META.ZIPPERED_SIGNALS` | `(workspace_key, pkey, occurred_at)` | Time-ordered timeline reads. |

Snowflake auto-clustering kicks in only at scale (~TB). For the portfolio
project these cluster keys are documentation + a free win when scanning
small extracts. No `ALTER TABLE … SUSPEND RECLUSTER` is necessary.

## Why no Dynamic Tables / Streams

The brief calls out portability. Dynamic Tables and Streams are Snowflake-
specific and would lock us in unnecessarily. STAGING is plain views, CORE
is plain tables, MARTS are plain views. The same schema could ship to
BigQuery / Databricks with `VARIANT → JSON / STRUCT` substitution.

A future enhancement: a stream + serverless task on `META.ZIPPERING_DECISIONS`
that fires an alert on any non-INSERT DML (UPDATE/DELETE) for defense-in-
depth. Deferred — the GRANT-based approach in P4 is simpler and equally
strong.

## Append-only enforcement (no triggers)

Snowflake has no row-level triggers. The append-only invariant on
`META.ZIPPERING_DECISIONS` is enforced by:

1. **Convention.** Documented in `CLAUDE.md`, table COMMENT, module docstring.
2. **Application.** `storage_snowflake.py::insert_decision` uses only
   `INSERT`. Unit-tested (`test_insert_decision_uses_insert_not_update`).
3. **RBAC (P4).** Grant the application role `INSERT` only:
   ```sql
   GRANT INSERT ON META.ZIPPERING_DECISIONS TO ROLE EHRZIPPER_APP;
   -- never grant UPDATE, DELETE, TRUNCATE on this table to APP
   ```

If you ever need to override a routing decision, the Zippering pattern is
to insert a **new** decision row with `decided_by = <operator_id>` and
`reason` explaining the override. Latest row by `decided_at DESC` wins.
