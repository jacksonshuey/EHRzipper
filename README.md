# EHRzipper

A working, end-to-end demonstration of a Flatiron-style **real-world oncology
data product** — built as a portfolio project for the Forward Deployed Software
Engineer role on the Core Products team.

> **Live demo:** _add your Streamlit Community Cloud URL here once deployed_
>
> **All data is fully synthetic — no real PHI anywhere, including tests.**

Take messy oncology records from many incompatible hospital systems, reconcile
them into one clean longitudinal dataset with a full append-only audit trail,
and produce the real-world cancer endpoints (lines of therapy, overall survival)
that pharma companies buy.

## Try it in the browser

The hosted app needs no setup or API key. The most representative path:

1. **Import Data** — drop a FHIR bundle, an HL7v2 message, or a CSV extract (or
   click **Load sample files**). Watch every source column get reconciled live
   through the three-tier engine, with the full provenance: per-tier decision
   counts, the append-only decision log, anything held for review, and the
   merged canonical record per patient.
2. **Cohort Builder** — filter the 50 synthetic aNSCLC patients by biomarker,
   stage, ECOG, histology, and practice type.
3. **Survival Analysis** — real-world overall survival (Kaplan-Meier) by subgroup.
4. **Audit Trail** — the same append-only provenance log, browsable.

## The reconciliation engine

Heterogeneous EHR sources never agree on column names, code systems, or units.
EHRzipper routes every incoming column through three tiers, recording an
append-only decision for each:

```
Source column (FHIR / HL7v2 / CSV)
        │
        ▼
  Tier 1 — Deterministic lookup     LOINC / RxNorm / ICD-10 carried in the data
        │ (no LLM call)             → resolved with zero ambiguity
        ▼
  Tier 2 — LLM semantic match       Uncoded / free-text columns (ECOG, histology
        │ (Claude Haiku)            phrasing) matched to a canonical target
        ▼
  Tier 3 — Append as new canonical  Genuinely novel signals become new columns
        │
        ▼
  Canonical longitudinal patient model  +  append-only audit log
```

When no `ANTHROPIC_API_KEY` is configured, the engine **degrades honestly**: it
applies only the deterministic Tier-1 matches and lists everything that would
need the LLM under *Held for review* — it never fabricates an LLM decision. The
hosted demo runs in exactly this mode.

The engine is a healthcare extension of **[zipper](https://github.com/jacksonshuey/zipper)**,
a generic, reusable schema-reconciliation engine. EHRzipper injects an oncology
normalizer (unit conversion, controlled-vocabulary validation) and a
deterministic code matcher through the seams zipper exposes — no fork.

## Run it locally

```bash
cd EHRzipper
uv sync --extra dev
uv run streamlit run ui/app.py
```

That's enough for the full UI on the bundled synthetic data. To regenerate data,
load Snowflake, run the engine from the CLI, and score the note-abstraction
evals, see **[DEMO.md](./DEMO.md)** for the complete run-book.

To enable the live LLM (Tier 2) or the Google Drive / Dropbox import connectors,
set `ANTHROPIC_API_KEY` and copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml`.

## Cohort anchor

Advanced non-small-cell lung cancer (aNSCLC) — Flatiron's flagship dataset and
the richest biomarker structure for demonstrating the reconciliation engine.

## Non-goals

- Real patient identity resolution (synthetic data has clean IDs; MPI patterns
  documented, not implemented).
- Full FHIR R4 compliance (a purposeful subset).
- Production HIPAA controls (a de-identification pattern is shown, not certified).
