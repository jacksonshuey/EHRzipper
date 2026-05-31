"""
Tests for the P5 derived-variable engines: lines of therapy, rwOS, Kaplan-Meier.

All patient data here is synthetic (CLAUDE.md hard rule 1).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from derived.dates import parse_partial_date, resolve_date
from derived.drugs import classify_drug, regimen_drug_class
from derived.km import greenwood_variance, kaplan_meier
from derived.lot import compute_lot
from derived.lot_validator import validate_lot
from derived.rwos import SurvivalRecord, compute_rwos

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def med(drug: str, start: str, end: str | None = None, drug_class: str | None = None) -> dict:
    return {
        "display": drug,
        "start_date": start,
        "end_date": end or start,
        "drug_class": drug_class,
    }


def cycles(drug: str, first: date, n: int, dclass: str, step: int = 21) -> list[dict]:
    out = []
    for i in range(n):
        d = first + timedelta(days=step * i)
        out.append(med(drug, d.isoformat(), d.isoformat(), dclass))
    return out


# ===========================================================================
# Drug classification
# ===========================================================================


def test_classify_tki() -> None:
    assert classify_drug("osimertinib") == "tki"
    assert classify_drug("Alectinib") == "tki"


def test_classify_io() -> None:
    assert classify_drug("pembrolizumab") == "io"
    assert classify_drug("nivolumab") == "io"


def test_classify_chemo() -> None:
    assert classify_drug("carboplatin") == "chemo"
    assert classify_drug("pemetrexed") == "chemo"


def test_classify_fallback_to_canonical_class() -> None:
    assert classify_drug("some_new_egfr_drug", "tki_egfr") == "tki"
    assert classify_drug("unknown_io", "io_pd1") == "io"


def test_regimen_drug_class_combinations() -> None:
    assert regimen_drug_class(["carboplatin", "pemetrexed"]) == "chemo"
    assert regimen_drug_class(["pembrolizumab"]) == "io"
    assert regimen_drug_class(["osimertinib"]) == "tki"
    assert regimen_drug_class(["carboplatin", "pemetrexed", "pembrolizumab"]) == "chemo+io"
    assert regimen_drug_class(["osimertinib", "pembrolizumab"]) == "tki+io"


# ===========================================================================
# Lines of Therapy
# ===========================================================================


def test_single_drug_single_line() -> None:
    meds = cycles("osimertinib", date(2020, 1, 1), 5, "tki_egfr", step=30)
    lines = compute_lot(meds, [])
    assert len(lines) == 1
    assert lines[0].line_number == 1
    assert lines[0].drugs == ["osimertinib"]
    assert lines[0].drug_class == "tki"
    assert lines[0].regimen_label == "osimertinib"


def test_combination_regimen_is_one_line() -> None:
    # Carbo + pem + pembro given on the same days for several cycles.
    meds: list[dict] = []
    for i in range(4):
        d = date(2020, 1, 1) + timedelta(days=21 * i)
        meds += [
            med("carboplatin", d.isoformat(), drug_class="chemotherapy_platinum"),
            med("pemetrexed", d.isoformat(), drug_class="chemotherapy_pemetrexed"),
            med("pembrolizumab", d.isoformat(), drug_class="io_pd1"),
        ]
    lines = compute_lot(meds, [])
    assert len(lines) == 1
    assert set(lines[0].drugs) == {"carboplatin", "pemetrexed", "pembrolizumab"}
    assert lines[0].drug_class == "chemo+io"


def test_gap_under_threshold_same_line() -> None:
    # Same drug, 60-day gap (< 90) — still one line.
    meds = [
        med("osimertinib", "2020-01-01"),
        med("osimertinib", "2020-03-01"),  # 60-day gap
    ]
    lines = compute_lot(meds, [])
    assert len(lines) == 1


def test_gap_over_threshold_different_drug_new_line() -> None:
    meds = [
        *cycles("osimertinib", date(2020, 1, 1), 3, "tki_egfr", step=30),
        # 120 days later, a different regimen
        med("carboplatin", "2020-07-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-07-01", drug_class="chemotherapy_pemetrexed"),
    ]
    lines = compute_lot(meds, [])
    assert len(lines) == 2
    assert lines[0].drugs == ["osimertinib"]
    assert set(lines[1].drugs) == {"carboplatin", "pemetrexed"}


def test_maintenance_detection() -> None:
    # carbo+pem+pembro induction x4, then pembro alone continues for months.
    meds: list[dict] = []
    for i in range(4):  # induction
        d = date(2020, 1, 1) + timedelta(days=21 * i)
        meds += [
            med("carboplatin", d.isoformat(), drug_class="chemotherapy_platinum"),
            med("pemetrexed", d.isoformat(), drug_class="chemotherapy_pemetrexed"),
            med("pembrolizumab", d.isoformat(), drug_class="io_pd1"),
        ]
    # pembro maintenance every 21 days for ~6 more months
    maint_start = date(2020, 1, 1) + timedelta(days=21 * 4)
    meds += cycles("pembrolizumab", maint_start, 8, "io_pd1", step=21)
    lines = compute_lot(meds, [])
    assert len(lines) == 1  # maintenance is NOT a new line
    assert lines[0].is_maintenance is True


def test_no_maintenance_for_single_drug() -> None:
    meds = cycles("pembrolizumab", date(2020, 1, 1), 6, "io_pd1", step=21)
    lines = compute_lot(meds, [])
    assert lines[0].is_maintenance is False


def test_progression_triggers_new_line() -> None:
    meds = [
        *cycles("osimertinib", date(2020, 1, 1), 4, "tki_egfr", step=30),
        # New drugs after progression, only 30 days later (< gap threshold)
        med("carboplatin", "2020-06-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-06-01", drug_class="chemotherapy_pemetrexed"),
    ]
    progs = [{"event_date": "2020-05-15", "progression_type": "on_treatment_progression"}]
    lines = compute_lot(meds, progs)
    assert len(lines) == 2
    assert lines[0].end_reason == "progression"


def test_regimen_expansion_same_line() -> None:
    # carbo+pem ongoing, bevacizumab added mid-treatment (within window) → same line.
    meds = [
        med("carboplatin", "2020-01-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-01-01", drug_class="chemotherapy_pemetrexed"),
        med("carboplatin", "2020-01-15", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-01-15", drug_class="chemotherapy_pemetrexed"),
        # bevacizumab added 10 days after last admin (within combination window)
        med("bevacizumab", "2020-01-25", drug_class="antiangiogenic"),
    ]
    lines = compute_lot(meds, [])
    assert len(lines) == 1
    assert "bevacizumab" in lines[0].drugs


def test_egfr_clinical_scenario() -> None:
    # EGFR+ patient: osimertinib L1 → progresses → carbo+pem L2.
    meds = [
        *cycles("osimertinib", date(2021, 1, 1), 6, "tki_egfr", step=30),
        med("carboplatin", "2021-09-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2021-09-01", drug_class="chemotherapy_pemetrexed"),
        med("carboplatin", "2021-09-22", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2021-09-22", drug_class="chemotherapy_pemetrexed"),
    ]
    progs = [{"event_date": "2021-08-15", "progression_type": "on_treatment_progression"}]
    lines = compute_lot(meds, progs)
    assert len(lines) == 2
    assert lines[0].drugs == ["osimertinib"]
    assert lines[0].drug_class == "tki"
    assert set(lines[1].drugs) == {"carboplatin", "pemetrexed"}
    assert lines[1].drug_class == "chemo"
    assert lines[1].line_number == 2


def test_regimen_label_generation() -> None:
    meds = [
        med("carboplatin", "2020-01-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-01-01", drug_class="chemotherapy_pemetrexed"),
    ]
    lines = compute_lot(meds, [])
    assert lines[0].regimen_label == "carboplatin + pemetrexed"


def test_empty_meds_no_lines() -> None:
    assert compute_lot([], []) == []


def test_three_lines() -> None:
    meds = [
        *cycles("osimertinib", date(2020, 1, 1), 3, "tki_egfr", step=30),
        med("carboplatin", "2020-08-01", drug_class="chemotherapy_platinum"),
        med("pemetrexed", "2020-08-01", drug_class="chemotherapy_pemetrexed"),
        med("docetaxel", "2021-02-01", drug_class="chemotherapy_taxane"),
    ]
    progs = [
        {"event_date": "2020-07-01", "progression_type": "on_treatment_progression"},
        {"event_date": "2021-01-01", "progression_type": "on_treatment_progression"},
    ]
    lines = compute_lot(meds, progs)
    assert len(lines) == 3
    assert [ln.line_number for ln in lines] == [1, 2, 3]


def test_death_end_reason() -> None:
    meds = cycles("pembrolizumab", date(2020, 1, 1), 4, "io_pd1", step=21)
    last = date(2020, 1, 1) + timedelta(days=21 * 3)
    lines = compute_lot(meds, [], deceased_date=last + timedelta(days=20))
    assert lines[0].end_reason == "death"


# ===========================================================================
# LoT validator
# ===========================================================================


def test_validator_treatment_before_diagnosis() -> None:
    meds = cycles("osimertinib", date(2020, 1, 1), 2, "tki_egfr", step=30)
    lines = compute_lot(meds, [])
    warnings = validate_lot(lines, advanced_diagnosis_date=date(2020, 6, 1))
    assert any(w.code == "treatment_before_diagnosis" for w in warnings)


def test_validator_clean_when_after_diagnosis() -> None:
    meds = cycles("osimertinib", date(2020, 6, 1), 2, "tki_egfr", step=30)
    lines = compute_lot(meds, [])
    warnings = validate_lot(lines, advanced_diagnosis_date=date(2020, 1, 1))
    assert not any(w.code == "treatment_before_diagnosis" for w in warnings)


def test_validator_unrecognized_drug() -> None:
    meds = [med("aspirin", "2020-01-01")]
    lines = compute_lot(meds, [])
    warnings = validate_lot(lines)
    assert any(w.code == "unrecognized_drug" for w in warnings)


def test_validator_empty_lines_no_warnings() -> None:
    assert validate_lot([]) == []


# ===========================================================================
# Date parsing
# ===========================================================================


def test_parse_full_date() -> None:
    d, prec, assumed = parse_partial_date("2020-04-01")
    assert d == date(2020, 4, 1)
    assert prec == "day"
    assert assumed is False


def test_parse_month_precision_assumes_day_15() -> None:
    d, prec, assumed = parse_partial_date("2020-04")
    assert d == date(2020, 4, 15)
    assert prec == "month"
    assert assumed is True


def test_parse_year_precision() -> None:
    d, prec, assumed = parse_partial_date("2020")
    assert d == date(2020, 7, 1)
    assert prec == "year"
    assert assumed is True


def test_parse_partial_date_dict() -> None:
    d, prec, assumed = parse_partial_date({"value": "1952-08", "precision": "month"})
    assert d == date(1952, 8, 15)
    assert prec == "month"
    assert assumed is True


def test_parse_empty_returns_none() -> None:
    assert resolve_date("") is None
    assert resolve_date(None) is None


# ===========================================================================
# rwOS
# ===========================================================================


def test_rwos_deceased() -> None:
    pats = [
        {
            "patient_id": "p1",
            "advanced_diagnosis_date": "2020-01-01",
            "vital_status": "deceased",
            "date_of_death": "2020-04-10",
            "last_known_alive_date": "2020-04-01",
            "age_at_advanced_diagnosis": "67",
        }
    ]
    recs = compute_rwos(pats)
    assert len(recs) == 1
    r = recs[0]
    assert r.event == 1
    assert r.os_days == (date(2020, 4, 10) - date(2020, 1, 1)).days
    assert r.age_at_index == 67


def test_rwos_alive_censored() -> None:
    pats = [
        {
            "patient_id": "p2",
            "advanced_diagnosis_date": "2020-01-01",
            "vital_status": "alive",
            "date_of_death": "",
            "last_known_alive_date": "2021-01-01",
        }
    ]
    recs = compute_rwos(pats)
    assert recs[0].event == 0
    assert recs[0].os_days == (date(2021, 1, 1) - date(2020, 1, 1)).days


def test_rwos_month_precision_index() -> None:
    pats = [
        {
            "patient_id": "p3",
            "advanced_diagnosis_date": {"value": "2020-01", "precision": "month"},
            "vital_status": "deceased",
            "date_of_death": "2020-06-15",
            "last_known_alive_date": "2020-06-01",
        }
    ]
    recs = compute_rwos(pats)
    assert recs[0].index_date == date(2020, 1, 15)
    assert recs[0].index_date_assumed is True
    assert recs[0].index_date_precision == "month"


def test_rwos_skips_unresolvable() -> None:
    pats = [{"patient_id": "p4", "vital_status": "alive"}]
    assert compute_rwos(pats) == []


def test_rwos_negative_floored() -> None:
    # Death apparently before index due to precision; floor at 0.
    pats = [
        {
            "patient_id": "p5",
            "advanced_diagnosis_date": "2020-06-15",
            "vital_status": "deceased",
            "date_of_death": "2020-06-01",
            "last_known_alive_date": "2020-06-01",
        }
    ]
    recs = compute_rwos(pats)
    assert recs[0].os_days == 0


# ===========================================================================
# Kaplan-Meier
# ===========================================================================


def sr(os_days: int, event: int, pid: str = "p") -> SurvivalRecord:
    return SurvivalRecord(
        patient_id=pid,
        index_date=date(2020, 1, 1),
        event_date=date(2020, 1, 1) + timedelta(days=os_days),
        os_days=os_days,
        event=event,
        vital_status="deceased" if event else "alive",
        index_date_precision="day",
        index_date_assumed=False,
        age_at_index=None,
    )


def test_km_single_event_drops_to_zero() -> None:
    res = kaplan_meier([sr(100, 1)])
    assert res.survival_prob[-1] == pytest.approx(0.0)
    assert res.times[-1] == 100.0
    assert res.median_os_days == 100.0


def test_km_empty() -> None:
    res = kaplan_meier([])
    assert res.median_os_days is None
    assert res.times == []


def test_km_all_censored_median_none() -> None:
    res = kaplan_meier([sr(100, 0), sr(200, 0), sr(300, 0)])
    assert res.median_os_days is None
    assert all(s == 1.0 for s in res.survival_prob)


def test_km_median_ten_patients() -> None:
    # 10 deaths at 10,20,...,100. Median = first time S(t) <= 0.5.
    # After 5 deaths (at t=50), S = 0.5 → median is 50.
    recs = [sr(10 * (i + 1), 1, f"p{i}") for i in range(10)]
    res = kaplan_meier(recs)
    assert res.median_os_days == 50.0


def test_km_with_ties() -> None:
    # Two events at day 100, one at day 200, n=4 (one censored at 300).
    recs = [sr(100, 1, "a"), sr(100, 1, "b"), sr(200, 1, "c"), sr(300, 0, "d")]
    res = kaplan_meier(recs)
    # At t=100: 2 events of 4 at risk → S = 0.5.
    idx = res.times.index(100.0)
    assert res.survival_prob[idx] == pytest.approx(0.5)
    assert res.n_events[idx] == 2
    assert res.n_at_risk[idx] == 4


def test_km_n_at_risk_decreases() -> None:
    recs = [sr(50, 1), sr(100, 0), sr(150, 1)]
    res = kaplan_meier(recs)
    assert res.n_at_risk == sorted(res.n_at_risk, reverse=True)
    assert res.n_at_risk[0] == 3


def test_greenwood_variance_non_negative() -> None:
    recs = [sr(10 * (i + 1), 1 if i % 2 == 0 else 0, f"p{i}") for i in range(10)]
    for t in [10, 50, 100]:
        assert greenwood_variance(recs, t) >= 0.0


def test_km_median_ci_bounds_ordered() -> None:
    # Larger sample so the CI band is non-degenerate.
    recs = []
    for i in range(40):
        recs.append(sr(10 + i * 5, 1, f"p{i}"))
    res = kaplan_meier(recs)
    assert res.median_os_days is not None
    if res.ci_lower is not None and res.ci_upper is not None:
        assert res.ci_lower <= res.median_os_days <= res.ci_upper


def test_km_survival_monotonic_non_increasing() -> None:
    recs = [sr(10 * (i + 1), 1, f"p{i}") for i in range(10)]
    res = kaplan_meier(recs)
    for a, b in zip(res.survival_prob, res.survival_prob[1:], strict=False):
        assert b <= a + 1e-12


# ===========================================================================
# Pipeline (integration against the synthetic sample)
# ===========================================================================


def test_pipeline_on_sample(tmp_path: object) -> None:
    from pathlib import Path

    from derived.pipeline import run_derived_variables

    sample = Path(__file__).parent.parent / "synthetic" / "output" / "_sample"
    if not (sample / "csv" / "patients.csv").exists():
        pytest.skip("synthetic sample not present")
    result = run_derived_variables(sample)
    assert result["n_patients"] >= 1
    assert "median_os_days" in result["summary"]
    assert isinstance(result["summary"]["line1_drug_class_distribution"], dict)
