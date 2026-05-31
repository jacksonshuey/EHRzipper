"""Page 5 — Audit Trail.

Inspect append-only zippering decisions from the schema reconciliation
engine. Decisions are stored in SQLite and are never updated or deleted.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ui.components.theme import chart, header, setup_page

setup_page("Audit Trail")

header(
    "Audit Trail",
    "Every schema routing decision the engine makes is recorded in an "
    "append-only log — never updated or deleted. Filter by routing tier and "
    "see the decision timeline.",
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SCHEMA_SQL = _PROJECT_ROOT / "ehrzipper" / "migrations" / "001_zippering_tables.sql"
_DB_PATH = _PROJECT_ROOT / "ui" / "data" / "audit_demo.db"
# Real decisions exported from the live engine run against Snowflake
# (META.ZIPPERING_DECISIONS). Preferred over the illustrative SQLite fixture.
_LIVE_CSV = _PROJECT_ROOT / "ui" / "data" / "zippering_decisions_live.csv"

# ---------------------------------------------------------------------------
# Bootstrap demo database
# ---------------------------------------------------------------------------
_DEMO_DECISIONS = [
    (
        "ehr_source_a", "pt_gender", "sex", "lookup",
        "LOINC 76689-9 maps directly to sex field",
        1.0, "join", "2024-01-05T09:00:00",
    ),
    (
        "ehr_source_a", "dob", "date_of_birth", "lookup",
        "Standard date of birth field -- direct match",
        1.0, "join", "2024-01-05T09:01:00",
    ),
    (
        "ehr_source_a", "primary_dx_code", "histology_icdo3_code", "llm",
        "ICD-O-3 code column -- semantic match to histology_icdo3_code",
        0.92, "join", "2024-01-05T09:02:00",
    ),
    (
        "ehr_source_a", "adv_stage_grp", "stage_at_advanced_diagnosis", "llm",
        "Staging group label -- high similarity to stage_at_advanced_diagnosis",
        0.88, "join", "2024-01-05T09:03:00",
    ),
    (
        "ehr_source_b", "patient_id_ext", "patient_id", "lookup",
        "UUID patient identifier -- direct identity match",
        1.0, "join", "2024-01-06T10:00:00",
    ),
    (
        "ehr_source_b", "egfr_result", "egfr_status", "lookup",
        "LOINC 53041-0 maps to EGFR mutation status",
        1.0, "join", "2024-01-06T10:01:00",
    ),
    (
        "ehr_source_b", "alk_fish_result", "alk_status", "llm",
        "ALK FISH result column -- semantic match to alk_status",
        0.85, "join", "2024-01-06T10:02:00",
    ),
    (
        "ehr_source_b", "pdl1_score_pct", "pdl1_tps_value", "llm",
        "PD-L1 percent score -- matches pdl1_tps_value numeric field",
        0.91, "join", "2024-01-06T10:03:00",
    ),
    (
        "ehr_source_b", "clinic_site_type", "practice_type", "llm",
        "Clinic setting -- community vs academic -- matches practice_type",
        0.79, "join", "2024-01-07T11:00:00",
    ),
    (
        "ehr_source_c", "rx_name", "medication_administration", "llm",
        "Drug name field -- maps to medication_administration event type",
        0.82, "join", "2024-01-07T11:01:00",
    ),
    (
        "ehr_source_c", "infusion_date", "medication_administration",
        "lookup",
        "RxNorm-coded infusion date -- joins to medication_administration",
        1.0, "join", "2024-01-07T11:02:00",
    ),
    (
        "ehr_source_c", "tumor_size_mm", "imaging_study", "llm",
        "Tumor measurement in mm -- append as imaging_study observation",
        0.74, "append", "2024-01-08T08:00:00",
    ),
    (
        "ehr_source_c", "ecog_score", "ecog_at_advanced_diagnosis",
        "lookup",
        "ECOG numeric score -- direct match to ecog_at_advanced_diagnosis",
        1.0, "join", "2024-01-08T08:01:00",
    ),
    (
        "ehr_source_a", "smoke_pack_years", "pack_years", "llm",
        "Pack-year history -- semantic match to pack_years field",
        0.87, "join", "2024-01-08T08:02:00",
    ),
    (
        "ehr_source_a", "insurance_plan", None, "llm",
        "Insurance plan code -- no canonical field; appended as new column",
        None, "append", "2024-01-09T09:00:00",
    ),
    (
        "ehr_source_b", "zip_code_5", "state_of_residence", "llm",
        "ZIP code -- partial match to geography; operator mapped to state",
        0.61, "join", "2024-01-09T09:01:00",
    ),
    (
        "ehr_source_c", "deceased_flag", "vital_status", "lookup",
        "Boolean deceased flag -- maps to vital_status coded value",
        1.0, "join", "2024-01-10T10:00:00",
    ),
    (
        "ehr_source_c", "last_visit_dt", "last_known_alive_date", "llm",
        "Last visit date -- high similarity to last_known_alive_date",
        0.90, "join", "2024-01-10T10:01:00",
    ),
    (
        "ehr_source_a", "adv_diag_pathway", "advanced_diagnosis_pathway",
        "operator",
        "Operator override: corrected the LLM verdict from unclear to join",
        None, "join", "2024-01-10T14:00:00",
    ),
    (
        "ehr_source_b", "kras_g12c_flag", "kras_status", "lookup",
        "KRAS G12C binary flag -- LOINC 21704-5 match to kras_status",
        1.0, "join", "2024-01-11T09:30:00",
    ),
]


def _ensure_db() -> None:
    """Create demo SQLite database if it does not exist."""
    if _DB_PATH.exists():
        return

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    cur = con.cursor()

    # Read schema SQL if available
    ddl = """
    CREATE TABLE IF NOT EXISTS zippering_decisions (
        id TEXT PRIMARY KEY,
        workspace_key TEXT NOT NULL DEFAULT 'ehrzipper-default',
        pkey TEXT NOT NULL,
        source TEXT NOT NULL,
        source_column TEXT NOT NULL,
        source_data_type TEXT,
        source_description TEXT,
        source_samples TEXT,
        verdict TEXT NOT NULL,
        canonical_name TEXT,
        is_global_target INTEGER NOT NULL DEFAULT 0,
        similarity_score REAL,
        reason TEXT,
        needs_review INTEGER NOT NULL DEFAULT 0,
        decided_by TEXT NOT NULL DEFAULT 'llm',
        decided_at TEXT NOT NULL
    );
    """
    cur.executescript(ddl)

    insert_sql = """
    INSERT INTO zippering_decisions
        (id, workspace_key, pkey, source, source_column, canonical_name,
         decided_by, reason, similarity_score, verdict, decided_at)
    VALUES (?, 'ehrzipper-demo', 'aNSCLC', ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for row in _DEMO_DECISIONS:
        cur.execute(
            insert_sql,
            (
                str(uuid.uuid4()),
                row[0],  # source
                row[1],  # source_column
                row[2],  # canonical_name
                row[3],  # decided_by
                row[4],  # reason
                row[5],  # similarity_score
                row[6],  # verdict
                row[7],  # decided_at
            ),
        )

    con.commit()
    con.close()


_ensure_db()

# ---------------------------------------------------------------------------
# Load decisions
# ---------------------------------------------------------------------------


def load_decisions() -> tuple[pd.DataFrame, bool]:
    """Load decisions.

    Prefers the live snapshot exported from the engine's Snowflake run; falls
    back to the illustrative SQLite fixture if the snapshot is absent. Returns
    (dataframe, is_live).
    """
    cols = [
        "source", "source_column", "canonical_name", "decided_by",
        "similarity_score", "verdict", "reason", "decided_at",
    ]
    if _LIVE_CSV.exists():
        live = pd.read_csv(_LIVE_CSV)
        return live[cols].sort_values("decided_at").reset_index(drop=True), True
    con = sqlite3.connect(str(_DB_PATH))
    df = pd.read_sql_query(
        "SELECT source, source_column, canonical_name, decided_by, "
        "similarity_score, verdict, reason, decided_at "
        "FROM zippering_decisions ORDER BY decided_at ASC",
        con,
    )
    con.close()
    return df, False


df, _is_live = load_decisions()
if _is_live:
    st.caption(
        f"Showing **{len(df)} real decisions** from the engine run against the "
        "three synthetic source formats (FHIR / HL7v2 / CSV), read from Snowflake."
    )

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")

all_deciders = sorted(df["decided_by"].dropna().unique().tolist())
sel_decider = st.sidebar.multiselect(
    "Decided by",
    options=all_deciders,
    default=[],
    placeholder="All",
)

all_verdicts = sorted(df["verdict"].dropna().unique().tolist())
sel_verdict = st.sidebar.multiselect(
    "Verdict",
    options=all_verdicts,
    default=[],
    placeholder="All",
)

mask = pd.Series([True] * len(df))
if sel_decider:
    mask = mask & df["decided_by"].isin(sel_decider)
if sel_verdict:
    mask = mask & df["verdict"].isin(sel_verdict)

filtered = df[mask].copy()

# ---------------------------------------------------------------------------
# Decision log table
# ---------------------------------------------------------------------------
st.subheader("Decision Log")
st.caption(
    f"Showing {len(filtered)} of {len(df)} decisions. "
    "This table is **append-only** — no edits or deletes are permitted."
)

st.dataframe(
    filtered.rename(
        columns={
            "source": "Source",
            "source_column": "Source Column",
            "canonical_name": "Canonical Field",
            "decided_by": "Decided By",
            "similarity_score": "Similarity",
            "verdict": "Verdict",
            "reason": "Reason",
            "decided_at": "Decided At",
        }
    ),
    width="stretch",
    hide_index=True,
)

# ---------------------------------------------------------------------------
# Timeline view
# ---------------------------------------------------------------------------
st.subheader("Decision Timeline")

timeline_df = filtered.copy()
timeline_df["decided_at_dt"] = pd.to_datetime(
    timeline_df["decided_at"], errors="coerce"
)
timeline_df = timeline_df.dropna(subset=["decided_at_dt"])

if not timeline_df.empty:
    # Count decisions per day
    daily = (
        timeline_df.groupby(
            [timeline_df["decided_at_dt"].dt.date, "decided_by"]
        )
        .size()
        .reset_index(name="count")
    )
    daily.columns = ["Date", "Decided By", "Decisions"]

    DECIDER_COLORS = {
        "lookup": "#00A8A8",
        "llm": "#1B3A6B",
        "normalizer": "#9B59B6",
        "operator": "#E67E22",
    }

    fig = px.bar(
        daily,
        x="Date",
        y="Decisions",
        color="Decided By",
        title="Decisions per Day by Routing Tier",
        color_discrete_map=DECIDER_COLORS,
    )
    chart(fig, height=380)
else:
    st.info("No timeline data available for the current filter.")

# ---------------------------------------------------------------------------
# Append-only notice
# ---------------------------------------------------------------------------
st.info(
    "**Audit invariant:** `zippering_decisions` is append-only. "
    "No UPDATE or DELETE operations are permitted. "
    "Operator overrides insert a new row with `decided_by = 'operator'`.",
    icon="🔒",
)
