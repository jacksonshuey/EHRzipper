"""
Lines of Therapy (LoT) derivation — Flatiron-aligned.

A *line of therapy* is a continuous course of antineoplastic treatment. The
engine ingests ``medication_administration`` events (one row per drug per
administration) and ``progression_event`` rows, and emits an ordered list of
:class:`TherapyLine`.

Rules (see module-level tests and methodology/cohort-definition.md §1):

  1. **New line** when the prior line is discontinued AND a drug not in the
     prior regimen is introduced (a genuinely new agent, not maintenance of an
     existing one).
  2. **Same line continues** when:
       - a drug is *added* to an ongoing regimen (regimen expansion), or
       - maintenance therapy continues after induction (the backbone drops out
         but a persisting agent carries on — flagged ``is_maintenance``), or
       - there is a brief interruption (< ``gap_threshold_days``) in the same
         drugs followed by a restart of those same drugs.
  3. **New line after progression**: a progression event followed by *different*
     drugs starts a new line regardless of the gap length.
  4. **Combination = one regimen**: drugs administered within
     ``combination_window_days`` of each other that persist together are one
     regimen, not sequential lines.

Implementation strategy
------------------------
Administrations are first collapsed into *episodes* per drug (consecutive
administrations of the same drug with no gap larger than the threshold form one
continuous drug episode). Episodes are then swept chronologically; the active
regimen is the set of drug episodes overlapping (within the combination window)
the current line. A new line is opened when the rules above fire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from derived.dates import resolve_date
from derived.drugs import normalize_drug_name, regimen_drug_class

EndReason = Literal["progression", "toxicity", "completion", "death", "unknown"]


@dataclass
class TherapyLine:
    """One derived line of therapy for a single patient."""

    line_number: int
    drugs: list[str]
    start_date: date
    end_date: date | None
    end_reason: EndReason | None
    is_maintenance: bool
    regimen_label: str
    drug_class: str


@dataclass
class _DrugEpisode:
    """A continuous course of a single drug."""

    name: str
    canonical_class: str | None
    start: date
    end: date
    admin_count: int = 1
    canonical_classes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Episode construction
# ---------------------------------------------------------------------------


def _build_drug_episodes(
    medication_events: list[dict[str, Any]],
    gap_threshold_days: int,
) -> list[_DrugEpisode]:
    """Collapse per-administration rows into continuous per-drug episodes."""
    # Group administrations by normalized drug name.
    by_drug: dict[str, list[tuple[date, date, str | None]]] = {}
    for ev in medication_events:
        name = ev.get("display") or ev.get("drug_name") or ev.get("medication_code")
        if isinstance(name, dict):  # coded_value
            name = name.get("display") or name.get("code")
        if not name:
            continue
        start = resolve_date(ev.get("start_date"))
        if start is None:
            continue
        end = resolve_date(ev.get("end_date")) or start
        if end < start:
            end = start
        canon = ev.get("drug_class")
        by_drug.setdefault(normalize_drug_name(str(name)), []).append((start, end, canon))

    episodes: list[_DrugEpisode] = []
    for drug, admins in by_drug.items():
        admins.sort(key=lambda a: a[0])
        cur: _DrugEpisode | None = None
        for start, end, canon in admins:
            if cur is None:
                cur = _DrugEpisode(drug, canon, start, end, 1, [canon] if canon else [])
                continue
            # Same drug resuming within the gap threshold → still one episode.
            if (start - cur.end).days <= gap_threshold_days:
                cur.end = max(cur.end, end)
                cur.admin_count += 1
                if canon:
                    cur.canonical_classes.append(canon)
            else:
                episodes.append(cur)
                cur = _DrugEpisode(drug, canon, start, end, 1, [canon] if canon else [])
        if cur is not None:
            episodes.append(cur)

    episodes.sort(key=lambda e: (e.start, e.name))
    return episodes


def _parse_progressions(progression_events: list[dict[str, Any]]) -> list[date]:
    dates: list[date] = []
    for pe in progression_events:
        # Only on-treatment / recurrence progressions advance the line clock;
        # a "to_advanced" event is the cohort index, not a treatment-line break.
        ptype = (pe.get("progression_type") or "").lower()
        if ptype == "to_advanced":
            continue
        d = resolve_date(pe.get("event_date"))
        if d is not None:
            dates.append(d)
    return sorted(dates)


# ---------------------------------------------------------------------------
# Line assembly
# ---------------------------------------------------------------------------


@dataclass
class _Line:
    episodes: list[_DrugEpisode]
    start: date
    after_progression: bool = False

    @property
    def drug_names(self) -> set[str]:
        return {e.name for e in self.episodes}

    @property
    def end(self) -> date:
        return max(e.end for e in self.episodes)


def _label_and_finalize(
    line: _Line,
    line_number: int,
    next_line_start: date | None,
    progression_dates: list[date],
    deceased_date: date | None,
) -> TherapyLine:
    """Produce a TherapyLine: ordered drugs, label, class, end reason, maintenance."""
    # Order drugs by episode start then name for a stable, readable label.
    ordered = sorted(line.episodes, key=lambda e: (e.start, e.name))
    drug_names = [e.name for e in ordered]
    classes = [e.canonical_class for e in ordered]

    # Maintenance: induction had >1 drug, but the line ends on a single
    # persisting agent (a backbone partner dropped out while one continued).
    is_maintenance = _detect_maintenance(ordered)

    label = " + ".join(drug_names)
    dclass = regimen_drug_class(drug_names, classes)

    line_end = line.end
    end_reason: EndReason | None
    if deceased_date is not None and abs((deceased_date - line_end).days) <= 90 and (
        next_line_start is None
    ):
        end_reason = "death"
        end_date: date | None = line_end
    elif next_line_start is not None:
        # A subsequent line exists. If a progression sits between this line's
        # end and the next start, attribute the end to progression.
        progressed = any(line_end <= p <= next_line_start for p in progression_dates)
        end_reason = "progression" if progressed else "completion"
        end_date = line_end
    else:
        # No next line. Ongoing vs. completed is ambiguous from meds alone;
        # report end_date as last administration with unknown reason.
        end_reason = "unknown"
        end_date = line_end

    return TherapyLine(
        line_number=line_number,
        drugs=drug_names,
        start_date=line.start,
        end_date=end_date,
        end_reason=end_reason,
        is_maintenance=is_maintenance,
        regimen_label=label,
        drug_class=dclass,
    )


def _detect_maintenance(ordered: list[_DrugEpisode]) -> bool:
    """
    A line shows maintenance when an induction combination (>=2 drugs) narrows
    to a single agent that continues meaningfully past the others.

    Heuristic: at least one drug's episode ends >= 42 days (two ~21-day cycles)
    after the latest end among the *other* drugs, AND the induction had >=2
    distinct drugs. The persisting agent is typically IO (pembrolizumab) or an
    antifolate (pemetrexed).
    """
    if len(ordered) < 2:
        return False
    overall_end = max(e.end for e in ordered)
    for ep in ordered:
        if ep.end < overall_end:
            continue
        others_end = max((o.end for o in ordered if o is not ep), default=ep.end)
        if (ep.end - others_end).days >= 42:
            return True
    return False


def compute_lot(
    medication_events: list[dict[str, Any]],
    progression_events: list[dict[str, Any]],
    gap_threshold_days: int = 90,
    combination_window_days: int = 28,
    deceased_date: date | None = None,
) -> list[TherapyLine]:
    """
    Derive ordered lines of therapy for a single patient.

    Args:
        medication_events: CORE.MEDICATION_ADMINISTRATION-shaped dicts.
            Recognized keys: display | drug_name | medication_code,
            start_date, end_date, drug_class.
        progression_events: CORE.PROGRESSION_EVENT-shaped dicts
            (event_date, progression_type).
        gap_threshold_days: gap in the *same* drugs beyond which a restart is a
            new line (and within which it is one continuous course).
        combination_window_days: drugs starting within this window of the line
            anchor are part of the same combination regimen.
        deceased_date: resolved date of death, used to set end_reason="death".

    Returns:
        Lines ordered by ``line_number`` (1-based).
    """
    episodes = _build_drug_episodes(medication_events, gap_threshold_days)
    if not episodes:
        return []
    progression_dates = _parse_progressions(progression_events)

    lines: list[_Line] = []
    current = _Line(episodes=[episodes[0]], start=episodes[0].start)

    for ep in episodes[1:]:
        cur_drugs = current.drug_names
        is_new_drug = ep.name not in cur_drugs

        # Has a progression occurred since the current line started, at or
        # before this episode begins?
        progression_between = any(current.start <= p <= ep.start for p in progression_dates)

        # Gap from the current line's running end to this episode's start.
        gap = (ep.start - current.end).days

        if not is_new_drug:
            # Same drug resuming. Episode construction already merged within
            # gap_threshold, so reaching here means a long gap → new line.
            _close_and_open(lines, current)
            current = _Line(episodes=[ep], start=ep.start)
            continue

        # New drug introduced.
        if progression_between:
            # Rule 3: progression + different drug → new line, any gap.
            _close_and_open(lines, current)
            current = _Line(episodes=[ep], start=ep.start, after_progression=True)
            continue

        if ep.start <= current.start + timedelta(days=combination_window_days):
            # Rule 4: started within the combination window of the line anchor
            # → part of the initial combination regimen.
            current.episodes.append(ep)
            continue

        if gap <= combination_window_days:
            # Rule 2: a new drug *added* to an ongoing regimen (regimen
            # expansion, e.g. adding bevacizumab mid-treatment) → same line.
            current.episodes.append(ep)
            continue

        # New drug, no progression, but a real gap with the prior regimen
        # already wound down → new line (rule 1).
        _close_and_open(lines, current)
        current = _Line(episodes=[ep], start=ep.start)

    lines.append(current)

    # Finalize with line numbers, labels, and end reasons.
    out: list[TherapyLine] = []
    for i, ln in enumerate(lines):
        next_start = lines[i + 1].start if i + 1 < len(lines) else None
        out.append(
            _label_and_finalize(
                ln, i + 1, next_start, progression_dates, deceased_date
            )
        )
    return out


def _close_and_open(lines: list[_Line], current: _Line) -> None:
    lines.append(current)
