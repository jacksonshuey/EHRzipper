"""
Unstructured clinical note generator.

Generates 2-4 clinical notes per patient:
  - Initial oncology consult
  - Pathology report
  - Radiology report (CT chest)
  - Progress note (if on treatment)

Each note mentions: stage, biomarker results, ECOG, and at least one
progression event (in patients with progression), so the downstream
abstraction model can extract them.

Two modes:
  1. LLM mode  — calls claude-haiku-4-5 with temperature=0.4 for variety.
                 Requires ANTHROPIC_API_KEY env var.
  2. Template mode (--no-llm) — deterministic template-based notes.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from synthetic.profiles import PatientProfile

# Lazy import so the module loads fine even without the anthropic package
# being available (template mode has no dependency on it).
_anthropic_available = False
try:
    import anthropic

    _anthropic_available = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Note context helpers
# ---------------------------------------------------------------------------


def _biomarker_summary(p: PatientProfile) -> str:
    parts = []
    for bm_name, status in [
        ("EGFR", p.egfr_status),
        ("ALK", p.alk_status),
        ("ROS1", p.ros1_status),
        ("KRAS", p.kras_status),
        ("BRAF", p.braf_status),
    ]:
        if status != "not_tested":
            parts.append(f"{bm_name}: {status}")
    if p.pdl1_status != "not_tested":
        pdl1_str = f"PD-L1: {p.pdl1_status}"
        if p.pdl1_tps_value is not None:
            pdl1_str += f" (TPS {p.pdl1_tps_value}%)"
        parts.append(pdl1_str)
    return "; ".join(parts) if parts else "biomarker panel pending"


def _treatment_summary(p: PatientProfile) -> str:
    if not p.drug_administrations:
        return "no systemic therapy initiated"
    unique_drugs = list(dict.fromkeys(a.display for a in p.drug_administrations))
    return ", ".join(unique_drugs[:4])


def _progression_summary(p: PatientProfile) -> str:
    on_tx_prg = [
        e for e in p.progression_events if e.progression_type == "on_treatment_progression"
    ]
    if not on_tx_prg:
        return ""
    latest = max(on_tx_prg, key=lambda e: e.event_date)
    sites = (
        ", ".join(latest.new_metastatic_sites)
        if latest.new_metastatic_sites
        else "multiple sites"
    )
    return (
        f"Disease progression documented on {latest.event_date.isoformat()} "
        f"with new involvement at: {sites}."
    )


# ---------------------------------------------------------------------------
# Template-based note generation (deterministic)
# ---------------------------------------------------------------------------

_CONSULT_TEMPLATE = """\
ONCOLOGY INITIAL CONSULTATION NOTE
Date: {adv_date}
Patient: {last_name}, {first_name} | DOB: {dob} | MRN: {patient_id}
Practice: {practice_id}

REASON FOR CONSULTATION:
New diagnosis of advanced non-small cell lung cancer, stage {stage}.

HISTORY OF PRESENT ILLNESS:
{first_name} {last_name} is a {age}-year-old {sex} with a {smoking_history} history
who presents with a new diagnosis of {histology} of the lung, stage {stage} per
AJCC 8th edition. Initial symptoms included progressive dyspnea and a 6-week
history of hemoptysis. CT of the chest revealed a {lobe} mass with mediastinal
lymphadenopathy. PET/CT confirmed {stage} disease.

PERFORMANCE STATUS:
ECOG performance status: {ecog}

MOLECULAR TESTING:
{biomarker_summary}

ASSESSMENT AND PLAN:
Diagnosis: {histology}, stage {stage}, {pathway}.
{regimen_plan}

Follow-up in {followup_interval} weeks for treatment monitoring.
"""

_PATHOLOGY_TEMPLATE = """\
SURGICAL PATHOLOGY REPORT
Accession Number: PATH-{patient_id}
Specimen Date: {adv_date}
Patient: {last_name}, {first_name} | MRN: {patient_id}

CLINICAL HISTORY:
Right upper lobe mass, suspicious for malignancy. Rule out primary lung carcinoma.

SPECIMENS SUBMITTED:
A. CT-guided core needle biopsy, right upper lobe mass (3 cores)
B. Bronchial washings

GROSS DESCRIPTION:
A. Three tan-white cores measuring 0.5-1.2 cm in aggregate length.

MICROSCOPIC DESCRIPTION:
Sections show fragments of lung parenchyma with infiltrating carcinoma.
The tumor demonstrates {histology_description}.

DIAGNOSIS:
A-B. {histology_formal}, {icd_o3}
   - Stage at diagnosis: {stage} (AJCC 8th edition)
   - Lymphovascular invasion: present
   - Ki-67 proliferative index: approximately 35%

MOLECULAR ANCILLARY STUDIES:
{biomarker_summary}

COMMENT:
{comment}

Electronically signed: Synthetic Pathologist, MD
"""

_RADIOLOGY_TEMPLATE = """\
RADIOLOGY REPORT — CT CHEST WITH CONTRAST
Study Date: {scan_date}
Patient: {last_name}, {first_name} | MRN: {patient_id}
Ordering Provider: Medical Oncology

INDICATION:
{histology} lung cancer, stage {stage}. Staging evaluation.

COMPARISON:
No prior CT available.

TECHNIQUE:
Helical CT acquisition through the chest with IV contrast.

FINDINGS:
Primary tumor: {lobe} mass measuring {tumor_size} cm in greatest dimension,
with spiculated margins. No evidence of chest wall invasion.

Mediastinum/Hilar: Enlarged mediastinal lymph nodes measuring up to 1.8 cm,
most prominent in the right paratracheal station (4R). {mediastinal_finding}

Pleural spaces: {pleural_finding}

Pulmonary vasculature: Normal.

Bones: {bone_finding}

IMPRESSION:
1. {tumor_size} cm {lobe} primary lung mass consistent with known {histology},
   stage {stage}.
2. Mediastinal lymphadenopathy as described above.
3. {impression_extra}

{progression_note}
"""

_PROGRESS_NOTE_TEMPLATE = """\
ONCOLOGY PROGRESS NOTE
Date: {note_date}
Patient: {last_name}, {first_name} | MRN: {patient_id}

SUBJECTIVE:
Patient returns for cycle {cycle} of {regimen}. {symptom_report}

OBJECTIVE:
ECOG performance status: {ecog}
Weight: {weight} kg
Laboratory values within acceptable parameters for treatment continuation.

ASSESSMENT:
{histology} NSCLC, stage {stage}.
Treatment: {regimen} (initiated {start_date}).
{response_note}

PLAN:
{plan}

{progression_paragraph}
"""


def _template_consult(p: PatientProfile, rng: random.Random) -> str:
    lobes = [
        "right upper lobe", "right lower lobe", "left upper lobe",
        "left lower lobe", "right middle lobe",
    ]
    lobe = rng.choice(lobes)
    smoking_map = {
        "current": "active smoking (current >10 pack-year)",
        "former": f"{p.pack_years or 30}-pack-year smoking",
        "never": "never-smoking",
        "unknown": "unclear smoking",
    }
    regimen_plan = (
        f"Will initiate {p.primary_regimen_display} per guideline-concordant approach."
        if p.primary_regimen_display
        else "Treatment options discussed; plan for watchful waiting vs. clinical trial enrollment."
    )
    return _CONSULT_TEMPLATE.format(
        adv_date=p.advanced_diagnosis_date.isoformat(),
        last_name=p.last_name,
        first_name=p.first_name,
        dob=p.date_of_birth.strftime("%Y-%m"),
        patient_id=p.patient_id,
        practice_id=p.practice_id,
        stage=p.stage_at_advanced_diagnosis,
        age=p.age_at_advanced_diagnosis,
        sex=p.sex,
        smoking_history=smoking_map.get(p.smoking_status, "unknown"),
        histology=p.histology.replace("_", " "),
        lobe=lobe,
        ecog=p.ecog_at_advanced_diagnosis,
        biomarker_summary=_biomarker_summary(p),
        regimen_plan=regimen_plan,
        pathway=p.advanced_diagnosis_pathway.replace("_", " "),
        followup_interval=rng.choice([3, 4, 6]),
    )


def _template_pathology(p: PatientProfile) -> str:
    histology_desc_map = {
        "adenocarcinoma": (
            "glandular architecture with mucin production, consistent with adenocarcinoma."
        ),
        "squamous_cell_carcinoma": (
            "sheets of malignant squamous epithelium with keratinization and intercellular bridges."
        ),
        "large_cell_carcinoma": (
            "large undifferentiated malignant cells without glandular or squamous differentiation."
        ),
        "adenosquamous_carcinoma": "mixed glandular and squamous elements.",
        "sarcomatoid_carcinoma": (
            "spindle cell morphology with pleomorphic nuclei, "
            "consistent with sarcomatoid carcinoma."
        ),
        "nsclc_nos": (
            "malignant epithelial cells that defy further classification "
            "without additional molecular studies."
        ),
    }
    histology_formal_map = {
        "adenocarcinoma": "Invasive adenocarcinoma of the lung",
        "squamous_cell_carcinoma": "Squamous cell carcinoma of the lung",
        "large_cell_carcinoma": "Large cell carcinoma of the lung",
        "adenosquamous_carcinoma": "Adenosquamous carcinoma of the lung",
        "sarcomatoid_carcinoma": "Pulmonary sarcomatoid carcinoma",
        "nsclc_nos": "Non-small cell carcinoma of the lung, NOS",
    }
    comment = (
        "This case was reviewed at multidisciplinary tumor board. Molecular testing "
        "was recommended per NCCN guidelines for advanced NSCLC."
    )
    if p.egfr_status == "positive":
        comment += " EGFR mutation detected; TKI therapy appropriate."
    elif p.pdl1_status == "high":
        comment += " PD-L1 TPS ≥50%; immunotherapy monotherapy is a first-line option."
    return _PATHOLOGY_TEMPLATE.format(
        patient_id=p.patient_id,
        adv_date=p.advanced_diagnosis_date.isoformat(),
        last_name=p.last_name,
        first_name=p.first_name,
        histology_description=histology_desc_map.get(p.histology, "malignant cells present."),
        histology_formal=histology_formal_map.get(p.histology, "NSCLC"),
        icd_o3=p.histology_icdo3_code,
        stage=p.stage_at_advanced_diagnosis,
        biomarker_summary=_biomarker_summary(p),
        comment=comment,
    )


def _template_radiology(p: PatientProfile, rng: random.Random) -> str:
    tumor_size = round(rng.uniform(2.1, 7.8), 1)
    lobes = ["right upper lobe", "left upper lobe", "right lower lobe", "left lower lobe"]
    lobe = rng.choice(lobes)
    pleural = (
        "Small right pleural effusion present." if rng.random() < 0.4 else "No pleural effusion."
    )
    bone_find = (
        "Lytic lesion noted in T7 vertebral body, concerning for metastasis."
        if "bone" in [s for prg in p.progression_events for s in prg.new_metastatic_sites]
        else "No bone lesions identified on current study."
    )
    med_find = (
        "Bilateral mediastinal adenopathy raising concern for N2 or N3 nodal involvement."
        if p.stage_at_advanced_diagnosis in ("IIIB", "IIIC")
        else "Mediastinal nodes mildly enlarged."
    )
    impression_extra = (
        "Pleural effusion as above, may warrant thoracentesis."
        if "pleural" in pleural.lower()
        else "No additional significant findings."
    )
    progression_note = _progression_summary(p)
    return _RADIOLOGY_TEMPLATE.format(
        scan_date=(p.advanced_diagnosis_date).isoformat(),
        last_name=p.last_name,
        first_name=p.first_name,
        patient_id=p.patient_id,
        histology=p.histology.replace("_", " "),
        stage=p.stage_at_advanced_diagnosis,
        lobe=lobe,
        tumor_size=tumor_size,
        mediastinal_finding=med_find,
        pleural_finding=pleural,
        bone_finding=bone_find,
        impression_extra=impression_extra,
        progression_note=progression_note,
    )


def _template_progress_note(p: PatientProfile, rng: random.Random) -> str | None:
    if not p.drug_administrations:
        return None
    regimen = _treatment_summary(p)
    start_date = min(a.start_date for a in p.drug_administrations).isoformat()
    cycle = rng.randint(3, 6)
    symptoms = rng.choice([
        "Patient reports mild fatigue, grade 1. No nausea or vomiting.",
        "Patient tolerating therapy well. Mild peripheral neuropathy, grade 1.",
        "Reports mild cough and dyspnea on exertion; otherwise tolerating treatment.",
        "No significant side effects. Appetite improved since last visit.",
    ])
    response = rng.choice([
        "CT imaging shows stable disease. No new lesions identified.",
        "Partial response to therapy. Primary tumor decreased 30% in size.",
        "Stable disease per RECIST 1.1. Continuing current regimen.",
    ])
    plan = (
        f"Continue {regimen} per current dosing schedule. "
        "Repeat CT chest in 6 weeks. CBC and CMP prior to next cycle."
    )
    progression_para = _progression_summary(p)
    if progression_para:
        plan = (
            f"Disease progression identified. Discontinue current {regimen}. "
            "Referral to clinical trial team. Consider second-line therapy options."
        )
    return _PROGRESS_NOTE_TEMPLATE.format(
        note_date=(
            p.advanced_diagnosis_date + __import__("datetime").timedelta(days=cycle * 21)
        ).isoformat(),
        last_name=p.last_name,
        first_name=p.first_name,
        patient_id=p.patient_id,
        cycle=cycle,
        regimen=regimen,
        symptom_report=symptoms,
        ecog=p.ecog_at_advanced_diagnosis,
        weight=round(rng.uniform(55, 95), 1),
        histology=p.histology.replace("_", " "),
        stage=p.stage_at_advanced_diagnosis,
        start_date=start_date,
        response_note=response,
        plan=plan,
        progression_paragraph=progression_para,
    )


# ---------------------------------------------------------------------------
# LLM note generation
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a clinical documentation specialist generating synthetic (fictional) "
    "oncology notes for a de-identified dataset. Write realistic clinical prose. "
    "No real patient information. Output ONLY the note text — no preamble."
)


def _llm_note(
    client: anthropic.Anthropic,
    note_type: str,
    context: str,
) -> str:
    """Call claude-haiku-4-5 to generate a clinical note."""
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        temperature=0.4,
        system=_LLM_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Generate a synthetic {note_type} for this fictional NSCLC patient.\n\n"
                    f"Patient context:\n{context}\n\n"
                    "The note must explicitly mention: stage, biomarker results "
                    "(EGFR/ALK/ROS1/KRAS/PD-L1), "
                    "ECOG performance status, and any progression events. "
                    f"Write in realistic clinical style. ~300-400 words."
                ),
            }
        ],
    )
    block = message.content[0]
    if hasattr(block, "text"):
        return block.text
    return str(block)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_notes(
    p: PatientProfile,
    out_dir: Path,
    use_llm: bool = False,
    seed: int | None = None,
) -> list[Path]:
    """
    Generate 2-4 clinical notes for patient *p*.

    Notes are written to *out_dir*/{patient_id}/notes/.

    Args:
        p: Patient profile.
        out_dir: Root output directory.
        use_llm: If True, call Anthropic API; otherwise use templates.
        seed: Random seed for template variation.

    Returns:
        List of paths to written note files.
    """
    notes_dir = out_dir / p.patient_id / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed if seed is not None else hash(p.patient_id) % (2**31))

    client: object | None = None
    if use_llm:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise OSError(
                "ANTHROPIC_API_KEY is not set. Use --no-llm for template-based notes."
            )
        if not _anthropic_available:
            raise ImportError("anthropic package is not installed. Run: uv add anthropic")
        import anthropic as _anthropic

        client = _anthropic.Anthropic(api_key=api_key)

    context = (
        f"Stage: {p.stage_at_advanced_diagnosis}\n"
        f"Histology: {p.histology}\n"
        f"ECOG: {p.ecog_at_advanced_diagnosis}\n"
        f"Biomarkers: {_biomarker_summary(p)}\n"
        f"Treatment: {_treatment_summary(p)}\n"
        f"Progression: {_progression_summary(p) or 'none documented'}\n"
        f"Vital status: {p.vital_status}\n"
        f"Advanced dx date: {p.advanced_diagnosis_date.isoformat()}"
    )

    written: list[Path] = []

    note_specs = [
        ("initial_consult", "initial oncology consultation note"),
        ("pathology_report", "surgical pathology report"),
        ("radiology_report", "CT chest radiology report"),
    ]
    if p.drug_administrations:
        note_specs.append(("progress_note", "oncology progress note"))

    for note_key, note_label in note_specs:
        out_path = notes_dir / f"{note_key}.txt"

        if use_llm and client is not None:
            note_text = _llm_note(client, note_label, context)  # type: ignore[arg-type]
        else:
            if note_key == "initial_consult":
                note_text = _template_consult(p, rng)
            elif note_key == "pathology_report":
                note_text = _template_pathology(p)
            elif note_key == "radiology_report":
                note_text = _template_radiology(p, rng)
            elif note_key == "progress_note":
                note_text = _template_progress_note(p, rng) or ""
            else:
                note_text = ""

        if note_text.strip():
            out_path.write_text(note_text, encoding="utf-8")
            written.append(out_path)

    return written
