"""
CodeLookup — deterministic Tier-1 matching.

Inspects a column's name and sample values against LOINC, RxNorm, and ICD-10.
Returns a LookupVerdict (always confidence=1.0) on a clean match, or None to
let the engine fall through to the Haiku tier.

Match strategies (in priority order):
 1. Sample values look like exact LOINC codes (NNNNN-N) and resolve.
 2. Sample values look like ICD-10 codes (^[A-Z]\\d{2}(\\.\\d+)?$) and resolve.
 3. Sample values are RxNorm drug names that exactly match the registry
    (case-insensitive, by generic or brand).
 4. Column name contains a unique LOINC alias.
 5. Column name explicitly references an ICD-10 family ("diagnosis_code",
    "icd10_code", etc.) AND samples confirm the pattern.
 6. Column name is "drug" / "medication" AND samples are drug names.

Anything ambiguous → return None.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ehrzipper.lookup.registries import (
    ICD10_REGISTRY,
    LOINC_REGISTRY,
    RXNORM_REGISTRY,
    Icd10Entry,
    LoincEntry,
    RxNormEntry,
)
from ehrzipper.lookup.types import LookupVerdict

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# LOINC code: 1-5 digits, hyphen, single check digit
_LOINC_PATTERN = re.compile(r"^\d{1,5}-\d$")

# ICD-10: one letter, two digits, optional ".N..." extension
_ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(\.\d+)?$")

# RxNorm CUI: 4-7 digit numeric string. Used only when paired with a name.
_RXNORM_CUI_PATTERN = re.compile(r"^\d{4,7}$")

# Heuristic column names that strongly imply each registry
_DRUG_COLUMN_HINTS = ("drug", "medication", "medicine", "treatment", "rxnorm")
_DIAGNOSIS_COLUMN_HINTS = ("diagnosis", "icd10", "icd_10", "icd-10", "dx_code")
_LOINC_COLUMN_HINTS = ("loinc",)


# ---------------------------------------------------------------------------
# Index builds (run once at module import)
# ---------------------------------------------------------------------------


def _build_loinc_by_code() -> dict[str, LoincEntry]:
    return {e.loinc_code: e for e in LOINC_REGISTRY}


def _build_icd10_by_code() -> dict[str, Icd10Entry]:
    return {e.icd10_code.upper(): e for e in ICD10_REGISTRY}


def _build_rxnorm_by_name() -> dict[str, RxNormEntry]:
    """Lowercase drug name (generic + brands) → entry."""
    idx: dict[str, RxNormEntry] = {}
    for e in RXNORM_REGISTRY:
        idx[e.drug_name.lower()] = e
        for b in e.brand_names:
            idx[b.lower()] = e
    return idx


def _build_rxnorm_by_cui() -> dict[str, RxNormEntry]:
    return {e.rxnorm_cui: e for e in RXNORM_REGISTRY}


_LOINC_BY_CODE = _build_loinc_by_code()
_ICD10_BY_CODE = _build_icd10_by_code()
_RXNORM_BY_NAME = _build_rxnorm_by_name()
_RXNORM_BY_CUI = _build_rxnorm_by_cui()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stringify(samples: Iterable[object]) -> list[str]:
    out: list[str] = []
    for s in samples:
        if s is None:
            continue
        if isinstance(s, str):
            stripped = s.strip()
            if stripped:
                out.append(stripped)
        else:
            out.append(str(s))
    return out


def _column_name_norm(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def _loinc_from_column_name(column_name: str) -> LoincEntry | None:
    """Return the unique LOINC entry whose alias appears in column_name, else None."""
    norm = _column_name_norm(column_name)
    matches: list[LoincEntry] = []
    for entry in LOINC_REGISTRY:
        for alias in entry.name_aliases:
            alias_norm = alias.lower().replace("-", "_").replace(" ", "_")
            if alias_norm and alias_norm in norm:
                matches.append(entry)
                break
    # Unique match only — ambiguous → defer to Haiku
    if len(matches) == 1:
        return matches[0]
    return None


def _rxnorm_from_samples(samples: list[str]) -> RxNormEntry | None:
    """All samples must resolve to the same RxNorm drug."""
    if not samples:
        return None
    resolved: set[str] = set()
    for s in samples:
        key = s.lower().strip()
        entry = _RXNORM_BY_NAME.get(key)
        if entry is None and _RXNORM_CUI_PATTERN.match(s):
            entry = _RXNORM_BY_CUI.get(s)
        if entry is None:
            return None
        resolved.add(entry.rxnorm_cui)
    if len(resolved) == 1:
        cui = next(iter(resolved))
        return _RXNORM_BY_CUI[cui]
    return None


def _samples_all_match(pattern: re.Pattern[str], samples: list[str]) -> bool:
    return bool(samples) and all(pattern.match(s) for s in samples)


# ---------------------------------------------------------------------------
# Public matcher
# ---------------------------------------------------------------------------


class CodeLookup:
    """
    Deterministic Tier-1 matcher. Stateless; safe to share across requests.

    The constructor takes no required arguments; tests can swap registries
    by subclassing if needed.
    """

    def __init__(self) -> None:
        # All state lives in module-level indexes for now.
        pass

    def match(
        self,
        source_column: str,
        samples: list[object] | None = None,
    ) -> LookupVerdict | None:
        # Param names mirror the zipper.Lookup Protocol (source_column, samples)
        # so CodeLookup conforms structurally and can be injected into the engine.
        sample_strs = _stringify(samples or [])

        # ----- Strategy 1: explicit LOINC code in samples
        if _samples_all_match(_LOINC_PATTERN, sample_strs):
            unique_codes = set(sample_strs)
            if len(unique_codes) == 1:
                loinc_entry = _LOINC_BY_CODE.get(next(iter(unique_codes)))
                if loinc_entry is not None:
                    return self._loinc_verdict(
                        loinc_entry, matched_on="sample_value_code"
                    )

        # ----- Strategy 2: explicit ICD-10 code in samples
        if _samples_all_match(_ICD10_PATTERN, sample_strs):
            unique_codes = {s.upper() for s in sample_strs}
            # All samples might be distinct codes from the same family —
            # accept if every one resolves to a known ICD-10 entry.
            if all(c in _ICD10_BY_CODE for c in unique_codes):
                # Use the first sample as the matched_code (representative)
                entry = _ICD10_BY_CODE[next(iter(unique_codes))]
                return self._icd10_verdict(
                    entry, matched_on="sample_value_code"
                )

        # ----- Strategy 3: RxNorm — samples are drug names / CUIs
        norm_name = _column_name_norm(source_column)
        if any(hint in norm_name for hint in _DRUG_COLUMN_HINTS):
            rx_entry = _rxnorm_from_samples(sample_strs)
            if rx_entry is not None:
                return self._rxnorm_verdict(
                    rx_entry, matched_on="sample_value_code"
                )

        # ----- Strategy 4: LOINC alias in column name (no conflicting samples)
        loinc_entry = _loinc_from_column_name(source_column)
        if loinc_entry is not None:
            return self._loinc_verdict(loinc_entry, matched_on="column_name")

        # ----- Strategy 5: explicit ICD-10 column hint + sample pattern
        if (
            any(hint in norm_name for hint in _DIAGNOSIS_COLUMN_HINTS)
            and _samples_all_match(_ICD10_PATTERN, sample_strs)
        ):
            unique_codes = {s.upper() for s in sample_strs}
            if all(c in _ICD10_BY_CODE for c in unique_codes):
                entry = _ICD10_BY_CODE[next(iter(unique_codes))]
                return self._icd10_verdict(entry, matched_on="column_name")

        return None

    # ------------------------------------------------------------------
    # Verdict factories
    # ------------------------------------------------------------------

    @staticmethod
    def _loinc_verdict(
        entry: LoincEntry,
        matched_on: str,
    ) -> LookupVerdict:
        reason = (
            f"LOINC {entry.loinc_code} ({entry.display}) matched "
            f"by {matched_on}"
        )
        return LookupVerdict(
            canonical_column=entry.canonical_field_name,
            canonical_unit=entry.canonical_unit,
            data_type=entry.value_type,
            matched_registry="LOINC",
            matched_code=entry.loinc_code,
            matched_on="sample_value_code" if matched_on == "sample_value_code"
            else "column_name",
            reason=reason,
        )

    @staticmethod
    def _rxnorm_verdict(
        entry: RxNormEntry,
        matched_on: str,
    ) -> LookupVerdict:
        reason = (
            f"RxNorm {entry.rxnorm_cui} ({entry.drug_name}) matched "
            f"by {matched_on}"
        )
        return LookupVerdict(
            canonical_column=entry.canonical_field_name,
            canonical_unit=None,
            data_type="text",
            matched_registry="RxNorm",
            matched_code=entry.rxnorm_cui,
            matched_on="sample_value_code" if matched_on == "sample_value_code"
            else "column_name",
            reason=reason,
        )

    @staticmethod
    def _icd10_verdict(
        entry: Icd10Entry,
        matched_on: str,
    ) -> LookupVerdict:
        reason = (
            f"ICD-10 {entry.icd10_code} ({entry.display}) matched "
            f"by {matched_on}"
        )
        return LookupVerdict(
            canonical_column=entry.canonical_field_name,
            canonical_unit=None,
            data_type="coded_value",
            matched_registry="ICD-10",
            matched_code=entry.icd10_code,
            matched_on="sample_value_code" if matched_on == "sample_value_code"
            else "column_name",
            reason=reason,
        )
