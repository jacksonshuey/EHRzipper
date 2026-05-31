"""
Deterministic code-lookup tier — Tier 1 of the three-tier routing pipeline.

Runs BEFORE the Haiku LLM tier. Inspects a column's name and sample values
against three healthcare vocabularies (LOINC, RxNorm, ICD-10) and returns
a high-confidence verdict when there is an unambiguous match. Otherwise
returns None so the engine falls through to the Haiku tier.

Public API
----------
CodeLookup.match(source_column, samples) -> LookupVerdict | None
"""

from ehrzipper.lookup.matcher import CodeLookup
from ehrzipper.lookup.types import LookupVerdict

__all__ = ["CodeLookup", "LookupVerdict"]
