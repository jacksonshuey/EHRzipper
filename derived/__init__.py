"""
EHRzipper derived clinical variables (P5).

Two endpoint engines that turn the canonical CORE event store into the
analytic variables pharma RWE buyers actually consume:

  * Lines of therapy (:func:`compute_lot`) — Flatiron-aligned regimen lines.
  * Real-world overall survival (:func:`compute_rwos`) + Kaplan-Meier
    (:func:`kaplan_meier`).

The Python engines compute locally against synthetic data; the production
equivalents live in ``snowflake/ddl/05_marts.sql``.
"""

from __future__ import annotations

from derived.km import KMResult, greenwood_variance, kaplan_meier
from derived.lot import TherapyLine, compute_lot
from derived.lot_validator import LotWarning, validate_lot
from derived.pipeline import run_derived_variables
from derived.rwos import SurvivalRecord, compute_rwos

__all__ = [
    "KMResult",
    "LotWarning",
    "SurvivalRecord",
    "TherapyLine",
    "compute_lot",
    "compute_rwos",
    "greenwood_variance",
    "kaplan_meier",
    "run_derived_variables",
    "validate_lot",
]
