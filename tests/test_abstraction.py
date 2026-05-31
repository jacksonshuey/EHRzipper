"""
Tests for the abstraction layer (P4).

No live API calls: the Anthropic client is mocked (same pattern as
tests/conftest.py). Covers AbstractedFields validation, rule-based extraction,
confidence scoring, the LLM abstractor (mocked), retry/backoff, the evaluator's
precision/recall/accuracy math, and batch concurrency limiting.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from abstraction.abstractor import (
    NoteAbstractor,
    RuleBasedAbstractor,
    _coerce_fields,
)
from abstraction.batch import (
    abstract_cohort,
    discover_patient_dirs,
    load_results_jsonl,
    write_results_jsonl,
)
from abstraction.eval import (
    AbstractionEvaluator,
    format_summary,
    merge_results,
    normalize_scalar,
    normalize_set,
)
from abstraction.eval_set.ground_truth import build_ground_truth, profile_to_ground_truth
from abstraction.pipeline import abstract_patient_notes, infer_note_type
from abstraction.types import AbstractedFields, AbstractionResult
from synthetic.profiles import generate_profiles

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MOLECULAR_LINE = (
    "EGFR: negative; ALK: negative; ROS1: negative; "
    "KRAS: positive; BRAF: negative; PD-L1: high (TPS 80.0%)"
)

CONSULT_NOTE = f"""\
ONCOLOGY INITIAL CONSULTATION NOTE
Date: 2020-02-28
Patient: Doe, Jane | MRN: pat_test

REASON FOR CONSULTATION:
New diagnosis of advanced non-small cell lung cancer, stage IVA.

HISTORY OF PRESENT ILLNESS:
Jane Doe presents with adenocarcinoma of the lung, stage IVA per AJCC 8th.

PERFORMANCE STATUS:
ECOG performance status: 1

MOLECULAR TESTING:
{_MOLECULAR_LINE}

ASSESSMENT AND PLAN:
Will initiate pembrolizumab per guideline-concordant approach.
"""

PROGRESS_NOTE = """\
ONCOLOGY PROGRESS NOTE
Date: 2020-06-12
Patient: Doe, Jane | MRN: pat_test

OBJECTIVE:
ECOG performance status: 1

ASSESSMENT:
adenocarcinoma NSCLC, stage IVA.
Treatment: carboplatin, pemetrexed, pembrolizumab (initiated 2020-04-01).

PLAN:
Disease progression identified.

Disease progression documented on 2020-12-13 with new involvement at: liver, brain.
"""

EMPTY_ISH_NOTE = "Patient seen today. Routine follow-up. No new findings."


def make_fake_extract_client(fields: AbstractedFields) -> Any:
    """Fake AsyncAnthropic returning a tool_use block with `fields`."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "extract_fields"
    block.input = fields.model_dump()

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50

    message = MagicMock()
    message.content = [block]
    message.usage = usage

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=message)
    return client


# ---------------------------------------------------------------------------
# AbstractedFields validation
# ---------------------------------------------------------------------------


class TestAbstractedFields:
    def test_defaults(self) -> None:
        f = AbstractedFields()
        assert f.histology is None
        assert f.progression_mentioned is False
        assert f.new_metastatic_sites == []
        assert f.treatments_mentioned == []
        assert f.extraction_confidence == "medium"

    def test_full_validation(self) -> None:
        f = AbstractedFields(
            histology="adenocarcinoma",
            stage="IVA",
            ecog=2,
            pdl1_tps=80.0,
            extraction_confidence="high",
            new_metastatic_sites=["liver"],
        )
        assert f.ecog == 2
        assert f.pdl1_tps == 80.0
        assert f.new_metastatic_sites == ["liver"]

    def test_invalid_confidence_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AbstractedFields(extraction_confidence="superb")  # type: ignore[arg-type]

    def test_coerce_fields_drops_unknown_keys(self) -> None:
        raw = {"stage": "IVB", "garbage_key": 1, "progression_mentioned": False}
        f = _coerce_fields(raw, "consult")
        assert f.stage == "IVB"
        assert f.source_note_type == "consult"

    def test_coerce_fields_rejects_non_dict(self) -> None:
        with pytest.raises(RuntimeError):
            _coerce_fields("not a dict", "consult")


# ---------------------------------------------------------------------------
# Rule-based extractor
# ---------------------------------------------------------------------------


class TestRuleBasedExtractor:
    def setup_method(self) -> None:
        self.abs = RuleBasedAbstractor()

    def test_stage_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.stage == "IVA"

    def test_histology_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.histology == "adenocarcinoma"

    def test_ecog_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.ecog == 1

    def test_biomarker_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.egfr_status == "negative"
        assert f.kras_status == "positive"
        assert f.alk_status == "negative"

    def test_pdl1_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.pdl1_status == "high"
        assert f.pdl1_tps == 80.0

    def test_treatments_extraction(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert "pembrolizumab" in f.treatments_mentioned

    def test_progression_extraction(self) -> None:
        f = self.abs.extract(PROGRESS_NOTE, "progress")
        assert f.progression_mentioned is True
        assert f.progression_date == "2020-12-13"
        assert set(f.new_metastatic_sites) == {"liver", "brain"}

    def test_confidence_high_when_many_anchors(self) -> None:
        f = self.abs.extract(CONSULT_NOTE, "consult")
        assert f.extraction_confidence == "high"

    def test_confidence_low_on_empty_note(self) -> None:
        f = self.abs.extract(EMPTY_ISH_NOTE, "progress")
        assert f.extraction_confidence == "low"
        assert f.stage is None
        assert "stage" in f.uncertain_fields

    @pytest.mark.asyncio
    async def test_abstract_wraps_result(self) -> None:
        result = await self.abs.abstract(
            CONSULT_NOTE, patient_id="pat_test", note_type="consult"
        )
        assert isinstance(result, AbstractionResult)
        assert result.patient_id == "pat_test"
        assert result.model == "rule-based-v1"
        assert result.raw_note == CONSULT_NOTE


# ---------------------------------------------------------------------------
# LLM abstractor (mocked)
# ---------------------------------------------------------------------------


class TestNoteAbstractor:
    @pytest.mark.asyncio
    async def test_returns_fields_from_tool_use(self) -> None:
        expected = AbstractedFields(stage="IVB", histology="squamous_cell_carcinoma")
        client = make_fake_extract_client(expected)
        ab = NoteAbstractor(client=client)
        result = await ab.abstract(
            "some note", patient_id="p1", note_type="pathology"
        )
        assert result.fields.stage == "IVB"
        assert result.fields.histology == "squamous_cell_carcinoma"
        assert result.tokens_used == 150
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_forced_tool_choice_and_temperature(self) -> None:
        client = make_fake_extract_client(AbstractedFields())
        ab = NoteAbstractor(client=client)
        await ab.abstract("note", patient_id="p1", note_type="consult")
        _, kwargs = client.messages.create.call_args
        assert kwargs["temperature"] == 0
        assert kwargs["tool_choice"] == {"type": "tool", "name": "extract_fields"}
        assert kwargs["model"] == "claude-haiku-4-5"

    @pytest.mark.asyncio
    async def test_missing_tool_use_raises(self) -> None:
        message = MagicMock()
        text_block = MagicMock()
        text_block.type = "text"
        message.content = [text_block]
        message.usage = MagicMock(input_tokens=1, output_tokens=1)
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=message)
        ab = NoteAbstractor(client=client)
        with pytest.raises(RuntimeError):
            await ab.abstract("note", patient_id="p", note_type="consult")

    @pytest.mark.asyncio
    async def test_retry_then_success(self) -> None:
        expected = AbstractedFields(stage="IVA")
        block = MagicMock()
        block.type = "tool_use"
        block.name = "extract_fields"
        block.input = expected.model_dump()
        message = MagicMock()
        message.content = [block]
        message.usage = MagicMock(input_tokens=10, output_tokens=5)

        call_count = {"n": 0}

        async def flaky(*_a: Any, **_k: Any) -> Any:
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise anthropic.APIConnectionError(request=MagicMock())
            return message

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = flaky
        ab = NoteAbstractor(client=client)
        result = await ab.abstract("note", patient_id="p", note_type="consult")
        assert result.fields.stage == "IVA"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self) -> None:
        async def always_fail(*_a: Any, **_k: Any) -> Any:
            raise anthropic.APIConnectionError(request=MagicMock())

        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = always_fail
        ab = NoteAbstractor(client=client)
        with pytest.raises(anthropic.APIConnectionError):
            await ab.abstract("note", patient_id="p", note_type="consult")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_infer_note_type(self) -> None:
        assert infer_note_type(Path("initial_consult.txt")) == "consult"
        assert infer_note_type(Path("pathology_report.txt")) == "pathology"
        assert infer_note_type(Path("radiology_report.txt")) == "radiology"
        assert infer_note_type(Path("progress_note.txt")) == "progress"
        assert infer_note_type(Path("mystery.txt")) == "unknown"

    @pytest.mark.asyncio
    async def test_abstract_patient_notes(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        (notes_dir / "initial_consult.txt").write_text(CONSULT_NOTE)
        (notes_dir / "progress_note.txt").write_text(PROGRESS_NOTE)
        results = await abstract_patient_notes(
            "pat_x", notes_dir, RuleBasedAbstractor()
        )
        assert len(results) == 2
        assert {r.note_type for r in results} == {"consult", "progress"}

    @pytest.mark.asyncio
    async def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        results = await abstract_patient_notes(
            "pat_x", tmp_path / "nope", RuleBasedAbstractor()
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_blank_note_skipped(self, tmp_path: Path) -> None:
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        (notes_dir / "blank.txt").write_text("   \n  ")
        results = await abstract_patient_notes(
            "pat_x", notes_dir, RuleBasedAbstractor()
        )
        assert results == []


# ---------------------------------------------------------------------------
# Batch + concurrency
# ---------------------------------------------------------------------------


def _make_cohort_dir(root: Path, n: int) -> Path:
    for i in range(n):
        notes = root / f"pat_{i:03d}" / "notes"
        notes.mkdir(parents=True)
        (notes / "initial_consult.txt").write_text(CONSULT_NOTE)
    # Decoys that must be ignored.
    (root / "_sample").mkdir()
    (root / "fhir").mkdir()
    return root


class TestBatch:
    def test_discover_patient_dirs_skips_helpers(self, tmp_path: Path) -> None:
        _make_cohort_dir(tmp_path, 3)
        dirs = discover_patient_dirs(tmp_path)
        assert len(dirs) == 3
        assert all(d.name.startswith("pat_") for d in dirs)

    @pytest.mark.asyncio
    async def test_abstract_cohort_writes_jsonl(self, tmp_path: Path) -> None:
        root = _make_cohort_dir(tmp_path / "patients", 3)
        out = tmp_path / "out" / "results.jsonl"
        cohort = await abstract_cohort(
            root, RuleBasedAbstractor(), concurrency=2, results_path=out
        )
        assert len(cohort) == 3
        assert out.exists()
        reloaded = load_results_jsonl(out)
        assert set(reloaded.keys()) == set(cohort.keys())

    @pytest.mark.asyncio
    async def test_concurrency_limit_respected(self, tmp_path: Path) -> None:
        root = _make_cohort_dir(tmp_path / "patients", 8)
        out = tmp_path / "out" / "results.jsonl"

        state = {"active": 0, "max": 0}

        class TrackingAbstractor:
            model = "tracking"

            async def abstract(
                self,
                note_text: str,
                *,
                patient_id: str,
                note_type: str,
                note_path: str | None = None,
            ) -> AbstractionResult:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
                await asyncio.sleep(0.01)
                state["active"] -= 1
                return AbstractionResult(
                    patient_id=patient_id,
                    note_type=note_type,
                    raw_note=note_text,
                    fields=AbstractedFields(),
                    model=self.model,
                )

        await abstract_cohort(
            root, TrackingAbstractor(), concurrency=3, results_path=out
        )
        assert state["max"] <= 3
        assert state["max"] >= 2  # concurrency was actually exercised

    def test_roundtrip_jsonl(self, tmp_path: Path) -> None:
        out = tmp_path / "r.jsonl"
        cohort = {
            "p1": [
                AbstractionResult(
                    patient_id="p1",
                    note_type="consult",
                    raw_note="x",
                    fields=AbstractedFields(stage="IVA"),
                    model="m",
                )
            ]
        }
        write_results_jsonl(cohort, out)
        back = load_results_jsonl(out)
        assert back["p1"][0].fields.stage == "IVA"


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class TestEvaluator:
    def test_normalize_scalar(self) -> None:
        assert normalize_scalar("IV A".replace(" ", "")) == "iva"
        assert normalize_scalar("Adeno Carcinoma") == "adeno_carcinoma"
        assert normalize_scalar(None) is None
        assert normalize_scalar(True) is True
        assert normalize_scalar(2) == 2

    def test_normalize_set(self) -> None:
        assert normalize_set(["Liver", "brain ", ""]) == {"liver", "brain"}

    def test_merge_results_unions_lists(self) -> None:
        r1 = AbstractionResult(
            patient_id="p",
            note_type="consult",
            raw_note="",
            fields=AbstractedFields(stage="IVA", new_metastatic_sites=["liver"]),
            model="m",
        )
        r2 = AbstractionResult(
            patient_id="p",
            note_type="progress",
            raw_note="",
            fields=AbstractedFields(
                ecog=1,
                progression_mentioned=True,
                new_metastatic_sites=["brain"],
            ),
            model="m",
        )
        merged = merge_results([r1, r2])
        assert merged.stage == "IVA"
        assert merged.ecog == 1
        assert merged.progression_mentioned is True
        assert set(merged.new_metastatic_sites) == {"liver", "brain"}

    def test_perfect_extraction_scores_high(self) -> None:
        gt = {"p": AbstractedFields(stage="IVA", histology="adenocarcinoma", ecog=1)}
        results = {
            "p": [
                AbstractionResult(
                    patient_id="p",
                    note_type="consult",
                    raw_note="",
                    fields=AbstractedFields(
                        stage="IVA", histology="adenocarcinoma", ecog=1
                    ),
                    model="m",
                )
            ]
        }
        report = AbstractionEvaluator().evaluate(gt, results)
        assert report.scalar_accuracy["stage"] == 1.0
        assert report.scalar_accuracy["histology"] == 1.0
        assert report.scalar_accuracy["ecog"] == 1.0

    def test_miss_rate_counts_none_predictions(self) -> None:
        gt = {"p": AbstractedFields(stage="IVA")}
        results = {
            "p": [
                AbstractionResult(
                    patient_id="p",
                    note_type="consult",
                    raw_note="",
                    fields=AbstractedFields(stage=None),
                    model="m",
                )
            ]
        }
        report = AbstractionEvaluator().evaluate(gt, results)
        assert report.scalar_accuracy["stage"] == 0.0
        assert report.scalar_miss_rate["stage"] == 1.0

    def test_list_precision_recall(self) -> None:
        gt = {
            "p": AbstractedFields(new_metastatic_sites=["liver", "brain"])
        }
        results = {
            "p": [
                AbstractionResult(
                    patient_id="p",
                    note_type="progress",
                    raw_note="",
                    # predicts liver (TP) + bone (FP); misses brain (FN)
                    fields=AbstractedFields(new_metastatic_sites=["liver", "bone"]),
                    model="m",
                )
            ]
        }
        report = AbstractionEvaluator().evaluate(gt, results)
        m = report.list_metrics["new_metastatic_sites"]
        assert m["precision"] == pytest.approx(0.5)  # 1 TP / (1 TP + 1 FP)
        assert m["recall"] == pytest.approx(0.5)  # 1 TP / (1 TP + 1 FN)

    def test_confusion_matrix_populated(self) -> None:
        gt = {"p": AbstractedFields(egfr_status="positive")}
        results = {
            "p": [
                AbstractionResult(
                    patient_id="p",
                    note_type="consult",
                    raw_note="",
                    fields=AbstractedFields(egfr_status="negative"),
                    model="m",
                )
            ]
        }
        report = AbstractionEvaluator().evaluate(gt, results)
        assert report.confusion["egfr_status"]["positive"]["negative"] == 1

    def test_format_summary_runs(self) -> None:
        gt = {"p": AbstractedFields(stage="IVA")}
        results = {
            "p": [
                AbstractionResult(
                    patient_id="p",
                    note_type="consult",
                    raw_note="",
                    fields=AbstractedFields(stage="IVA"),
                    model="m",
                )
            ]
        }
        report = AbstractionEvaluator().evaluate(gt, results)
        text = format_summary(report)
        assert "Macro accuracy" in text
        assert "stage" in text


# ---------------------------------------------------------------------------
# Ground truth derivation
# ---------------------------------------------------------------------------


class TestGroundTruth:
    def test_profile_to_ground_truth_basic_fields(self) -> None:
        profiles = generate_profiles(n=5, seed=42)
        p = profiles[0]
        gt = profile_to_ground_truth(p)
        assert gt.stage == p.stage_at_advanced_diagnosis
        assert gt.histology == p.histology
        assert gt.ecog == p.ecog_at_advanced_diagnosis

    def test_not_tested_biomarker_is_none(self) -> None:
        f = AbstractedFields()  # sanity baseline
        assert f.egfr_status is None
        profiles = generate_profiles(n=20, seed=7)
        for p in profiles:
            gt = profile_to_ground_truth(p)
            if p.pdl1_status == "not_tested":
                assert gt.pdl1_status is None

    def test_build_ground_truth_keys_by_patient(self) -> None:
        profiles = generate_profiles(n=4, seed=1)
        gt = build_ground_truth(profiles)
        assert set(gt.keys()) == {p.patient_id for p in profiles}

    @pytest.mark.asyncio
    async def test_end_to_end_rule_based_eval_high_accuracy(
        self, tmp_path: Path
    ) -> None:
        """Generate notes from profiles, abstract them, score — expect strong
        accuracy on the structured fields the templates surface."""
        from synthetic.notes import generate_notes

        profiles = generate_profiles(n=6, seed=99)
        out_dir = tmp_path / "patients"
        for p in profiles:
            generate_notes(p, out_dir, use_llm=False, seed=99)

        cohort = await abstract_cohort(
            out_dir,
            RuleBasedAbstractor(),
            concurrency=4,
            results_path=tmp_path / "results.jsonl",
        )
        gt = build_ground_truth(profiles)
        report = AbstractionEvaluator().evaluate(gt, cohort)

        assert report.n_patients == 6
        # Core structured fields should be recovered near-perfectly.
        assert report.scalar_accuracy["stage"] >= 0.95
        assert report.scalar_accuracy["histology"] >= 0.95
        assert report.scalar_accuracy["ecog"] >= 0.95
        assert report.scalar_accuracy["egfr_status"] >= 0.9
