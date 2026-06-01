"""
EHRzipper — schema-reconciliation engine for oncology data integration.

This package is the healthcare extension of zipper, a generic
schema-reconciliation engine (https://github.com/jacksonshuey/zipper). It
reconciles schemas at ingest time: when a new row arrives from any data
integration, each incoming column is routed to either (a) JOIN an existing
canonical column, (b) APPEND a new canonical column, or (c) flag as UNCLEAR
for human review.

Key modules
-----------
types          — Pydantic v2 models mirroring the TypeScript interfaces exactly.
coercions      — Type-normalization registry (UnsafeCoercion + normalize()).
haiku_router   — LLM routing via claude-haiku-4-5 with forced tool_choice.
storage        — Storage Protocol (ABC) defining the persistence contract.
storage_sqlite — SQLite implementation of Storage for local dev and tests.
engine         — zipper_merge() hot path + read helpers.

Invariants (non-negotiable)
---------------------------
- zippering_decisions is APPEND-ONLY. Never UPDATE.
- Cache hit on (pkey, source, source_column) uses latest row by decided_at DESC.
- Operator/normalizer overrides insert a NEW row with decided_by set.
- needs_review is per-decision, not a global toggle.
"""

from ehrzipper.types import (
    GlobalCanonicalColumn,
    HaikuRoutingVerdict,
    IngestRow,
    IngestValue,
    ZipperedSignalRow,
    ZipperingDataType,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
    ZipperingVerdict,
)

__all__ = [
    "GlobalCanonicalColumn",
    "HaikuRoutingVerdict",
    "IngestRow",
    "IngestValue",
    "ZipperedSignalRow",
    "ZipperingDataType",
    "ZipperingDecisionRow",
    "ZipperingSchemaRow",
    "ZipperingVerdict",
]
