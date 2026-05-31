-- zipper reconciliation tables — Phase 0 schema (SQLite dialect).
--
-- Mirrors the canonical schema of the generic zipper engine
-- (https://github.com/jacksonshuey/zipper), rendered in the SQLite dialect.
--
-- SQLite-dialect changes from the Postgres original:
--   uuid         → text  (UUIDs generated in Python and passed in)
--   text[]       → text  (JSON-encoded array stored as TEXT)
--   jsonb        → text  (JSON stored as TEXT; parsed/serialised in Python)
--   timestamptz  → text  (ISO 8601 strings; ordered lexicographically)
--   gen_random_uuid()     → removed (Python generates UUIDs)
--   now()                 → (not used in DDL; Python sets decided_at on insert)
--   enable row level security → dropped (SQLite has no RLS)
--   pgcrypto extension   → dropped
--   Partial indexes WHERE clause → supported in SQLite 3.8.9+
--
-- Idempotent via IF NOT EXISTS.

-- ---------------------------------------------------------------------------
-- 1. global_canonical_columns — cross-pkey shared field registry
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS global_canonical_columns (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'ehrzipper-default',
    name            TEXT NOT NULL,
    data_type       TEXT NOT NULL CHECK (data_type IN (
                        'text', 'integer', 'numeric', 'boolean',
                        'timestamp', 'jsonb', 'string[]',
                        'partial_date', 'quantity_with_unit', 'coded_value'
                    )),
    description     TEXT,
    semantic_tags   TEXT NOT NULL DEFAULT '[]',   -- JSON array
    created_at      TEXT NOT NULL,
    -- Clinical data-dictionary columns (EHRzipper extension). Read at
    -- normalize time off the resolved canonical target; NULL for non-clinical
    -- globals (e.g. the generic CRM-style example fields below).
    canonical_unit         TEXT,   -- UCUM unit the value should normalize to
    controlled_vocabulary  TEXT,   -- pipe-delimited allowed values
    analyte                TEXT,   -- analyte hint for unit conversion (e.g. glucose)
    code_system            TEXT,   -- coding system for coded_value (e.g. ICD-10)
    UNIQUE (workspace_key, name)
);

CREATE INDEX IF NOT EXISTS global_canonical_columns_workspace_idx
    ON global_canonical_columns (workspace_key);

-- ---------------------------------------------------------------------------
-- 2. zippering_schema — per-pkey canonical inventory (CURRENT state, mutable)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS zippering_schema (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'ehrzipper-default',
    pkey            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    data_type       TEXT NOT NULL CHECK (data_type IN (
                        'text', 'integer', 'numeric', 'boolean',
                        'timestamp', 'jsonb', 'string[]',
                        'partial_date', 'quantity_with_unit', 'coded_value'
                    )),
    description     TEXT,
    is_global       INTEGER NOT NULL DEFAULT 0,   -- 0=false, 1=true
    source_origin   TEXT,
    first_seen_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (workspace_key, pkey, canonical_name)
);

CREATE INDEX IF NOT EXISTS zippering_schema_workspace_pkey_idx
    ON zippering_schema (workspace_key, pkey);

CREATE INDEX IF NOT EXISTS zippering_schema_canonical_idx
    ON zippering_schema (workspace_key, canonical_name);

-- ---------------------------------------------------------------------------
-- 3. zippering_decisions — APPEND-ONLY engine + operator audit
--
-- Every engine verdict appends a row (decided_by: 'lookup' | 'llm' |
-- 'normalizer'). Every operator override appends a new row (NEVER updates an
-- existing one). Latest row by decided_at DESC for a given
-- (workspace_key, pkey, source, source_column) is the active routing.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS zippering_decisions (
    id                  TEXT PRIMARY KEY,
    workspace_key       TEXT NOT NULL DEFAULT 'ehrzipper-default',
    pkey                TEXT NOT NULL,
    source              TEXT NOT NULL,
    source_column       TEXT NOT NULL,
    source_data_type    TEXT,
    source_description  TEXT,
    source_samples      TEXT,            -- JSON array
    verdict             TEXT NOT NULL CHECK (verdict IN ('join', 'append', 'unclear')),
    canonical_name      TEXT NOT NULL,
    is_global_target    INTEGER NOT NULL DEFAULT 0,
    similarity_score    REAL,
    reason              TEXT,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    decided_by          TEXT NOT NULL DEFAULT 'llm',
    decided_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS zippering_decisions_lookup_idx
    ON zippering_decisions (workspace_key, pkey, source, source_column, decided_at DESC);

CREATE INDEX IF NOT EXISTS zippering_decisions_needs_review_idx
    ON zippering_decisions (workspace_key, needs_review)
    WHERE needs_review = 1;

CREATE INDEX IF NOT EXISTS zippering_decisions_canonical_idx
    ON zippering_decisions (workspace_key, pkey, canonical_name);

-- ---------------------------------------------------------------------------
-- 4. zippered_signals — the wide rows
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS zippered_signals (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'ehrzipper-default',
    pkey            TEXT NOT NULL,
    source          TEXT NOT NULL,
    external_id     TEXT,
    occurred_at     TEXT NOT NULL,
    columns         TEXT NOT NULL DEFAULT '{}',   -- JSON object
    ingested_at     TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS zippered_signals_pkey_time_idx
    ON zippered_signals (workspace_key, pkey, occurred_at DESC);

CREATE INDEX IF NOT EXISTS zippered_signals_source_idx
    ON zippered_signals (workspace_key, source, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- 5. zippering_conflicts — value-disagreement audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS zippering_conflicts (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'ehrzipper-default',
    pkey            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    source_a        TEXT NOT NULL,
    value_a         TEXT,            -- JSON
    source_b        TEXT NOT NULL,
    value_b         TEXT,            -- JSON
    occurred_at     TEXT NOT NULL,
    resolution      TEXT,
    detected_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS zippering_conflicts_lookup_idx
    ON zippering_conflicts (workspace_key, pkey, canonical_name, detected_at DESC);

-- ---------------------------------------------------------------------------
-- Seed: global_canonical_columns — foundational cross-pkey fields.
--
-- Two families coexist, demonstrating that the engine is domain-agnostic:
--   gcc-001..017 — generic CRM-style example fields (no clinical metadata),
--                  showing the same reconciliation core handling a non-clinical
--                  schema. Exercised by the engine/router unit tests.
--   gcc-101..109 — EHRzipper clinical data dictionary. These carry the
--                  canonical_unit / controlled_vocabulary / analyte /
--                  code_system metadata that EHRNormalizer reads at normalize
--                  time off the resolved target. Names MUST match the lookup
--                  registry canonical_field_names so deterministic + LLM joins
--                  land on the same canonical column.
--
-- UUIDs are deterministic placeholders — safe to re-run (ON CONFLICT DO NOTHING).
-- ---------------------------------------------------------------------------

INSERT OR IGNORE INTO global_canonical_columns
    (id, workspace_key, name, data_type, description, semantic_tags, created_at)
VALUES
    ('gcc-001', 'ehrzipper-default', 'company_name',          'text',      'Display name of the account.',                                '["identity"]',                     '2026-05-25T00:00:00.000Z'),
    ('gcc-002', 'ehrzipper-default', 'domain',                'text',      'Primary web domain for the account.',                         '["identity"]',                     '2026-05-25T00:00:00.000Z'),
    ('gcc-003', 'ehrzipper-default', 'ticker',                'text',      'Public-company ticker symbol.',                               '["identity","public_co"]',          '2026-05-25T00:00:00.000Z'),
    ('gcc-004', 'ehrzipper-default', 'industry',              'text',      'Industry classification.',                                    '["taxonomy"]',                     '2026-05-25T00:00:00.000Z'),
    ('gcc-005', 'ehrzipper-default', 'hq_location',           'text',      'Headquarters city / region.',                                 '["geography"]',                    '2026-05-25T00:00:00.000Z'),
    ('gcc-006', 'ehrzipper-default', 'employee_count',        'integer',   'Approximate headcount.',                                      '["size","people"]',                '2026-05-25T00:00:00.000Z'),
    ('gcc-007', 'ehrzipper-default', 'account_owner',         'text',      'Internal owner (rep_id or display name).',                    '["ownership"]',                    '2026-05-25T00:00:00.000Z'),
    ('gcc-008', 'ehrzipper-default', 'deal_stage',            'text',      'Current pipeline stage.',                                     '["deal_state"]',                   '2026-05-25T00:00:00.000Z'),
    ('gcc-009', 'ehrzipper-default', 'deal_amount',           'integer',   'Open deal ACV in whole USD.',                                 '["deal_state","money"]',           '2026-05-25T00:00:00.000Z'),
    ('gcc-010', 'ehrzipper-default', 'close_date',            'timestamp', 'Expected close date for the open deal.',                      '["deal_state","timing"]',          '2026-05-25T00:00:00.000Z'),
    ('gcc-011', 'ehrzipper-default', 'latest_signal_at',      'timestamp', 'Timestamp of the most recent signal of any kind.',            '["freshness"]',                    '2026-05-25T00:00:00.000Z'),
    ('gcc-012', 'ehrzipper-default', 'latest_signal_summary', 'text',      'One-line summary of the most recent signal.',                 '["freshness","narrative"]',        '2026-05-25T00:00:00.000Z'),
    ('gcc-013', 'ehrzipper-default', 'funding_signal',        'jsonb',     'Most recent funding event (round, amount, lead).',            '["intel","money"]',                '2026-05-25T00:00:00.000Z'),
    ('gcc-014', 'ehrzipper-default', 'hiring_signal',         'jsonb',     'Most recent hiring / leadership change event.',               '["intel","people"]',               '2026-05-25T00:00:00.000Z'),
    ('gcc-015', 'ehrzipper-default', 'risk_flags',            'jsonb',     'Active risk signals (champion change, kill point hit, etc.)', '["intel","risk"]',                 '2026-05-25T00:00:00.000Z'),
    ('gcc-016', 'ehrzipper-default', 'last_contact_at',       'timestamp', 'Timestamp of last two-way contact (email / call / meeting).', '["engagement","freshness"]',       '2026-05-25T00:00:00.000Z'),
    ('gcc-017', 'ehrzipper-default', 'last_meeting_summary',  'text',      'Summary of the most recent meeting / call.',                  '["engagement","narrative"]',       '2026-05-25T00:00:00.000Z');

-- EHRzipper clinical data dictionary. Clinical metadata columns are populated
-- here (canonical_unit / controlled_vocabulary / analyte / code_system); the
-- generic seed above leaves them NULL. analyte is set only for glucose and
-- creatinine, the two analytes ucum.convert supports; other passthrough units
-- short-circuit on identity so the hint is harmless when absent.
INSERT OR IGNORE INTO global_canonical_columns
    (id, workspace_key, name, data_type, description, semantic_tags, created_at,
     canonical_unit, controlled_vocabulary, analyte, code_system)
VALUES
    ('gcc-101', 'ehrzipper-default', 'wbc_count',                  'quantity_with_unit', 'White blood cell count.',          '["lab","cbc"]',          '2026-05-25T00:00:00.000Z', '10*3/uL', NULL,                       NULL,         NULL),
    ('gcc-102', 'ehrzipper-default', 'hemoglobin',                 'quantity_with_unit', 'Hemoglobin concentration.',        '["lab","cbc"]',          '2026-05-25T00:00:00.000Z', 'g/dL',    NULL,                       NULL,         NULL),
    ('gcc-103', 'ehrzipper-default', 'platelet_count',             'quantity_with_unit', 'Platelet count.',                  '["lab","cbc"]',          '2026-05-25T00:00:00.000Z', '10*3/uL', NULL,                       NULL,         NULL),
    ('gcc-104', 'ehrzipper-default', 'creatinine',                 'quantity_with_unit', 'Serum creatinine.',                '["lab","cmp"]',          '2026-05-25T00:00:00.000Z', 'mg/dL',   NULL,                       'creatinine', NULL),
    ('gcc-105', 'ehrzipper-default', 'glucose',                    'quantity_with_unit', 'Serum glucose.',                   '["lab","cmp"]',          '2026-05-25T00:00:00.000Z', 'mg/dL',   NULL,                       'glucose',    NULL),
    ('gcc-106', 'ehrzipper-default', 'ecog_at_advanced_diagnosis', 'integer',            'ECOG performance status.',         '["clinical","staging"]', '2026-05-25T00:00:00.000Z', NULL,      NULL,                       NULL,         NULL),
    ('gcc-107', 'ehrzipper-default', 'drug_name',                  'text',               'Generic drug name (RxNorm).',      '["medication"]',         '2026-05-25T00:00:00.000Z', NULL,      NULL,                       NULL,         NULL),
    ('gcc-108', 'ehrzipper-default', 'diagnosis_code',             'coded_value',        'Diagnosis code (ICD-10).',         '["diagnosis"]',          '2026-05-25T00:00:00.000Z', NULL,      NULL,                       NULL,         'ICD-10'),
    ('gcc-109', 'ehrzipper-default', 'egfr_status',                'coded_value',        'EGFR mutation status.',            '["biomarker"]',          '2026-05-25T00:00:00.000Z', NULL,      'positive|negative|unknown', NULL,        NULL);
