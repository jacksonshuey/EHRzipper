"""HL7v2 adapter.

Parses pipe-delimited HL7v2 messages (ADT / ORU / RDE blocks) for a single
patient and extracts the canonical ingest columns from the segments that carry
them: PID (patient id), DG1 (ICD-10 diagnosis + histology text), the first
LOINC-coded OBX (lab), and RXA (administered drug).
"""

from __future__ import annotations

from ehrzipper.types import IngestRow
from ingest.adapters.common import build_columns
from ingest.types import SOURCE_LABEL, UploadedFile

_SOURCE = SOURCE_LABEL["hl7v2"]


def _unescape(value: str) -> str:
    return (
        value.replace("\\F\\", "|").replace("\\S\\", "^").replace("\\X000D\\", "\n")
    )


def _components(field: str) -> list[str]:
    return field.split("^")


def _hl7_date_to_iso(value: str) -> str:
    digits = value.strip()[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _segments(text: str) -> list[list[str]]:
    segs: list[list[str]] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line:
            segs.append(line.split("|"))
    return segs


def _get(fields: list[str], idx: int) -> str:
    return fields[idx] if idx < len(fields) else ""


def parse(uploaded: UploadedFile) -> list[IngestRow]:
    segments = _segments(uploaded.data.decode("utf-8", "replace"))

    pkey: str | None = None
    icd10: str | None = None
    histology: str | None = None
    loinc: str | None = None
    lab_display: str | None = None
    drug: str | None = None
    occurred_at = ""

    for fields in segments:
        seg = fields[0]

        if seg == "PID" and pkey is None:
            pkey = _get(fields, 3).strip() or None

        elif seg == "DG1" and icd10 is None:
            icd10 = _get(fields, 3).strip() or None
            desc = _unescape(_get(fields, 4)).strip()
            if desc:
                # Writer emits "NSCLC <Histology>"; keep the histology phrase.
                histology = desc[len("NSCLC ") :] if desc.startswith("NSCLC ") else desc
            occurred_at = occurred_at or _hl7_date_to_iso(_get(fields, 5))

        elif seg == "OBX" and loinc is None:
            comps = _components(_get(fields, 3))
            if comps and comps[0]:
                loinc = comps[0].strip()
                lab_display = _unescape(comps[1]).strip() if len(comps) > 1 else None

        elif seg == "RXA" and drug is None:
            comps = _components(_get(fields, 5))
            if len(comps) > 1 and comps[1]:
                drug = _unescape(comps[1]).strip()

    if not pkey:
        raise ValueError(f"{uploaded.name!r} has no PID segment with a patient id.")

    columns = build_columns(
        loinc_code=loinc,
        lab_display=lab_display,
        drug_name=drug,
        icd10_code=icd10,
        histology_text=histology,
    )
    if not columns:
        return []

    return [
        IngestRow(
            pkey=pkey,
            source=_SOURCE,
            external_id=f"{_SOURCE}:{pkey}",
            occurred_at=occurred_at,
            columns=columns,
        )
    ]
