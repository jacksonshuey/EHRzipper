-- 03_meta.sql — Zippering meta tables (META schema).
--
-- Port of ehrzipper/migrations/001_zippering_tables.sql to Snowflake.
-- Mirrors the canonical schema of the generic zipper engine
-- (https://github.com/jacksonshuey/zipper).
--
-- Snowflake type mapping:
--   uuid           → STRING (UUIDs generated in Python and passed in)
--   text[]         → ARRAY  (Snowflake native)
--   jsonb          → VARIANT
--   timestamptz    → TIMESTAMP_TZ
--   gen_random_uuid → UUID_STRING() default (Snowflake)
--   now()          → CURRENT_TIMESTAMP()
--
-- APPEND-ONLY INVARIANT (zippering_decisions):
--   Snowflake does not support row-level triggers. The invariant is enforced
--   by three layers:
--     1. Convention + comment on the table.
--     2. Application: storage_snowflake.py uses INSERT only, never UPDATE/MERGE.
--     3. Optional defense-in-depth: a stream + serverless task could detect
--        any UPDATE/DELETE on this table and emit an alert (deferred — see
--        snowflake/ARCHITECTURE.md). For P3 we rely on (1) + (2).
--   Grants pattern (future P4): GRANT INSERT only on META.ZIPPERING_DECISIONS
--   to the application role; deny UPDATE/DELETE at the role layer.

USE DATABASE EHRZIPPER;
USE SCHEMA META;

-- ---------------------------------------------------------------------------
-- 1. GLOBAL_CANONICAL_COLUMNS — cross-pkey shared field registry
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS META.GLOBAL_CANONICAL_COLUMNS (
    id              STRING       NOT NULL DEFAULT UUID_STRING(),
    workspace_key   STRING       NOT NULL DEFAULT 'ehrzipper-default',
    name            STRING       NOT NULL,
    data_type       STRING       NOT NULL,
    description     STRING,
    semantic_tags   ARRAY        NOT NULL DEFAULT ARRAY_CONSTRUCT(),
    created_at      TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_global_canonical_columns PRIMARY KEY (id),
    CONSTRAINT uq_global_canonical_columns UNIQUE (workspace_key, name),
    CONSTRAINT ck_global_data_type CHECK (data_type IN (
        'text', 'integer', 'numeric', 'boolean', 'timestamp', 'jsonb', 'string[]',
        'partial_date', 'quantity_with_unit', 'coded_value'
    ))
)
CLUSTER BY (workspace_key)
COMMENT = 'Cross-pkey shared canonical field registry. Mirrors the zipper engine schema.';

-- ---------------------------------------------------------------------------
-- 2. ZIPPERING_SCHEMA — per-pkey canonical inventory (CURRENT state, mutable)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS META.ZIPPERING_SCHEMA (
    id              STRING       NOT NULL DEFAULT UUID_STRING(),
    workspace_key   STRING       NOT NULL DEFAULT 'ehrzipper-default',
    pkey            STRING       NOT NULL,
    canonical_name  STRING       NOT NULL,
    data_type       STRING       NOT NULL,
    description     STRING,
    is_global       BOOLEAN      NOT NULL DEFAULT FALSE,
    source_origin   STRING,
    first_seen_at   TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_zippering_schema PRIMARY KEY (id),
    CONSTRAINT uq_zippering_schema UNIQUE (workspace_key, pkey, canonical_name),
    CONSTRAINT ck_zippering_schema_data_type CHECK (data_type IN (
        'text', 'integer', 'numeric', 'boolean', 'timestamp', 'jsonb', 'string[]',
        'partial_date', 'quantity_with_unit', 'coded_value'
    ))
)
CLUSTER BY (workspace_key, pkey)
COMMENT = 'Per-pkey current canonical inventory. Mutable. Updated via MERGE on upsert.';

-- ---------------------------------------------------------------------------
-- 3. ZIPPERING_DECISIONS — APPEND-ONLY audit
--
-- !!! INSERT-ONLY. NEVER UPDATE. NEVER DELETE. !!!
-- See CLAUDE.md and the header of this file for the invariant.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS META.ZIPPERING_DECISIONS (
    id                  STRING       NOT NULL DEFAULT UUID_STRING(),
    workspace_key       STRING       NOT NULL DEFAULT 'ehrzipper-default',
    pkey                STRING       NOT NULL,
    source              STRING       NOT NULL,
    source_column       STRING       NOT NULL,
    source_data_type    STRING,
    source_description  STRING,
    source_samples      VARIANT,                                  -- jsonb equivalent
    verdict             STRING       NOT NULL,
    canonical_name      STRING       NOT NULL,
    is_global_target    BOOLEAN      NOT NULL DEFAULT FALSE,
    similarity_score    FLOAT,
    reason              STRING,
    needs_review        BOOLEAN      NOT NULL DEFAULT FALSE,
    decided_by          STRING       NOT NULL DEFAULT 'llm',
    decided_at          TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_zippering_decisions PRIMARY KEY (id),
    CONSTRAINT ck_zippering_decisions_verdict CHECK (verdict IN ('join', 'append', 'unclear'))
)
CLUSTER BY (workspace_key, pkey, source, source_column)
COMMENT = 'APPEND-ONLY. Every engine verdict + every operator override is a new row. NEVER UPDATE.';

-- ---------------------------------------------------------------------------
-- 4. ZIPPERED_SIGNALS — the wide rows
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS META.ZIPPERED_SIGNALS (
    id              STRING       NOT NULL DEFAULT UUID_STRING(),
    workspace_key   STRING       NOT NULL DEFAULT 'ehrzipper-default',
    pkey            STRING       NOT NULL,
    source          STRING       NOT NULL,
    external_id     STRING,
    occurred_at     TIMESTAMP_TZ NOT NULL,
    columns         VARIANT      NOT NULL DEFAULT TO_VARIANT(OBJECT_CONSTRUCT()),
    ingested_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_zippered_signals PRIMARY KEY (id),
    CONSTRAINT uq_zippered_signals UNIQUE (source, external_id)
)
CLUSTER BY (workspace_key, pkey, occurred_at)
COMMENT = 'Wide-row signal store. UPSERT on (source, external_id) for idempotent re-ingest.';

-- ---------------------------------------------------------------------------
-- 5. ZIPPERING_CONFLICTS — value-disagreement audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS META.ZIPPERING_CONFLICTS (
    id              STRING       NOT NULL DEFAULT UUID_STRING(),
    workspace_key   STRING       NOT NULL DEFAULT 'ehrzipper-default',
    pkey            STRING       NOT NULL,
    canonical_name  STRING       NOT NULL,
    source_a        STRING       NOT NULL,
    value_a         VARIANT,
    source_b        STRING       NOT NULL,
    value_b         VARIANT,
    occurred_at     TIMESTAMP_TZ NOT NULL,
    resolution      STRING,
    detected_at     TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_zippering_conflicts PRIMARY KEY (id)
)
CLUSTER BY (workspace_key, pkey, canonical_name)
COMMENT = 'Audit of two-source value disagreements. Write-only; not in read path.';

-- The clinical canonical schema (oncology fields) is loaded into
-- META.GLOBAL_CANONICAL_COLUMNS from methodology/canonical-schema-seed.csv via
-- the pipeline layer, not seeded here.
