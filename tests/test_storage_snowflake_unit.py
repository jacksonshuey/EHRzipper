"""
Unit tests for SnowflakeStorage — mocked. No live Snowflake required.

These tests verify SQL string generation and the append-only invariant on
``insert_decision``. They run unconditionally in CI.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ehrzipper.storage_snowflake import (
    SnowflakeStorage,
    SnowflakeStorageConfig,
)


@pytest.fixture
def mock_conn() -> MagicMock:
    conn = MagicMock()
    return conn


@pytest.fixture
def storage(mock_conn: MagicMock) -> SnowflakeStorage:
    return SnowflakeStorage(connection=mock_conn)


def _last_execute(mock_conn: MagicMock) -> tuple[str, dict[str, Any]]:
    """Return (sql, params) of the most recent .execute() call across cursors."""
    # cursor() returns a MagicMock; track the most recent execute call.
    cur = mock_conn.cursor.return_value
    args, _kwargs = cur.execute.call_args
    sql = args[0]
    params = args[1] if len(args) > 1 else {}
    return sql, params


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acc.region")
    monkeypatch.setenv("SNOWFLAKE_USER", "ehruser")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "pw")
    monkeypatch.setenv("SNOWFLAKE_ROLE", "EHRZIPPER_RW")
    cfg = SnowflakeStorageConfig.from_env()
    assert cfg.account == "acc.region"
    assert cfg.user == "ehruser"
    assert cfg.warehouse == "EHRZIPPER_WH"
    assert cfg.database == "EHRZIPPER"
    assert cfg.schema_name == "META"
    assert cfg.role == "EHRZIPPER_RW"


# ---------------------------------------------------------------------------
# Reads — SQL shape
# ---------------------------------------------------------------------------


def test_load_globals_sql(storage: SnowflakeStorage, mock_conn: MagicMock) -> None:
    mock_conn.cursor.return_value.fetchall.return_value = []
    storage.load_globals("ehrzipper-default")
    sql, params = _last_execute(mock_conn)
    assert "META.GLOBAL_CANONICAL_COLUMNS" in sql
    assert "workspace_key = %(workspace_key)s" in sql
    assert params == {"workspace_key": "ehrzipper-default"}


def test_load_pkey_schema_sql(storage: SnowflakeStorage, mock_conn: MagicMock) -> None:
    mock_conn.cursor.return_value.fetchall.return_value = []
    storage.load_pkey_schema("ws", "pat_1")
    sql, params = _last_execute(mock_conn)
    assert "META.ZIPPERING_SCHEMA" in sql
    assert params == {"workspace_key": "ws", "pkey": "pat_1"}


def test_latest_decision_sql_orders_desc(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    mock_conn.cursor.return_value.fetchone.return_value = None
    result = storage.latest_decision_for_column("ws", "p", "src", "col")
    assert result is None
    sql, params = _last_execute(mock_conn)
    assert "ORDER BY decided_at DESC" in sql
    assert "LIMIT 1" in sql
    assert params["source_column"] == "col"


def test_get_decision_history_sql(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    mock_conn.cursor.return_value.fetchall.return_value = []
    storage.get_decision_history("ws", "p", "patient_id")
    sql, params = _last_execute(mock_conn)
    assert "canonical_name = %(canonical_name)s" in sql
    assert params["canonical_name"] == "patient_id"


def test_get_zippered_timeline_sql(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    mock_conn.cursor.return_value.fetchall.return_value = []
    storage.get_zippered_timeline("ws", "p", "2025-01-01T00:00:00Z")
    sql, params = _last_execute(mock_conn)
    assert "occurred_at >= %(since)s" in sql
    assert params["since"] == "2025-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# insert_decision — APPEND-ONLY
# ---------------------------------------------------------------------------


def test_insert_decision_uses_insert_not_update(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    """The append-only invariant: insert_decision must use INSERT, never UPDATE/MERGE."""
    cur = mock_conn.cursor.return_value
    cur.fetchone.return_value = {
        "ID": "fixed-id",
        "WORKSPACE_KEY": "ws",
        "PKEY": "p",
        "SOURCE": "src",
        "SOURCE_COLUMN": "col",
        "SOURCE_DATA_TYPE": "text",
        "SOURCE_DESCRIPTION": None,
        "SOURCE_SAMPLES": None,
        "VERDICT": "join",
        "CANONICAL_NAME": "company_name",
        "IS_GLOBAL_TARGET": True,
        "SIMILARITY_SCORE": 0.91,
        "REASON": "exact",
        "NEEDS_REVIEW": False,
        "DECIDED_BY": "haiku",
        "DECIDED_AT": "2025-01-01T00:00:00Z",
    }
    storage.insert_decision(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "source": "src",
            "source_column": "col",
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
            "similarity_score": 0.91,
            "reason": "exact",
            "source_samples": ["a", "b"],
        }
    )

    # Look across ALL execute calls — the insert call must be present and
    # there must be no UPDATE/MERGE/DELETE on ZIPPERING_DECISIONS anywhere.
    all_calls = cur.execute.call_args_list
    sqls = [c.args[0] for c in all_calls]
    insert_sqls = [s for s in sqls if "INSERT INTO META.ZIPPERING_DECISIONS" in s]
    forbidden = [
        s
        for s in sqls
        if (
            ("UPDATE META.ZIPPERING_DECISIONS" in s)
            or ("MERGE INTO META.ZIPPERING_DECISIONS" in s)
            or ("DELETE FROM META.ZIPPERING_DECISIONS" in s)
        )
    ]
    assert len(insert_sqls) == 1
    assert forbidden == []
    assert "PARSE_JSON(%(source_samples)s)" in insert_sqls[0]


def test_insert_decision_returns_pydantic_row(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    cur = mock_conn.cursor.return_value
    cur.fetchone.return_value = {
        "ID": "fixed-id",
        "WORKSPACE_KEY": "ws",
        "PKEY": "p",
        "SOURCE": "src",
        "SOURCE_COLUMN": "col",
        "SOURCE_DATA_TYPE": "text",
        "SOURCE_DESCRIPTION": "desc",
        "SOURCE_SAMPLES": '["a","b"]',
        "VERDICT": "join",
        "CANONICAL_NAME": "company_name",
        "IS_GLOBAL_TARGET": True,
        "SIMILARITY_SCORE": 0.91,
        "REASON": "exact",
        "NEEDS_REVIEW": False,
        "DECIDED_BY": "haiku",
        "DECIDED_AT": "2025-01-01T00:00:00Z",
    }
    row = storage.insert_decision(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "source": "src",
            "source_column": "col",
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
        }
    )
    assert row.id == "fixed-id"
    assert row.verdict == "join"
    assert row.source_samples == ["a", "b"]
    assert row.is_global_target is True


# ---------------------------------------------------------------------------
# merge_schema_row — uses MERGE
# ---------------------------------------------------------------------------


def test_merge_schema_row_uses_merge(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    storage.merge_schema_row(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "canonical_name": "patient_id",
            "data_type": "text",
            "description": "stable id",
            "is_global": True,
            "source_origin": "epic_fhir",
        }
    )
    sql, params = _last_execute(mock_conn)
    assert "MERGE INTO META.ZIPPERING_SCHEMA" in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert params["canonical_name"] == "patient_id"
    assert params["is_global"] is True


# ---------------------------------------------------------------------------
# merge_signal — MERGE on (source, external_id)
# ---------------------------------------------------------------------------


def test_merge_signal_with_external_id_uses_merge(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    cur = mock_conn.cursor.return_value
    # No existing row → new id generated, MERGE INSERTs.
    cur.fetchone.return_value = None

    row_id = storage.merge_signal(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "source": "epic_fhir",
            "external_id": "ext-123",
            "occurred_at": "2025-01-01T00:00:00Z",
            "columns": {"vital_status": "alive"},
        }
    )
    assert isinstance(row_id, str) and len(row_id) > 0

    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("MERGE INTO META.ZIPPERED_SIGNALS" in s for s in sqls)
    assert any("PARSE_JSON(%(columns)s)" in s for s in sqls)


def test_merge_signal_without_external_id_uses_insert(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    storage.merge_signal(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "source": "csv",
            "external_id": None,
            "occurred_at": "2025-01-01T00:00:00Z",
            "columns": {},
        }
    )
    sql, _params = _last_execute(mock_conn)
    assert "INSERT INTO META.ZIPPERED_SIGNALS" in sql
    assert "PARSE_JSON(%(columns)s)" in sql


def test_merge_signal_with_existing_external_id_reuses_id(
    storage: SnowflakeStorage, mock_conn: MagicMock
) -> None:
    cur = mock_conn.cursor.return_value
    cur.fetchone.return_value = {"ID": "existing-id-42"}
    row_id = storage.merge_signal(
        {
            "workspace_key": "ws",
            "pkey": "p",
            "source": "epic_fhir",
            "external_id": "ext-xyz",
            "occurred_at": "2025-01-01T00:00:00Z",
            "columns": {"x": 1},
        }
    )
    assert row_id == "existing-id-42"
