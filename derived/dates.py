"""
Precision-aware date parsing for derived-variable engines.

Input dates arrive in two shapes depending on source:

  1. A plain ISO string ("2020-04-01", "2020-04", "2020") — synthetic CSV/FHIR.
  2. A canonical ``partial_date`` dict ``{"value": "1952-08", "precision":
     "month"}`` — CORE VARIANT columns (canonical-schema.md).

Both resolve to a concrete ``datetime.date`` plus a precision tag. When a
component is missing we ASSUME a value and report the assumption so survival
math is reproducible and auditable:

  * month precision  → assume day 15  (mid-month; minimizes max error vs. day 1)
  * year precision   → assume July 1  (mid-year)

The "day 15" rule for month-precision index dates is mandated by the rwOS
methodology and is applied here centrally so every engine agrees.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Day assumed when only month is known (mid-month).
ASSUMED_DAY_FOR_MONTH = 15
# Month/day assumed when only year is known (mid-year).
ASSUMED_MONTH_FOR_YEAR = 7
ASSUMED_DAY_FOR_YEAR = 1


def parse_partial_date(raw: Any) -> tuple[date | None, str, bool]:
    """
    Resolve a raw date value to ``(date, precision, assumed)``.

    Returns ``(None, "unknown", False)`` when the value is missing/empty.
    ``assumed`` is True when any component (day, or month+day) was filled in.
    """
    if raw is None:
        return None, "unknown", False

    value: str
    precision: str | None

    if isinstance(raw, dict):
        value = str(raw.get("value", "")).strip()
        precision = raw.get("precision")
    else:
        value = str(raw).strip()
        precision = None

    if not value or value.lower() in {"none", "null", "nan", "unknown"}:
        return None, "unknown", False

    # Normalize: drop any time component if a full timestamp was supplied.
    value = value.split("T")[0].split(" ")[0]
    parts = value.split("-")

    try:
        if len(parts) >= 3:
            resolved = date(int(parts[0]), int(parts[1]), int(parts[2]))
            return resolved, precision or "day", False
        if len(parts) == 2:
            resolved = date(int(parts[0]), int(parts[1]), ASSUMED_DAY_FOR_MONTH)
            return resolved, precision or "month", True
        if len(parts) == 1 and parts[0]:
            resolved = date(int(parts[0]), ASSUMED_MONTH_FOR_YEAR, ASSUMED_DAY_FOR_YEAR)
            return resolved, precision or "year", True
    except (ValueError, TypeError):
        return None, "unknown", False

    return None, "unknown", False


def resolve_date(raw: Any) -> date | None:
    """Convenience: resolved date only (assumptions applied), or None."""
    return parse_partial_date(raw)[0]
