"""
Cohort-level abstraction with bounded concurrency.

Discovers patients under `patients_dir` (each is a `<patient_id>/notes/` dir),
runs the per-patient pipeline under an asyncio semaphore, and writes one JSON
line per `AbstractionResult` to `abstraction/output/results.jsonl`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from abstraction.pipeline import Abstractor, abstract_patient_notes
from abstraction.types import AbstractionResult

DEFAULT_RESULTS_PATH = Path("abstraction/output/results.jsonl")


def discover_patient_dirs(patients_dir: Path) -> list[Path]:
    """Return sorted patient directories (those containing a `notes/` subdir).

    Skips hidden helper dirs (e.g. `_sample`) and the format export dirs
    (`fhir`, `hl7v2`, `csv`) that don't carry per-patient notes.
    """
    if not patients_dir.exists():
        return []
    dirs: list[Path] = []
    for child in sorted(patients_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith((".", "_")):
            continue
        if (child / "notes").is_dir():
            dirs.append(child)
    return dirs


async def abstract_cohort(
    patients_dir: Path,
    abstractor: Abstractor,
    concurrency: int = 5,
    results_path: Path | None = None,
) -> dict[str, list[AbstractionResult]]:
    """Abstract every patient under `patients_dir`, bounded by `concurrency`.

    Writes results to `results_path` (default `abstraction/output/results.jsonl`)
    as JSONL and returns them keyed by patient_id.
    """
    patient_dirs = discover_patient_dirs(patients_dir)
    semaphore = asyncio.Semaphore(concurrency)

    async def _run(patient_dir: Path) -> tuple[str, list[AbstractionResult]]:
        patient_id = patient_dir.name
        async with semaphore:
            results = await abstract_patient_notes(
                patient_id, patient_dir / "notes", abstractor
            )
        return patient_id, results

    pairs = await asyncio.gather(*(_run(pd) for pd in patient_dirs))
    cohort: dict[str, list[AbstractionResult]] = dict(pairs)

    out_path = results_path or DEFAULT_RESULTS_PATH
    write_results_jsonl(cohort, out_path)
    return cohort


def write_results_jsonl(
    cohort: dict[str, list[AbstractionResult]],
    out_path: Path,
) -> None:
    """Write all results as one JSON object per line."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for _patient_id, results in cohort.items():
            for result in results:
                fh.write(result.model_dump_json())
                fh.write("\n")


def load_results_jsonl(path: Path) -> dict[str, list[AbstractionResult]]:
    """Read a results JSONL file back into a per-patient dict."""
    cohort: dict[str, list[AbstractionResult]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            result = AbstractionResult.model_validate_json(line)
            cohort.setdefault(result.patient_id, []).append(result)
    return cohort
