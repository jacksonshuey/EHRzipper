"""EHRzipper — one-page reconciliation demo.

Upload real-world-shaped EHR files the way a hospital delivers them — FHIR R4
Bundles, HL7v2 messages, or flat CSV extracts — and watch the three-tier
Zippering engine reconcile them into one canonical, audited dataset you can
download as a clean CSV. Everything lives on this single page: the upload, a
flow diagram of how the engine routes each column, the merged table, and the
append-only provenance log.

Reconciliation runs in memory against a throwaway SQLite store seeded from the
clinical data dictionary. All data is fully synthetic — never upload real PHI.

Run with:
    streamlit run ui/app.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd
import plotly.express as px
import streamlit as st

from ingest import IngestReport, UploadedFile
from ingest.runner import run_ingest
from ui.components.theme import (
    CANVAS,
    INK,
    LINE,
    MUTED,
    NAVY,
    NAVY_SOFT,
    TEAL,
    chart,
    header,
    setup_page,
)

setup_page("Reconciliation Engine")

_PROJECT_ROOT = Path(__file__).parent.parent
_SAMPLE_GLOBS = (
    "synthetic/output/fhir/*.json",
    "synthetic/output/hl7v2/*.hl7",
)
_ACCEPTED = ["json", "hl7", "hl7v2", "csv", "txt"]
# Per-tier colors, shared with the provenance chart.
_DECIDER_COLORS = {
    "lookup": TEAL,
    "normalizer": "#7B61C9",
    "haiku": NAVY_SOFT,
    "llm": NAVY_SOFT,
    "append": "#E6883C",
}


# ---------------------------------------------------------------------------
# Staging — files chosen but not yet reconciled, keyed by name
# ---------------------------------------------------------------------------
def _staged() -> dict[str, UploadedFile]:
    return cast(
        "dict[str, UploadedFile]",
        st.session_state.setdefault("staged", {}),
    )


def _stage(file: UploadedFile) -> None:
    _staged()[file.name] = file


def _load_samples() -> None:
    for pattern in _SAMPLE_GLOBS:
        for path in sorted(glob.glob(str(_PROJECT_ROOT / pattern)))[:2]:
            p = Path(path)
            _stage(UploadedFile(name=p.name, data=p.read_bytes()))
    csv_path = _PROJECT_ROOT / "synthetic" / "output" / "csv" / "patients.csv"
    if csv_path.exists():
        _stage(UploadedFile(name=csv_path.name, data=csv_path.read_bytes()))


# ---------------------------------------------------------------------------
# Tier tallies — collapse the engine's decided_by/verdict vocab into the three
# documented tiers (deterministic / LLM / append).
# ---------------------------------------------------------------------------
def _tier_counts(tally: dict[str, int]) -> dict[str, int]:
    return {
        "tier1": tally.get("lookup", 0) + tally.get("normalizer", 0),
        "tier2": tally.get("haiku", 0) + tally.get("llm", 0),
        "tier3": tally.get("verdict:append", 0),
    }


# ---------------------------------------------------------------------------
# Engine flow diagram — the same picture before and after a run; once a report
# exists, each tier node is annotated with how many columns it routed.
# ---------------------------------------------------------------------------
def _engine_flow(report: IngestReport | None) -> str:
    if report is not None:
        c = _tier_counts(report.tally)
        t1 = f"{c['tier1']} columns routed"
        t2 = (
            f"{c['tier2']} columns routed"
            if report.llm_available
            else "offline — no API key"
        )
        t3 = f"{c['tier3']} appended"
    else:
        t1 = t2 = t3 = "awaiting files"

    return f"""
digraph engine {{
  rankdir=LR;
  bgcolor="transparent";
  pad=0.2; nodesep=0.35; ranksep=0.55;
  node [shape=box style="rounded,filled" fontname="Inter" fontsize=11
        color="{LINE}" fontcolor="{INK}" fillcolor="white" margin="0.20,0.13"];
  edge [color="{MUTED}" arrowsize=0.7 penwidth=1.1];

  src   [label="EHR files\\nFHIR · HL7v2 · CSV" fillcolor="{CANVAS}"];
  parse [label="Parse + normalize\\n→ uniform IngestRow" fillcolor="{CANVAS}"];

  subgraph cluster_engine {{
    label="Zippering engine — per-column routing";
    labeljust="l"; fontname="Inter" fontsize=11 fontcolor="{NAVY}";
    color="{LINE}"; style="rounded"; bgcolor="white";
    t1 [label="Tier 1 — Deterministic\\nLOINC · RxNorm · ICD-10 · SNOMED\\n{t1}"
        fillcolor="{TEAL}" fontcolor="white"];
    t2 [label="Tier 2 — LLM semantic\\nClaude Haiku\\n{t2}"
        fillcolor="{NAVY_SOFT}" fontcolor="white"];
    t3 [label="Tier 3 — Append\\nnew canonical field\\n{t3}"
        fillcolor="#E6883C" fontcolor="white"];
  }}

  canon [label="Canonical record\\nmerged, per patient" fillcolor="white"];
  out   [label="Clean CSV\\n+ append-only audit" fillcolor="{NAVY}" fontcolor="white"];

  src -> parse;
  parse -> t1; parse -> t2; parse -> t3;
  t1 -> canon; t2 -> canon; t3 -> canon;
  canon -> out;
}}
"""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def _cell(value: Any) -> Any:
    """Coerce nested merge values to something a table / CSV can hold."""
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return value


def _canonical_frame(report: IngestReport) -> pd.DataFrame:
    rows = [
        {"patient": pkey, **{k: _cell(v) for k, v in record.items()}}
        for pkey, record in report.canonical_records.items()
    ]
    return pd.DataFrame(rows)


def _render_results(report: IngestReport) -> None:
    counts = _tier_counts(report.tally)

    if report.llm_available:
        st.success("Tier 2 (LLM) online — Claude Haiku routed uncoded columns.", icon="🟢")
    else:
        st.warning(
            "Tier 2 (LLM) offline — no `ANTHROPIC_API_KEY`. Tier-1 matches "
            "applied; the rest are held for review.",
            icon="🟡",
        )

    m = st.columns(4)
    m[0].metric("Patients", report.n_patients)
    m[1].metric("Decisions", report.n_decisions)
    m[2].metric("Tier-1 deterministic", counts["tier1"])
    m[3].metric("Tier-2 LLM", counts["tier2"])

    # The headline payoff: the merged, downloadable dataset.
    st.subheader("Reconciled dataset")
    frame = _canonical_frame(report)
    if frame.empty:
        st.info("No canonical records were produced from these files.")
    else:
        st.dataframe(frame, width="stretch", hide_index=True)
        st.download_button(
            "Download reconciled CSV",
            data=frame.to_csv(index=False),
            file_name="ehrzipper_reconciled.csv",
            mime="text/csv",
            type="primary",
        )

    # The provenance: how every column got there.
    if report.decisions:
        st.subheader("How each column was routed")
        st.caption("Append-only provenance — one row per routing decision.")
        decisions = pd.DataFrame(report.decisions)
        display_cols = [
            "source", "source_column", "canonical_name", "decided_by",
            "similarity_score", "verdict", "reason",
        ]
        st.dataframe(
            decisions[display_cols].rename(
                columns={
                    "source": "Source",
                    "source_column": "Source Column",
                    "canonical_name": "Canonical Field",
                    "decided_by": "Decided By",
                    "similarity_score": "Similarity",
                    "verdict": "Verdict",
                    "reason": "Reason",
                }
            ),
            width="stretch",
            hide_index=True,
        )

        by_tier = (
            decisions.groupby("decided_by").size().reset_index(name="count")
        )
        fig = px.bar(
            by_tier,
            x="decided_by",
            y="count",
            color="decided_by",
            color_discrete_map=_DECIDER_COLORS,
            labels={"decided_by": "Decided by", "count": "Decisions"},
        )
        chart(fig, show_legend=False, height=300)

    if report.held_columns:
        with st.expander(f"Held for review ({len(report.held_columns)})"):
            st.caption("Columns Tier-1 couldn't resolve — an LLM key routes these through Tier 2.")
            st.dataframe(
                pd.DataFrame(report.held_columns).rename(
                    columns={
                        "source": "Source",
                        "source_column": "Column",
                        "source_data_type": "Type",
                        "reason": "Reason",
                    }
                ),
                width="stretch",
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Page body
# ---------------------------------------------------------------------------
header(
    "EHRzipper",
    "Reconcile multi-source EHR files into one clean, audited dataset.",
)
st.info("Fully synthetic data — never upload real PHI.", icon="🔒")

# --- 1. Upload --------------------------------------------------------------
st.subheader("1 · Upload")
uploads = st.file_uploader(
    "Drop FHIR (.json), HL7v2 (.hl7), or CSV files",
    type=_ACCEPTED,
    accept_multiple_files=True,
    label_visibility="collapsed",
)
for up in uploads or []:
    _stage(UploadedFile(name=up.name, data=up.getvalue()))

if st.button("Load sample files"):
    _load_samples()

staged = _staged()
if staged:
    head_col, clear_col = st.columns([4, 1])
    head_col.write(
        f"**{len(staged)} file(s) staged:** "
        + ", ".join(f"`{name}`" for name in staged)
    )
    if clear_col.button("Clear", width="stretch"):
        staged.clear()
        st.session_state.pop("report", None)
        st.rerun()

# --- 2. How it works (live flow) -------------------------------------------
report = st.session_state.get("report")
report = report if isinstance(report, IngestReport) else None

st.subheader("2 · How it works")
st.graphviz_chart(_engine_flow(report), width="stretch")

if staged and st.button("Reconcile & build dataset", type="primary"):
    with st.spinner("Parsing and reconciling…"):
        st.session_state["report"] = run_ingest(list(staged.values()))
    st.rerun()

# --- 3. Result --------------------------------------------------------------
if report is not None:
    st.divider()
    st.subheader("3 · Result")
    _render_results(report)
