"""
Pydantic v2 models for the abstraction layer (P4).

`AbstractedFields` is the structured output we extract from one clinical note.
`AbstractionResult` wraps it with provenance (which note, which patient, model,
token usage, latency) so the eval and downstream consumers have full context.

The tool schema sent to Claude (see abstractor.py) mirrors `AbstractedFields`
field-for-field; keep the two in sync.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Note types we recognise (matches the synthetic note filenames in
# synthetic/output/<patient>/notes/<type>.txt).
NoteType = Literal["pathology", "radiology", "consult", "progress", "unknown"]

ConfidenceLevel = Literal["high", "medium", "low"]


class AbstractedFields(BaseModel):
    """Structured fields extracted from a single clinical note.

    Notes do not always contain every field; anything not explicitly stated is
    left as None (scalars) / empty list (collections). The abstractor is
    instructed not to infer.
    """

    # Disease
    histology: str | None = None  # adenocarcinoma, squamous_cell_carcinoma, etc.
    stage: str | None = None  # IIIB, IIIC, IVA, IVB

    # Biomarkers
    egfr_status: str | None = None  # positive, negative, not_tested, unknown
    egfr_mutation: str | None = None  # exon19_deletion, L858R, etc. if mentioned
    alk_status: str | None = None
    ros1_status: str | None = None
    kras_status: str | None = None
    kras_variant: str | None = None  # G12C, G12D, etc.
    braf_status: str | None = None
    pdl1_status: str | None = None  # high, low, negative
    pdl1_tps: float | None = None  # 0-100

    # Clinical
    ecog: int | None = None  # 0-4

    # Events
    progression_mentioned: bool = False
    progression_date: str | None = None  # ISO date if mentioned
    new_metastatic_sites: list[str] = Field(default_factory=list)

    # Treatment mentioned in note
    treatments_mentioned: list[str] = Field(default_factory=list)

    # Extraction metadata
    source_note_type: str | None = None  # pathology, radiology, consult, progress
    extraction_confidence: ConfidenceLevel = "medium"
    uncertain_fields: list[str] = Field(default_factory=list)


class AbstractionResult(BaseModel):
    """One `AbstractedFields` plus everything needed to trace it back.

    `raw_note` is synthetic text (no real PHI per CLAUDE.md hard rule 1), so it
    is safe to persist verbatim.
    """

    patient_id: str
    note_type: str
    note_path: str | None = None
    raw_note: str
    fields: AbstractedFields
    model: str
    tokens_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
