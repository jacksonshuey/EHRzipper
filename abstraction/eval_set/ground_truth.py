"""
Ground truth derivation for the abstraction eval set.

Because the synthetic notes are generated *from* `PatientProfile` objects
(see synthetic/notes.py), we know the exact correct answer for every field
that appears in a patient's notes. This module maps a profile to the
`AbstractedFields` we expect a perfect abstractor to recover from the union of
that patient's notes.

Fields that the note templates never surface (e.g. demographics) are not part
of the abstraction target and are left at their defaults.
"""

from __future__ import annotations

from abstraction.types import AbstractedFields
from synthetic.profiles import PatientProfile


def _biomarker_gt(status: str) -> str | None:
    """A biomarker only appears in a note if it was tested.

    The note generator omits `not_tested` biomarkers entirely, so the expected
    extraction is None (field absent) for those.
    """
    return None if status == "not_tested" else status


def profile_to_ground_truth(profile: PatientProfile) -> AbstractedFields:
    """Map a PatientProfile to the expected union-of-notes AbstractedFields."""
    # Treatments: the note mentions the patient's regimen drugs.
    treatments: list[str] = []
    seen: set[str] = set()
    for admin in profile.drug_administrations:
        if admin.display not in seen:
            seen.add(admin.display)
            treatments.append(admin.display)

    # Progression: notes surface on-treatment progression events.
    on_tx = [
        e for e in profile.progression_events
        if e.progression_type == "on_treatment_progression"
    ]
    progression_mentioned = bool(on_tx)
    progression_date: str | None = None
    sites: list[str] = []
    if on_tx:
        latest = max(on_tx, key=lambda e: e.event_date)
        progression_date = latest.event_date.isoformat()
        sites = list(latest.new_metastatic_sites)

    # EGFR mutation / KRAS variant come from biomarker result_value text.
    egfr_mutation: str | None = None
    kras_variant: str | None = None
    for bm in profile.biomarker_results:
        if bm.biomarker_name == "egfr" and bm.result == "positive" and bm.result_value:
            if "exon 19" in bm.result_value.lower():
                egfr_mutation = "exon19_deletion"
            elif "l858r" in bm.result_value.lower():
                egfr_mutation = "L858R"
        if bm.biomarker_name == "kras" and bm.result == "positive" and bm.result_value:
            text = bm.result_value.upper()
            for variant in ("G12C", "G12D", "G12V", "G12A", "G13D"):
                if variant in text:
                    kras_variant = variant
                    break

    pdl1_status = None if profile.pdl1_status == "not_tested" else profile.pdl1_status

    return AbstractedFields(
        histology=profile.histology,
        stage=profile.stage_at_advanced_diagnosis,
        egfr_status=_biomarker_gt(profile.egfr_status),
        egfr_mutation=egfr_mutation,
        alk_status=_biomarker_gt(profile.alk_status),
        ros1_status=_biomarker_gt(profile.ros1_status),
        kras_status=_biomarker_gt(profile.kras_status),
        kras_variant=kras_variant,
        braf_status=_biomarker_gt(profile.braf_status),
        pdl1_status=pdl1_status,
        pdl1_tps=profile.pdl1_tps_value,
        ecog=profile.ecog_at_advanced_diagnosis,
        progression_mentioned=progression_mentioned,
        progression_date=progression_date,
        new_metastatic_sites=sites,
        treatments_mentioned=treatments,
        source_note_type=None,
        extraction_confidence="high",
        uncertain_fields=[],
    )


def build_ground_truth(
    profiles: list[PatientProfile],
) -> dict[str, AbstractedFields]:
    """Build a patient_id -> expected AbstractedFields mapping."""
    return {p.patient_id: profile_to_ground_truth(p) for p in profiles}
