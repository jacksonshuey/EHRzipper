"""
Tests for ehrzipper/engine.py — port of zippering.test.ts.

ALL storage calls use an in-memory SQLite database (db_storage fixture).
ALL Haiku calls use a fake router (make_fake_router from conftest).
No live DB, no API keys required.

Key invariant tests:
  - test_append_only_invariant: proves zippering_decisions is INSERT-only by
    inserting two decisions for the same (pkey, source, source_column) and
    asserting both rows still exist.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ehrzipper.engine import (
    ZipperUpsertResult,
    get_decision_history,
    get_zippered_row,
    get_zippered_timeline,
    zipper_upsert,
)
from ehrzipper.storage_sqlite import SQLiteStorage
from ehrzipper.types import HaikuRoutingVerdict, IngestRow, IngestValue
from tests.conftest import make_fake_router

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WS = "ehrzipper-default"
PKEY = "acc_test"


def _now() -> str:
    return (
        datetime.now(tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Verdict factories
# ---------------------------------------------------------------------------

APPEND_V = HaikuRoutingVerdict(
    verdict="append",
    canonical_name="company_name",
    is_global_target=False,
    similarity_score=0.9,
    reason="ok",
)
GLOBAL_V = HaikuRoutingVerdict(
    verdict="join",
    canonical_name="company_name",
    is_global_target=True,
    similarity_score=0.97,
    reason="global match",
)
UNCLEAR_V = HaikuRoutingVerdict(
    verdict="unclear",
    canonical_name="mystery",
    is_global_target=False,
    similarity_score=0.5,
    reason="ambiguous",
)


def _base_row(external_id: str = "ext-001", **kwargs: object) -> IngestRow:
    return IngestRow(
        workspace_key=WS,
        pkey=PKEY,
        source="granola",
        external_id=external_id,
        occurred_at=_now(),
        columns={"name": IngestValue(value="Acme", source_data_type="text")},
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# zipperUpsert tests
# ---------------------------------------------------------------------------


class TestZipperUpsert:
    async def test_1_happy_path_new_column_append(
        self, db_storage: SQLiteStorage
    ) -> None:
        """New column → append verdict, value written, schema upserted."""
        router = make_fake_router(APPEND_V)
        result = await zipper_upsert(_base_row(), db_storage, router)

        assert isinstance(result, ZipperUpsertResult)
        assert result.signal_id != ""
        assert len(result.decisions) == 1
        assert result.decisions[0].verdict == "append"
        assert result.decisions[0].decided_by == "llm"

    async def test_2_cache_hit_haiku_not_called(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Second ingest of same column reuses cached decision; Haiku called once."""
        router = make_fake_router(APPEND_V)

        # First ingest: Haiku should be called
        r1 = await zipper_upsert(_base_row(), db_storage, router)
        assert len(r1.decisions) == 1

        # Second ingest: same (pkey, source, source_column) → cache hit
        # We swap the router to one that would return a different verdict —
        # if cache works, the new router's verdict is never invoked.
        router2 = make_fake_router(
            HaikuRoutingVerdict(
                verdict="unclear",
                canonical_name="should_not_appear",
                is_global_target=False,
                similarity_score=0.1,
                reason="should not be called",
            )
        )
        r2 = await zipper_upsert(_base_row(), db_storage, router2)

        # Decision ID should be the same cached row
        assert r2.decisions[0].id == r1.decisions[0].id
        # canonical_name from cache, not the second router's verdict
        assert r2.decisions[0].canonical_name == "company_name"

    async def test_3_unsafe_coercion_normalizer_decision(
        self, db_storage: SQLiteStorage
    ) -> None:
        """
        Unsafe coercion: Haiku routes text source to integer global canonical.
        normalize("hello", "text", "integer") throws UnsafeCoercion.
        Engine inserts a normalizer decision with needs_review=True.
        """
        # employee_count is already seeded as integer in globals
        router = make_fake_router(
            HaikuRoutingVerdict(
                verdict="join",
                canonical_name="employee_count",
                is_global_target=True,
                similarity_score=0.8,
                reason="headcount column matches employee_count",
            )
        )
        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="granola",
            external_id="ext-coerce",
            occurred_at=_now(),
            columns={
                "empcount": IngestValue(value="hello", source_data_type="text")
            },
        )
        result = await zipper_upsert(row, db_storage, router)

        review_decision = next(
            (d for d in result.decisions if d.decided_by == "normalizer"), None
        )
        assert review_decision is not None
        assert review_decision.needs_review is True

    async def test_4_join_global_schema_is_global_true(
        self, db_storage: SQLiteStorage
    ) -> None:
        """JOIN verdict against a global canonical: schema row has is_global=True."""
        router = make_fake_router(GLOBAL_V)
        result = await zipper_upsert(_base_row(), db_storage, router)

        assert result.decisions[0].is_global_target is True

        # Verify schema row was upserted with is_global=1
        schema_rows = db_storage.load_pkey_schema(WS, PKEY)
        global_row = next(
            (r for r in schema_rows if r.canonical_name == "company_name"), None
        )
        assert global_row is not None
        assert global_row.is_global is True

    async def test_5_unclear_verdict_needs_review(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Unclear verdict: decision row has needs_review=True."""
        router = make_fake_router(UNCLEAR_V)
        result = await zipper_upsert(_base_row(), db_storage, router)

        assert result.decisions[0].verdict == "unclear"
        assert result.decisions[0].needs_review is True

    async def test_6_idempotent_reingest_same_signal_id(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Same external_id ingested twice returns the same signal row id."""
        router = make_fake_router(APPEND_V)
        r1 = await zipper_upsert(_base_row(), db_storage, router)

        # Second call — cache hit on decision, same external_id → update not insert
        r2 = await zipper_upsert(_base_row(), db_storage, router)

        assert r1.signal_id == r2.signal_id

    async def test_7_integer_to_timestamp_coercion(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Integer epoch_ms coerces to ISO timestamp string for last_contact_at."""
        router = make_fake_router(
            HaikuRoutingVerdict(
                verdict="join",
                canonical_name="last_contact_at",
                is_global_target=True,
                similarity_score=0.8,
                reason="epoch timestamp matches last_contact_at",
            )
        )
        row = IngestRow(
            workspace_key=WS,
            pkey=PKEY,
            source="granola",
            external_id="ext-ts",
            occurred_at=_now(),
            columns={
                "ts": IngestValue(value=1_716_681_600_000, source_data_type="integer")
            },
        )
        result = await zipper_upsert(row, db_storage, router)
        assert result.signal_id != ""

        # The signal's columns JSON should have an ISO timestamp string
        signal = db_storage.get_zippered_row(WS, PKEY)
        assert signal is not None
        v = signal.columns.get("last_contact_at")
        assert isinstance(v, str)
        assert v.startswith("20")  # e.g. "2024-..."

    async def test_8_multi_column_row_three_decisions(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Three columns → three decisions, each from Haiku."""
        # The fake router always returns the same verdict; we customize per-call
        # by using three sequential routers backed by the same fake client
        # but different canonical_names.
        from unittest.mock import AsyncMock, MagicMock

        verdicts = [
            HaikuRoutingVerdict(
                verdict="append", canonical_name="company_name",
                is_global_target=False, similarity_score=0.9, reason="ok"
            ),
            HaikuRoutingVerdict(
                verdict="append", canonical_name="domain",
                is_global_target=False, similarity_score=0.9, reason="ok"
            ),
            HaikuRoutingVerdict(
                verdict="append", canonical_name="deal_stage",
                is_global_target=False, similarity_score=0.9, reason="ok"
            ),
        ]

        call_count = 0

        async def _side_effect(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            v = verdicts[call_count % 3]
            call_count += 1
            block = MagicMock()
            block.type = "tool_use"
            block.name = "zippering_routing_verdict"
            block.input = v.model_dump()
            msg = MagicMock()
            msg.content = [block]
            return msg

        fake_client = MagicMock()
        fake_client.messages = MagicMock()
        fake_client.messages.create = AsyncMock(side_effect=_side_effect)

        from ehrzipper.haiku_router import HaikuRouter
        router = HaikuRouter(client=fake_client)

        row = IngestRow(
            workspace_key=WS,
            pkey="acc_multi",
            source="granola",
            external_id="ext-multi",
            occurred_at=_now(),
            columns={
                "name":   IngestValue(value="Acme", source_data_type="text"),
                "domain": IngestValue(value="acme.com", source_data_type="text"),
                "stage":  IngestValue(value="Negotiation", source_data_type="text"),
            },
        )
        result = await zipper_upsert(row, db_storage, router)
        assert len(result.decisions) == 3
        canonical_names = {d.canonical_name for d in result.decisions}
        assert canonical_names == {"company_name", "domain", "deal_stage"}


# ---------------------------------------------------------------------------
# Append-only invariant test (critical — explicitly required by spec)
# ---------------------------------------------------------------------------


class TestAppendOnlyInvariant:
    async def test_two_decisions_same_key_both_rows_exist(
        self, db_storage: SQLiteStorage
    ) -> None:
        """
        CRITICAL: Insert two decisions for the same (pkey, source, source_column).
        Both rows must still exist — the table is APPEND-ONLY.
        """
        decision_a = {
            "workspace_key": WS,
            "pkey": PKEY,
            "source": "granola",
            "source_column": "org_name",
            "source_data_type": "text",
            "verdict": "append",
            "canonical_name": "company_name",
            "is_global_target": False,
            "similarity_score": 0.9,
            "reason": "first decision",
            "needs_review": False,
            "decided_by": "haiku",
            "decided_at": "2026-01-01T00:00:00.000Z",
        }
        decision_b = {
            **decision_a,
            "verdict": "join",
            "canonical_name": "company_name",
            "reason": "operator override — confirmed join",
            "decided_by": "rep_abc123",
            "decided_at": "2026-01-02T00:00:00.000Z",  # strictly later
        }

        row_a = db_storage.insert_decision(decision_a)
        row_b = db_storage.insert_decision(decision_b)

        # Both rows should have distinct IDs
        assert row_a.id != row_b.id

        # Query the raw table to prove both rows exist
        cur = db_storage._conn.execute(
            "SELECT COUNT(*) FROM zippering_decisions "
            "WHERE pkey = ? AND source = ? AND source_column = ?",
            (PKEY, "granola", "org_name"),
        )
        count = cur.fetchone()[0]
        assert count == 2, f"Expected 2 rows; got {count}. Table is not append-only!"

        # Latest decision (by decided_at DESC) should be row_b
        latest = db_storage.latest_decision_for_column(WS, PKEY, "granola", "org_name")
        assert latest is not None
        assert latest.decided_by == "rep_abc123"

    async def test_normalizer_decision_appends_new_row(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Normalizer override inserts a NEW row, not update of Haiku row."""
        haiku_dec = {
            "workspace_key": WS,
            "pkey": PKEY,
            "source": "sec_edgar",
            "source_column": "emp_count",
            "source_data_type": "text",
            "verdict": "join",
            "canonical_name": "employee_count",
            "is_global_target": True,
            "similarity_score": 0.85,
            "reason": "employee count match",
            "needs_review": False,
            "decided_by": "haiku",
        }
        normalizer_dec = {
            **haiku_dec,
            "reason": "Unsafe coercion text→integer for value 'N/A'",
            "needs_review": True,
            "decided_by": "normalizer",
        }

        db_storage.insert_decision(haiku_dec)
        db_storage.insert_decision(normalizer_dec)

        cur = db_storage._conn.execute(
            "SELECT decided_by FROM zippering_decisions "
            "WHERE pkey = ? AND source = ? AND source_column = ? "
            "ORDER BY decided_at",
            (PKEY, "sec_edgar", "emp_count"),
        )
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0]["decided_by"] == "haiku"
        assert rows[1]["decided_by"] == "normalizer"


# ---------------------------------------------------------------------------
# Read helper tests
# ---------------------------------------------------------------------------


class TestReadHelpers:
    async def test_get_zippered_row_returns_none_when_empty(
        self, db_storage: SQLiteStorage
    ) -> None:
        row = await get_zippered_row(WS, "acc_nonexistent", db_storage)
        assert row is None

    async def test_get_zippered_row_returns_latest(
        self, db_storage: SQLiteStorage
    ) -> None:
        router = make_fake_router(APPEND_V)
        await zipper_upsert(_base_row("ext-r1"), db_storage, router)

        row = await get_zippered_row(WS, PKEY, db_storage)
        assert row is not None
        assert row.pkey == PKEY

    async def test_get_zippered_timeline_returns_rows_since(
        self, db_storage: SQLiteStorage
    ) -> None:
        router = make_fake_router(APPEND_V)
        await zipper_upsert(_base_row("ext-tl1"), db_storage, router)

        rows = await get_zippered_timeline(
            WS, PKEY, "2020-01-01T00:00:00.000Z", db_storage
        )
        assert len(rows) >= 1

    async def test_get_decision_history_returns_ordered(
        self, db_storage: SQLiteStorage
    ) -> None:
        # Insert two decisions manually so we can verify ordering
        dec1 = {
            "workspace_key": WS,
            "pkey": PKEY,
            "source": "granola",
            "source_column": "name",
            "source_data_type": "text",
            "verdict": "append",
            "canonical_name": "company_name",
            "is_global_target": False,
            "similarity_score": 0.9,
            "reason": "first",
            "needs_review": False,
            "decided_by": "haiku",
            "decided_at": "2026-01-01T00:00:00.000Z",
        }
        dec2 = {
            **dec1,
            "verdict": "join",
            "reason": "second override",
            "decided_by": "rep_x",
            "decided_at": "2026-01-02T00:00:00.000Z",
        }
        db_storage.insert_decision(dec1)
        db_storage.insert_decision(dec2)

        history = await get_decision_history(WS, PKEY, "company_name", db_storage)
        assert len(history) == 2
        # Latest first (decided_at DESC)
        assert history[0].decided_by == "rep_x"
        assert history[1].decided_by == "haiku"

    async def test_get_zippered_timeline_empty_before_since(
        self, db_storage: SQLiteStorage
    ) -> None:
        """Signals before the since timestamp are excluded."""
        router = make_fake_router(APPEND_V)
        await zipper_upsert(_base_row("ext-before"), db_storage, router)

        # Far future since — should return nothing
        rows = await get_zippered_timeline(
            WS, PKEY, "2099-01-01T00:00:00.000Z", db_storage
        )
        assert rows == []
