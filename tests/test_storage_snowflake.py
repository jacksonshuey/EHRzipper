"""
Live Snowflake smoke test for SnowflakeStorage.

Skipped unless SNOWFLAKE_ACCOUNT is set in the environment. To run:

    export SNOWFLAKE_ACCOUNT=...
    export SNOWFLAKE_USER=...
    export SNOWFLAKE_PASSWORD=...
    export SNOWFLAKE_WAREHOUSE=EHRZIPPER_WH
    export SNOWFLAKE_DATABASE=EHRZIPPER
    export SNOWFLAKE_SCHEMA=META
    python snowflake/migrate.py --up
    pytest tests/test_storage_snowflake.py -v -m snowflake
"""

from __future__ import annotations

import os
import uuid

import pytest

snowflake_required = pytest.mark.skipif(
    not os.environ.get("SNOWFLAKE_ACCOUNT"),
    reason="SNOWFLAKE_ACCOUNT not set — skipping live Snowflake tests",
)

pytestmark = [pytest.mark.snowflake, snowflake_required]


@pytest.fixture
def storage():  # type: ignore[no-untyped-def]
    from ehrzipper.storage_snowflake import SnowflakeStorage

    s = SnowflakeStorage()
    yield s
    s.close()


def test_connect_and_load_globals(storage) -> None:  # type: ignore[no-untyped-def]
    # Seeded by 03_meta.sql — at least one row should exist.
    rows = storage.load_globals("ehrzipper-default")
    names = {r.name for r in rows}
    assert "company_name" in names


def test_insert_decision_roundtrip(storage) -> None:  # type: ignore[no-untyped-def]
    workspace = "ehrzipper-default"
    pkey = f"test_{uuid.uuid4().hex[:8]}"
    source = "smoketest"
    column = "company"

    written = storage.insert_decision(
        {
            "workspace_key": workspace,
            "pkey": pkey,
            "source": source,
            "source_column": column,
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
            "similarity_score": 0.92,
            "reason": "exact match",
            "source_samples": ["Acme", "Acme Inc."],
            "decided_by": "haiku",
        }
    )

    fetched = storage.latest_decision_for_column(workspace, pkey, source, column)
    assert fetched is not None
    assert fetched.id == written.id
    assert fetched.canonical_name == "company_name"
    assert fetched.source_samples == ["Acme", "Acme Inc."]


def test_merge_signal_merge(storage) -> None:  # type: ignore[no-untyped-def]
    workspace = "ehrzipper-default"
    pkey = f"test_{uuid.uuid4().hex[:8]}"
    external_id = f"ext_{uuid.uuid4().hex[:8]}"
    signal = {
        "workspace_key": workspace,
        "pkey": pkey,
        "source": "smoketest",
        "external_id": external_id,
        "occurred_at": "2025-06-01T00:00:00Z",
        "columns": {"vital_status": "alive"},
    }
    id1 = storage.merge_signal(signal)
    signal["columns"] = {"vital_status": "deceased"}
    id2 = storage.merge_signal(signal)
    assert id1 == id2  # MERGE preserved the id

    row = storage.get_zippered_row(workspace, pkey)
    assert row is not None
    assert row.columns["vital_status"] == "deceased"


def test_append_only_documented() -> None:
    """
    APPEND-ONLY enforcement is documented in 03_meta.sql + storage_snowflake.py.
    No trigger exists (Snowflake has none). Defense:
      1. Storage class uses INSERT only — covered by unit test.
      2. Future P4: role-level GRANT INSERT only on META.ZIPPERING_DECISIONS.
    """
    # Marker test — the unit test in test_storage_snowflake_unit.py is the
    # real enforcement check; this one documents the design call.
    assert True
