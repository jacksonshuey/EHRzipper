"""
Verdict type returned by the deterministic lookup tier.

Extends zipper's generic ``LookupVerdict`` (canonical_column, data_type,
confidence, matched_on, reason) with the healthcare provenance fields the audit
trail needs: which registry matched and on what code.
"""

from __future__ import annotations

from typing import Literal

from zipper import LookupVerdict as _BaseLookupVerdict


class LookupVerdict(_BaseLookupVerdict):
    """
    A successful deterministic match. Always confidence=1.0 — if a registry
    matches at all, it matches exactly. Anything ambiguous returns None.
    """

    verdict: Literal["matched"] = "matched"
    canonical_unit: str | None = None
    matched_registry: Literal["LOINC", "RxNorm", "ICD-10"]
    matched_code: str
