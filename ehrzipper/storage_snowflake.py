"""
Snowflake implementation of the Storage protocol.

Backs the Zippering engine against the EHRzipper Snowflake canonical store
(see snowflake/ddl/ for the DDL).

Connection model
----------------
One ``snowflake.connector`` connection per ``SnowflakeStorage`` instance,
reused across calls. The engine layer is responsible for wrapping sync
calls in ``asyncio.to_thread`` from async contexts.

Type mapping
------------
* ``VARIANT`` columns are written via ``PARSE_JSON(%(name)s)`` with a JSON
  string parameter — never via concatenation.
* ``ARRAY`` columns (e.g. ``semantic_tags``) round-trip as JSON arrays too,
  parsed via ``PARSE_JSON``; Snowflake silently widens to ARRAY when the
  parsed value is an array.
* ``TIMESTAMP_TZ`` columns accept ISO 8601 strings; the Python connector
  binds them as STRING and Snowflake casts on insert.

Append-only invariant
---------------------
``insert_decision`` uses ``INSERT`` only — never ``UPDATE`` or ``MERGE``.
``ZIPPERING_DECISIONS`` is APPEND-ONLY per CLAUDE.md and the DDL comment.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, Field
from zipper import GlobalCanonicalColumn

from ehrzipper.types import GlobalCanonicalColumn as EHRGlobalCanonicalColumn
from ehrzipper.types import (
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
)

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from snowflake.connector import SnowflakeConnection
    from snowflake.connector.cursor import SnowflakeCursor


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class SnowflakeStorageConfig(BaseModel):
    """Connection parameters for Snowflake. Read from env by default."""

    account: str = Field(..., description="Snowflake account locator.")
    user: str = Field(..., description="Snowflake username.")
    password: str = Field(..., description="Snowflake password (or PAT).")
    warehouse: str = Field(default="EHRZIPPER_WH")
    database: str = Field(default="EHRZIPPER")
    schema_name: str = Field(default="META", alias="schema")
    role: str | None = Field(default=None)

    @classmethod
    def from_env(cls) -> SnowflakeStorageConfig:
        """Load config from SNOWFLAKE_* env vars."""
        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "EHRZIPPER_WH"),
            database=os.environ.get("SNOWFLAKE_DATABASE", "EHRZIPPER"),
            schema=os.environ.get("SNOWFLAKE_SCHEMA", "META"),
            role=os.environ.get("SNOWFLAKE_ROLE"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _row_to_global(row: dict[str, Any]) -> GlobalCanonicalColumn:
    tags = row.get("SEMANTIC_TAGS")
    parsed_tags: list[str]
    if tags is None:
        parsed_tags = []
    elif isinstance(tags, str):
        parsed_tags = json.loads(tags)
    else:
        parsed_tags = list(tags)
    # Construct the EHR subclass (data-dictionary properties) but annotate the
    # return as the base type so this conforms to zipper.Storage (list is
    # invariant: list[Sub] is not assignable to list[Base]).
    return EHRGlobalCanonicalColumn(
        id=row["ID"],
        workspace_key=row["WORKSPACE_KEY"],
        name=row["NAME"],
        data_type=row["DATA_TYPE"],
        description=row.get("DESCRIPTION"),
        semantic_tags=parsed_tags,
        created_at=_to_iso(row["CREATED_AT"]),
        canonical_unit=row.get("CANONICAL_UNIT"),
        controlled_vocabulary=row.get("CONTROLLED_VOCABULARY"),
        analyte=row.get("ANALYTE"),
        code_system=row.get("CODE_SYSTEM"),
    )


def _row_to_schema(row: dict[str, Any]) -> ZipperingSchemaRow:
    return ZipperingSchemaRow(
        id=row["ID"],
        workspace_key=row["WORKSPACE_KEY"],
        pkey=row["PKEY"],
        canonical_name=row["CANONICAL_NAME"],
        data_type=row["DATA_TYPE"],
        description=row.get("DESCRIPTION"),
        is_global=bool(row["IS_GLOBAL"]),
        source_origin=row.get("SOURCE_ORIGIN"),
        first_seen_at=_to_iso(row["FIRST_SEEN_AT"]),
        updated_at=_to_iso(row["UPDATED_AT"]),
    )


def _row_to_decision(row: dict[str, Any]) -> ZipperingDecisionRow:
    samples_raw = row.get("SOURCE_SAMPLES")
    samples: list[Any] | None
    if samples_raw is None:
        samples = None
    elif isinstance(samples_raw, str):
        samples = json.loads(samples_raw)
    else:
        samples = samples_raw
    return ZipperingDecisionRow(
        id=row["ID"],
        workspace_key=row["WORKSPACE_KEY"],
        pkey=row["PKEY"],
        source=row["SOURCE"],
        source_column=row["SOURCE_COLUMN"],
        source_data_type=row.get("SOURCE_DATA_TYPE"),
        source_description=row.get("SOURCE_DESCRIPTION"),
        source_samples=samples,
        verdict=row["VERDICT"],
        canonical_name=row["CANONICAL_NAME"],
        is_global_target=bool(row["IS_GLOBAL_TARGET"]),
        similarity_score=row.get("SIMILARITY_SCORE"),
        reason=row.get("REASON"),
        needs_review=bool(row["NEEDS_REVIEW"]),
        decided_by=row["DECIDED_BY"],
        decided_at=_to_iso(row["DECIDED_AT"]),
    )


def _row_to_signal(row: dict[str, Any]) -> ZipperedSignalRow:
    cols_raw = row.get("COLUMNS")
    cols: dict[str, Any]
    if cols_raw is None:
        cols = {}
    elif isinstance(cols_raw, str):
        cols = json.loads(cols_raw)
    else:
        cols = dict(cols_raw)
    return ZipperedSignalRow(
        id=row["ID"],
        workspace_key=row["WORKSPACE_KEY"],
        pkey=row["PKEY"],
        source=row["SOURCE"],
        external_id=row.get("EXTERNAL_ID"),
        occurred_at=_to_iso(row["OCCURRED_AT"]),
        columns=cols,
        ingested_at=_to_iso(row["INGESTED_AT"]),
    )


def _to_iso(value: Any) -> str:
    """Coerce Snowflake datetime/str to ISO 8601 UTC string."""
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# SnowflakeStorage
# ---------------------------------------------------------------------------


class SnowflakeStorage:
    """
    Snowflake-backed implementation of the Storage protocol.

    Holds one connection per instance. Call :meth:`close` when done.
    """

    def __init__(
        self,
        config: SnowflakeStorageConfig | None = None,
        connection: SnowflakeConnection | None = None,
        dict_cursor: bool = False,
    ) -> None:
        self._dict_cursor_cls: Any
        if connection is not None:
            self._conn: SnowflakeConnection = connection
            self._owns_conn = False
            # When a connection is injected by a unit test (a MagicMock),
            # cursor() already returns a usable mock and we leave the class
            # unset. When a real connection is injected (e.g. the key-pair
            # connection from ehrzipper.sf_connect, used by the live engine
            # pipeline), pass dict_cursor=True so reads come back keyed by
            # column name like the self-built path.
            if dict_cursor:
                from snowflake.connector import DictCursor

                self._dict_cursor_cls = DictCursor
            else:
                self._dict_cursor_cls = None
        else:
            cfg = config or SnowflakeStorageConfig.from_env()
            import snowflake.connector

            kwargs: dict[str, Any] = {
                "account": cfg.account,
                "user": cfg.user,
                "password": cfg.password,
                "warehouse": cfg.warehouse,
                "database": cfg.database,
                "schema": cfg.schema_name,
            }
            if cfg.role:
                kwargs["role"] = cfg.role
            self._conn = snowflake.connector.connect(**kwargs)
            self._owns_conn = True
            from snowflake.connector import DictCursor

            self._dict_cursor_cls = DictCursor

    # ------------------------------------------------------------------
    # Cursor helper
    # ------------------------------------------------------------------

    def _cursor(self) -> SnowflakeCursor:
        if self._dict_cursor_cls is None:
            # Mock-injected connection path (unit tests).
            cur: SnowflakeCursor = self._conn.cursor()
            return cur
        cur2: SnowflakeCursor = self._conn.cursor(self._dict_cursor_cls)
        return cur2

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def load_globals(self, workspace_key: str) -> list[GlobalCanonicalColumn]:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.GLOBAL_CANONICAL_COLUMNS "
                "WHERE workspace_key = %(workspace_key)s",
                {"workspace_key": workspace_key},
            )
            rows = cast("list[dict[str, Any]]", cur.fetchall())
        finally:
            cur.close()
        return [_row_to_global(r) for r in rows]

    def load_pkey_schema(
        self, workspace_key: str, pkey: str
    ) -> list[ZipperingSchemaRow]:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.ZIPPERING_SCHEMA "
                "WHERE workspace_key = %(workspace_key)s AND pkey = %(pkey)s",
                {"workspace_key": workspace_key, "pkey": pkey},
            )
            rows = cast("list[dict[str, Any]]", cur.fetchall())
        finally:
            cur.close()
        return [_row_to_schema(r) for r in rows]

    def latest_decision_for_column(
        self,
        workspace_key: str,
        pkey: str,
        source: str,
        source_column: str,
    ) -> ZipperingDecisionRow | None:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.ZIPPERING_DECISIONS "
                "WHERE workspace_key = %(workspace_key)s "
                "  AND pkey = %(pkey)s "
                "  AND source = %(source)s "
                "  AND source_column = %(source_column)s "
                "ORDER BY decided_at DESC LIMIT 1",
                {
                    "workspace_key": workspace_key,
                    "pkey": pkey,
                    "source": source,
                    "source_column": source_column,
                },
            )
            row = cast("dict[str, Any] | None", cur.fetchone())
        finally:
            cur.close()
        return _row_to_decision(row) if row else None

    def get_decision_history(
        self,
        workspace_key: str,
        pkey: str,
        canonical_name: str,
    ) -> list[ZipperingDecisionRow]:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.ZIPPERING_DECISIONS "
                "WHERE workspace_key = %(workspace_key)s "
                "  AND pkey = %(pkey)s "
                "  AND canonical_name = %(canonical_name)s "
                "ORDER BY decided_at DESC",
                {
                    "workspace_key": workspace_key,
                    "pkey": pkey,
                    "canonical_name": canonical_name,
                },
            )
            rows = cast("list[dict[str, Any]]", cur.fetchall())
        finally:
            cur.close()
        return [_row_to_decision(r) for r in rows]

    def get_zippered_row(
        self, workspace_key: str, pkey: str
    ) -> ZipperedSignalRow | None:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.ZIPPERED_SIGNALS "
                "WHERE workspace_key = %(workspace_key)s AND pkey = %(pkey)s "
                "ORDER BY occurred_at DESC LIMIT 1",
                {"workspace_key": workspace_key, "pkey": pkey},
            )
            row = cast("dict[str, Any] | None", cur.fetchone())
        finally:
            cur.close()
        return _row_to_signal(row) if row else None

    def get_zippered_timeline(
        self, workspace_key: str, pkey: str, since_iso: str
    ) -> list[ZipperedSignalRow]:
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT * FROM META.ZIPPERED_SIGNALS "
                "WHERE workspace_key = %(workspace_key)s "
                "  AND pkey = %(pkey)s "
                "  AND occurred_at >= %(since)s "
                "ORDER BY occurred_at DESC",
                {
                    "workspace_key": workspace_key,
                    "pkey": pkey,
                    "since": since_iso,
                },
            )
            rows = cast("list[dict[str, Any]]", cur.fetchall())
        finally:
            cur.close()
        return [_row_to_signal(r) for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_decision(self, decision: dict[str, Any]) -> ZipperingDecisionRow:
        """
        INSERT a new zippering_decisions row.

        APPEND-ONLY: this method must never UPDATE/MERGE. The
        ZIPPERING_DECISIONS table is the immutable audit trail.
        """
        row_id = _new_uuid()
        decided_at = decision.get("decided_at") or _now_iso()
        samples_json = _json_or_none(decision.get("source_samples"))

        cur = self._cursor()
        try:
            cur.execute(
                """
                INSERT INTO META.ZIPPERING_DECISIONS (
                    id, workspace_key, pkey, source, source_column,
                    source_data_type, source_description, source_samples,
                    verdict, canonical_name, is_global_target, similarity_score,
                    reason, needs_review, decided_by, decided_at
                )
                SELECT
                    %(id)s, %(workspace_key)s, %(pkey)s, %(source)s, %(source_column)s,
                    %(source_data_type)s, %(source_description)s,
                    PARSE_JSON(%(source_samples)s),
                    %(verdict)s, %(canonical_name)s, %(is_global_target)s,
                    %(similarity_score)s, %(reason)s, %(needs_review)s,
                    %(decided_by)s, %(decided_at)s
                """,
                {
                    "id": row_id,
                    "workspace_key": decision["workspace_key"],
                    "pkey": decision["pkey"],
                    "source": decision["source"],
                    "source_column": decision["source_column"],
                    "source_data_type": decision.get("source_data_type"),
                    "source_description": decision.get("source_description"),
                    "source_samples": samples_json,
                    "verdict": decision["verdict"],
                    "canonical_name": decision["canonical_name"],
                    "is_global_target": bool(decision.get("is_global_target")),
                    "similarity_score": decision.get("similarity_score"),
                    "reason": decision.get("reason"),
                    "needs_review": bool(decision.get("needs_review")),
                    "decided_by": decision.get("decided_by", "llm"),
                    "decided_at": decided_at,
                },
            )
            self._conn.commit()

            cur.execute(
                "SELECT * FROM META.ZIPPERING_DECISIONS WHERE id = %(id)s",
                {"id": row_id},
            )
            row = cast("dict[str, Any] | None", cur.fetchone())
        finally:
            cur.close()

        if row is None:  # pragma: no cover - defensive
            raise RuntimeError(f"INSERT into ZIPPERING_DECISIONS produced no row for {row_id}")
        return _row_to_decision(row)

    def merge_schema_row(self, schema_row: dict[str, Any]) -> None:
        """MERGE INTO META.ZIPPERING_SCHEMA on (workspace_key, pkey, canonical_name)."""
        row_id = _new_uuid()
        now = _now_iso()
        params = {
            "id": row_id,
            "workspace_key": schema_row["workspace_key"],
            "pkey": schema_row["pkey"],
            "canonical_name": schema_row["canonical_name"],
            "data_type": schema_row["data_type"],
            "description": schema_row.get("description"),
            "is_global": bool(schema_row.get("is_global")),
            "source_origin": schema_row.get("source_origin"),
            "now": now,
        }
        cur = self._cursor()
        try:
            cur.execute(
                """
                MERGE INTO META.ZIPPERING_SCHEMA t
                USING (
                    SELECT
                        %(id)s            AS id,
                        %(workspace_key)s AS workspace_key,
                        %(pkey)s          AS pkey,
                        %(canonical_name)s AS canonical_name,
                        %(data_type)s     AS data_type,
                        %(description)s   AS description,
                        %(is_global)s     AS is_global,
                        %(source_origin)s AS source_origin,
                        %(now)s           AS now_ts
                ) s
                ON  t.workspace_key  = s.workspace_key
                AND t.pkey           = s.pkey
                AND t.canonical_name = s.canonical_name
                WHEN MATCHED THEN UPDATE SET
                    data_type     = s.data_type,
                    description   = s.description,
                    is_global     = s.is_global,
                    source_origin = s.source_origin,
                    updated_at    = s.now_ts
                WHEN NOT MATCHED THEN INSERT (
                    id, workspace_key, pkey, canonical_name, data_type,
                    description, is_global, source_origin, first_seen_at, updated_at
                ) VALUES (
                    s.id, s.workspace_key, s.pkey, s.canonical_name, s.data_type,
                    s.description, s.is_global, s.source_origin, s.now_ts, s.now_ts
                )
                """,
                params,
            )
            self._conn.commit()
        finally:
            cur.close()

    def merge_signal(self, signal: dict[str, Any]) -> str:
        """
        MERGE INTO META.ZIPPERED_SIGNALS on (source, external_id).
        Returns the id of the mergeed row.
        """
        cols_json = json.dumps(signal.get("columns") or {})
        now = _now_iso()
        external_id = signal.get("external_id")

        # If external_id is None we cannot dedupe — fall back to plain INSERT.
        if external_id is None:
            row_id = _new_uuid()
            cur = self._cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO META.ZIPPERED_SIGNALS (
                        id, workspace_key, pkey, source, external_id,
                        occurred_at, columns, ingested_at
                    )
                    SELECT
                        %(id)s, %(workspace_key)s, %(pkey)s, %(source)s, NULL,
                        %(occurred_at)s, PARSE_JSON(%(columns)s), %(ingested_at)s
                    """,
                    {
                        "id": row_id,
                        "workspace_key": signal["workspace_key"],
                        "pkey": signal["pkey"],
                        "source": signal["source"],
                        "occurred_at": signal["occurred_at"],
                        "columns": cols_json,
                        "ingested_at": now,
                    },
                )
                self._conn.commit()
            finally:
                cur.close()
            return row_id

        # Look up existing row id first to return a stable id post-merge.
        cur = self._cursor()
        try:
            cur.execute(
                "SELECT id FROM META.ZIPPERED_SIGNALS "
                "WHERE source = %(source)s AND external_id = %(external_id)s",
                {"source": signal["source"], "external_id": external_id},
            )
            existing = cast("dict[str, Any] | None", cur.fetchone())
            row_id = existing["ID"] if existing else _new_uuid()

            cur.execute(
                """
                MERGE INTO META.ZIPPERED_SIGNALS t
                USING (
                    SELECT
                        %(id)s            AS id,
                        %(workspace_key)s AS workspace_key,
                        %(pkey)s          AS pkey,
                        %(source)s        AS source,
                        %(external_id)s   AS external_id,
                        %(occurred_at)s   AS occurred_at,
                        PARSE_JSON(%(columns)s) AS columns,
                        %(ingested_at)s   AS ingested_at
                ) s
                ON  t.source      = s.source
                AND t.external_id = s.external_id
                WHEN MATCHED THEN UPDATE SET
                    pkey        = s.pkey,
                    occurred_at = s.occurred_at,
                    columns     = s.columns,
                    ingested_at = s.ingested_at
                WHEN NOT MATCHED THEN INSERT (
                    id, workspace_key, pkey, source, external_id,
                    occurred_at, columns, ingested_at
                ) VALUES (
                    s.id, s.workspace_key, s.pkey, s.source, s.external_id,
                    s.occurred_at, s.columns, s.ingested_at
                )
                """,
                {
                    "id": row_id,
                    "workspace_key": signal["workspace_key"],
                    "pkey": signal["pkey"],
                    "source": signal["source"],
                    "external_id": external_id,
                    "occurred_at": signal["occurred_at"],
                    "columns": cols_json,
                    "ingested_at": now,
                },
            )
            self._conn.commit()
        finally:
            cur.close()
        return str(row_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection if owned by this instance."""
        if self._owns_conn:
            self._conn.close()
