"""
Integration tests for the engine's deterministic-lookup tier.

Verifies that:
 - When the lookup tier matches, decided_by='lookup' and Haiku
   is NOT called.
 - The schema row is upserted with the lookup-provided data_type and unit.
 - Second ingest of the same column hits the decision cache (tier 0)
   and again does not call Haiku.
 - When the lookup tier returns None, Haiku is called normally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from ehrzipper.engine import zipper_upsert
from ehrzipper.haiku_router import HaikuRouter
from ehrzipper.lookup import CodeLookup
from ehrzipper.storage_sqlite import SQLiteStorage
from ehrzipper.types import HaikuRoutingVerdict, IngestRow, IngestValue
from tests.conftest import make_fake_anthropic_client

WS = "ehrzipper-default"
PKEY = "pat_001"


def _now() -> str:
    return (
        datetime.now(tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _strict_haiku_router() -> tuple[HaikuRouter, AsyncMock]:
    """
    A router whose Anthropic client raises if `messages.create` is ever called.
    Use to assert "Haiku was not called" in lookup-tier success paths.
    """
    fake_client = MagicMock()
    fake_client.messages = MagicMock()
    fake_client.messages.create = AsyncMock(
        side_effect=AssertionError("Haiku must not be called when lookup matches")
    )
    return HaikuRouter(client=fake_client), fake_client.messages.create


class TestLookupTierFires:
    async def test_loinc_match_skips_haiku(
        self, db_storage: SQLiteStorage
    ) -> None:
        router, haiku_create = _strict_haiku_router()
        lookup = CodeLookup()

        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="lab_csv",
            external_id="lab-1",
            occurred_at=_now(),
            columns={
                "wbc": IngestValue(value="8.4", source_data_type="text"),
            },
        )

        # Pre-stage the schema so quantity_with_unit normalization has a clean target.
        # The lookup tier itself upserts the schema; the value coercion runs after.
        # For a text→quantity_with_unit coercion we need a numeric input.
        row.columns["wbc"] = IngestValue(
            value={"value": 8.4, "unit": "10*3/uL"},
            source_data_type="jsonb",
        )

        result = await zipper_upsert(row, db_storage, router, lookup=lookup)

        assert len(result.decisions) == 1
        d = result.decisions[0]
        assert d.decided_by == "lookup"
        assert d.canonical_name == "wbc_count"
        assert d.verdict == "join"

        # Haiku was never called
        haiku_create.assert_not_called()

        # Schema row was upserted with the LOINC data_type
        schema_rows = db_storage.load_pkey_schema(WS, PKEY)
        wbc_schema = next(
            (s for s in schema_rows if s.canonical_name == "wbc_count"), None
        )
        assert wbc_schema is not None
        assert wbc_schema.data_type == "quantity_with_unit"

    async def test_rxnorm_match_skips_haiku(
        self, db_storage: SQLiteStorage
    ) -> None:
        router, haiku_create = _strict_haiku_router()
        lookup = CodeLookup()

        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="med_csv",
            external_id="med-1",
            occurred_at=_now(),
            columns={
                "drug": IngestValue(value="osimertinib", source_data_type="text"),
            },
        )

        result = await zipper_upsert(row, db_storage, router, lookup=lookup)

        d = result.decisions[0]
        assert d.decided_by == "lookup"
        assert d.canonical_name == "drug_name"
        haiku_create.assert_not_called()

    async def test_second_ingest_hits_cache_not_haiku(
        self, db_storage: SQLiteStorage
    ) -> None:
        """After a lookup decision is cached, the next ingest reuses it."""
        # First ingest — lookup fires.
        router1, _ = _strict_haiku_router()
        lookup = CodeLookup()

        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="med_csv",
            external_id="med-1",
            occurred_at=_now(),
            columns={
                "drug": IngestValue(value="osimertinib", source_data_type="text"),
            },
        )
        r1 = await zipper_upsert(row, db_storage, router1, lookup=lookup)

        # Second ingest — same (pkey, source, source_column), different external_id.
        # The decision cache should resolve before either lookup or Haiku is called.
        # Provide a different lookup that would also assertion-fail to be sure.
        router2, haiku_create2 = _strict_haiku_router()

        class BoomLookup(CodeLookup):
            def match(  # type: ignore[override]
                self,
                source_column: str,
                samples: list[object] | None = None,
            ) -> None:
                raise AssertionError("Cache must short-circuit before lookup runs")

        row2 = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="med_csv",
            external_id="med-2",
            occurred_at=_now(),
            columns={
                "drug": IngestValue(value="alectinib", source_data_type="text"),
            },
        )
        r2 = await zipper_upsert(row2, db_storage, router2, lookup=BoomLookup())

        assert r2.decisions[0].id == r1.decisions[0].id
        assert r2.decisions[0].decided_by == "lookup"
        haiku_create2.assert_not_called()


class TestLookupTierMisses:
    async def test_no_match_falls_through_to_haiku(
        self, db_storage: SQLiteStorage
    ) -> None:
        """When CodeLookup returns None, Haiku gets called as before."""
        verdict = HaikuRoutingVerdict(
            verdict="append",
            canonical_name="free_text_note",
            is_global_target=False,
            similarity_score=0.5,
            reason="no good match",
        )
        client = make_fake_anthropic_client(verdict)
        router = HaikuRouter(client=client)
        lookup = CodeLookup()

        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="src",
            external_id="x-1",
            occurred_at=_now(),
            columns={
                "comments": IngestValue(value="some note", source_data_type="text"),
            },
        )
        result = await zipper_upsert(row, db_storage, router, lookup=lookup)

        assert result.decisions[0].decided_by == "llm"
        client.messages.create.assert_called_once()

    async def test_no_lookup_passed_still_uses_haiku(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Backward compat: lookup=None means engine behaves like before."""
        verdict = HaikuRoutingVerdict(
            verdict="append",
            canonical_name="some_col",
            is_global_target=False,
            similarity_score=0.5,
            reason="ok",
        )
        client = make_fake_anthropic_client(verdict)
        router = HaikuRouter(client=client)

        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="src",
            external_id="x-2",
            occurred_at=_now(),
            columns={
                "wbc": IngestValue(value="8.4", source_data_type="text"),
            },
        )
        # Note: no lookup= kwarg
        result = await zipper_upsert(row, db_storage, router)
        assert result.decisions[0].decided_by == "llm"
