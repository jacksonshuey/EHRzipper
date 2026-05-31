"""Format adapters: source file bytes -> engine IngestRows.

One adapter per delivery format a hospital actually uses:
  - FHIR R4 Bundle JSON      (fhir.py)      -> epic_fhir_r4
  - HL7v2 pipe-delimited      (hl7.py)       -> legacy_hl7v2
  - flat CSV extract          (csv_file.py)  -> registry_csv_export

All three converge on the same canonical ingest columns (see common.py) so the
reconciliation demo is identical regardless of how the data arrived.
"""

from __future__ import annotations

import json

from ehrzipper.types import IngestRow
from ingest.adapters import csv_file, fhir, hl7
from ingest.types import SourceFormat, UploadedFile


class UnknownFormatError(ValueError):
    """Raised when a file's format cannot be determined."""


def detect_format(uploaded: UploadedFile) -> SourceFormat:
    """Best-effort format detection from extension first, then content.

    Extension is the strong signal (it's how files are delivered); content
    sniffing is the fallback for ambiguous or extension-less uploads.
    """
    name = uploaded.name.lower()
    if name.endswith(".json"):
        return "fhir"
    if name.endswith((".hl7", ".hl7v2")):
        return "hl7v2"
    if name.endswith(".csv"):
        return "csv"

    # Content sniff for extension-less / .txt uploads.
    head = uploaded.data[:4096].lstrip()
    if head.startswith(b"{") or head.startswith(b"["):
        try:
            obj = json.loads(uploaded.data.decode("utf-8", "replace"))
        except ValueError:
            pass
        else:
            if isinstance(obj, dict) and obj.get("resourceType") == "Bundle":
                return "fhir"
    if head.startswith(b"MSH|"):
        return "hl7v2"
    first_line = head.splitlines()[0] if head.splitlines() else b""
    if b"," in first_line:
        return "csv"

    raise UnknownFormatError(
        f"Could not determine source format for {uploaded.name!r}. "
        "Supported: FHIR R4 Bundle (.json), HL7v2 (.hl7), flat extract (.csv)."
    )


def parse_file(uploaded: UploadedFile) -> tuple[SourceFormat, list[IngestRow]]:
    """Detect the format and parse the file into IngestRows."""
    fmt = detect_format(uploaded)
    if fmt == "fhir":
        return fmt, fhir.parse(uploaded)
    if fmt == "hl7v2":
        return fmt, hl7.parse(uploaded)
    return fmt, csv_file.parse(uploaded)


__all__ = ["UnknownFormatError", "detect_format", "parse_file"]
