"""
Minimal UCUM unit-conversion table for the quantity_with_unit data type.

Scope: just the units needed by the oncology demo. Not a general UCUM library
(intentionally — pulling in pint/pint-pandas is way too heavy for this).

Conventions:
 - All units are case-sensitive as they appear in clinical data feeds
   (mg, g, kg, mL, L, mmHg, ...), with a few common-case aliases handled
   in canonicalize_unit_alias().
 - Conversion factor `f` means: value_in_canonical = value_in_unit * f
 - Special-case affine conversions (Fahrenheit↔Celsius) use a function.
 - Glucose and creatinine mg/dL↔mmol/L use analyte-specific factors and
   are exposed as named conversion sets, not generic dimension conversions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

# ---------------------------------------------------------------------------
# Linear conversions: factor to canonical (multiply by f)
# ---------------------------------------------------------------------------

# Mass — canonical g
_MASS: Final[dict[str, float]] = {
    "mg": 1e-3,
    "g": 1.0,
    "kg": 1e3,
    "ug": 1e-6,
    "mcg": 1e-6,
}

# Volume — canonical L
_VOLUME: Final[dict[str, float]] = {
    "mL": 1e-3,
    "ml": 1e-3,
    "L": 1.0,
    "l": 1.0,
}

# Length — canonical m
_LENGTH: Final[dict[str, float]] = {
    "mm": 1e-3,
    "cm": 1e-2,
    "m": 1.0,
    "in": 0.0254,
}

# Mass on weight scale — canonical kg
_BODY_WEIGHT: Final[dict[str, float]] = {
    "kg": 1.0,
    "lb": 0.45359237,
}

# Pressure — mmHg only, no conversion
_PRESSURE: Final[set[str]] = {"mmHg"}

# Concentration units that have no conversion within demo scope
_CONCENTRATION_PASSTHROUGH: Final[set[str]] = {
    "mEq/L",
    "U/L",
    "%",
    "percent",
    "ng/mL",
    "pg/mL",
    "10*3/uL",
    "10*6/uL",
    "cells/uL",
    # Recognized for analyte-specific conversions in convert()
    "mg/dL",
    "mmol/L",
    "umol/L",
    # Common dosing-rate units (no generic conversion in demo)
    "g/dL",
}

# Analyte-specific mg/dL <-> mmol/L conversions.
# value_mmol_per_L = value_mg_per_dL * factor
_ANALYTE_MGDL_TO_MMOL: Final[dict[str, float]] = {
    "glucose": 0.0555,
    # NB: creatinine is conventionally reported mg/dL ↔ μmol/L with factor
    # 88.4. We keep that factor accessible via _ANALYTE_MGDL_TO_UMOL.
    "creatinine": 1.0 / 88.4,
}

_ANALYTE_MGDL_TO_UMOL: Final[dict[str, float]] = {
    "creatinine": 88.4,
}


# All linear groups, keyed by canonical unit
_LINEAR_GROUPS: Final[dict[str, dict[str, float]]] = {
    "g": _MASS,
    "L": _VOLUME,
    "m": _LENGTH,
    "kg": _BODY_WEIGHT,
}


# ---------------------------------------------------------------------------
# Affine conversions (temperature)
# ---------------------------------------------------------------------------


def _f_to_c(v: float) -> float:
    return (v - 32.0) * 5.0 / 9.0


def _c_to_f(v: float) -> float:
    return v * 9.0 / 5.0 + 32.0


_AFFINE: Final[dict[tuple[str, str], Callable[[float], float]]] = {
    ("[degF]", "Cel"): _f_to_c,
    ("degF", "Cel"): _f_to_c,
    ("F", "C"): _f_to_c,
    ("Cel", "[degF]"): _c_to_f,
    ("C", "F"): _c_to_f,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class UnknownUnitError(ValueError):
    """Raised when a unit is outside the demo UCUM table."""


def known_unit(unit: str) -> bool:
    """Return True if `unit` is in any of the demo conversion tables."""
    if unit in _PRESSURE or unit in _CONCENTRATION_PASSTHROUGH:
        return True
    for group in _LINEAR_GROUPS.values():
        if unit in group:
            return True
    return any(unit in pair for pair in _AFFINE)


def convert(
    value: float,
    from_unit: str,
    to_unit: str,
    *,
    analyte: str | None = None,
) -> float:
    """
    Convert ``value`` from ``from_unit`` to ``to_unit``.

    ``analyte`` is required for mg/dL <-> mmol/L (glucose) and
    mg/dL <-> umol/L (creatinine).

    Raises UnknownUnitError when either unit is outside the demo table,
    or the pair is not convertible.
    """
    if from_unit == to_unit:
        return value

    # Affine first
    affine = _AFFINE.get((from_unit, to_unit))
    if affine is not None:
        return affine(value)

    # Analyte-specific concentration conversions
    if analyte is not None:
        if from_unit == "mg/dL" and to_unit == "mmol/L":
            factor = _ANALYTE_MGDL_TO_MMOL.get(analyte)
            if factor is not None:
                return value * factor
        if from_unit == "mmol/L" and to_unit == "mg/dL":
            factor = _ANALYTE_MGDL_TO_MMOL.get(analyte)
            if factor is not None:
                return value / factor
        if from_unit == "mg/dL" and to_unit == "umol/L":
            factor = _ANALYTE_MGDL_TO_UMOL.get(analyte)
            if factor is not None:
                return value * factor
        if from_unit == "umol/L" and to_unit == "mg/dL":
            factor = _ANALYTE_MGDL_TO_UMOL.get(analyte)
            if factor is not None:
                return value / factor

    # Pressure / passthrough — only valid when from == to (already handled)
    if from_unit in _PRESSURE or from_unit in _CONCENTRATION_PASSTHROUGH:
        raise UnknownUnitError(
            f"No conversion from {from_unit!r} to {to_unit!r}"
        )

    # Linear groups: find a group containing both units
    for group in _LINEAR_GROUPS.values():
        if from_unit in group and to_unit in group:
            # value -> canonical -> target
            canonical = value * group[from_unit]
            return canonical / group[to_unit]

    if not known_unit(from_unit):
        raise UnknownUnitError(f"Unknown unit: {from_unit!r}")
    if not known_unit(to_unit):
        raise UnknownUnitError(f"Unknown unit: {to_unit!r}")
    raise UnknownUnitError(
        f"No conversion from {from_unit!r} to {to_unit!r}"
    )


def canonical_for(unit: str) -> str | None:
    """Return the canonical-unit string for ``unit``, or None if unknown."""
    if unit in _PRESSURE:
        return unit
    if unit in _CONCENTRATION_PASSTHROUGH:
        return unit
    for canonical, group in _LINEAR_GROUPS.items():
        if unit in group:
            return canonical
    return None
