# Synthetic aNSCLC Patient Generator

Generates synthetic advanced non-small cell lung cancer (aNSCLC) patients for
the EHRzipper portfolio project. All data is entirely fictional — no real PHI.

## Quick start

```bash
# Generate 50 patients with template notes (no API key needed):
uv run python -m synthetic.generator --n 50 --out synthetic/output/ --seed 42 --no-llm

# Generate 50 patients with LLM-generated notes (requires ANTHROPIC_API_KEY):
ANTHROPIC_API_KEY=sk-... uv run python -m synthetic.generator --n 50 --out synthetic/output/ --seed 42

# Small smoke test:
uv run python -m synthetic.generator --n 5 --out /tmp/synth_test --seed 1 --no-llm
```

## Output structure

```
synthetic/output/
├── manifest.json                  # run metadata + patient IDs
├── fhir/
│   └── pat_<id>.json              # FHIR R4 Bundle per patient (~17 patients)
├── hl7v2/
│   └── pat_<id>.hl7               # HL7v2 messages per patient (~17 patients)
├── csv/
│   ├── patients.csv               # one row per patient
│   ├── encounters.csv
│   ├── conditions.csv
│   ├── observations.csv           # labs + ECOG + smoking
│   ├── medication_administrations.csv
│   ├── biomarker_results.csv
│   ├── progression_events.csv
│   └── imaging_studies.csv
└── pat_<id>/
    └── notes/
        ├── initial_consult.txt
        ├── pathology_report.txt
        ├── radiology_report.txt
        └── progress_note.txt      # only for treated patients
```

## What's generated

### Patient demographics

| Field | Distribution |
|---|---|
| Age | median 68, range 35–90 (Gaussian, σ=10) |
| Sex | 55% male, 45% female |
| Race | 72% white, 13% Black, 6% Asian, 9% other |
| Smoking | 55% former, 20% current, 20% never, 5% unknown |

### Disease characteristics

| Field | Distribution |
|---|---|
| Histology | 60% adenocarcinoma, 25% squamous, 15% other |
| Stage at advanced dx | 45% IVA, 30% IVB, 15% IIIB, 10% IIIC |
| Advanced dx pathway | 60% de novo advanced, 30% progression from earlier stage, 10% metastatic recurrence |
| ECOG | 30% ECOG 0, 50% ECOG 1, 15% ECOG 2, 5% ECOG 3–4 |

### Biomarker prevalence

| Biomarker | Prevalence |
|---|---|
| EGFR positive | ~15% (adenocarcinoma-enriched) |
| ALK positive | ~5% |
| ROS1 positive | ~2% |
| KRAS positive | ~25% |
| BRAF positive | ~3% |
| PD-L1 high (TPS ≥50%) | ~30% |

### Treatment mapping (1L)

| Biomarker | First-line regimen |
|---|---|
| EGFR+ | osimertinib |
| ALK+ | alectinib or lorlatinib |
| ROS1+ | entrectinib or crizotinib |
| PD-L1 high, no driver | pembrolizumab monotherapy |
| Non-squamous, no driver | carboplatin + pemetrexed + pembrolizumab |
| Squamous, no driver | carboplatin + paclitaxel + pembrolizumab |

~70% of patients receive at least one line of systemic therapy.

### Outcomes

| Outcome | Rate |
|---|---|
| Deceased at data cutoff (2024-12-31) | ~30% |
| Documented progression event | ~40% |

## Schema mapping

The generated data maps to the EHRzipper canonical schema (`methodology/canonical-schema.md`):

### §A Patient-level fields
All 30 canonical §A fields are populated in every format:
- `patient_id` through `data_cutoff_date`
- Biomarker statuses: `egfr_status`, `alk_status`, `ros1_status`, `kras_status`, `braf_status`, `pdl1_status`, `pdl1_tps_value`

### §B Event types
All 10 canonical §B event types are covered:
- `encounter` → encounters.csv / FHIR Encounter / HL7v2 PV1
- `condition` → conditions.csv / FHIR Condition / HL7v2 DG1
- `observation` → observations.csv / FHIR Observation / HL7v2 OBX
- `medication_administration` → medication_administrations.csv / FHIR MedicationAdministration / HL7v2 RXA
- `procedure` → FHIR Procedure (biopsy)
- `biomarker_result` → biomarker_results.csv / FHIR Observation / HL7v2 OBX
- `imaging_study` → imaging_studies.csv / FHIR ImagingStudy
- `pathology_report` → notes/*.txt / FHIR DiagnosticReport / HL7v2 TXA
- `progression_event` → progression_events.csv
- `response_assessment` → embedded in progress notes

## Code structure

| File | Purpose |
|---|---|
| `generator.py` | CLI entrypoint |
| `profiles.py` | Pydantic patient model + generation logic |
| `vocab.py` | ~50 curated RxNorm/LOINC/ICD-10/SNOMED codes |
| `fhir_writer.py` | FHIR R4 Bundle JSON serialisation |
| `hl7_writer.py` | HL7v2-shaped pipe-delimited message serialisation |
| `csv_writer.py` | Flat CSV serialisation (one file per resource type) |
| `notes.py` | Template + LLM clinical note generation |

## LOINC codes used

| LOINC | Concept |
|---|---|
| 26464-8 | WBC |
| 26515-7 | Platelets |
| 718-7 | Hemoglobin |
| 2160-0 | Creatinine |
| 1742-6 | ALT |
| 85337-4 | PD-L1 IHC |
| 53041-0 | EGFR mutation |
| 76042-8 | ALK FISH |
| 81202-7 | ROS1 FISH |
| 21704-5 | KRAS mutation |
| 89247-1 | ECOG performance status |

## Limitations

- FHIR bundles are structurally valid but not validated against a FHIR validator
- HL7v2 messages are plausibly shaped but not wire-compliant
- LLM notes use `claude-haiku-4-5` (temperature=0.4); quality varies
- ~50 patients is a smoke-test corpus; production runs should target 1,000+
