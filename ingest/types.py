"""Shared types for the ingestion layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceFormat = Literal["fhir", "hl7v2", "csv"]

# Source label as it would arrive from a real integration, keyed by format.
# Mirrors pipeline/run_engine.py so uploaded data is labelled identically to
# the synthetic engine run.
SOURCE_LABEL: dict[SourceFormat, str] = {
    "fhir": "epic_fhir_r4",
    "hl7v2": "legacy_hl7v2",
    "csv": "registry_csv_export",
}


@dataclass
class UploadedFile:
    """A file acquired from any source (computer, Drive, Dropbox).

    ``data`` is the raw bytes exactly as delivered — nothing is parsed or
    mutated before it reaches the format adapter.
    """

    name: str
    data: bytes


@dataclass
class FileOutcome:
    """What happened to one uploaded file."""

    name: str
    detected_format: SourceFormat | None = None
    n_records: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    """Result of reconciling one or more uploaded files.

    Everything the Import page renders comes from here: the per-file outcomes,
    the append-only routing decisions, the merged canonical record per patient,
    and tallies by tier/verdict.
    """

    files: list[FileOutcome] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    canonical_records: dict[str, dict[str, Any]] = field(default_factory=dict)
    tally: dict[str, int] = field(default_factory=dict)
    llm_available: bool = False
    held_columns: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n_patients(self) -> int:
        return len(self.canonical_records)

    @property
    def n_decisions(self) -> int:
        return len(self.decisions)
