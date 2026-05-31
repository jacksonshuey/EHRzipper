"""
Tests for ehrzipper/haiku_router.py — port of zippering-haiku.test.ts.

ALL tests use an injected fake Anthropic client.
ZERO real network calls. No ANTHROPIC_API_KEY required.

The fake client is built via conftest.make_fake_anthropic_client() which
returns a canned tool_use block containing a HaikuRoutingVerdict.
"""

from __future__ import annotations

import pytest

from ehrzipper.haiku_router import AssessInputs, _parse_verdict
from ehrzipper.types import (
    GlobalCanonicalColumn,
    HaikuRoutingVerdict,
    ZipperingSchemaRow,
)
from tests.conftest import make_fake_router

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

GLOBAL_CANDIDATE = GlobalCanonicalColumn(
    id="gc-1",
    workspace_key="ehrzipper-default",
    name="company_name",
    data_type="text",
    description="Legal company name of the account",
    semantic_tags=["identity"],
    created_at="2026-01-01T00:00:00Z",
)

PKEY_CANDIDATE = ZipperingSchemaRow(
    id="ps-1",
    workspace_key="ehrzipper-default",
    pkey="acc_stripe",
    canonical_name="internal_notes",
    data_type="text",
    description="Internal notes specific to this account",
    is_global=False,
    source_origin="granola",
    first_seen_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
)

BASE_INPUTS = dict(
    pkey="acc_stripe",
    source="granola",
    source_column="org_name",
    source_data_type="text",
    source_description="Company name from the Granola meeting record",
    source_samples=["Stripe Inc.", "Stripe", "Stripe, Inc."],
)


def make_inputs(**kwargs: object) -> AssessInputs:
    merged = {**BASE_INPUTS, **kwargs}
    return AssessInputs(
        pkey=str(merged["pkey"]),
        source=str(merged["source"]),
        source_column=str(merged["source_column"]),
        source_data_type=merged["source_data_type"],  # type: ignore[arg-type]
        source_description=merged.get("source_description"),  # type: ignore[arg-type]
        source_samples=list(merged.get("source_samples", [])),  # type: ignore[arg-type]
        candidates_global=list(merged.get("candidates_global", [])),  # type: ignore[arg-type]
        candidates_pkey=list(merged.get("candidates_pkey", [])),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssessColumnRouting:
    async def test_join_global_canonical(self) -> None:
        """JOIN against a global canonical — is_global_target is True."""
        stubbed: HaikuRoutingVerdict = HaikuRoutingVerdict(
            verdict="join",
            canonical_name="company_name",
            is_global_target=True,
            similarity_score=0.97,
            reason="org_name carries the company's legal name; direct match to company_name.",
        )
        router = make_fake_router(stubbed)
        result = await router.assess(
            make_inputs(candidates_global=[GLOBAL_CANDIDATE], candidates_pkey=[])
        )
        assert result.verdict == "join"
        assert result.canonical_name == "company_name"
        assert result.is_global_target is True
        assert abs(result.similarity_score - 0.97) < 1e-9
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    async def test_append_no_candidates(self) -> None:
        """APPEND when no candidates match."""
        stubbed = HaikuRoutingVerdict(
            verdict="append",
            canonical_name="granola_org_name",
            is_global_target=False,
            similarity_score=0.1,
            reason="No existing canonical matches org_name; appending as new column.",
        )
        router = make_fake_router(stubbed)
        result = await router.assess(
            make_inputs(
                source_column="granola_org_name",
                candidates_global=[],
                candidates_pkey=[],
            )
        )
        assert result.verdict == "append"
        assert result.canonical_name == "granola_org_name"
        assert result.is_global_target is False
        assert result.similarity_score < 0.5

    async def test_unclear_verdict_has_canonical_name(self) -> None:
        """UNCLEAR returns unclear verdict and still has canonical_name set."""
        stubbed = HaikuRoutingVerdict(
            verdict="unclear",
            canonical_name="risk_signals",
            is_global_target=False,
            similarity_score=0.45,
            reason="Sample values inconsistent — some look like tags, others free text.",
        )
        router = make_fake_router(stubbed)
        result = await router.assess(
            make_inputs(
                source_column="risk_flags",
                source_data_type="string[]",
                source_samples=["budget", ["budget", "churn"], "see notes"],
                candidates_global=[GLOBAL_CANDIDATE],
                candidates_pkey=[PKEY_CANDIDATE],
            )
        )
        assert result.verdict == "unclear"
        assert isinstance(result.canonical_name, str)
        assert len(result.canonical_name) > 0
        assert result.is_global_target is False

    async def test_missing_source_description_does_not_throw(self) -> None:
        """
        Omitting source_description renders '(none provided)' in the prompt
        and does not cause an exception.
        """
        stubbed = HaikuRoutingVerdict(
            verdict="append",
            canonical_name="attendees",
            is_global_target=False,
            similarity_score=0.05,
            reason="No existing canonical; appending as attendees.",
        )
        router = make_fake_router(stubbed)
        result = await router.assess(
            AssessInputs(
                pkey="acc_stripe",
                source="granola",
                source_column="attendees",
                source_data_type="string[]",
                source_description=None,  # intentionally omitted
                source_samples=["alice@stripe.com", "bob@stripe.com"],
                candidates_global=[GLOBAL_CANDIDATE],
                candidates_pkey=[],
            )
        )
        assert result.verdict == "append"
        assert result.canonical_name == "attendees"

    async def test_empty_candidate_lists(self) -> None:
        """Empty candidate lists force an APPEND verdict path without error."""
        stubbed = HaikuRoutingVerdict(
            verdict="append",
            canonical_name="filing_url",
            is_global_target=False,
            similarity_score=0.0,
            reason="No global or per-pkey canonicals exist yet; appending.",
        )
        router = make_fake_router(stubbed)
        result = await router.assess(
            AssessInputs(
                pkey="acc_sap",
                source="sec_edgar",
                source_column="filing_url",
                source_data_type="text",
                source_description="URL to the SEC filing document",
                source_samples=["https://www.sec.gov/Archives/..."],
                candidates_global=[],
                candidates_pkey=[],
            )
        )
        assert result.verdict == "append"
        assert result.canonical_name == "filing_url"
        assert result.is_global_target is False
        assert 0 <= result.similarity_score <= 1


# ---------------------------------------------------------------------------
# _parse_verdict validation tests
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_valid_join_verdict(self) -> None:
        raw = {
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
            "similarity_score": 0.97,
            "reason": "Direct semantic match.",
        }
        result = _parse_verdict(raw)
        assert result.verdict == "join"
        assert result.canonical_name == "company_name"
        assert result.is_global_target is True
        assert abs(result.similarity_score - 0.97) < 1e-9

    def test_invalid_verdict_raises(self) -> None:
        raw = {
            "verdict": "maybe",
            "canonical_name": "foo",
            "is_global_target": False,
            "similarity_score": 0.5,
            "reason": "test",
        }
        with pytest.raises(RuntimeError, match="Invalid verdict"):
            _parse_verdict(raw)

    def test_missing_canonical_name_raises(self) -> None:
        raw = {
            "verdict": "append",
            "canonical_name": "",
            "is_global_target": False,
            "similarity_score": 0.1,
            "reason": "test",
        }
        with pytest.raises(RuntimeError, match="canonical_name"):
            _parse_verdict(raw)

    def test_non_boolean_is_global_target_raises(self) -> None:
        raw = {
            "verdict": "join",
            "canonical_name": "foo",
            "is_global_target": "yes",  # should be bool
            "similarity_score": 0.9,
            "reason": "test",
        }
        with pytest.raises(RuntimeError, match="is_global_target"):
            _parse_verdict(raw)

    def test_similarity_score_out_of_range_raises(self) -> None:
        raw = {
            "verdict": "join",
            "canonical_name": "foo",
            "is_global_target": False,
            "similarity_score": 1.5,  # > 1
            "reason": "test",
        }
        with pytest.raises(RuntimeError, match="similarity_score"):
            _parse_verdict(raw)

    def test_missing_reason_raises(self) -> None:
        raw = {
            "verdict": "append",
            "canonical_name": "foo",
            "is_global_target": False,
            "similarity_score": 0.5,
            "reason": "",  # empty
        }
        with pytest.raises(RuntimeError, match="reason"):
            _parse_verdict(raw)

    def test_non_object_input_raises(self) -> None:
        with pytest.raises(RuntimeError, match="not an object"):
            _parse_verdict("raw string")

    def test_score_boundary_zero_valid(self) -> None:
        raw = {
            "verdict": "append",
            "canonical_name": "new_col",
            "is_global_target": False,
            "similarity_score": 0.0,
            "reason": "no match",
        }
        result = _parse_verdict(raw)
        assert result.similarity_score == 0.0

    def test_score_boundary_one_valid(self) -> None:
        raw = {
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
            "similarity_score": 1.0,
            "reason": "perfect match",
        }
        result = _parse_verdict(raw)
        assert result.similarity_score == 1.0
