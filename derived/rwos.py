"""
Real-world overall survival (rwOS) derivation.

Per methodology/cohort-definition.md §5 and the rwOS spec:

  * **Index date** = ``advanced_diagnosis_date`` (the cohort anchor).
  * **Event** (event=1) = death, when ``vital_status == "deceased"``; the event
    date is ``date_of_death``.
  * **Censoring** (event=0) = patient alive at data cutoff; censored at
    ``last_known_alive_date``.
  * **OS time** = ``(event_date - index_date).days``.
  * **Precision handling**: a month-precision index date assumes day 15 (see
    derived.dates). The assumption is reported on each record so it is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from derived.dates import parse_partial_date, resolve_date


@dataclass
class SurvivalRecord:
    """One patient's overall-survival observation."""

    patient_id: str
    index_date: date
    event_date: date
    os_days: int
    event: int  # 1 = death, 0 = censored
    vital_status: str
    index_date_precision: str  # "day" | "month" | "year"
    index_date_assumed: bool  # True when the day component was assumed
    age_at_index: int | None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))  # tolerate "67" and "67.0"
    except (ValueError, TypeError):
        return None


def compute_rwos(patients: list[dict[str, Any]]) -> list[SurvivalRecord]:
    """
    Build survival records for a list of CORE.PATIENT-shaped dicts.

    Patients without a resolvable index date, or deceased patients without a
    death date, or alive/unknown patients without a last-known-alive date, are
    skipped (they cannot contribute a valid OS observation).
    """
    records: list[SurvivalRecord] = []
    for p in patients:
        index_date, precision, assumed = parse_partial_date(p.get("advanced_diagnosis_date"))
        if index_date is None:
            continue

        vital = (p.get("vital_status") or "unknown").lower()

        if vital == "deceased":
            event_date = resolve_date(p.get("date_of_death"))
            event = 1
            if event_date is None:
                # Deceased but no death date — fall back to last known alive
                # (censor) rather than dropping; flag via event=0.
                event_date = resolve_date(p.get("last_known_alive_date"))
                event = 0
        else:
            event_date = resolve_date(p.get("last_known_alive_date"))
            event = 0

        if event_date is None:
            continue

        os_days = (event_date - index_date).days
        # Guard against negative follow-up from precision assumptions.
        if os_days < 0:
            os_days = 0
            event_date = index_date

        records.append(
            SurvivalRecord(
                patient_id=str(p.get("patient_id", "")),
                index_date=index_date,
                event_date=event_date,
                os_days=os_days,
                event=event,
                vital_status=vital,
                index_date_precision=precision,
                index_date_assumed=assumed,
                age_at_index=_coerce_int(p.get("age_at_advanced_diagnosis")),
            )
        )
    return records
