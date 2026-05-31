"""Page 1 — Cohort Builder.

Build and refine a patient cohort using sidebar filters, then explore
demographics and biomarker co-occurrence across the matched population.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from ui.data.loader import filter_patients, load_patients

st.set_page_config(page_title="Cohort Builder | EHRzipper", layout="wide")

st.title("Cohort Builder")
st.markdown(
    """
    Use the sidebar filters to define a patient cohort. The main panel updates in real time,
    showing cohort size, demographic breakdowns, and biomarker co-occurrence. You can export
    the current filter state as a JSON cohort definition file.
    """
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
all_patients = load_patients()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------
st.sidebar.header("Cohort Filters")

age_range = st.sidebar.slider(
    "Age at Advanced Diagnosis",
    min_value=35,
    max_value=90,
    value=(35, 90),
    step=1,
)

histology_options = [
    "adenocarcinoma",
    "squamous_cell_carcinoma",
    "large_cell_carcinoma",
    "adenosquamous_carcinoma",
    "sarcomatoid_carcinoma",
    "nsclc_nos",
]
sel_histology = st.sidebar.multiselect(
    "Histology",
    options=histology_options,
    default=[],
    placeholder="All",
)

stage_options = ["IIIB", "IIIC", "IVA", "IVB"]
sel_stage = st.sidebar.multiselect(
    "Stage at Advanced Diagnosis",
    options=stage_options,
    default=[],
    placeholder="All",
)

egfr_options = ["positive", "negative", "equivocal", "not_tested", "unknown"]
sel_egfr = st.sidebar.multiselect(
    "EGFR Status",
    options=egfr_options,
    default=[],
    placeholder="All",
)

alk_options = ["positive", "negative", "equivocal", "not_tested", "unknown"]
sel_alk = st.sidebar.multiselect(
    "ALK Status",
    options=alk_options,
    default=[],
    placeholder="All",
)

pdl1_options = ["high", "low", "negative", "equivocal", "not_tested", "unknown"]
sel_pdl1 = st.sidebar.multiselect(
    "PD-L1 Status",
    options=pdl1_options,
    default=[],
    placeholder="All",
)

ecog_options = ["0", "1", "2", "3", "4"]
sel_ecog = st.sidebar.multiselect(
    "ECOG at Advanced Diagnosis",
    options=ecog_options,
    default=[],
    placeholder="All",
)

practice_options = ["community", "academic", "mixed"]
sel_practice = st.sidebar.multiselect(
    "Practice Type",
    options=practice_options,
    default=[],
    placeholder="All",
)

vital_options = ["alive", "deceased", "unknown"]
sel_vital = st.sidebar.multiselect(
    "Vital Status",
    options=vital_options,
    default=[],
    placeholder="All",
)

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
cohort = filter_patients(
    all_patients,
    age_min=age_range[0],
    age_max=age_range[1],
    histology=sel_histology or None,
    stage=sel_stage or None,
    egfr_status=sel_egfr or None,
    alk_status=sel_alk or None,
    pdl1_status=sel_pdl1 or None,
    ecog=sel_ecog or None,
    practice_type=sel_practice or None,
    vital_status=sel_vital or None,
)

# ---------------------------------------------------------------------------
# N metric
# ---------------------------------------------------------------------------
st.metric("Patients matching criteria", f"N = {len(cohort):,}")

if not cohort:
    st.warning("No patients match the current filters. Broaden your selection.")
    st.stop()

df = pd.DataFrame(cohort)

# ---------------------------------------------------------------------------
# Cohort summary table
# ---------------------------------------------------------------------------
st.subheader("Cohort Summary")

summary_fields: list[tuple[str, str]] = [
    ("histology", "Histology"),
    ("stage_at_advanced_diagnosis", "Stage at Advanced Dx"),
    ("egfr_status", "EGFR Status"),
    ("alk_status", "ALK Status"),
    ("pdl1_status", "PD-L1 Status"),
    ("ecog_at_advanced_diagnosis", "ECOG"),
    ("practice_type", "Practice Type"),
    ("vital_status", "Vital Status"),
]

summary_rows: list[dict[str, Any]] = []
for col, label in summary_fields:
    if col not in df.columns:
        continue
    counts = df[col].value_counts()
    for val, cnt in counts.items():
        pct = 100.0 * cnt / len(df)
        summary_rows.append(
            {
                "Field": label,
                "Value": str(val),
                "N": int(cnt),
                "%": f"{pct:.1f}%",
            }
        )

st.dataframe(
    pd.DataFrame(summary_rows),
    use_container_width=True,
    hide_index=True,
)

# ---------------------------------------------------------------------------
# Demographics charts
# ---------------------------------------------------------------------------
st.subheader("Demographics Breakdown")

col1, col2 = st.columns(2)

NAVY = "#1B3A6B"
TEAL = "#00A8A8"
GRAY = "#888888"

with col1:
    if "sex" in df.columns:
        sex_counts = df["sex"].value_counts().reset_index()
        sex_counts.columns = ["Sex", "Count"]
        fig_sex = px.bar(
            sex_counts,
            x="Sex",
            y="Count",
            title="Sex Distribution",
            color="Sex",
            color_discrete_sequence=[TEAL, NAVY, GRAY],
        )
        fig_sex.update_layout(showlegend=False)
        st.plotly_chart(fig_sex, use_container_width=True)
    else:
        st.info("No data available for sex distribution.")

with col2:
    if "race" in df.columns:
        race_counts = df["race"].value_counts().reset_index()
        race_counts.columns = ["Race", "Count"]
        fig_race = px.bar(
            race_counts,
            x="Count",
            y="Race",
            orientation="h",
            title="Race/Ethnicity Distribution",
            color="Race",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_race.update_layout(showlegend=False)
        st.plotly_chart(fig_race, use_container_width=True)
    else:
        st.info("No data available for race distribution.")

# ---------------------------------------------------------------------------
# Biomarker co-occurrence heatmap
# ---------------------------------------------------------------------------
st.subheader("Biomarker Co-occurrence")
st.caption(
    "Each cell shows the number of patients positive for both biomarkers."
    " Only patients with 'positive' status are counted."
)

biomarker_cols = ["egfr_status", "alk_status", "ros1_status", "kras_status", "braf_status"]
available_bm = [c for c in biomarker_cols if c in df.columns]

if available_bm:
    # Build binary matrix: 1 if positive
    bm_df = pd.DataFrame(index=df.index)
    for col in available_bm:
        bm_df[col.replace("_status", "").upper()] = (df[col] == "positive").astype(int)

    bm_labels = list(bm_df.columns)
    cooccur = pd.DataFrame(0, index=bm_labels, columns=bm_labels)
    for i, a in enumerate(bm_labels):
        for b in bm_labels[i:]:
            val = int((bm_df[a] & bm_df[b]).sum())
            cooccur.loc[a, b] = val
            cooccur.loc[b, a] = val

    fig_hm = px.imshow(
        cooccur,
        title="Biomarker Co-occurrence (positive x positive)",
        color_continuous_scale=[[0, "#1B3A6B"], [0.5, "#00A8A8"], [1, "#00FFE0"]],
        text_auto=True,
    )
    st.plotly_chart(fig_hm, use_container_width=True)
else:
    st.info("No biomarker data available.")

# ---------------------------------------------------------------------------
# Export button
# ---------------------------------------------------------------------------
st.subheader("Export Cohort Definition")

filter_state: dict[str, Any] = {
    "age_range": list(age_range),
    "histology": sel_histology,
    "stage_at_advanced_diagnosis": sel_stage,
    "egfr_status": sel_egfr,
    "alk_status": sel_alk,
    "pdl1_status": sel_pdl1,
    "ecog_at_advanced_diagnosis": sel_ecog,
    "practice_type": sel_practice,
    "vital_status": sel_vital,
    "n_patients": len(cohort),
}

st.download_button(
    label="Download cohort definition (JSON)",
    data=json.dumps(filter_state, indent=2),
    file_name="ehrzipper_cohort_definition.json",
    mime="application/json",
)
