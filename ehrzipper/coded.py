"""
Coded-value helpers — validation against a controlled vocabulary.

A `controlled_vocabulary` from the canonical-schema seed CSV is a
pipe-separated list of allowed codes for a coded_value column, e.g.::

    male|female|unknown

Matching is case-insensitive. If a column row has no vocabulary, any code
is accepted (the upstream schema is open).
"""

from __future__ import annotations


def parse_vocabulary(spec: str | None) -> list[str] | None:
    """
    Parse a pipe-separated controlled-vocabulary string.

    Returns None if `spec` is None or empty (= no validation).
    Returns a list of codes (preserving original case for display).
    """
    if spec is None:
        return None
    s = spec.strip()
    if not s:
        return None
    return [c.strip() for c in s.split("|") if c.strip()]


def is_allowed(code: str, vocabulary: list[str] | None) -> bool:
    """Return True if ``code`` is in ``vocabulary`` (case-insensitive)."""
    if vocabulary is None:
        return True
    lowered = code.strip().lower()
    return any(v.strip().lower() == lowered for v in vocabulary)


def canonicalize_code(code: str, vocabulary: list[str] | None) -> str:
    """
    Return the vocabulary's canonical-cased form of ``code`` when possible,
    otherwise return ``code`` unchanged. Useful so we store the
    schema-canonical spelling rather than whatever case the source used.
    """
    if vocabulary is None:
        return code
    lowered = code.strip().lower()
    for v in vocabulary:
        if v.strip().lower() == lowered:
            return v
    return code
