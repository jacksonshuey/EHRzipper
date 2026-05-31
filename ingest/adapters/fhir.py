"""FHIR R4 Bundle adapter.

Parses a transaction Bundle (one patient per bundle, as Epic/Cerner/Synthea
bulk export delivers) and extracts the canonical ingest columns from its
Patient / Condition / Observation / MedicationAdministration resources.

Tolerant by design: a real bundle may omit any resource, so every extraction
is best-effort and missing fields are simply dropped.
"""

from __future__ import annotations

import json
from typing import Any, cast

from ehrzipper.types import IngestRow
from ingest.adapters.common import build_columns
from ingest.types import SOURCE_LABEL, UploadedFile

_SOURCE = SOURCE_LABEL["fhir"]
_LOINC = "http://loinc.org"
_ECOG_LOINC = "89247-1"


def _resources(bundle: dict[str, Any], rtype: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource") or {}
        if res.get("resourceType") == rtype:
            out.append(res)
    return out


def _first_coding(concept: dict[str, Any], system_contains: str) -> dict[str, Any] | None:
    for coding in concept.get("coding", []):
        if system_contains in (coding.get("system") or ""):
            return cast("dict[str, Any]", coding)
    return None


def _patient_id(bundle: dict[str, Any]) -> str | None:
    pts = _resources(bundle, "Patient")
    if not pts:
        return None
    patient = pts[0]
    for ident in patient.get("identifier", []):
        if "patient-id" in (ident.get("system") or "") and ident.get("value"):
            return str(ident["value"])
    return str(patient.get("id")) if patient.get("id") else None


def _diagnosis_code(bundle: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (icd10_code, histology_text) from the first Condition."""
    for cond in _resources(bundle, "Condition"):
        code = cond.get("code") or {}
        icd = _first_coding(code, "icd-10")
        icdo3 = _first_coding(code, "icd-o-3")
        icd10_code = icd.get("code") if icd else None
        histology = (icdo3.get("display") if icdo3 else None) or code.get("text")
        if icd10_code or histology:
            return icd10_code, histology
    return None, None


def _lab(bundle: dict[str, Any]) -> tuple[str | None, str | None]:
    """First true lab Observation (LOINC-coded, valueQuantity) -> (code, display)."""
    for obs in _resources(bundle, "Observation"):
        if "valueQuantity" not in obs:
            continue
        coding = _first_coding(obs.get("code") or {}, _LOINC)
        if coding and coding.get("code"):
            return coding["code"], coding.get("display")
    return None, None


def _ecog(bundle: dict[str, Any]) -> int | None:
    for obs in _resources(bundle, "Observation"):
        coding = _first_coding(obs.get("code") or {}, _LOINC)
        if coding and coding.get("code") == _ECOG_LOINC and "valueInteger" in obs:
            return int(obs["valueInteger"])
    return None


def _medication(bundle: dict[str, Any]) -> str | None:
    for ma in _resources(bundle, "MedicationAdministration"):
        concept = ma.get("medicationCodeableConcept") or {}
        if concept.get("text"):
            return str(concept["text"])
        for coding in concept.get("coding", []):
            if coding.get("display"):
                return str(coding["display"])
    return None


def _occurred_at(bundle: dict[str, Any]) -> str:
    for cond in _resources(bundle, "Condition"):
        if cond.get("onsetDateTime"):
            return str(cond["onsetDateTime"])[:10]
    ts = bundle.get("timestamp")
    return str(ts)[:10] if ts else ""


def parse(uploaded: UploadedFile) -> list[IngestRow]:
    bundle = json.loads(uploaded.data.decode("utf-8", "replace"))
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ValueError(f"{uploaded.name!r} is not a FHIR Bundle.")

    pkey = _patient_id(bundle)
    if not pkey:
        raise ValueError(f"{uploaded.name!r} has no identifiable Patient resource.")

    icd10, histology = _diagnosis_code(bundle)
    loinc, lab_display = _lab(bundle)
    columns = build_columns(
        loinc_code=loinc,
        lab_display=lab_display,
        drug_name=_medication(bundle),
        icd10_code=icd10,
        ecog=_ecog(bundle),
        histology_text=histology,
    )
    if not columns:
        return []

    return [
        IngestRow(
            pkey=pkey,
            source=_SOURCE,
            external_id=f"{_SOURCE}:{pkey}",
            occurred_at=_occurred_at(bundle),
            columns=columns,
        )
    ]
