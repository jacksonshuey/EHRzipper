"""Flat CSV adapter.

Handles a single delimited extract as a registry / legacy EHR would SFTP it.
Recognizes a fixed set of header names and maps them onto the canonical ingest
columns, grouping rows by ``patient_id`` so each patient becomes one IngestRow
(first-seen value wins per field — the demo wants one representative row per
patient, mirroring the synthetic engine run).

Works for any of the synthetic CSVs (patients / observations / conditions /
medication_administrations) because it keys off whichever recognized columns
are present rather than a fixed schema.
"""

from __future__ import annotations

import csv
import io

from ehrzipper.types import IngestRow
from ingest.adapters.common import build_columns
from ingest.types import SOURCE_LABEL, UploadedFile

_SOURCE = SOURCE_LABEL["csv"]
_DATE_HEADERS = (
    "observation_date",
    "start_date",
    "onset_date",
    "advanced_diagnosis_date",
    "result_date",
    "event_date",
)


def _to_ecog(value: str) -> int | None:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse(uploaded: UploadedFile) -> list[IngestRow]:
    text = uploaded.data.decode("utf-8-sig", "replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"{uploaded.name!r} has no header row.")

    headers = {h.lower().strip() for h in reader.fieldnames}
    drug_file = "rxnorm_code" in headers or "drug_class" in headers

    # patient_id -> first-seen raw fields
    acc: dict[str, dict[str, object]] = {}
    order: list[str] = []

    for raw_row in reader:
        row = {(k or "").lower().strip(): (v or "").strip() for k, v in raw_row.items()}
        pid = row.get("patient_id")
        if not pid:
            continue
        if pid not in acc:
            acc[pid] = {}
            order.append(pid)
        cur = acc[pid]

        if "loinc_code" in row and row["loinc_code"] and "loinc_code" not in cur:
            cur["loinc_code"] = row["loinc_code"]
            if row.get("display"):
                cur["lab_display"] = row["display"]

        if drug_file and row.get("display") and "drug_name" not in cur:
            cur["drug_name"] = row["display"]

        for dx_key in ("icd10_code", "condition_code"):
            if row.get(dx_key) and "icd10_code" not in cur:
                cur["icd10_code"] = row[dx_key]

        if row.get("ecog_at_advanced_diagnosis") and "ecog" not in cur:
            ecog = _to_ecog(row["ecog_at_advanced_diagnosis"])
            if ecog is not None:
                cur["ecog"] = ecog

        if row.get("histology") and "histology" not in cur:
            cur["histology"] = row["histology"]

        if "occurred_at" not in cur:
            for dk in _DATE_HEADERS:
                if row.get(dk):
                    cur["occurred_at"] = row[dk]
                    break

    rows: list[IngestRow] = []
    for pid in order:
        cur = acc[pid]
        columns = build_columns(
            loinc_code=cur.get("loinc_code"),  # type: ignore[arg-type]
            lab_display=cur.get("lab_display"),  # type: ignore[arg-type]
            drug_name=cur.get("drug_name"),  # type: ignore[arg-type]
            icd10_code=cur.get("icd10_code"),  # type: ignore[arg-type]
            ecog=cur.get("ecog"),  # type: ignore[arg-type]
            histology_text=cur.get("histology"),  # type: ignore[arg-type]
        )
        if not columns:
            continue
        rows.append(
            IngestRow(
                pkey=pid,
                source=_SOURCE,
                external_id=f"{_SOURCE}:{pid}",
                occurred_at=str(cur.get("occurred_at", "")),
                columns=columns,
            )
        )

    return rows
