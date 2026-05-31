"""
CLI for the derived-variable pipeline.

Usage:
    python -m derived compute --patients-dir synthetic/output/ --out derived/output/
    python -m derived km-plot --out derived/output/km.json

``compute`` runs the full pipeline and writes:
    <out>/lines_of_therapy.json   — per-patient derived lines + warnings
    <out>/survival.json           — per-patient survival records
    <out>/km.json                 — Kaplan-Meier curve + median/CI
    <out>/summary.json            — cohort-level summary stats

``km-plot`` re-runs the pipeline and writes only the KM curve JSON (a
convenience for refreshing a plot input).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from derived.km import KMResult
from derived.pipeline import run_derived_variables


def _json_default(obj: Any) -> Any:
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Not JSON-serializable: {type(obj)!r}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default))


def _km_payload(km: KMResult) -> dict[str, Any]:
    return asdict(km)


def _cmd_compute(patients_dir: Path, out_dir: Path) -> None:
    result = run_derived_variables(patients_dir)

    lot_payload = {
        pid: {
            "lines": [asdict(ln) for ln in lines],
            "warnings": [asdict(w) for w in result["lot_warnings"].get(pid, [])],
        }
        for pid, lines in result["lines_of_therapy"].items()
    }
    _write_json(out_dir / "lines_of_therapy.json", lot_payload)
    _write_json(
        out_dir / "survival.json",
        [asdict(r) for r in result["survival_records"]],
    )
    _write_json(out_dir / "km.json", _km_payload(result["km"]))
    _write_json(out_dir / "summary.json", result["summary"])

    s = result["summary"]
    print(
        f"Derived variables computed for {result['n_patients']} patients "
        f"({result['n_treated']} treated).\n"
        f"  Median OS: {s['median_os_days']} days  CI={s['median_os_ci']}\n"
        f"  Reaching 2L: {s['pct_reaching_line_2']}%  "
        f"3L: {s['pct_reaching_line_3']}%\n"
        f"  1L drug-class mix: {s['line1_drug_class_distribution']}\n"
        f"  Output → {out_dir}"
    )


def _cmd_km_plot(patients_dir: Path, out_path: Path) -> None:
    result = run_derived_variables(patients_dir)
    _write_json(out_path, _km_payload(result["km"]))
    print(f"KM curve written → {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m derived")
    sub = parser.add_subparsers(dest="command", required=True)

    pc = sub.add_parser("compute", help="run the full derived-variable pipeline")
    pc.add_argument("--patients-dir", required=True, type=Path)
    pc.add_argument("--out", required=True, type=Path)

    pk = sub.add_parser("km-plot", help="write only the Kaplan-Meier curve JSON")
    pk.add_argument("--patients-dir", default=Path("synthetic/output"), type=Path)
    pk.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "compute":
        _cmd_compute(args.patients_dir, args.out)
    elif args.command == "km-plot":
        _cmd_km_plot(args.patients_dir, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
