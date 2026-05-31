"""Tests for the ingest layer — format detection, adapters, and the runner.

All fixtures here are synthetic (made-up identifiers); no real PHI, per the
project's hard rule. The runner tests pin the router explicitly so they never
depend on ``ANTHROPIC_API_KEY`` being set or unset in the environment.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from ehrzipper.types import HaikuRoutingVerdict
from ingest import UploadedFile
from ingest.adapters import UnknownFormatError, detect_format, parse_file
from ingest.adapters.common import build_columns
from ingest.runner import _OfflineRouter, run_ingest
from tests.conftest import make_fake_router

# ---------------------------------------------------------------------------
# Synthetic fixtures (no real PHI)
# ---------------------------------------------------------------------------
_FHIR_BUNDLE = {
    "resourceType": "Bundle",
    "type": "transaction",
    "timestamp": "2020-01-02",
    "entry": [
        {
            "resource": {
                "resourceType": "Patient",
                "id": "pat_test01",
                "identifier": [
                    {"system": "urn:ehr:patient-id", "value": "pat_test01"}
                ],
            }
        },
        {
            "resource": {
                "resourceType": "Condition",
                "code": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/icd-10-cm",
                            "code": "C34.10",
                        },
                        {"system": "urn:oid:icd-o-3", "display": "Adenocarcinoma"},
                    ]
                },
                "onsetDateTime": "2020-01-02",
            }
        },
        {
            "resource": {
                "resourceType": "Observation",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "26464-8",
                            "display": "WBC",
                        }
                    ]
                },
                "valueQuantity": {"value": 7.2},
            }
        },
        {
            "resource": {
                "resourceType": "Observation",
                "code": {"coding": [{"system": "http://loinc.org", "code": "89247-1"}]},
                "valueInteger": 1,
            }
        },
    ],
}

_HL7_MESSAGE = (
    "MSH|^~\\&|EPIC||LAB||20210305||ORU^R01|1|P|2.3\r"
    "PID|1||pat_test02||DOE^JANE\r"
    "DG1|1||C34.10|NSCLC Adenocarcinoma|20210305\r"
    "OBX|1|NM|26464-8^WBC^LN||7.2\r"
    "RXA|0|1|20210305||6809^carboplatin^RXN\r"
)

_CSV_EXTRACT = (
    "patient_id,icd10_code,histology,ecog_at_advanced_diagnosis,advanced_diagnosis_date\r\n"
    "pat_test03,C34.10,adenocarcinoma,1,2021-03-05\r\n"
    "pat_test03,C34.10,adenocarcinoma,1,2021-03-05\r\n"
    "pat_test04,C34.90,squamous_cell_carcinoma,0,2021-04-10\r\n"
)

# One patient carrying only an uncoded (Tier-2) column.
_CSV_UNCODED_ONLY = (
    "patient_id,histology,onset_date\r\npat_test05,adenocarcinoma,2021-05-01\r\n"
)

# A held column routed by the LLM tier gets appended as a brand-new canonical.
_APPEND_VERDICT = HaikuRoutingVerdict(
    verdict="append",
    canonical_name="tumor_histology_text",
    is_global_target=False,
    similarity_score=0.91,
    reason="semantic match (fake)",
)


def _uf(name: str, data: str | Mapping[str, object]) -> UploadedFile:
    raw = json.dumps(data) if isinstance(data, Mapping) else data
    return UploadedFile(name=name, data=raw.encode("utf-8"))


# ---------------------------------------------------------------------------
# detect_format
# ---------------------------------------------------------------------------
class TestDetectFormat:
    def test_by_extension(self) -> None:
        assert detect_format(_uf("bundle.json", _FHIR_BUNDLE)) == "fhir"
        assert detect_format(_uf("msg.hl7", _HL7_MESSAGE)) == "hl7v2"
        assert detect_format(_uf("extract.csv", _CSV_EXTRACT)) == "csv"

    def test_by_content_when_extensionless(self) -> None:
        assert detect_format(_uf("bundle", _FHIR_BUNDLE)) == "fhir"
        assert detect_format(_uf("message.txt", _HL7_MESSAGE)) == "hl7v2"
        assert detect_format(_uf("rows.txt", _CSV_EXTRACT)) == "csv"

    def test_unknown_raises(self) -> None:
        with pytest.raises(UnknownFormatError):
            detect_format(_uf("mystery.txt", "just some prose with no structure"))


# ---------------------------------------------------------------------------
# Adapters — every format converges on the same canonical columns
# ---------------------------------------------------------------------------
class TestAdapters:
    def test_fhir(self) -> None:
        fmt, rows = parse_file(_uf("bundle.json", _FHIR_BUNDLE))
        assert fmt == "fhir"
        assert len(rows) == 1
        row = rows[0]
        assert row.pkey == "pat_test01"
        assert row.source == "epic_fhir_r4"
        assert row.columns["lab_test_code"].value == "26464-8"
        assert row.columns["diagnosis_code"].value == "C34.10"
        assert row.columns["ecog_performance_status"].value == 1
        assert row.columns["tumor_histology_text"].value == "Adenocarcinoma"

    def test_hl7(self) -> None:
        fmt, rows = parse_file(_uf("msg.hl7", _HL7_MESSAGE))
        assert fmt == "hl7v2"
        assert len(rows) == 1
        row = rows[0]
        assert row.pkey == "pat_test02"
        assert row.source == "legacy_hl7v2"
        assert row.columns["lab_test_code"].value == "26464-8"
        assert row.columns["medication"].value == "carboplatin"
        assert row.columns["diagnosis_code"].value == "C34.10"
        # "NSCLC " prefix is stripped, leaving the histology phrase.
        assert row.columns["tumor_histology_text"].value == "Adenocarcinoma"

    def test_csv_groups_by_patient(self) -> None:
        fmt, rows = parse_file(_uf("extract.csv", _CSV_EXTRACT))
        assert fmt == "csv"
        # Two distinct patients despite three data rows (first-seen wins).
        assert {r.pkey for r in rows} == {"pat_test03", "pat_test04"}
        first = next(r for r in rows if r.pkey == "pat_test03")
        assert first.columns["diagnosis_code"].value == "C34.10"
        assert first.columns["ecog_performance_status"].value == 1


class TestBuildColumns:
    def test_omits_empty_fields(self) -> None:
        cols = build_columns(icd10_code="C34.10")
        assert set(cols) == {"diagnosis_code"}
        assert cols["diagnosis_code"].source_data_type == "coded_value"

    def test_empty_input_yields_no_columns(self) -> None:
        assert build_columns() == {}


# ---------------------------------------------------------------------------
# Runner — the two routing modes
# ---------------------------------------------------------------------------
class TestRunIngestOffline:
    def test_degrades_without_fabricating_llm_decisions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "ingest.runner._build_router", lambda: (_OfflineRouter(), False)
        )
        report = run_ingest([_uf("bundle.json", _FHIR_BUNDLE)])

        assert report.llm_available is False
        # Uncoded columns can't be resolved deterministically -> held, not routed.
        held = {h["source_column"] for h in report.held_columns}
        assert "ecog_performance_status" in held
        assert "tumor_histology_text" in held
        # Nothing is labelled as an LLM decision when the LLM tier is offline.
        assert all(d["decided_by"] != "llm" for d in report.decisions)
        # But the deterministic tier still did real work.
        assert any(d["decided_by"] == "lookup" for d in report.decisions)


class TestRunIngestOnline:
    def test_routes_uncoded_columns_through_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = make_fake_router(_APPEND_VERDICT)
        monkeypatch.setattr(
            "ingest.runner._build_router", lambda: (router, True)
        )
        report = run_ingest([_uf("uncoded.csv", _CSV_UNCODED_ONLY)])

        assert report.llm_available is True
        assert report.held_columns == []
        assert any(d["decided_by"] == "llm" for d in report.decisions)
        assert report.n_patients == 1
