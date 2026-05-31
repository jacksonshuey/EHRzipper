"""
CLI for the abstraction layer (P4).

    python -m abstraction abstract --patients-dir synthetic/output/ \
        --out abstraction/output/ [--no-llm]
    python -m abstraction eval --results abstraction/output/results.jsonl \
        --ground-truth synthetic/output/

`--no-llm` swaps the Anthropic-backed abstractor for the deterministic
regex extractor (no API key, no network) — useful for CI and local testing.

The eval command reconstructs ground truth by reading the manifest in the
ground-truth dir (seed + n_patients) and regenerating the PatientProfile
objects deterministically (the notes were generated from them).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from abstraction.abstractor import NoteAbstractor, RuleBasedAbstractor
from abstraction.batch import abstract_cohort, load_results_jsonl
from abstraction.eval import (
    AbstractionEvaluator,
    format_summary,
    write_report,
)
from abstraction.eval_set.ground_truth import build_ground_truth
from abstraction.pipeline import Abstractor
from synthetic.profiles import PatientProfile


def _build_abstractor(no_llm: bool) -> Abstractor:
    if no_llm:
        return RuleBasedAbstractor()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY not set. Use --no-llm for the rule-based extractor."
        )
    return NoteAbstractor()


def _cmd_abstract(args: argparse.Namespace) -> int:
    patients_dir = Path(args.patients_dir)
    out_dir = Path(args.out)
    results_path = out_dir / "results.jsonl"
    abstractor = _build_abstractor(args.no_llm)

    cohort = asyncio.run(
        abstract_cohort(
            patients_dir,
            abstractor,
            concurrency=args.concurrency,
            results_path=results_path,
        )
    )
    n_results = sum(len(v) for v in cohort.values())
    print(
        f"[abstraction] {len(cohort)} patients, {n_results} notes abstracted "
        f"-> {results_path}"
    )
    return 0


def _load_profiles_from_manifest(ground_truth_dir: Path) -> list[PatientProfile]:
    manifest_path = ground_truth_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"No manifest.json in {ground_truth_dir}; cannot derive GT.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Imported lazily so the abstract command doesn't pull in faker.
    from synthetic.profiles import generate_profiles

    return generate_profiles(n=manifest["n_patients"], seed=manifest["seed"])


def _cmd_eval(args: argparse.Namespace) -> int:
    results_path = Path(args.results)
    ground_truth_dir = Path(args.ground_truth)
    if not results_path.exists():
        raise SystemExit(f"Results file not found: {results_path}")

    cohort_results = load_results_jsonl(results_path)
    profiles = _load_profiles_from_manifest(ground_truth_dir)
    ground_truth = build_ground_truth(profiles)

    evaluator = AbstractionEvaluator()
    report = evaluator.evaluate(ground_truth, cohort_results)

    out_path = Path(args.report) if args.report else results_path.parent / "eval_report.json"
    write_report(report, out_path)
    print(format_summary(report))
    print(f"\n[abstraction] eval report -> {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abstraction", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_abs = sub.add_parser("abstract", help="Extract fields from notes.")
    p_abs.add_argument("--patients-dir", required=True)
    p_abs.add_argument("--out", default="abstraction/output/")
    p_abs.add_argument("--no-llm", action="store_true")
    p_abs.add_argument("--concurrency", type=int, default=5)
    p_abs.set_defaults(func=_cmd_abstract)

    p_eval = sub.add_parser("eval", help="Score results against ground truth.")
    p_eval.add_argument("--results", required=True)
    p_eval.add_argument("--ground-truth", required=True)
    p_eval.add_argument("--report", default=None)
    p_eval.set_defaults(func=_cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
