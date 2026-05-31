"""
FHIR R4 Bundle writer.

Serializes a PatientProfile into a FHIR R4 Bundle JSON file.
Resources included: Patient, Condition, Observation, MedicationAdministration,
Procedure, Encounter, DiagnosticReport.

Not fully wire-compliant but structurally valid for downstream parsing.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from synthetic.profiles import PatientProfile
from synthetic.vocab import (
    CPT,
    LOINC,
    RXNORM,
)


def _d(d: date) -> str:
    """ISO date string."""
    return d.isoformat()


def _dt(d: date) -> str:
    """ISO datetime string (midnight UTC)."""
    return f"{d.isoformat()}T00:00:00Z"


def _ref(resource_type: str, rid: str) -> dict[str, str]:
    return {"reference": f"{resource_type}/{rid}"}


def _coding(code: str, system: str, display: str) -> dict[str, Any]:
    return {
        "coding": [{"system": system, "code": code, "display": display}],
        "text": display,
    }


def _loinc_coding(loinc_code: str) -> dict[str, Any]:
    info = LOINC.get(loinc_code, {"display": loinc_code, "unit": ""})
    return _coding(loinc_code, "http://loinc.org", info["display"])


def _rxnorm_coding(rxnorm_code: str) -> dict[str, Any]:
    info = RXNORM.get(rxnorm_code, {"display": rxnorm_code, "drug_class": "other"})
    return _coding(rxnorm_code, "http://www.nlm.nih.gov/research/umls/rxnorm", info["display"])


def _patient_resource(p: PatientProfile) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": p.patient_id,
        "meta": {"source": f"synthetic/{p.source_format}"},
        "identifier": [
            {
                "system": "urn:ehrzipper:patient-id",
                "value": p.patient_id,
            }
        ],
        "name": [
            {
                "use": "official",
                "family": p.last_name,
                "given": [p.first_name],
            }
        ],
        "gender": p.sex,
        "birthDate": p.date_of_birth.strftime("%Y-%m"),  # month precision
        "address": [
            {
                "use": "home",
                "line": [p.street_address],
                "city": p.city,
                "state": p.state_of_residence,
                "postalCode": p.zip_code,
                "country": "US",
            }
        ],
        "extension": [
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {"display": p.race},
                    }
                ],
            },
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {"display": p.ethnicity},
                    }
                ],
            },
        ],
    }
    if p.vital_status == "deceased":
        if p.date_of_death:
            resource["deceasedDateTime"] = _dt(p.date_of_death)
        else:
            resource["deceasedBoolean"] = True
    return resource


def _condition_resource(p: PatientProfile) -> dict[str, Any]:
    icdo3_display = p.histology.replace("_", " ").title()
    return {
        "resourceType": "Condition",
        "id": f"cond_{p.patient_id}",
        "subject": _ref("Patient", p.patient_id),
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": p.icd10_code,
                    "display": "Malignant neoplasm of lung",
                },
                {
                    "system": "http://terminology.hl7.org/CodeSystem/icd-o-3",
                    "code": p.histology_icdo3_code,
                    "display": icdo3_display,
                },
            ],
            "text": f"NSCLC - {icdo3_display}",
        },
        "clinicalStatus": _coding(
            "active",
            "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "Active",
        ),
        "onsetDateTime": _dt(p.initial_nsclc_diagnosis_date),
        "stage": [
            {
                "summary": _coding(
                    p.stage_at_advanced_diagnosis,
                    "http://cancerstaging.org",
                    f"Stage {p.stage_at_advanced_diagnosis}",
                )
            }
        ],
        "category": [
            _coding(
                "problem-list-item",
                "http://terminology.hl7.org/CodeSystem/condition-category",
                "Problem List Item",
            )
        ],
    }


def _observation_ecog(p: PatientProfile) -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "id": f"obs_ecog_{p.patient_id}",
        "status": "final",
        "code": _loinc_coding("89247-1"),
        "subject": _ref("Patient", p.patient_id),
        "effectiveDateTime": _dt(p.advanced_diagnosis_date),
        "valueInteger": p.ecog_at_advanced_diagnosis,
    }


def _observation_smoking(p: PatientProfile) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"obs_smoking_{p.patient_id}",
        "status": "final",
        "code": _loinc_coding("72166-2"),
        "subject": _ref("Patient", p.patient_id),
        "effectiveDateTime": _dt(p.advanced_diagnosis_date),
        "valueCodeableConcept": _coding(
            p.smoking_status,
            "http://snomed.info/sct",
            p.smoking_status.replace("_", " ").title(),
        ),
    }
    if p.pack_years:
        obs["component"] = [
            {
                "code": _loinc_coding("8663-7"),
                "valueQuantity": {"value": p.pack_years, "unit": "{PackYears}"},
            }
        ]
    return obs


def _observation_lab(p: PatientProfile, lab: Any) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": lab.observation_id,
        "status": "final",
        "code": _loinc_coding(lab.loinc_code),
        "subject": _ref("Patient", p.patient_id),
        "effectiveDateTime": _dt(lab.observation_date),
        "valueQuantity": {"value": lab.value, "unit": lab.unit},
    }
    if lab.ref_low is not None and lab.ref_high is not None:
        obs["referenceRange"] = [
            {
                "low": {"value": lab.ref_low, "unit": lab.unit},
                "high": {"value": lab.ref_high, "unit": lab.unit},
            }
        ]
    return obs


def _observation_biomarker(p: PatientProfile, bm: Any) -> dict[str, Any]:
    loinc_info = LOINC.get(bm.loinc_code, {"display": bm.biomarker_name.upper(), "unit": ""})
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": bm.biomarker_id,
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": bm.loinc_code,
                    "display": loinc_info["display"],
                }
            ],
            "text": f"{bm.biomarker_name.upper()} test",
        },
        "subject": _ref("Patient", p.patient_id),
        "effectiveDateTime": _dt(bm.result_date),
        "valueCodeableConcept": _coding(bm.result, "http://snomed.info/sct", bm.result.title()),
        "method": _coding(bm.test_method, "http://snomed.info/sct", bm.test_method.upper()),
        "specimen": {
            "display": bm.specimen_type,
        },
        "performer": [{"display": bm.lab_vendor}],
    }
    if bm.result_value:
        obs["note"] = [{"text": bm.result_value}]
    return obs


def _medication_administration(p: PatientProfile, admin: Any) -> dict[str, Any]:
    ma: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": admin.medication_id,
        "status": "completed",
        "medicationCodeableConcept": _rxnorm_coding(admin.rxnorm_code),
        "subject": _ref("Patient", p.patient_id),
        "effectivePeriod": {
            "start": _dt(admin.start_date),
        },
        "dosage": {
            "dose": {"value": admin.dose_value, "unit": admin.dose_unit},
            "route": _coding(
                admin.route,
                "http://snomed.info/sct",
                admin.route.replace("_", " ").title(),
            ),
        },
        "extension": [
            {
                "url": "urn:ehrzipper:drug-class",
                "valueString": admin.drug_class,
            },
            {
                "url": "urn:ehrzipper:regimen-id",
                "valueString": admin.regimen_id,
            },
            {
                "url": "urn:ehrzipper:cycle",
                "valueInteger": admin.cycle,
            },
        ],
    }
    if admin.end_date:
        ma["effectivePeriod"]["end"] = _dt(admin.end_date)
    return ma


def _procedure_biopsy(p: PatientProfile) -> dict[str, Any]:
    cpt_code = "32408"
    return {
        "resourceType": "Procedure",
        "id": f"proc_biopsy_{p.patient_id}",
        "status": "completed",
        "code": {
            "coding": [
                {
                    "system": "http://www.ama-assn.org/go/cpt",
                    "code": cpt_code,
                    "display": CPT[cpt_code],
                }
            ]
        },
        "subject": _ref("Patient", p.patient_id),
        "performedDateTime": _dt(
            p.advanced_diagnosis_date + __import__("datetime").timedelta(days=-7)
        ),
        "bodySite": [
            _coding("44029006", "http://snomed.info/sct", "Lung structure")
        ],
    }


def _encounter_resource(p: PatientProfile, enc: Any) -> dict[str, Any]:
    enc_class_map = {
        "office_visit": ("AMB", "ambulatory"),
        "infusion": ("AMB", "ambulatory"),
        "inpatient": ("IMP", "inpatient encounter"),
        "emergency": ("EMER", "emergency"),
        "telehealth": ("VR", "virtual"),
        "other": ("AMB", "ambulatory"),
    }
    cls_code, cls_display = enc_class_map.get(enc.encounter_type, ("AMB", "ambulatory"))
    return {
        "resourceType": "Encounter",
        "id": enc.encounter_id,
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": cls_code,
            "display": cls_display,
        },
        "type": [
            _coding(
                enc.encounter_type,
                "urn:ehrzipper:encounter-type",
                enc.encounter_type.replace("_", " ").title(),
            )
        ],
        "subject": _ref("Patient", p.patient_id),
        "period": {
            "start": _dt(enc.encounter_date),
            "end": _dt(enc.encounter_date),
        },
        "serviceProvider": {"display": p.practice_id},
        "participant": [
            {
                "type": [
                    _coding(
                        enc.provider_specialty,
                        "urn:ehrzipper:specialty",
                        enc.provider_specialty.replace("_", " ").title(),
                    )
                ],
            }
        ],
    }


def _diagnostic_report(p: PatientProfile) -> dict[str, Any]:
    """Pathology / staging report placeholder."""
    return {
        "resourceType": "DiagnosticReport",
        "id": f"dr_{p.patient_id}",
        "status": "final",
        "category": [_coding("PAT", "http://terminology.hl7.org/CodeSystem/v2-0074", "Pathology")],
        "code": _coding("11529-5", "http://loinc.org", "Surgical pathology study"),
        "subject": _ref("Patient", p.patient_id),
        "effectiveDateTime": _dt(p.advanced_diagnosis_date),
        "conclusion": (
            f"{p.histology.replace('_', ' ').title()}, stage {p.stage_at_advanced_diagnosis}, "
            f"ECOG {p.ecog_at_advanced_diagnosis}. "
            f"EGFR: {p.egfr_status}. ALK: {p.alk_status}. ROS1: {p.ros1_status}. "
            f"KRAS: {p.kras_status}. PD-L1: {p.pdl1_status}"
            + (f" (TPS {p.pdl1_tps_value}%)" if p.pdl1_tps_value is not None else "")
            + "."
        ),
    }


def write_fhir_bundle(p: PatientProfile, out_dir: Path) -> Path:
    """Write a FHIR R4 Bundle JSON for patient *p* to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []

    def _entry(resource: dict[str, Any]) -> dict[str, Any]:
        rid = resource.get("id", str(uuid.uuid4()))
        rtype = resource["resourceType"]
        return {
            "fullUrl": f"urn:uuid:{rid}",
            "resource": resource,
            "request": {
                "method": "PUT",
                "url": f"{rtype}/{rid}",
            },
        }

    entries.append(_entry(_patient_resource(p)))
    entries.append(_entry(_condition_resource(p)))
    entries.append(_entry(_observation_ecog(p)))
    entries.append(_entry(_observation_smoking(p)))
    entries.append(_entry(_procedure_biopsy(p)))
    entries.append(_entry(_diagnostic_report(p)))

    for lab in p.lab_observations:
        entries.append(_entry(_observation_lab(p, lab)))

    for bm in p.biomarker_results:
        entries.append(_entry(_observation_biomarker(p, bm)))

    for admin in p.drug_administrations:
        entries.append(_entry(_medication_administration(p, admin)))

    for enc in p.encounters:
        entries.append(_entry(_encounter_resource(p, enc)))

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": f"bundle_{p.patient_id}",
        "type": "transaction",
        "timestamp": f"{p.data_cutoff_date.isoformat()}T00:00:00Z",
        "entry": entries,
    }

    out_path = out_dir / f"{p.patient_id}.json"
    out_path.write_text(json.dumps(bundle, indent=2, default=str))
    return out_path


def write_all_fhir(profiles: list[PatientProfile], out_dir: Path) -> list[Path]:
    """Write FHIR bundles for all FHIR-format profiles."""
    fhir_dir = out_dir / "fhir"
    fhir_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for p in profiles:
        if p.source_format == "fhir":
            paths.append(write_fhir_bundle(p, fhir_dir))
    return paths
