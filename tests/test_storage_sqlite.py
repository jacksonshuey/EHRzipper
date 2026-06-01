"""SQLite storage behavior tests — signal dedup is tenant-scoped.

``upsert_signal`` deduplicates on (workspace_key, source, external_id). The same
source identifier in a different workspace must never match an existing row, so
ingesting into workspace B cannot mutate a signal owned by workspace A.
"""

from __future__ import annotations

from ehrzipper.storage_sqlite import SQLiteStorage


def _signal(workspace_key: str, vital_status: str, occurred_at: str) -> dict:
    return {
        "workspace_key": workspace_key,
        "pkey": "pat-1",
        "source": "epic_fhir",
        "external_id": "epic_fhir:pat-1",
        "occurred_at": occurred_at,
        "columns": {"vital_status": vital_status},
    }


def test_upsert_signal_does_not_collide_across_workspaces(
    db_storage: SQLiteStorage,
) -> None:
    a_id = db_storage.upsert_signal(_signal("ws-a", "alive", "2025-01-01"))
    b_id = db_storage.upsert_signal(_signal("ws-b", "deceased", "2025-02-02"))

    # Same (source, external_id) in two workspaces must be two distinct rows.
    assert a_id != b_id

    row_a = db_storage.get_zippered_row("ws-a", "pat-1")
    row_b = db_storage.get_zippered_row("ws-b", "pat-1")
    assert row_a is not None and row_a.columns["vital_status"] == "alive"
    assert row_b is not None and row_b.columns["vital_status"] == "deceased"


def test_upsert_signal_idempotent_within_workspace(
    db_storage: SQLiteStorage,
) -> None:
    first = db_storage.upsert_signal(_signal("ws-a", "alive", "2025-01-01"))
    second = db_storage.upsert_signal(_signal("ws-a", "deceased", "2025-02-02"))

    # Re-ingest of the same identifier in the same workspace reuses the row.
    assert first == second
    row = db_storage.get_zippered_row("ws-a", "pat-1")
    assert row is not None and row.columns["vital_status"] == "deceased"
