"""
Integration test: all population-level DQ checks pass on the seed-42 cohort.
"""

from __future__ import annotations

import pytest

from pipeline.data_quality import run_checks
from synthetic.profiles import PatientProfile, generate_profiles


@pytest.fixture(scope="module")
def seed42_profiles() -> list[PatientProfile]:
    return generate_profiles(n=50, seed=42)


def test_all_dq_checks_pass(seed42_profiles: list[PatientProfile]) -> None:
    """run_checks must return True (all checks pass) on the canonical cohort."""
    passed = run_checks(seed42_profiles, verbose=True)
    assert passed, "One or more data-quality checks failed on the seed-42 cohort"
