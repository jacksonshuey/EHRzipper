"""
Zippering ingest engine — EHRzipper entrypoint.

EHRzipper does NOT fork the engine. The hot path and read helpers live in
zipper; this module is a thin wrapper that injects the four healthcare seams so
the generic engine behaves as an oncology data-integration tool:

  - lookup     (Tier 1, deterministic): ehrzipper.lookup.CodeLookup
  - router     (Tier 2, LLM semantic):  zipper.HaikuRouter
  - storage    (persistence):           SQLite / Snowflake implementations
  - normalizer (value coercion):        ehrzipper.normalizer.EHRNormalizer

Routing order is deterministic → zipper (LLM) → append, exactly as zipper's
engine sequences its tiers. The only EHRzipper-specific wiring is the
``EHRNormalizer`` injected here so clinical units / controlled vocabularies /
partial dates are honored against the resolved canonical target.

Hot path:  zipper_merge(row, storage, router, lookup=None)
Read path: get_zippered_row / get_zippered_timeline / get_decision_history
"""

from __future__ import annotations

from zipper import Lookup, Router, Storage, ZipperMergeResult
from zipper.engine import get_decision_history as get_decision_history
from zipper.engine import get_merged_record as get_merged_record
from zipper.engine import get_zippered_row as get_zippered_row
from zipper.engine import get_zippered_timeline as get_zippered_timeline
from zipper.engine import zipper_merge as _zipper_merge

from ehrzipper.normalizer import EHRNormalizer
from ehrzipper.types import IngestRow


async def zipper_merge(
    row: IngestRow,
    storage: Storage,
    router: Router,
    lookup: Lookup | None = None,
) -> ZipperMergeResult:
    """Ingest one integration row, injecting EHRzipper's clinical normalizer."""
    return await _zipper_merge(
        row, storage, router, lookup=lookup, normalizer=EHRNormalizer()
    )


__all__ = [
    "ZipperMergeResult",
    "get_decision_history",
    "get_merged_record",
    "get_zippered_row",
    "get_zippered_timeline",
    "zipper_merge",
]
