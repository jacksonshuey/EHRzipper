# EHRzipper — Demo Run-book

A five-minute walkthrough of the system: messy multi-source oncology data in,
one audit-ready real-world-evidence dataset out. Everything here is synthetic.

> **Just want to click around?** The hosted app (link in the
> [README](./README.md)) runs the whole UI — live reconciliation, cohort
> builder, survival curves, audit trail — on bundled synthetic data with no
> Snowflake and no API key. This run-book is the deeper, local end-to-end path
> (data generation → Snowflake → CLI engine → note abstraction).

## One-sentence pitch

> Take oncology records from many incompatible hospital systems, reconcile them
> into one clean dataset with a full audit trail, and produce the real-world
> cancer endpoints (lines of therapy, overall survival) that pharma buys.

## The four steps

| Step | What happens | Where to see it |
|---|---|---|
| 1. Reconcile | Every source column routed through 3 tiers: deterministic code lookup (LOINC/RxNorm/ICD) → Claude Haiku → append-new. Every decision logged append-only. | Streamlit **Audit Trail** tab |
| 2. Store | raw → staging → core → marts in Snowflake; healthcare-aware types validate at the boundary. | Snowflake `EHRZIPPER` db |
| 3. Derive | Lines of therapy (1L–3L) and real-world overall survival (Kaplan-Meier). | Streamlit **Survival Analysis** tab |
| 4. Abstract | LLM pulls stage / ECOG / biomarkers / progression from free-text notes — 94.3% measured accuracy. | `abstraction/REPORT.md` |

## Prerequisites

```bash
cd EHRzipper
uv sync --extra dev --extra snowflake
set -a && . ./.env && set +a   # ANTHROPIC_API_KEY + Snowflake key-pair vars
```

## Run it end to end

```bash
# 1. Generate 50 synthetic aNSCLC patients across FHIR / HL7v2 / CSV (+ notes)
uv run python -m synthetic.generator --n 50 --out synthetic/output/ --seed 42 --no-llm

# 2. Build the Snowflake schema (idempotent) and load the data
uv run python snowflake/migrate.py --up
uv run python pipeline/load_snowflake.py --seed 42 --n 50

# 3. Run the reconciliation engine on the multi-source columns (writes the audit log)
uv run python pipeline/run_engine.py --n-patients 10 --reset

# 4. Abstract structured fields from the notes + score accuracy
uv run python -m abstraction abstract --patients-dir synthetic/output/ --out abstraction/output/
uv run python -m abstraction eval --results abstraction/output/results.jsonl --ground-truth synthetic/output/

# 5. Open the cohort app
uv run streamlit run ui/app.py
```

## Quick checks (talking points)

```bash
# Population data-quality gate
uv run python pipeline/data_quality.py

# The full test + type + lint gate (what CI runs)
uv run ruff check . && uv run mypy --strict ehrzipper/ synthetic/ abstraction/ derived/ pipeline/ ui/ snowflake/ ingest/ && uv run pytest -q
```

## What lives where

- `ehrzipper/` — the reconciliation engine (3-tier router, healthcare types, storage)
- `ehrzipper/sf_connect.py` — Snowflake key-pair auth + clock-skew tolerance
- `synthetic/` — deterministic patient generator (3 source formats + notes)
- `snowflake/` — DDL (raw/staging/core/marts/meta) + migration runner
- `pipeline/` — `load_snowflake.py`, `run_engine.py`, `data_quality.py`
- `derived/` — lines of therapy + rwOS + Kaplan-Meier
- `abstraction/` — LLM note → fields + eval (`REPORT.md`)
- `ui/` — Streamlit cohort builder / survival / audit trail
- `methodology/` — cohort definition + derived-variable specs (the source of truth)

## Snowflake quirks solved (how it got connected)

1. Trial enforces **MFA** on password login → switched to **key-pair auth**.
2. Local clock ran ~100s ahead, invalidating the 60s JWT → measure the server
   clock and backdate the token (`ehrzipper/sf_connect.py`).
3. `row` is reserved and `ARRAY_CONSTRUCT` is illegal in a `VALUES` clause → DDL fixes.
4. A window function inside a correlated subquery is rejected → restructured the
   lines-of-therapy view into a materialized CTE.
