# EHRzipper Derived Clinical Variables — Lines of Therapy & rwOS

**Version:** 0.1 (portfolio demonstration)
**Author:** Jackson Shuey
**Status:** synthetic-data draft; mirrors Flatiron Health's published derived-variable methodology
**Last updated:** 2026-05-27

This spec is the source of truth for the two core endpoints pharma RWE buyers
consume. The Python implementation (`derived/`) and the Snowflake marts
(`snowflake/ddl/05_marts.sql`) are implementations of *this document* per
CLAUDE.md hard rule 6.

---

## 1. Lines of Therapy (LoT)

### 1.1 Clinical definition

A **line of therapy** is a continuous course of antineoplastic treatment.
EHRzipper derives lines from `CORE.MEDICATION_ADMINISTRATION` events
(one row per drug per administration) anchored against
`CORE.PROGRESSION_EVENT`. The derivation is Flatiron-aligned.

### 1.2 Rules

1. **New line starts** when the prior line is discontinued AND a drug not in
   the prior regimen is introduced (a genuinely new agent — not maintenance of
   an agent already on board).
2. **The same line continues** when any of:
   - a drug is **added** to an ongoing regimen within the combination window
     (regimen expansion, e.g. adding bevacizumab mid-treatment);
   - **maintenance** therapy continues after induction — the multi-drug
     induction backbone drops out but a persisting agent (typically IO or
     pemetrexed) carries on. This is flagged `is_maintenance = true`, **not** a
     new line;
   - a **brief interruption** (< `gap_threshold_days`, default 90) in the same
     drugs followed by a restart of those same drugs.
3. **New line after progression**: a progression event followed by *different*
   drugs starts a new line regardless of the gap length.
4. **Combination = one regimen**: drugs administered within
   `combination_window_days` (default 28) of each other that persist together
   are a single regimen, not sequential lines.

### 1.3 Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `gap_threshold_days` | 90 | Max gap in the *same* drugs that is still one continuous course; a longer gap with the same drugs opens a new line. |
| `combination_window_days` | 28 | Drugs starting within this window of the line anchor (or added to an ongoing regimen within this gap) are part of the same combination. |

### 1.4 Maintenance heuristic

Induction had ≥2 distinct drugs and the line ends on ≥1 agent whose
administration extends ≥42 days (≈ two 21-day cycles) past the last
administration of the *other* drugs. The canonical example: carboplatin +
pemetrexed + pembrolizumab induction → pembrolizumab (± pemetrexed)
maintenance. The maintenance continuation stays in **Line 1**.

### 1.5 Drug classification

| Class | Members (RxNorm display) |
|---|---|
| TKI | osimertinib, gefitinib, erlotinib, afatinib, dacomitinib, alectinib, lorlatinib, crizotinib, ceritinib, brigatinib, entrectinib, sotorasib, adagrasib, selpercatinib, capmatinib, tepotinib, dabrafenib, trametinib |
| IO | pembrolizumab, nivolumab, atezolizumab, durvalumab, cemiplimab, ipilimumab, tremelimumab |
| Chemo | carboplatin, cisplatin, pemetrexed, paclitaxel, nab-paclitaxel, docetaxel, gemcitabine, vinorelbine, etoposide, bevacizumab, ramucirumab |

Regimen-level class is the combination: `chemo`, `io`, `tki`, `chemo+io`,
`tki+io`, `tki+chemo`. Unknown drugs fall back to the canonical fine-grained
`drug_class` prefix, else default to `chemo`.

### 1.6 End reasons

`death` (death within 90 days of last admin and no subsequent line),
`progression` (a progression event between this line's end and the next line's
start), `completion` (a next line exists with no intervening progression),
`unknown` (no subsequent line — ongoing-vs-completed is unresolvable from meds
alone).

### 1.7 Validation (warnings, not errors)

- Line 1 cannot start before `advanced_diagnosis_date`.
- Line numbers are sequential from 1 with no gaps.
- Every drug is on the recognized oncology list.
- No line exceeds 10 years.
- `end_date` is not before `start_date`.

---

## 2. Real-World Overall Survival (rwOS)

### 2.1 Definition

- **Index date** = `advanced_diagnosis_date` (cohort anchor, methodology
  cohort-definition.md §5).
- **Event** (event = 1): death, when `vital_status = deceased`; event date =
  `date_of_death`.
- **Censoring** (event = 0): patient alive (or unknown) at the data cutoff;
  censored at `last_known_alive_date`.
- **OS time** = `(event_date − index_date).days`.

### 2.2 Date-precision handling

Real mortality/diagnosis dates are often month- or year-precision. EHRzipper
resolves them deterministically and reports the assumption:

- **month precision → assume day 15** (mid-month; minimizes max error).
- **year precision → assume July 1** (mid-year).

Each `SurvivalRecord` carries `index_date_precision` and `index_date_assumed`
so the assumption is auditable. Negative OS arising from precision assumptions
is floored at 0.

### 2.3 Kaplan-Meier estimator

Product-limit estimator implemented from scratch (no `lifelines`):

`S(t) = ∏_{t_i ≤ t} (1 − d_i / n_i)`.

- **Variance**: Greenwood's formula,
  `Var(S(t)) = S(t)² · Σ d_i / (n_i (n_i − d_i))`.
- **Median OS**: first time at which `S(t) ≤ 0.5`; `None` if the curve never
  reaches 0.5 (insufficient events / heavy censoring).
- **95% CI on the median**: derived from the **log-log** (complementary
  log-log) pointwise confidence band, preferred over the linear band for small
  samples because it respects the [0, 1] bounds. The CI bounds on the median
  are the earliest times the upper / lower survival bands cross 0.5.

---

## 3. Production parity

The Python engines compute locally against synthetic CSV output. The Snowflake
marts `MARTS.LINES_OF_THERAPY` and `MARTS.RWOS` implement the same definitions
against the CORE tables for production-scale queries. The Snowflake LoT view
uses a simplified gap/combination window approach in SQL; the authoritative,
fully-featured maintenance and progression logic lives in the Python engine
(intended to materialize `regimen_id` back onto `CORE.MEDICATION_ADMINISTRATION`).
