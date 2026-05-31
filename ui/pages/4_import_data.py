"""Page 4 — Import Data.

Bring real-world-shaped EHR files into the platform from three sources —
computer upload, Google Drive, or Dropbox — then reconcile them live through
the three-tier Zippering engine and show the provenance: every routing
decision, the merged canonical record per patient, and what (if anything) was
held for review.

Cloud sources use real OAuth 2.0 (see ``ui/integrations``); they appear with
setup instructions until an app is configured in ``.streamlit/secrets.toml``.
Computer upload always works. Reconciliation runs against an in-memory SQLite
store seeded from the clinical data dictionary — nothing here touches the
Snowflake/demo databases the other pages read.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import cast

import pandas as pd
import plotly.express as px
import streamlit as st

from ingest import IngestReport, UploadedFile
from ingest.runner import run_ingest
from ui.integrations import CONNECTORS, ConnectorError, _store

st.set_page_config(page_title="Import Data | EHRzipper", layout="wide")

# Mirror the Audit Trail page so a routing tier is the same color everywhere.
_DECIDER_COLORS = {
    "lookup": "#00A8A8",
    "llm": "#1B3A6B",
    "normalizer": "#9B59B6",
    "collision": "#C0392B",
    "operator": "#E67E22",
}
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SAMPLE_GLOBS = {
    "fhir": "synthetic/output/fhir/*.json",
    "hl7v2": "synthetic/output/hl7v2/*.hl7",
}
_ACCEPTED = ["json", "hl7", "hl7v2", "csv", "txt"]


# ---------------------------------------------------------------------------
# Staging — files chosen but not yet reconciled, keyed by name
# ---------------------------------------------------------------------------
def _staged() -> dict[str, UploadedFile]:
    return cast(
        "dict[str, UploadedFile]",
        st.session_state.setdefault("import_staged", {}),
    )


def _stage(file: UploadedFile) -> None:
    _staged()[file.name] = file


# ---------------------------------------------------------------------------
# OAuth callback — runs first, before any source UI
# ---------------------------------------------------------------------------
def _handle_oauth_callback() -> None:
    params = dict(st.query_params)
    if "code" not in params:
        return
    state = params.get("state", "")
    provider = _store.provider_for(state) or _store.provider_for(
        state.split("|", 1)[0]
    )
    if provider is None or provider not in CONNECTORS:
        st.warning("Received an OAuth callback that didn't match a pending connection.")
        st.query_params.clear()
        return
    try:
        CONNECTORS[provider].complete_auth(params)
        st.success(f"Connected to {provider}.")
    except ConnectorError as err:
        st.error(f"{provider} connection failed: {err}")
    st.query_params.clear()


# ---------------------------------------------------------------------------
# Source panels
# ---------------------------------------------------------------------------
def _computer_panel() -> None:
    uploads = st.file_uploader(
        "Drop EHR files here",
        type=_ACCEPTED,
        accept_multiple_files=True,
        help="FHIR R4 Bundle (.json), HL7v2 (.hl7), or a flat extract (.csv).",
    )
    for up in uploads or []:
        _stage(UploadedFile(name=up.name, data=up.getvalue()))

    cols = st.columns(2)
    with cols[0]:
        if st.button("Load sample files", use_container_width=True):
            _load_samples()
    with cols[1]:
        st.caption("No files handy? Load a few synthetic records of each format.")


def _load_samples() -> None:
    for pattern in _SAMPLE_GLOBS.values():
        matches = sorted(glob.glob(str(_PROJECT_ROOT / pattern)))[:2]
        for path in matches:
            p = Path(path)
            _stage(UploadedFile(name=p.name, data=p.read_bytes()))
    csv_path = _PROJECT_ROOT / "synthetic" / "output" / "csv" / "patients.csv"
    if csv_path.exists():
        _stage(UploadedFile(name=csv_path.name, data=csv_path.read_bytes()))


def _cloud_panel(provider: str) -> None:
    mod = CONNECTORS[provider]
    if not mod.configured():
        st.info(mod.setup_help())
        return
    if not mod.sdk_available():
        st.warning(
            f"{provider} is configured but its SDK isn't installed.\n\n"
            "Run `pip install -e '.[integrations]'` and restart the app."
        )
        return

    if not mod.connected():
        st.link_button(
            f"Connect {provider}", mod.auth_url(), use_container_width=True
        )
        st.caption(
            "Opens the provider's consent screen, then returns here. Read-only access."
        )
        return

    left, right = st.columns([3, 1])
    left.success(f"Connected to {provider}.")
    if right.button("Disconnect", use_container_width=True):
        mod.disconnect()
        st.rerun()

    try:
        remote = mod.list_files()
    except ConnectorError as err:
        st.error(str(err))
        return

    if not remote:
        st.caption("No files found in this account.")
        return

    label_to_file = {f"{rf.name}": rf for rf in remote}
    chosen = st.multiselect(f"Files in {provider}", options=list(label_to_file))
    if chosen and st.button(f"Add {len(chosen)} file(s)", use_container_width=True):
        for label in chosen:
            rf = label_to_file[label]
            try:
                _stage(mod.fetch(rf.id, rf.name))
            except ConnectorError as err:
                st.error(str(err))
        st.rerun()


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def _render_report(report: IngestReport) -> None:
    if report.llm_available:
        st.success(
            "**Tier 2 (LLM) is online.** Uncoded columns (ECOG, histology text) "
            "were routed by the Haiku semantic matcher.",
            icon="🟢",
        )
    else:
        st.warning(
            "**Tier 2 (LLM) is offline** — no `ANTHROPIC_API_KEY` set. Only "
            "deterministic Tier-1 matches were applied; columns that need the "
            "LLM are listed under *Held for review* below.",
            icon="🟡",
        )

    m = st.columns(4)
    m[0].metric("Patients", report.n_patients)
    m[1].metric("Decisions", report.n_decisions)
    m[2].metric("Tier-1 (lookup)", report.tally.get("lookup", 0))
    m[3].metric("Tier-2 (LLM)", report.tally.get("llm", 0))

    st.subheader("Files")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "File": fo.name,
                    "Format": fo.detected_format or "—",
                    "Records": fo.n_records,
                    "Error": fo.error or "",
                }
                for fo in report.files
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    if report.decisions:
        _render_decisions(report)

    if report.held_columns:
        st.subheader("Held for review")
        st.caption(
            "Columns the deterministic tier couldn't resolve. With an LLM key "
            "these route through Tier 2 instead of being held."
        )
        st.dataframe(
            pd.DataFrame(report.held_columns).rename(
                columns={
                    "source": "Source",
                    "source_column": "Column",
                    "source_data_type": "Type",
                    "reason": "Reason",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    if report.canonical_records:
        st.subheader("Merged canonical records")
        st.caption("Newest-wins merge of every reconciled signal, per patient.")
        for pkey, record in report.canonical_records.items():
            with st.expander(f"Patient {pkey}"):
                st.json(record)


def _render_decisions(report: IngestReport) -> None:
    st.subheader("Reconciliation decisions")
    st.caption(
        "Append-only provenance — one row per routing decision, exactly as the "
        "engine recorded it. This is the same log the Audit Trail page reads."
    )
    df = pd.DataFrame(report.decisions)
    display_cols = [
        "source", "source_column", "canonical_name", "decided_by",
        "similarity_score", "verdict", "reason",
    ]
    st.dataframe(
        df[display_cols].rename(
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
        use_container_width=True,
        hide_index=True,
    )

    by_tier = (
        df.groupby("decided_by").size().reset_index(name="count")
        if not df.empty
        else pd.DataFrame(columns=["decided_by", "count"])
    )
    if not by_tier.empty:
        fig = px.bar(
            by_tier,
            x="decided_by",
            y="count",
            color="decided_by",
            title="Decisions by routing tier",
            color_discrete_map=_DECIDER_COLORS,
            labels={"decided_by": "Decided by", "count": "Decisions"},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Page body
# ---------------------------------------------------------------------------
st.title("Import Data")
st.markdown(
    """
    Bring EHR files into the platform the way a hospital would deliver them —
    **FHIR R4 Bundles**, **HL7v2 messages**, or **flat CSV extracts** — from your
    computer, Google Drive, or Dropbox. Each file is reconciled live through the
    three-tier engine and its full provenance is shown below.
    """
)
st.info(
    "All data here is **fully synthetic** — never upload real PHI. Files are "
    "parsed in memory and reconciled into a throwaway SQLite store.",
    icon="🔒",
)

_handle_oauth_callback()

source = st.radio(
    "Source",
    options=["Computer", *CONNECTORS.keys()],
    horizontal=True,
)
if source == "Computer":
    _computer_panel()
else:
    _cloud_panel(source)

# ---------------------------------------------------------------------------
# Staged files + reconcile
# ---------------------------------------------------------------------------
staged = _staged()
if staged:
    st.divider()
    head, clear = st.columns([4, 1])
    head.subheader(f"Staged files ({len(staged)})")
    if clear.button("Clear", use_container_width=True):
        staged.clear()
        st.session_state.pop("import_report", None)
        st.rerun()
    st.write(", ".join(f"`{name}`" for name in staged))

    if st.button("Reconcile & show provenance", type="primary"):
        with st.spinner("Parsing and reconciling…"):
            st.session_state["import_report"] = run_ingest(list(staged.values()))

report = st.session_state.get("import_report")
if isinstance(report, IngestReport):
    st.divider()
    _render_report(report)
