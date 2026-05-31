"""
HL7v2-shaped pipe-delimited message writer.

Produces plausibly-shaped HL7v2 messages (ADT^A01, ORU^R01, MDM^T02) in a
single .hl7 file per patient.  Not wire-compliant — designed to look and parse
like HL7v2 for downstream format-adapter testing without requiring a real HL7
parser.

Segment types produced per patient:
  MSH  — message header (once per message block)
  PID  — patient identification
  PV1  — patient visit (ADT)
  DG1  — diagnosis (ADT)
  OBR  — observation request (ORU — labs + biomarkers)
  OBX  — observation result (ORU — one per result)
  RXA  — pharmacy administration (ORU-style medication block)
  TXA  — transcription document header (MDM — note reference)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from synthetic.profiles import DrugAdministration, PatientProfile
from synthetic.vocab import LOINC, RXNORM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEP = "|"
_COMP = "^"


def _hl7_ts(d: date) -> str:
    """HL7 timestamp (YYYYMMDD)."""
    return d.strftime("%Y%m%d")


def _esc(s: str) -> str:
    """Escape pipe characters inside a field value."""
    return s.replace("|", "\\F\\").replace("^", "\\S\\").replace("\n", "\\X000D\\")


def _seg(*fields: str) -> str:
    """Join fields into a segment line."""
    return _SEP.join(fields)


# ---------------------------------------------------------------------------
# Segment builders
# ---------------------------------------------------------------------------

_msg_counter: list[int] = [0]


def _msh(msg_type: str, event: str, sending_app: str = "EHRZIPPER") -> str:
    _msg_counter[0] += 1
    ctrl_id = f"EHRZ{_msg_counter[0]:07d}"
    return _seg(
        "MSH",
        "^~\\&",          # field separator + encoding characters
        sending_app,
        "ONCOLOGY_EMR",
        "EHRZIPPER",
        "CANONICAL_STORE",
        "20241231120000",  # message date/time
        "",                # security
        f"{msg_type}^{event}^{msg_type}_{event}",
        ctrl_id,
        "P",              # processing ID (production)
        "2.5.1",          # HL7 version
    )


def _pid(p: PatientProfile) -> str:
    dob = p.date_of_birth.strftime("%Y%m")  # month precision
    sex_hl7 = "M" if p.sex == "male" else "F"
    race_hl7 = _esc(p.race.replace("_", " ").title())
    eth_hl7 = "H" if p.ethnicity == "hispanic_or_latino" else "N"
    return _seg(
        "PID",
        "1",
        "",                  # PID.2 external ID (blank)
        _esc(p.patient_id),  # PID.3 internal MRN
        "",                  # PID.4 alternate ID
        f"{_esc(p.last_name)}^{_esc(p.first_name)}",  # PID.5 name
        "",                  # PID.6 mother's maiden name
        dob,                 # PID.7 DOB
        sex_hl7,             # PID.8 sex
        "",
        race_hl7,            # PID.10 race
        # PID.11 address
        (
            f"{_esc(p.street_address)}^^{_esc(p.city)}"
            f"^{p.state_of_residence}^{_esc(p.zip_code)}^USA"
        ),
        "",
        "",
        "",
        "",
        eth_hl7,             # PID.22 ethnicity
        "",
        "",
        "",
        p.patient_id,        # PID.20 SSN-surrogate (patient_id re-used)
    )


def _pv1(p: PatientProfile, enc_date: date, encounter_type: str = "O") -> str:
    enc_hl7 = "O"
    if encounter_type == "inpatient":
        enc_hl7 = "I"
    elif encounter_type == "emergency":
        enc_hl7 = "E"
    return _seg(
        "PV1",
        "1",
        enc_hl7,                             # PV1.2 patient class
        f"{p.practice_id}^ONCOLOGY^^^",      # PV1.3 assigned patient location
        "",
        "",
        "",
        "DR9999^ONCOLOGIST^SYNTHETIC^MD",   # PV1.7 attending doctor
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        _hl7_ts(enc_date),   # PV1.44 admit date
        _hl7_ts(enc_date),   # PV1.45 discharge date
    )


def _dg1(p: PatientProfile, seq: int = 1) -> str:
    icdo3 = p.histology_icdo3_code.replace("/", ".")
    return _seg(
        "DG1",
        str(seq),
        "I10",                                    # coding method (ICD-10)
        p.icd10_code,                             # diagnosis code
        _esc(f"NSCLC {p.histology.replace('_', ' ').title()}"),  # description
        _hl7_ts(p.initial_nsclc_diagnosis_date),  # date
        "F",                                      # diagnosis type (Final)
        "",
        "",
        "",
        "",
        "",
        "",
        f"STAGE_{p.stage_at_advanced_diagnosis}",
        "",
        "",
        "",
        "",
        "",
        "",
        icdo3,  # ICD-O-3 in free field
    )


def _obr(seq: int, loinc_code: str, obs_date: date) -> str:
    loinc_display = LOINC.get(loinc_code, {}).get("display", loinc_code)
    return _seg(
        "OBR",
        str(seq),
        f"ORD{seq:05d}",                # placer order number
        f"FIL{seq:05d}",                # filler order number
        f"{loinc_code}^{_esc(loinc_display)}^LN",  # OBR.4 universal service ID
        "",
        _hl7_ts(obs_date),              # OBR.6 requested date
        _hl7_ts(obs_date),              # OBR.7 observation date
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "F",                            # OBR.25 result status (Final)
    )


def _obx(
    seq: int,
    loinc_code: str,
    value: str,
    unit: str,
    obs_date: date,
    ref_low: float | None = None,
    ref_high: float | None = None,
) -> str:
    loinc_display = LOINC.get(loinc_code, {}).get("display", loinc_code)
    ref_range = ""
    if ref_low is not None and ref_high is not None:
        ref_range = f"{ref_low}-{ref_high}"
    obs_type = "NM" if _is_numeric(value) else "ST"
    return _seg(
        "OBX",
        str(seq),
        obs_type,
        f"{loinc_code}^{_esc(loinc_display)}^LN",
        "",              # OBX.4 sub-ID
        _esc(str(value)),
        _esc(unit),
        ref_range,
        "",              # abnormal flags
        "",
        "F",             # observation result status
        "",
        "",
        _hl7_ts(obs_date),
    )


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _rxa(admin: DrugAdministration) -> str:
    rxnorm_display = RXNORM.get(admin.rxnorm_code, {}).get("display", admin.rxnorm_code)
    route_hl7 = "IV" if admin.route == "intravenous" else "PO"
    return _seg(
        "RXA",
        "0",             # give sub-ID
        "1",             # administration sub-ID
        _hl7_ts(admin.start_date),
        _hl7_ts(admin.end_date if admin.end_date else admin.start_date),
        f"{admin.rxnorm_code}^{_esc(rxnorm_display)}^RXN",  # administered code
        str(admin.dose_value),
        admin.dose_unit,
        "",
        route_hl7,
        "",
        "",
        "",
        "",
        "",
        "",
        "A",             # substance treatment refusal reason (A=administered)
        "",
        "",
        admin.regimen_id,  # administration notes (regimen)
    )


def _txa(patient_id: str, doc_date: date, doc_type: str, doc_id: str) -> str:
    doc_type_code = {
        "pathology": "11529-5",
        "radiology": "18748-4",
        "consult": "11488-4",
        "progress_note": "11506-3",
    }.get(doc_type, "34117-2")
    return _seg(
        "TXA",
        "1",
        doc_type_code,   # document type
        "TX",            # document content presentation
        _hl7_ts(doc_date),  # activity date/time
        "DR9999^ONCOLOGIST^SYNTHETIC^MD",  # primary activity provider
        _hl7_ts(doc_date),
        "",
        "",
        doc_id,          # unique document number
        "",
        "",
        "",
        "",
        "",
        "AU",            # document completion status (Authenticated)
        "",
        "",
        "",
        patient_id,
    )


# ---------------------------------------------------------------------------
# Message block builders
# ---------------------------------------------------------------------------

def _adt_block(p: PatientProfile) -> list[str]:
    """ADT^A01 (admission/registration) message."""
    lines = [
        _msh("ADT", "A01"),
        _pid(p),
        _pv1(p, p.advanced_diagnosis_date),
        _dg1(p, 1),
    ]
    return lines


def _oru_labs_block(p: PatientProfile) -> list[str]:
    """ORU^R01 for lab observations."""
    if not p.lab_observations:
        return []
    lines = [_msh("ORU", "R01"), _pid(p)]
    obr_seq = 1
    for lab in p.lab_observations:
        lines.append(_obr(obr_seq, lab.loinc_code, lab.observation_date))
        lines.append(
            _obx(
                1, lab.loinc_code, str(lab.value), lab.unit,
                lab.observation_date, lab.ref_low, lab.ref_high,
            )
        )
        obr_seq += 1
    return lines


def _oru_biomarkers_block(p: PatientProfile) -> list[str]:
    """ORU^R01 for biomarker results."""
    if not p.biomarker_results:
        return []
    lines = [_msh("ORU", "R01"), _pid(p)]
    for i, bm in enumerate(p.biomarker_results, 1):
        lines.append(_obr(i, bm.loinc_code, bm.result_date))
        result_val = bm.result_value if bm.result_value else bm.result
        lines.append(_obx(1, bm.loinc_code, result_val, "", bm.result_date))
    return lines


def _oru_medications_block(p: PatientProfile) -> list[str]:
    """ORU-style message carrying RXA segments for medication administrations."""
    if not p.drug_administrations:
        return []
    lines = [_msh("RDE", "O11"), _pid(p)]
    for admin in p.drug_administrations:
        lines.append(_rxa(admin))
    return lines


def _mdm_notes_block(p: PatientProfile) -> list[str]:
    """MDM^T02 document notification stubs for each note file."""
    lines = [_msh("MDM", "T02"), _pid(p)]
    note_types = [
        ("pathology", p.advanced_diagnosis_date),
        ("radiology", p.advanced_diagnosis_date),
        ("consult", p.advanced_diagnosis_date),
    ]
    for doc_type, doc_date in note_types:
        doc_id = f"doc_{p.patient_id}_{doc_type}"
        lines.append(_txa(p.patient_id, doc_date, doc_type, doc_id))
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_hl7_messages(p: PatientProfile, out_dir: Path) -> Path:
    """Write all HL7v2-shaped messages for patient *p* to a single .hl7 file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{p.patient_id}.hl7"

    all_lines: list[str] = []
    for block in [
        _adt_block(p),
        _oru_labs_block(p),
        _oru_biomarkers_block(p),
        _oru_medications_block(p),
        _mdm_notes_block(p),
    ]:
        if block:
            all_lines.extend(block)
            all_lines.append("")  # blank line between message blocks

    out_path.write_text("\n".join(all_lines))
    return out_path


def write_all_hl7(profiles: list[PatientProfile], out_dir: Path) -> list[Path]:
    """Write HL7v2 files for all hl7v2-format profiles."""
    hl7_dir = out_dir / "hl7v2"
    hl7_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for p in profiles:
        if p.source_format == "hl7v2":
            paths.append(write_hl7_messages(p, hl7_dir))
    return paths
