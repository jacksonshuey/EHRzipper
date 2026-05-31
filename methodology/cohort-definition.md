# EHRzipper Advanced NSCLC Cohort

**Cohort name:** EHRzipper Advanced Non-Small Cell Lung Cancer (aNSCLC) Cohort
**Version:** 0.1 (draft for portfolio demonstration)
**Author:** Jackson Shuey
**Status:** synthetic-data draft; mirrors Flatiron Health's published aNSCLC methodology for fidelity
**Last updated:** 2026-05-27

---

## 1. Clinical rationale

Non-small cell lung cancer (NSCLC) accounts for roughly 85% of US lung cancer
diagnoses and remains the single largest cause of cancer death in the country.
The clinical and commercial center of gravity for NSCLC research has moved
decisively to the *advanced* setting (stage IIIB and beyond), where the
treatment landscape has reorganized around biomarker-directed therapy: EGFR,
ALK, ROS1, BRAF, KRAS G12C, MET, RET, ERBB2, and PD-L1 expression now route
patients to distinct first-line regimens, each with its own real-world outcome
profile.

This cohort — advanced NSCLC (aNSCLC) — is Flatiron Health's flagship
oncology dataset and the most widely cited real-world oncology cohort in
regulatory submissions, comparative effectiveness research, and label
expansions. Mirroring its structure is the right anchor for a portfolio
project demonstrating fit for the Forward Deployed Software Engineer role on
Flatiron's Core Products team: the cohort is biomarker-rich (so the
reconciliation engine has interesting work to do), longitudinally deep
(so derived variables like lines of therapy and rwOS have something to
chew on), and clinically familiar enough that a reviewer can spot
methodological errors quickly.

The aNSCLC cohort enables the following downstream analyses, all of which
EHRzipper is built to support:

- **Treatment pattern analysis** — what regimens patients receive in 1L, 2L, 3L+, by biomarker subgroup.
- **Real-world overall survival (rwOS)** — Kaplan-Meier from index date stratified by treatment and biomarker.
- **Real-world time-to-next-treatment (rwTTNT)** — proxy progression endpoint without RECIST.
- **Biomarker testing patterns** — turnaround time, completeness, NCCN guideline adherence.
- **External control arm construction** — historical real-world comparators for single-arm trials.

## 2. Clinical definition of "advanced NSCLC"

Following Flatiron's published methodology [1, 2], advanced NSCLC is defined as:

> Stage IIIB, IIIC, IVA, or IVB NSCLC at initial diagnosis, **OR** earlier-stage NSCLC (stage I-IIIA) with documented progression to advanced or metastatic disease.

This dual-pathway definition matters: roughly 30-40% of patients in
real-world aNSCLC cohorts enter the cohort via recurrence/progression rather
than de novo advanced presentation, and dropping them produces a younger,
healthier, more favorably-prognosed cohort that does not generalize to
clinical practice. The cohort therefore requires an "advanced diagnosis
date" that is distinct from the initial NSCLC diagnosis date.

## 3. Inclusion criteria

A patient is included in the EHRzipper aNSCLC cohort if **all** of the following are true:

| # | Criterion | Operationalization |
|---|-----------|--------------------|
| I1 | NSCLC diagnosis | ≥1 encounter with ICD-10 code in `C34.0`–`C34.9` (malignant neoplasm of bronchus and lung) **OR** `C39.9` (respiratory tract, unspecified) recorded in the EHR. ICD-9 equivalent: `162.x`. Following Singal et al. 2019 [3]. |
| I2 | Histology confirms NSCLC | Pathology report or structured diagnosis indicates one of: adenocarcinoma, squamous cell carcinoma, large cell carcinoma, adenosquamous, sarcomatoid, NSCLC not otherwise specified (NOS). ICD-O-3 morphology codes 8046/3, 8140/3, 8070/3, 8012/3, 8560/3, 8033/3, 8255/3. Small cell carcinoma (8041/3, 8042/3, 8043/3, 8044/3, 8045/3) excludes the patient. |
| I3 | Advanced disease | Stage IIIB, IIIC, IVA, or IVB (AJCC 8th edition; 7th edition stage IIIB/IV also accepted with mapping) at the time of initial diagnosis, OR documented progression / recurrence to advanced disease after an earlier-stage diagnosis. |
| I4 | Age ≥ 18 at advanced diagnosis | Computed from date of birth and advanced diagnosis date. |
| I5 | Sufficient EHR activity | ≥2 documented clinical visits in the EHR on or after January 1, 2011, with at least one visit ≤90 days after the advanced diagnosis date. Mirrors Flatiron's published "structured activity within 90 days" requirement [1, 2]. |
| I6 | Known sex | Sex must be recorded as male or female (not missing). Following Khozin et al. [1]. |

## 4. Exclusion criteria

A patient is excluded if **any** of the following are true:

| # | Criterion | Rationale |
|---|-----------|-----------|
| E1 | Small cell lung cancer (SCLC) histology | Distinct disease biology, distinct treatment pathway. ICD-O-3 8041/3–8045/3. |
| E2 | NSCLC diagnosed before January 1, 2011 with no subsequent advanced disease event | EHR data quality before 2011 is heterogeneous across the synthetic data sources; matches Flatiron's documented cutoff [1]. |
| E3 | Missing or unknown age | Cannot anchor index date or compute follow-up. |
| E4 | Missing or unknown sex | Required field per Flatiron methodology. |
| E5 | No structured EHR activity within 90 days of advanced diagnosis date | The patient is not truly "in" the practice's care pathway — likely a one-time consult or referral. Matches Flatiron's published exclusion [1, 2]. |
| E6 | Advanced diagnosis date cannot be determined | Cohort cannot be anchored without an index date. |

Note: Unlike some Flatiron sub-cohort analyses (e.g., the EGFR/ALK-negative
first-line study by Khozin et al. [2]), the base EHRzipper aNSCLC cohort does
**not** exclude patients by biomarker status, prior therapy, or histologic
subtype. Those exclusions belong on downstream analytic cohorts derived from
this base.

## 5. Index date definition

**Index date = advanced diagnosis date.**

The advanced diagnosis date is defined as the earliest of:

1. The date of initial diagnosis, if the patient was diagnosed at stage IIIB/IIIC/IVA/IVB.
2. The date of documented progression to advanced or metastatic disease, if the patient was initially diagnosed at stage I-IIIA.
3. The date of documented recurrence with metastatic involvement, if the patient was previously treated to no evidence of disease.

In real-world Flatiron data, the advanced diagnosis date is determined by
trained clinical abstractors reviewing the full chart. Flatiron has published
work on using deep-learning models to extract this date from unstructured EHR
text [4]; in EHRzipper, the synthetic data carries this date as a ground-truth
field on each synthetic patient, and the abstraction layer is exercised on a
held-out subset to demonstrate the extraction pattern.

Analytic cohorts that anchor on treatment (e.g., a 1L-initiation cohort)
define a secondary index date — the start date of first-line therapy — but
the base cohort always anchors on the advanced diagnosis date.

## 6. Required data elements

To be included in the cohort, each patient must have:

- A computable advanced diagnosis date (per §5).
- At least one structured encounter within 90 days of advanced diagnosis.
- A recorded histology consistent with NSCLC.
- A recorded stage at advanced diagnosis.
- A recorded date of birth (precision: at least year).
- A recorded sex.

To be included in analytic sub-cohorts, additional fields are required:

- **Biomarker testing cohort:** ≥1 biomarker result (EGFR, ALK, ROS1, BRAF, KRAS, PD-L1) with a non-missing result date, within a window of 14 days prior to 90 days post advanced diagnosis [2].
- **First-line therapy cohort:** ≥1 systemic anticancer therapy administration record with a start date within 90 days of advanced diagnosis [2, 5].
- **Survival analysis cohort:** A non-missing vital status as of the data cutoff, and a last-known-alive date or date of death.

## 7. Cohort selection workflow

This is the algorithm a SQL or dbt author implements against the canonical
schema (`methodology/canonical-schema.md`):

1. **Universe.** Select all patients with `patient.is_test = false`.
2. **NSCLC condition filter.** Join to `condition` events where `condition_code` matches ICD-10 `C34.*` or `C39.9` (or ICD-9 `162.*`).
3. **Histology confirmation.** Join to `pathology_report` or `condition` events to confirm an NSCLC-consistent histology (ICD-O-3 in the included list). Exclude any patient with a small cell carcinoma morphology code.
4. **Advanced disease determination.** For each patient, compute `advanced_diagnosis_date` as:
   - The `condition.onset_date` of the initial NSCLC diagnosis, if `stage_at_initial_diagnosis IN ('IIIB','IIIC','IVA','IVB')`.
   - Otherwise, the earliest `progression_event.event_date` where `progression_event.progression_type IN ('to_advanced','metastatic_recurrence')`.
   - If neither resolves, the patient is excluded (E6).
5. **Age check.** Compute age at `advanced_diagnosis_date` from `date_of_birth`. Drop if < 18 (I4).
6. **EHR activity check.** Confirm ≥2 `encounter` rows on or after 2011-01-01 with ≥1 within 90 days after `advanced_diagnosis_date` (I5, E5).
7. **Demographics completeness.** Drop patients with missing sex (E4) or missing age (E3).
8. **Cohort table.** Emit one row per included patient with the patient-level fields enumerated in §A of `canonical-schema.md`, including `advanced_diagnosis_date`, `histology`, `stage_at_advanced_diagnosis`, and `ecog_at_advanced_diagnosis` (nearest ECOG within ±30 days, if available).

## 8. Expected cohort size

EHRzipper generates synthetic data; the size is a knob, not an observation.
For the portfolio demo, the target is approximately **1,000–2,500 simulated
aNSCLC patients** across three synthetic source EHRs, which is enough to:

- Populate a Kaplan-Meier curve with non-degenerate confidence intervals.
- Stratify by at least two biomarker subgroups (EGFR+ vs. wild-type, PD-L1 high vs. low).
- Demonstrate at least 3 lines of therapy in a meaningful subset of patients.

For reference, real-world Flatiron aNSCLC cohort sizes published in the literature:

- **17,696 aNSCLC patients** identified across Flatiron community oncology practices, 2011–2015 [5].
- **2,014 stage IV NSCLC patients** without known EGFR/ALK aberrations initiating 1L chemotherapy, 2012–2015 [2].
- **3,522 advanced NSCLC patients** in the Flatiron–Foundation Medicine Clinico-Genomic Database (CGDB) through 2018 [6].
- Flatiron publicly reports >2.4M total cancer patients across its network, of which NSCLC is the largest single tumor type.

The synthetic EHRzipper cohort is intentionally orders of magnitude smaller —
the goal is methodological fidelity, not statistical power.

## 9. Limitations and known gaps (synthetic data)

Honest accounting of what this cohort does **not** reproduce from real Flatiron data:

1. **No real abstractor variability.** Real-world charts are abstracted by trained clinical curators whose inter-rater agreement is itself a research topic. EHRzipper's synthetic notes are LLM-generated with controllable noise but do not reproduce the long tail of free-text idiosyncrasy that human curators encounter (illegible scans, conflicting impressions across providers, abbreviations specific to one practice).
2. **No real EHR vendor mess.** Real Epic, Cerner, OncoEMR, and Athena instances diverge in encoding (`F` vs. `Female` vs. `2` for sex), in date precision (timestamp vs. date vs. month/year), and in code system version (ICD-9 lingering into 2017, mixed SNOMED CT releases). EHRzipper simulates *three* clean source shapes; real Flatiron handles ~280 practices' worth of drift.
3. **No real mortality linkage.** Flatiron's composite mortality variable [7] blends EHR structured death dates, EHR-derived unstructured death evidence, and third-party death indices (e.g., obituary scrapes, SSA cross-walks). EHRzipper synthesizes a single ground-truth vital status; the composite mortality pattern is documented but not replicated.
4. **No real progression abstraction.** Flatiron's real-world progression endpoint requires manual abstractor review of imaging reports and clinician notes [8]. EHRzipper generates synthetic progression events as ground truth; the abstraction layer demonstrates the extraction pattern on a held-out subset but is not validated against a real RECIST reference.
5. **No real-world biomarker testing variability.** Real-world biomarker testing has documented disparities by site type, insurance, race, and age [5]. EHRzipper can simulate these disparities but does not derive them from real epidemiology.
6. **No real practice-type mix.** Flatiron's network is ~85% community oncology, ~15% academic. The synthetic practice_type field is simulated at this ratio but does not reflect any real practice's data quality or coding habits.
7. **Cohort size.** ~1,000–2,500 synthetic patients vs. tens of thousands in the real cohort. Adequate for demonstrating methodology; inadequate for any real epidemiology claim.

These gaps are deliberate scope choices for a portfolio project. None of
them block the demonstration of EHRzipper's core capability: reconciling
heterogeneous source schemas into a canonical longitudinal patient model
with full provenance.

## 10. References

[1] Khozin S, Carrigan G, Estévez M, et al. *Clinical Impact of Adherence to NCCN Guidelines for Biomarker Testing and First-Line Treatment in Advanced Non-Small Cell Lung Cancer (aNSCLC) Using Real-World Electronic Health Record Data.* The Oncologist. 2020. PMC7932942. https://pmc.ncbi.nlm.nih.gov/articles/PMC7932942/

[2] Ma X, Long L, Moon S, Adamson BJS, Baxi SS. *Comparison of Population Characteristics in Real-World Clinical Oncology Databases in the US: Flatiron Health, SEER, and NPCR.* medRxiv 2020.03.16.20037143. https://www.medrxiv.org/content/10.1101/2020.03.16.20037143v3.full

[3] Singal G, Miller PG, Agarwala V, et al. *Association of Patient Characteristics and Tumor Genomics With Clinical Outcomes Among Patients With Non–Small Cell Lung Cancer Using a Clinicogenomic Database.* JAMA. 2019;321(14):1391–1399. PMC6459115. https://pmc.ncbi.nlm.nih.gov/articles/PMC6459115/

[4] Estévez M, Hudson M, Devarapalli S, et al. *Extracting non-small cell lung cancer (NSCLC) diagnosis and diagnosis dates from electronic health record (EHR) text using a deep learning algorithm.* Flatiron Health Publications. https://resources.flatiron.com/publications/extracting-non-small-cell-lung-cancer-nsclc-diagnosis-and-diagnosis-dates-from-electronic-health-record-ehr-text-using-a-deep-learning-algorithm

[5] Khozin S, Carrigan G, Estévez M, et al. *Contemporary management of advanced non-small cell lung cancer (aNSCLC) in a large, real-world cohort.* Flatiron Health Publications. https://resources.flatiron.com/publications/contemporary-management-of-advanced-non-small-cell-lung-cancer-ansclc-in-a-large-real-world-cohort

[6] Singal G, et al. *Development and Validation of a Real-World Clinico-Genomic Database.* Foundation Medicine / Flatiron Health CGDB; ASCO 2017 oral presentation. Patient cohort: 4,064 NSCLC, 3,522 advanced (~86.7%). Companion: PMC6459115.

[7] Curtis MD, Griffith SD, Tucker M, et al. *Development and Validation of a High-Quality Composite Real-World Mortality Endpoint.* Health Services Research. 2018. (Flatiron composite mortality methodology.)

[8] Griffith SD, Tucker M, Bowser B, et al. *Generating real-world tumor burden endpoints from electronic health record data: Comparison of RECIST, radiology-anchored, and clinician-anchored approaches for abstracting real-world progression in non-small cell lung cancer.* bioRxiv 504878. https://www.biorxiv.org/content/10.1101/504878.full.pdf

[9] Wagner J, Karthikeyan S, et al. *Real-world first-line treatment and overall survival in non-small cell lung cancer without known EGFR mutations or ALK rearrangements in US community oncology setting.* PLOS One. 2018. PMC5482433. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5482433/
