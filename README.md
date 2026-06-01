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

The hosted app is a single focused reconciliation demo — no setup or API key
needed:

1. **Upload** — drop a FHIR bundle (`.json`), an HL7v2 message (`.hl7`), or a CSV
   extract, or click **Load sample files** for a bundled multi-source set.
2. **How it works** — a live engine-flow diagram shows your files routing through
   the three tiers as you reconcile.
3. **Result** — the merged, downloadable canonical dataset; per-tier decision
   counts; the append-only routing log (one row per decision: source, column,
   canonical field, decided-by, similarity, verdict, reason); and a *Held for
   review* list of columns Tier 1 couldn't resolve.

The cohort definition and the derived oncology endpoints (lines of therapy,
rwOS) are specified in [`methodology/`](./methodology/); they are not surfaced in
this demo UI.

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

To enable the live LLM (Tier 2), set `ANTHROPIC_API_KEY` — copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in.
Without a key the engine runs deterministic Tier-1 only and lists the rest under
*Held for review*, exactly as the hosted demo does.

## Cohort anchor

Advanced non-small-cell lung cancer (aNSCLC) — Flatiron's flagship dataset and
the richest biomarker structure for demonstrating the reconciliation engine.

## Non-goals

- Real patient identity resolution (synthetic data has clean IDs; MPI patterns
  documented, not implemented).
- Full FHIR R4 compliance (a purposeful subset).
- Production HIPAA controls (a de-identification pattern is shown, not certified).
