"""Canonical ingest-column builders shared by every format adapter.

Each adapter extracts whatever the source format carries, then calls
:func:`build_columns` so the resulting ``IngestRow`` exposes the same column
names — and therefore exercises the same three routing tiers — no matter which
format it came from. Mirrors ``pipeline/run_engine.py::_build_columns``:

  Tier-1 deterministic (coded):  lab_test_code, medication, diagnosis_code
  Tier-2/3 LLM (uncoded):        ecog_performance_status, tumor_histology_text
"""

from __future__ import annotations

from ehrzipper.types import IngestValue


def build_columns(
    *,
    loinc_code: str | None = None,
    lab_display: str | None = None,
    drug_name: str | None = None,
    icd10_code: str | None = None,
    ecog: int | None = None,
    histology_text: str | None = None,
) -> dict[str, IngestValue]:
    """Assemble the canonical ingest columns from whatever fields were found.

    Only non-empty fields are included, so a source that doesn't carry a given
    field simply omits that column (realistic — sources differ in coverage).
    """
    cols: dict[str, IngestValue] = {}

    if loinc_code:
        display = lab_display or loinc_code
        cols["lab_test_code"] = IngestValue(
            value=loinc_code,
            source_data_type="coded_value",
            source_description=f"Coded lab result ({display})",
        )

    if drug_name:
        cols["medication"] = IngestValue(
            value=drug_name,
            source_data_type="coded_value",
            source_description="Administered systemic therapy",
        )

    if icd10_code:
        cols["diagnosis_code"] = IngestValue(
            value=icd10_code,
            source_data_type="coded_value",
            source_description="Primary cancer diagnosis (ICD-10-CM)",
        )

    if ecog is not None:
        cols["ecog_performance_status"] = IngestValue(
            value=ecog,
            source_data_type="integer",
            source_description="Clinician-recorded performance status",
        )

    if histology_text:
        cols["tumor_histology_text"] = IngestValue(
            value=histology_text,
            source_data_type="text",
            source_description="Free-text histology from the pathology narrative",
        )

    return cols
