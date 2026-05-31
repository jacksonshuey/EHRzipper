"""
Write-time type normalization — port of zippering-coercions.ts, with
healthcare-extension types layered on top (partial_date, quantity_with_unit,
coded_value).

Provides:
    UnsafeCoercion  — raised when a coercion is not registered or fails at runtime.
    normalize()     — coerce `value` from `from_type` to `to_type`.

For healthcare types, the schema row carries extra metadata (canonical_unit,
controlled_vocabulary, analyte). Pass these via the `context` kwarg.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, TypedDict

from zipper.coercions import UnsafeCoercion as _ZipperUnsafeCoercion

from ehrzipper.coded import canonicalize_code, is_allowed, parse_vocabulary
from ehrzipper.ucum import UnknownUnitError, canonical_for, convert, known_unit


class CoercionContext(TypedDict, total=False):
    """Optional per-call context passed to coercers from the engine."""

    canonical_unit: str | None
    controlled_vocabulary: str | None  # pipe-separated, e.g. "male|female|unknown"
    analyte: str | None
    code_system: str | None  # default `system` for bare-string coded_value


class UnsafeCoercion(_ZipperUnsafeCoercion):
    """Raised when a type coercion is either unregistered or fails at runtime.

    Subclass of zipper's ``UnsafeCoercion`` so the engine's
    ``except zipper.coercions.UnsafeCoercion`` catch routes a failed healthcare
    coercion to review instead of crashing ingest. Sets ``self.name`` for parity
    with the TypeScript original (the base class does not).
    """

    def __init__(
        self,
        from_type: str,
        to_type: str,
        value: Any,
        detail: str | None = None,
    ) -> None:
        super().__init__(from_type, to_type, value, detail)
        self.name = "UnsafeCoercion"


# ---------------------------------------------------------------------------
# Generic scalar coercers (domain-agnostic, inherited from the zipper core)
# ---------------------------------------------------------------------------

_CoercionKey = str  # "{from}→{to}"
_Coercer = Callable[[Any], Any]


def _text_to_integer(v: Any) -> int:
    if not isinstance(v, str):
        raise UnsafeCoercion("text", "integer", v)
    try:
        return int(v, 10)
    except ValueError:
        raise UnsafeCoercion("text", "integer", v) from None


def _integer_to_timestamp(v: Any) -> str:
    return (
        datetime.fromtimestamp(int(v) / 1000.0, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _timestamp_to_integer(v: Any) -> int:
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _text_to_timestamp(v: Any) -> str:
    try:
        s = str(v)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise UnsafeCoercion("text", "timestamp", v) from None


_BASIC_COERCERS: dict[_CoercionKey, _Coercer] = {
    "integer→text":      lambda v: str(v),
    "numeric→text":      lambda v: str(v),
    "text→integer":      _text_to_integer,
    "integer→timestamp": _integer_to_timestamp,
    "timestamp→integer": _timestamp_to_integer,
    "text→timestamp":    _text_to_timestamp,
    "text→string[]":     lambda v: [v],
    "string[]→jsonb":    lambda v: v,
    "text→jsonb":        lambda v: v,
}


# ---------------------------------------------------------------------------
# partial_date
# ---------------------------------------------------------------------------

# YYYY                e.g. "2024"
_RE_YEAR = re.compile(r"^(\d{4})$")
# YYYY-MM             e.g. "2024-06"
_RE_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
# YYYY-MM-DD          e.g. "2024-06-15"
_RE_YEAR_MONTH_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
# MM/YYYY             e.g. "06/2024"
_RE_MM_YYYY = re.compile(r"^(\d{1,2})/(\d{4})$")
# Mon YYYY            e.g. "Jun 2024", "June 2024"
_RE_MONTH_NAME = re.compile(r"^([A-Za-z]{3,9})\s+(\d{4})$")
# Q1 YYYY             e.g. "Q2 2024"  -> month = quarter * 3
_RE_QUARTER = re.compile(r"^[Qq]([1-4])\s+(\d{4})$")

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _partial_date(year: int, month: int | None, day: int | None) -> dict[str, Any]:
    if month is not None and not (1 <= month <= 12):
        raise UnsafeCoercion("text", "partial_date", f"{year}-{month}", "month out of range")
    if day is not None:
        if month is None:
            raise UnsafeCoercion(
                "text", "partial_date", f"{year}--{day}",
                "day specified without month",
            )
        if not (1 <= day <= 31):
            raise UnsafeCoercion(
                "text", "partial_date", f"{year}-{month}-{day}", "day out of range"
            )
    if day is not None:
        precision: str = "day"
    elif month is not None:
        precision = "month"
    else:
        precision = "year"
    return {"year": year, "month": month, "day": day, "precision": precision}


def _to_partial_date(v: Any) -> dict[str, Any]:
    # Already in canonical form
    if isinstance(v, dict) and "year" in v and "precision" in v:
        year_v = v["year"]
        if not isinstance(year_v, int):
            raise UnsafeCoercion("jsonb", "partial_date", v, "year must be int")
        month_v = v.get("month")
        day_v = v.get("day")
        if month_v is not None and not isinstance(month_v, int):
            raise UnsafeCoercion("jsonb", "partial_date", v, "month must be int|None")
        if day_v is not None and not isinstance(day_v, int):
            raise UnsafeCoercion("jsonb", "partial_date", v, "day must be int|None")
        return _partial_date(year_v, month_v, day_v)

    if isinstance(v, datetime):
        return _partial_date(v.year, v.month, v.day)
    if isinstance(v, date):
        return _partial_date(v.year, v.month, v.day)

    if not isinstance(v, str):
        raise UnsafeCoercion("text", "partial_date", v)

    s = v.strip()

    # Try ISO-style first (with optional time component handled by datetime)
    if m := _RE_YEAR_MONTH_DAY.match(s):
        return _partial_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _RE_YEAR_MONTH.match(s):
        return _partial_date(int(m.group(1)), int(m.group(2)), None)
    if m := _RE_YEAR.match(s):
        return _partial_date(int(m.group(1)), None, None)
    if m := _RE_MM_YYYY.match(s):
        return _partial_date(int(m.group(2)), int(m.group(1)), None)
    if m := _RE_MONTH_NAME.match(s):
        month = _MONTH_NAMES.get(m.group(1).lower())
        if month is None:
            raise UnsafeCoercion("text", "partial_date", v, f"unknown month: {m.group(1)}")
        return _partial_date(int(m.group(2)), month, None)
    if m := _RE_QUARTER.match(s):
        quarter = int(m.group(1))
        return _partial_date(int(m.group(2)), quarter * 3, None)

    # Last resort: ISO datetime string
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return _partial_date(dt.year, dt.month, dt.day)
    except (ValueError, TypeError):
        raise UnsafeCoercion("text", "partial_date", v) from None


# ---------------------------------------------------------------------------
# quantity_with_unit
# ---------------------------------------------------------------------------


def _to_quantity_with_unit(v: Any, ctx: CoercionContext) -> dict[str, Any]:
    """
    Accept either:
      - {"value": float, "unit": str}
      - "12.5 mg"  (number + space + unit token)
    Convert into canonical units when ctx.canonical_unit is set.
    """
    value: float
    unit: str

    if isinstance(v, dict):
        raw_value = v.get("value")
        raw_unit = v.get("unit")
        if raw_value is None or raw_unit is None:
            raise UnsafeCoercion(
                "jsonb", "quantity_with_unit", v, "missing value or unit",
            )
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise UnsafeCoercion(
                "jsonb", "quantity_with_unit", v, "value must be numeric",
            ) from None
        if not isinstance(raw_unit, str) or not raw_unit:
            raise UnsafeCoercion(
                "jsonb", "quantity_with_unit", v, "unit must be a non-empty string",
            )
        unit = raw_unit
    elif isinstance(v, str):
        parts = v.strip().split(None, 1)
        if len(parts) != 2:
            raise UnsafeCoercion(
                "text", "quantity_with_unit", v,
                "expected '<number> <unit>'",
            )
        try:
            value = float(parts[0])
        except ValueError:
            raise UnsafeCoercion(
                "text", "quantity_with_unit", v, "non-numeric value",
            ) from None
        unit = parts[1]
    else:
        raise UnsafeCoercion("jsonb", "quantity_with_unit", v)

    if not known_unit(unit):
        raise UnsafeCoercion(
            "jsonb", "quantity_with_unit", v, f"unknown unit: {unit!r}"
        )

    canonical_unit = ctx.get("canonical_unit") or canonical_for(unit) or unit
    analyte = ctx.get("analyte")
    try:
        canonical_value = convert(value, unit, canonical_unit, analyte=analyte)
    except UnknownUnitError as err:
        raise UnsafeCoercion(
            "jsonb", "quantity_with_unit", v, str(err)
        ) from None

    return {
        "value": value,
        "unit": unit,
        "canonical_value": canonical_value,
        "canonical_unit": canonical_unit,
    }


# ---------------------------------------------------------------------------
# coded_value
# ---------------------------------------------------------------------------


def _to_coded_value(v: Any, ctx: CoercionContext) -> dict[str, Any]:
    vocab = parse_vocabulary(ctx.get("controlled_vocabulary"))
    default_system = ctx.get("code_system")

    code: str
    system: str | None
    display: str | None = None

    if isinstance(v, str):
        code = v.strip()
        system = default_system
    elif isinstance(v, dict):
        raw_code = v.get("code")
        if not isinstance(raw_code, str) or not raw_code.strip():
            raise UnsafeCoercion("jsonb", "coded_value", v, "missing code")
        code = raw_code.strip()
        raw_system = v.get("system")
        system = raw_system if isinstance(raw_system, str) and raw_system else default_system
        raw_display = v.get("display")
        if isinstance(raw_display, str) and raw_display:
            display = raw_display
    else:
        raise UnsafeCoercion("jsonb", "coded_value", v, "expected str or dict")

    if not is_allowed(code, vocab):
        raise UnsafeCoercion(
            "jsonb", "coded_value", v,
            f"code {code!r} not in controlled vocabulary",
        )

    canonical_code = canonicalize_code(code, vocab)
    if system is None:
        raise UnsafeCoercion(
            "jsonb", "coded_value", v, "no code_system provided in schema or value",
        )
    return {"code": canonical_code, "system": system, "display": display}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize(
    value: Any,
    from_type: str,
    to_type: str,
    context: CoercionContext | None = None,
) -> Any:
    """
    Coerce ``value`` from ``from_type`` to ``to_type``.

    - Identity (from == to): for the healthcare types, still passes through
      the canonicalizer so vocab validation / unit conversion runs.
    - Registered basic coercion: applies the coercer; may raise UnsafeCoercion.
    - Unregistered pair: raises UnsafeCoercion.
    """
    ctx: CoercionContext = context or {}

    # Healthcare-type targets: route to dedicated coercers regardless of
    # from_type. Identity passes through for validation.
    if to_type == "partial_date":
        return _to_partial_date(value)
    if to_type == "quantity_with_unit":
        return _to_quantity_with_unit(value, ctx)
    if to_type == "coded_value":
        return _to_coded_value(value, ctx)

    # Plain identity for non-healthcare types
    if from_type == to_type:
        return value

    key = f"{from_type}→{to_type}"
    coercer = _BASIC_COERCERS.get(key)
    if coercer is None:
        raise UnsafeCoercion(from_type, to_type, value)
    return coercer(value)
