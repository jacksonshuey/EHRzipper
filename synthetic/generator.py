"""
Main entrypoint for the synthetic aNSCLC patient data generator.

Usage:
    python -m synthetic.generator --n 50 --out synthetic/output/ --seed 42
    python -m synthetic.generator --n 5  --out /tmp/synth_test --seed 1 --no-llm

Options:
    --n       Number of patients to generate (default: 50)
    --out     Output directory (default: synthetic/output)
    --seed    Random seed for deterministic generation (default: 42)
    --no-llm  Use template-based notes instead of calling the Anthropic API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="synthetic.generator",
        description="Generate synthetic aNSCLC patient data in FHIR, HL7v2, and CSV formats.",
    )
    parser.add_argument("--n", type=int, default=50, help="Number of patients to generate")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("synthetic/output"),
        help="Output root directory",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        dest="no_llm",
        help="Use template-based notes (no Anthropic API call)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[generator] Generating {args.n} synthetic aNSCLC patients (seed={args.seed})...")

    # --- Generate patient profiles ---
    from synthetic.profiles import generate_profiles

    profiles = generate_profiles(n=args.n, seed=args.seed)

    # --- Write FHIR bundles ---
    from synthetic.fhir_writer import write_all_fhir

    fhir_paths = write_all_fhir(profiles, out_dir)
    print(f"[generator] FHIR: {len(fhir_paths)} bundles written")

    # --- Write HL7v2 messages ---
    from synthetic.hl7_writer import write_all_hl7

    hl7_paths = write_all_hl7(profiles, out_dir)
    print(f"[generator] HL7v2: {len(hl7_paths)} .hl7 files written")

    # --- Write CSVs ---
    from synthetic.csv_writer import write_canonical_patient_csv, write_csv_files

    csv_paths = write_csv_files(profiles, out_dir)
    print(f"[generator] CSV: {len(csv_paths)} CSV files written")

    # Flat canonical patient export across ALL formats (what the cohort UI reads).
    canon_path = write_canonical_patient_csv(profiles, out_dir)
    print(f"[generator] Canonical: all {len(profiles)} patients -> {canon_path.name}")

    # --- Write notes ---
    from synthetic.notes import generate_notes

    use_llm = not args.no_llm
    total_notes = 0
    for p in profiles:
        note_seed = args.seed + hash(p.patient_id) % 1000
        note_paths = generate_notes(p, out_dir, use_llm=use_llm, seed=note_seed)
        total_notes += len(note_paths)
    note_mode = "LLM" if use_llm else "templates"
    print(f"[generator] Notes: {total_notes} note files written ({note_mode})")

    # --- Write manifest ---
    format_counts = {"fhir": 0, "hl7v2": 0, "csv": 0}
    for p in profiles:
        format_counts[p.source_format] = format_counts.get(p.source_format, 0) + 1

    manifest = {
        "seed": args.seed,
        "n_patients": len(profiles),
        "data_cutoff_date": "2024-12-31",
        "format_distribution": format_counts,
        "output_dir": str(out_dir.resolve()),
        "llm_notes": use_llm,
        "patient_ids": [p.patient_id for p in profiles],
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[generator] Manifest written to {manifest_path}")
    total_files = len(fhir_paths) + len(hl7_paths) + len(csv_paths) + total_notes + 1
    print(f"[generator] Done. Total files: {total_files}")


if __name__ == "__main__":
    main(sys.argv[1:])
