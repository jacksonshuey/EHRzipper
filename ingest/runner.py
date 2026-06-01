"""Reconciliation runner — uploaded files in, provenance report out.

Wires the format adapters to the three-tier engine: parse each file into
IngestRows, run them through ``zipper_upsert`` against a fresh SQLite store
(seeded with the clinical data dictionary), and collect the append-only
decisions plus the merged canonical record per patient.

Tier 2 (LLM semantic match) needs ``ANTHROPIC_API_KEY``. When it is absent the
runner degrades honestly: it routes only the columns the deterministic Tier-1
lookup can resolve and reports the rest as "held for review" — it never labels
a non-LLM decision as an LLM one.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from pathlib import Path
from typing import Any

from ehrzipper.engine import get_merged_record, zipper_upsert
from ehrzipper.lookup import CodeLookup
from ehrzipper.storage_sqlite import SQLiteStorage
from ehrzipper.types import IngestRow, ZipperingDecisionRow
from ingest.adapters import parse_file
from ingest.types import FileOutcome, IngestReport, UploadedFile

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "ehrzipper"
    / "migrations"
    / "001_zippering_tables.sql"
)
_WORKSPACE = "ehrzipper-default"


class _OfflineRouter:
    """Stand-in router for when no LLM is configured.

    The runner pre-filters columns so this is never actually invoked; if it is,
    failing loudly is correct — we must not silently fabricate an LLM verdict.
    """

    async def assess(self, inputs: Any) -> Any:
        raise RuntimeError(
            "LLM routing tier is offline (no ANTHROPIC_API_KEY) and a column "
            f"reached it: {getattr(inputs, 'source_column', '?')}"
        )


def _build_router() -> tuple[Any, bool]:
    """Return (router, llm_available)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        from ehrzipper.haiku_router import HaikuRouter

        return HaikuRouter(), True
    return _OfflineRouter(), False


def _decision_dict(d: ZipperingDecisionRow) -> dict[str, Any]:
    return {
        "source": d.source,
        "source_column": d.source_column,
        "source_data_type": d.source_data_type,
        "canonical_name": d.canonical_name,
        "decided_by": d.decided_by,
        "similarity_score": d.similarity_score,
        "verdict": d.verdict,
        "reason": d.reason,
        "needs_review": d.needs_review,
        "decided_at": d.decided_at,
    }


def _filter_offline(
    row: IngestRow, lookup: CodeLookup, held: list[dict[str, Any]]
) -> IngestRow:
    """Keep only columns the deterministic tier can resolve; record the rest."""
    keep: dict[str, Any] = {}
    for col, val in row.columns.items():
        samples = [val.value] if val.value is not None else []
        if lookup.match(col, samples) is not None:
            keep[col] = val
        else:
            held.append(
                {
                    "source": row.source,
                    "source_column": col,
                    "source_data_type": val.source_data_type,
                    "reason": "Routes via Tier 2 (LLM) — offline in this environment.",
                }
            )
    return row.model_copy(update={"columns": keep})


async def _process(
    rows: list[IngestRow],
    storage: SQLiteStorage,
    router: Any,
    lookup: CodeLookup,
    report: IngestReport,
) -> None:
    tally: Counter[str] = Counter()
    pkeys: list[str] = []

    for row in rows:
        try:
            result = await zipper_upsert(row, storage, router, lookup)
        except Exception as err:
            tally["errors"] += 1
            report.held_columns.append(
                {
                    "source": row.source,
                    "source_column": "(row)",
                    "source_data_type": None,
                    "reason": f"Reconciliation failed: {err}",
                }
            )
            continue

        if row.pkey not in pkeys:
            pkeys.append(row.pkey)
        for d in result.decisions:
            report.decisions.append(_decision_dict(d))
            tally[d.decided_by] += 1
            tally[f"verdict:{d.verdict}"] += 1

    for pk in pkeys:
        report.canonical_records[pk] = await get_merged_record(_WORKSPACE, pk, storage)

    report.tally = dict(tally)


def run_ingest(
    files: list[UploadedFile], db_path: str = ":memory:"
) -> IngestReport:
    """Parse + reconcile uploaded files, returning a provenance report."""
    storage = SQLiteStorage(db_path=db_path)
    storage.apply_migration(_MIGRATION.read_text(encoding="utf-8"))
    lookup = CodeLookup()
    router, llm_available = _build_router()
    report = IngestReport(llm_available=llm_available)

    all_rows: list[IngestRow] = []
    for f in files:
        outcome = FileOutcome(name=f.name)
        try:
            fmt, rows = parse_file(f)
            outcome.detected_format = fmt
            if not llm_available:
                rows = [_filter_offline(r, lookup, report.held_columns) for r in rows]
                rows = [r for r in rows if r.columns]
            outcome.n_records = len(rows)
            all_rows.extend(rows)
        except Exception as err:
            outcome.error = str(err)
        report.files.append(outcome)

    if all_rows:
        asyncio.run(_process(all_rows, storage, router, lookup, report))

    storage.close()
    return report
