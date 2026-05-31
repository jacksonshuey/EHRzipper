"""
Tests for the P2 healthcare-extension types:
    partial_date, quantity_with_unit, coded_value
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from ehrzipper.coercions import UnsafeCoercion, normalize

# ---------------------------------------------------------------------------
# partial_date
# ---------------------------------------------------------------------------


class TestPartialDate:
    def test_year_only(self) -> None:
        v = normalize("2024", "text", "partial_date")
        assert v == {"year": 2024, "month": None, "day": None, "precision": "year"}

    def test_year_month_iso(self) -> None:
        v = normalize("2024-06", "text", "partial_date")
        assert v == {"year": 2024, "month": 6, "day": None, "precision": "month"}

    def test_full_iso_date(self) -> None:
        v = normalize("2024-06-15", "text", "partial_date")
        assert v == {"year": 2024, "month": 6, "day": 15, "precision": "day"}

    def test_mm_yyyy(self) -> None:
        v = normalize("06/2024", "text", "partial_date")
        assert v == {"year": 2024, "month": 6, "day": None, "precision": "month"}

    def test_month_name(self) -> None:
        v = normalize("Jun 2024", "text", "partial_date")
        assert v == {"year": 2024, "month": 6, "day": None, "precision": "month"}

    def test_month_full_name(self) -> None:
        v = normalize("September 2024", "text", "partial_date")
        assert v["month"] == 9
        assert v["precision"] == "month"

    def test_quarter(self) -> None:
        v = normalize("Q2 2024", "text", "partial_date")
        assert v["month"] == 6
        assert v["precision"] == "month"

    def test_datetime_object(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, tzinfo=UTC)
        v = normalize(dt, "timestamp", "partial_date")
        assert v["year"] == 2024
        assert v["month"] == 6
        assert v["day"] == 15
        assert v["precision"] == "day"

    def test_date_object(self) -> None:
        v = normalize(date(2024, 6, 15), "timestamp", "partial_date")
        assert v["day"] == 15

    def test_iso_full_datetime_string(self) -> None:
        v = normalize("2024-06-15T10:30:00Z", "text", "partial_date")
        assert v["year"] == 2024
        assert v["precision"] == "day"

    def test_existing_partial_date_passthrough(self) -> None:
        canonical = {"year": 2024, "month": 6, "day": None, "precision": "month"}
        v = normalize(canonical, "partial_date", "partial_date")
        assert v == canonical

    def test_equality_semantics(self) -> None:
        a = normalize("2024-06", "text", "partial_date")
        b = normalize("06/2024", "text", "partial_date")
        assert a == b

    def test_invalid_month(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize("2024-13", "text", "partial_date")

    def test_day_without_month_rejected(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize(
                {"year": 2024, "month": None, "day": 15, "precision": "day"},
                "jsonb",
                "partial_date",
            )

    def test_garbage_string(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize("hello", "text", "partial_date")


# ---------------------------------------------------------------------------
# quantity_with_unit
# ---------------------------------------------------------------------------


class TestQuantityWithUnit:
    def test_mg_to_g(self) -> None:
        v = normalize(
            {"value": 500, "unit": "mg"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "g"},
        )
        assert v["value"] == 500
        assert v["unit"] == "mg"
        assert v["canonical_unit"] == "g"
        assert v["canonical_value"] == pytest.approx(0.5)

    def test_g_to_kg(self) -> None:
        v = normalize(
            {"value": 2000, "unit": "g"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "kg"},
        )
        assert v["canonical_value"] == pytest.approx(2.0)

    def test_ml_to_l(self) -> None:
        v = normalize(
            {"value": 250, "unit": "mL"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "L"},
        )
        assert v["canonical_value"] == pytest.approx(0.25)

    def test_mm_cm_m(self) -> None:
        v = normalize(
            {"value": 150, "unit": "cm"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "m"},
        )
        assert v["canonical_value"] == pytest.approx(1.5)

    def test_inch_to_cm(self) -> None:
        v = normalize(
            {"value": 70, "unit": "in"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "cm"},
        )
        # 70 in * 2.54 = 177.8 cm
        assert v["canonical_value"] == pytest.approx(177.8, rel=1e-4)

    def test_lb_to_kg(self) -> None:
        v = normalize(
            {"value": 150, "unit": "lb"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "kg"},
        )
        assert v["canonical_value"] == pytest.approx(68.0388555)

    def test_fahrenheit_to_celsius(self) -> None:
        v = normalize(
            {"value": 98.6, "unit": "degF"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "Cel"},
        )
        assert v["canonical_value"] == pytest.approx(37.0)

    def test_mmhg_no_conversion(self) -> None:
        v = normalize(
            {"value": 120, "unit": "mmHg"},
            "jsonb",
            "quantity_with_unit",
        )
        assert v["canonical_unit"] == "mmHg"
        assert v["canonical_value"] == 120

    def test_glucose_mgdl_to_mmol(self) -> None:
        v = normalize(
            {"value": 100, "unit": "mg/dL"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "mmol/L", "analyte": "glucose"},
        )
        assert v["canonical_value"] == pytest.approx(5.55, rel=1e-3)

    def test_creatinine_mgdl_to_umol(self) -> None:
        v = normalize(
            {"value": 1.0, "unit": "mg/dL"},
            "jsonb",
            "quantity_with_unit",
            context={"canonical_unit": "umol/L", "analyte": "creatinine"},
        )
        assert v["canonical_value"] == pytest.approx(88.4)

    def test_string_form(self) -> None:
        v = normalize(
            "5 mg",
            "text",
            "quantity_with_unit",
            context={"canonical_unit": "g"},
        )
        assert v["value"] == 5.0
        assert v["unit"] == "mg"

    def test_unknown_unit_rejected(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize(
                {"value": 1.0, "unit": "frobnitz"},
                "jsonb",
                "quantity_with_unit",
            )

    def test_no_canonical_unit_passthrough(self) -> None:
        v = normalize(
            {"value": 100, "unit": "mg"},
            "jsonb",
            "quantity_with_unit",
        )
        # Defaults to mass-canonical "g"
        assert v["canonical_unit"] == "g"


# ---------------------------------------------------------------------------
# coded_value
# ---------------------------------------------------------------------------


class TestCodedValue:
    def test_bare_string_with_vocab(self) -> None:
        v = normalize(
            "male",
            "text",
            "coded_value",
            context={
                "controlled_vocabulary": "male|female|unknown",
                "code_system": "us-core/sex",
            },
        )
        assert v == {"code": "male", "system": "us-core/sex", "display": None}

    def test_case_insensitive_match(self) -> None:
        v = normalize(
            "MALE",
            "text",
            "coded_value",
            context={
                "controlled_vocabulary": "male|female|unknown",
                "code_system": "us-core/sex",
            },
        )
        # Canonicalized back to schema spelling
        assert v["code"] == "male"

    def test_dict_form_full(self) -> None:
        v = normalize(
            {"code": "C34.91", "system": "ICD-10-CM", "display": "Lung cancer right"},
            "jsonb",
            "coded_value",
        )
        assert v["code"] == "C34.91"
        assert v["system"] == "ICD-10-CM"
        assert v["display"] == "Lung cancer right"

    def test_invalid_code_rejected(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize(
                "purple",
                "text",
                "coded_value",
                context={
                    "controlled_vocabulary": "male|female|unknown",
                    "code_system": "us-core/sex",
                },
            )

    def test_missing_system_rejected(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize("male", "text", "coded_value")

    def test_open_vocab_accepts_any(self) -> None:
        v = normalize(
            "Z99.99",
            "text",
            "coded_value",
            context={"code_system": "ICD-10-CM"},
        )
        assert v["code"] == "Z99.99"

    def test_empty_code_rejected(self) -> None:
        with pytest.raises(UnsafeCoercion):
            normalize(
                {"code": ""},
                "jsonb",
                "coded_value",
                context={"code_system": "x"},
            )
