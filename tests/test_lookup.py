"""
Tests for the deterministic code-lookup tier.
"""

from __future__ import annotations

from ehrzipper.lookup import CodeLookup


class TestLoincMatching:
    def test_wbc_column_name_matches(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("wbc_count", ["8.4"])
        assert verdict is not None
        assert verdict.matched_registry == "LOINC"
        assert verdict.matched_code == "26464-8"
        assert verdict.canonical_column == "wbc_count"
        assert verdict.canonical_unit == "10*3/uL"
        assert verdict.matched_on == "column_name"

    def test_hemoglobin_alias(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("hgb", ["13.5"])
        assert verdict is not None
        assert verdict.canonical_column == "hemoglobin"

    def test_loinc_code_in_samples(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("test_code", ["26464-8"])
        assert verdict is not None
        assert verdict.matched_registry == "LOINC"
        assert verdict.matched_on == "sample_value_code"

    def test_egfr_column_matches_coded_value(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("egfr", ["positive"])
        assert verdict is not None
        assert verdict.canonical_column == "egfr_status"
        assert verdict.data_type == "coded_value"


class TestRxNormMatching:
    def test_drug_column_with_osimertinib(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("drug", ["osimertinib"])
        assert verdict is not None
        assert verdict.matched_registry == "RxNorm"
        assert verdict.matched_code == "1721560"
        assert verdict.canonical_column == "drug_name"

    def test_medication_column_brand_name(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("medication_name", ["Keytruda"])
        assert verdict is not None
        assert verdict.matched_registry == "RxNorm"
        # pembrolizumab CUI
        assert verdict.matched_code == "1547545"

    def test_mixed_drugs_returns_none(self) -> None:
        """Two distinct drugs in samples → ambiguous → defer to Haiku."""
        lookup = CodeLookup()
        verdict = lookup.match("drug", ["osimertinib", "pembrolizumab"])
        assert verdict is None

    def test_drug_without_drug_column_returns_none(self) -> None:
        """A drug name in a column not flagged as drug-related → ambiguous."""
        lookup = CodeLookup()
        verdict = lookup.match("notes", ["osimertinib"])
        assert verdict is None


class TestIcd10Matching:
    def test_diagnosis_code_in_samples(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("diagnosis_code", ["C34.91"])
        assert verdict is not None
        assert verdict.matched_registry == "ICD-10"
        assert verdict.matched_code == "C34.91"

    def test_comorbidity_i10(self) -> None:
        lookup = CodeLookup()
        verdict = lookup.match("dx_code", ["I10"])
        assert verdict is not None
        assert verdict.matched_registry == "ICD-10"

    def test_unknown_icd10_returns_none(self) -> None:
        """A pattern-valid but unregistered ICD-10 → None (don't fabricate)."""
        lookup = CodeLookup()
        verdict = lookup.match("diagnosis_code", ["Z99.0"])
        assert verdict is None


class TestAmbiguous:
    def test_no_match_returns_none(self) -> None:
        lookup = CodeLookup()
        assert lookup.match("comments", ["free text"]) is None

    def test_empty_samples_no_column_hint(self) -> None:
        lookup = CodeLookup()
        assert lookup.match("misc", []) is None

    def test_ambiguous_column_name_multiple_loinc_hits_returns_none(self) -> None:
        """Column "biomarker" doesn't uniquely hit any one entry."""
        lookup = CodeLookup()
        assert lookup.match("biomarker", []) is None
