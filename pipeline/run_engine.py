"""Run the Zippering reconciliation engine on the synthetic multi-source data.

This is the centerpiece demo: it feeds real columns from the three source
formats (FHIR / HL7v2 / flat CSV) through the three-tier router and writes every
routing decision to the append-only ``META.ZIPPERING_DECISIONS`` table in
Snowflake.

Tiers exercised (CLAUDE.md rule 5):
  - Tier 1 deterministic: columns carrying LOINC / RxNorm / ICD-10 codes resolve
    against the curated registries with no LLM call (decided_by=lookup).
  - Tier 2 LLM: columns with no code match go to Claude Haiku (decided_by=llm).
  - Tier 3 append: Haiku's "append" verdict registers a new canonical field.

Connection: key-pair auth via ehrzipper.sf_connect (handles MFA + clock skew),
injected into SnowflakeStorage with pyformat binds (storage_snowflake uses
%(name)s) and a real DictCursor.

    set -a && . ./.env && set +a
    python pipeline/run_engine.py --n-patients 8 --reset
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from ehrzipper.engine import zipper_upsert  # noqa: E402
from ehrzipper.haiku_router import HaikuRouter  # noqa: E402
from ehrzipper.lookup import CodeLookup  # noqa: E402
from ehrzipper.sf_connect import connect  # noqa: E402
from ehrzipper.storage_snowflake import SnowflakeStorage  # noqa: E402
from ehrzipper.types import IngestRow, IngestValue  # noqa: E402
from synthetic.profiles import PatientProfile, generate_profiles  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover
    from snowflake.connector import SnowflakeConnection

# Source-format label as it would arrive from an integration.
_SOURCE_LABEL = {
    "fhir": "epic_fhir_r4",
    "hl7v2": "legacy_hl7v2",
    "csv": "registry_csv_export",
}


def _build_columns(p: PatientProfile) -> dict[str, IngestValue]:
    """Construct a representative ingest row that exercises all three tiers.

    Coded columns (Tier 1): lab LOINC code, drug RxNorm code, ICD-10 diagnosis.
    Ambiguous columns (Tier 2/3): ECOG and histology free-text with no code.
    """
    cols: dict[str, IngestValue] = {}

    # Tier 1 — LOINC: a coded lab value (sample is the LOINC code).
    if p.lab_observations:
        lab = p.lab_observations[0]
        cols["lab_test_code"] = IngestValue(
            value=lab.loinc_code,
            source_data_type="coded_value",
            source_description=f"Coded lab result ({lab.display})",
        )

    # Tier 1 — RxNorm: a coded medication (sample is the drug name).
    if p.drug_administrations:
        drug = p.drug_administrations[0]
        cols["medication"] = IngestValue(
            value=drug.display,
            source_data_type="coded_value",
            source_description="Administered systemic therapy",
        )

    # Tier 1 — ICD-10: the primary diagnosis code.
    cols["diagnosis_code"] = IngestValue(
        value=p.icd10_code,
        source_data_type="coded_value",
        source_description="Primary cancer diagnosis (ICD-10-CM)",
    )

    # Tier 2/3 — no code; the LLM must decide how to route these.
    cols["ecog_performance_status"] = IngestValue(
        value=p.ecog_at_advanced_diagnosis,
        source_data_type="integer",
        source_description="Clinician-recorded performance status",
    )
    cols["tumor_histology_text"] = IngestValue(
        value=p.histology,
        source_data_type="text",
        source_description="Free-text histology from the pathology narrative",
    )
    return cols


def _reset_meta(conn: SnowflakeConnection) -> None:
    """Clear the META audit tables for a clean demo run.

    This is a setup-time reset (DDL TRUNCATE), not a runtime mutation — the
    append-only invariant governs the engine's writes during a run, which only
    ever INSERT.
    """
    cur = conn.cursor()
    try:
        for tbl in (
            "META.ZIPPERING_DECISIONS",
            "META.ZIPPERING_SCHEMA",
            "META.ZIPPERED_SIGNALS",
        ):
            cur.execute(f"TRUNCATE TABLE IF EXISTS {tbl}")
        conn.commit()
    finally:
        cur.close()


async def _run(profiles: list[PatientProfile], storage: SnowflakeStorage) -> Counter[str]:
    router = HaikuRouter()  # reads ANTHROPIC_API_KEY from the environment
    lookup = CodeLookup()
    tally: Counter[str] = Counter()

    for p in profiles:
        source = _SOURCE_LABEL.get(p.source_format, p.source_format)
        row = IngestRow(
            pkey=p.patient_id,
            source=source,
            external_id=f"{source}:{p.patient_id}",
            occurred_at=p.advanced_diagnosis_date.isoformat(),
            columns=_build_columns(p),
        )
        result = await zipper_upsert(row, storage, router, lookup)
        for d in result.decisions:
            tally[d.decided_by] += 1
            tally[f"verdict:{d.verdict}"] += 1
        tally["rows"] += 1
    return tally


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Zippering engine on synthetic data")
    ap.add_argument("--n-patients", type=int, default=8, help="How many patients to feed")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="Truncate META tables first")
    args = ap.parse_args(argv)

    profiles = generate_profiles(n=50, seed=args.seed)[: args.n_patients]

    # pyformat binds because storage_snowflake uses %(name)s; dict_cursor so the
    # read parsing (keyed by column name) works against the real connection.
    conn = connect(paramstyle="pyformat")
    try:
        if args.reset:
            _reset_meta(conn)
        storage = SnowflakeStorage(connection=conn, dict_cursor=True)
        tally = asyncio.run(_run(profiles, storage))
    finally:
        conn.close()

    print("== Zippering engine run ==")
    print(f"  patients fed        {tally['rows']}")
    print("  -- decisions by tier --")
    print(f"  lookup (deterministic){tally['lookup']:>5}")
    print(f"  llm (haiku)           {tally['llm']:>5}")
    print(f"  normalizer (review)   {tally['normalizer']:>5}")
    print("  -- by verdict --")
    for key in sorted(k for k in tally if k.startswith("verdict:")):
        print(f"  {key:<20}{tally[key]:>5}")
    print("== done — decisions written to META.ZIPPERING_DECISIONS (append-only) ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
