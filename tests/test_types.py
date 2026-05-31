"""
Tests for ehrzipper/types.py.

Verifies Pydantic v2 model construction, field defaults, and validation
for all public types.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ehrzipper.types import (
    GlobalCanonicalColumn,
    HaikuRoutingVerdict,
    IngestRow,
    IngestValue,
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
)


class TestGlobalCanonicalColumn:
    def test_minimal_construction(self) -> None:
        col = GlobalCanonicalColumn(
            id="gc-1",
            workspace_key="ehrzipper-default",
            name="company_name",
            data_type="text",
            created_at="2026-01-01T00:00:00Z",
        )
        assert col.name == "company_name"
        assert col.description is None
        assert col.semantic_tags == []

    def test_full_construction(self) -> None:
        col = GlobalCanonicalColumn(
            id="gc-2",
            workspace_key="ehrzipper-default",
            name="employee_count",
            data_type="integer",
            description="Approximate headcount",
            semantic_tags=["size", "people"],
            created_at="2026-01-01T00:00:00Z",
        )
        assert col.data_type == "integer"
        assert "size" in col.semantic_tags

    def test_open_data_type_accepted(self) -> None:
        # zipper's GlobalCanonicalColumn.data_type is an open str, so a custom
        # data_type that isn't in the documented ZipperingDataType alias is
        # still accepted. This lets EHRzipper carry clinical types without
        # forking the core type system.
        col = GlobalCanonicalColumn(
            id="gc-custom",
            workspace_key="x",
            name="foo",
            data_type="quantity_with_unit",
            created_at="2026-01-01T00:00:00Z",
        )
        assert col.data_type == "quantity_with_unit"

    def test_clinical_metadata_fields(self) -> None:
        # The EHRzipper extension adds the data-dictionary columns the
        # normalizer reads off the resolved canonical target.
        col = GlobalCanonicalColumn(
            id="gc-clin",
            workspace_key="ehrzipper-default",
            name="glucose",
            data_type="quantity_with_unit",
            created_at="2026-01-01T00:00:00Z",
            canonical_unit="mg/dL",
            analyte="glucose",
        )
        assert col.canonical_unit == "mg/dL"
        assert col.analyte == "glucose"
        assert col.controlled_vocabulary is None
        assert col.code_system is None


class TestZipperingSchemaRow:
    def test_defaults(self) -> None:
        row = ZipperingSchemaRow(
            id="s-1",
            workspace_key="ehrzipper-default",
            pkey="acc_test",
            canonical_name="company_name",
            data_type="text",
            first_seen_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        assert row.is_global is False
        assert row.source_origin is None
        assert row.description is None


class TestZipperingDecisionRow:
    def test_full_row(self) -> None:
        row = ZipperingDecisionRow(
            id="d-1",
            workspace_key="ehrzipper-default",
            pkey="acc_test",
            source="granola",
            source_column="org_name",
            verdict="join",
            canonical_name="company_name",
            decided_by="haiku",
            decided_at="2026-01-01T00:00:00Z",
        )
        assert row.verdict == "join"
        assert row.needs_review is False
        assert row.is_global_target is False

    def test_invalid_verdict_raises(self) -> None:
        with pytest.raises(ValidationError):
            ZipperingDecisionRow(
                id="d-bad",
                workspace_key="x",
                pkey="acc_x",
                source="s",
                source_column="c",
                verdict="maybe",  # type: ignore[arg-type]
                canonical_name="x",
                decided_by="haiku",
                decided_at="2026-01-01T00:00:00Z",
            )


class TestZipperedSignalRow:
    def test_defaults(self) -> None:
        sig = ZipperedSignalRow(
            id="sig-1",
            workspace_key="ehrzipper-default",
            pkey="acc_test",
            source="granola",
            occurred_at="2026-01-01T00:00:00Z",
            ingested_at="2026-01-01T00:00:00Z",
        )
        assert sig.columns == {}
        assert sig.external_id is None


class TestIngestRow:
    def test_workspace_key_defaults(self) -> None:
        row = IngestRow(
            pkey="acc_test",
            source="granola",
            occurred_at="2026-01-01T00:00:00Z",
            columns={},
        )
        assert row.workspace_key == "ehrzipper-default"

    def test_columns_with_ingest_values(self) -> None:
        row = IngestRow(
            pkey="acc_test",
            source="granola",
            occurred_at="2026-01-01T00:00:00Z",
            columns={
                "org_name": IngestValue(value="Acme", source_data_type="text"),
                "headcount": IngestValue(value=500, source_data_type="integer"),
            },
        )
        assert row.columns["org_name"].value == "Acme"
        assert row.columns["headcount"].source_data_type == "integer"


class TestHaikuRoutingVerdict:
    def test_valid_join(self) -> None:
        v = HaikuRoutingVerdict(
            verdict="join",
            canonical_name="company_name",
            is_global_target=True,
            similarity_score=0.97,
            reason="Direct match.",
        )
        assert v.verdict == "join"
        assert v.is_global_target is True

    def test_invalid_verdict_raises(self) -> None:
        with pytest.raises(ValidationError):
            HaikuRoutingVerdict(
                verdict="skip",  # type: ignore[arg-type]
                canonical_name="x",
                is_global_target=False,
                similarity_score=0.5,
                reason="x",
            )

    def test_score_boundaries_valid(self) -> None:
        for score in (0.0, 0.5, 1.0):
            v = HaikuRoutingVerdict(
                verdict="append",
                canonical_name="new_col",
                is_global_target=False,
                similarity_score=score,
                reason="ok",
            )
            assert v.similarity_score == score
