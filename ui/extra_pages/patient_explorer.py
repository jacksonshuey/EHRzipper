"""Page 2 — Patient Explorer.

Drill into individual patient records: biomarker badges, treatment timeline,
event log, and raw FHIR bundle inspection.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ui.data.loader import filter_patients, load_fhir_bundle, load_patient_events, load_patients

st.set_page_config(page_title="Patient Explorer | EHRzipper", layout="wide")

st.title("Patient Explorer")
st.markdown(
    """
    Select a patient from the filtered cohort to view their clinical summary, biomarker panel,
    medication timeline, and full event log. Use the Cohort Builder filters (applied via session
    state) or browse all patients. Raw FHIR Bundle JSON is available in the expandable section.
    """
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
all_patients = load_patients()

# Pick up filter state from session if available (set by cohort builder)
# For standalone use: show all patients
cohort = filter_patients(all_patients)

if not cohort:
    st.warning("No patient data available.")
    st.stop()

patient_ids = [p["patient_id"] for p in cohort]
id_to_patient: dict[str, dict[str, Any]] = {p["patient_id"]: p for p in cohort}

# ---------------------------------------------------------------------------
# Patient selector
# ---------------------------------------------------------------------------
selected_id = st.selectbox(
    "Select patient",
    options=patient_ids,
    format_func=lambda pid: f"{pid}  ({id_to_patient[pid].get('first_name', '')} "
    f"{id_to_patient[pid].get('last_name', '')})",
)

if not selected_id:
    st.info("Select a patient to begin.")
    st.stop()

p = id_to_patient[selected_id]

# ---------------------------------------------------------------------------
# Summary card
# ---------------------------------------------------------------------------
st.subheader("Patient Summary")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Age at Advanced Dx", p.get("age_at_advanced_diagnosis", "—"))
c2.metric("Sex", p.get("sex", "—").title())
c3.metric("ECOG", p.get("ecog_at_advanced_diagnosis", "—"))
c4.metric("Vital Status", p.get("vital_status", "—").title())
c5.metric("Practice Type", p.get("practice_type", "—").title())

st.markdown("---")

col_l, col_r = st.columns(2)
with col_l:
    st.markdown(f"**Histology:** {p.get('histology', '—').replace('_', ' ').title()}")
    st.markdown(f"**Stage at Advanced Dx:** {p.get('stage_at_advanced_diagnosis', '—')}")
    st.markdown(f"**Advanced Dx Date:** {p.get('advanced_diagnosis_date', '—')}")
    st.markdown(f"**Pathway:** {p.get('advanced_diagnosis_pathway', '—').replace('_', ' ')}")
with col_r:
    st.markdown(f"**Smoking Status:** {p.get('smoking_status', '—').title()}")
    st.markdown(f"**Race:** {p.get('race', '—').replace('_', ' ').title()}")
    st.markdown(f"**State:** {p.get('state_of_residence', '—')}")
    lka = p.get("date_of_death") or p.get("last_known_alive_date") or "—"
    label = "Date of Death" if p.get("vital_status") == "deceased" else "Last Known Alive"
    st.markdown(f"**{label}:** {lka}")

# ---------------------------------------------------------------------------
# Biomarker badges
# ---------------------------------------------------------------------------
st.subheader("Biomarker Panel")

BIOMARKER_FIELDS = [
    ("egfr_status", "EGFR"),
    ("alk_status", "ALK"),
    ("ros1_status", "ROS1"),
    ("kras_status", "KRAS"),
    ("braf_status", "BRAF"),
    ("pdl1_status", "PD-L1"),
]

STATUS_COLORS: dict[str, str] = {
    "positive": "background-color:#004d40;color:#00E5C8;border-radius:8px;padding:4px 12px;",
    "negative": "background-color:#1B2A4B;color:#A0B0D0;border-radius:8px;padding:4px 12px;",
    "high": "background-color:#004d40;color:#00E5C8;border-radius:8px;padding:4px 12px;",
    "low": "background-color:#1a1a2e;color:#99AABB;border-radius:8px;padding:4px 12px;",
}

badge_html = "<div style='display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;'>"
for field, label in BIOMARKER_FIELDS:
    val = str(p.get(field, "unknown")).strip()
    style = STATUS_COLORS.get(
        val,
        "background-color:#2a2a2a;color:#888;border-radius:8px;padding:4px 12px;",
    )
    badge_html += f"<span style='{style}'><b>{label}</b>: {val}</span>"
badge_html += "</div>"
st.markdown(badge_html, unsafe_allow_html=True)

if p.get("pdl1_tps_value"):
    st.caption(f"PD-L1 TPS: {p['pdl1_tps_value']}%")

# ---------------------------------------------------------------------------
# Load patient events
# ---------------------------------------------------------------------------
events = load_patient_events(selected_id)

# ---------------------------------------------------------------------------
# Treatment timeline
# ---------------------------------------------------------------------------
st.subheader("Medication Timeline")

meds = events.get("medications", [])
if meds:
    med_df = pd.DataFrame(meds)
    # Build Gantt-style timeline
    timeline_rows = []
    for _, row in med_df.iterrows():
        start = row.get("start_date", "") or ""
        end = row.get("end_date", "") or start
        if not start:
            continue
        timeline_rows.append(
            {
                "Drug": row.get("display", "Unknown"),
                "Class": row.get("drug_class", "unknown"),
                "Start": start,
                "End": end if end else start,
                "Cycle": row.get("cycle", ""),
            }
        )

    if timeline_rows:
        tl_df = pd.DataFrame(timeline_rows)
        # Color by drug class
        class_colors: dict[str, str] = {}
        palette = [
            "#00A8A8", "#1B3A6B", "#E67E22", "#8E44AD",
            "#2ECC71", "#E74C3C", "#3498DB", "#F39C12",
        ]
        for i, cls in enumerate(tl_df["Class"].unique()):
            class_colors[cls] = palette[i % len(palette)]

        fig_tl = go.Figure()
        for _, row in tl_df.iterrows():
            fig_tl.add_trace(
                go.Bar(
                    x=[row["End"]],
                    y=[row["Drug"]],
                    orientation="h",
                    marker_color=class_colors.get(row["Class"], "#888"),
                    name=str(row["Class"]),
                    hovertemplate=(
                        f"<b>{row['Drug']}</b><br>"
                        f"Class: {row['Class']}<br>"
                        f"Start: {row['Start']}<br>"
                        f"End: {row['End']}<br>"
                        f"Cycle: {row['Cycle']}<extra></extra>"
                    ),
                    showlegend=False,
                )
            )

        # Simple horizontal bar chart showing drugs ordered by start date
        tl_sorted = tl_df.sort_values("Start")
        fig_simple = px.timeline(
            tl_sorted.assign(
                Start=pd.to_datetime(tl_sorted["Start"], errors="coerce"),
                End=pd.to_datetime(tl_sorted["End"], errors="coerce"),
            ).dropna(subset=["Start", "End"]),
            x_start="Start",
            x_end="End",
            y="Drug",
            color="Class",
            title="Lines of Therapy",
            color_discrete_sequence=[
                "#00A8A8", "#1B3A6B", "#E67E22", "#8E44AD",
                "#2ECC71", "#E74C3C",
            ],
        )
        fig_simple.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_simple, use_container_width=True)
    else:
        st.info("No medication dates available for timeline rendering.")
else:
    st.info("No medication data available for this patient.")

# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------
st.subheader("Event Log")

all_event_rows: list[dict[str, Any]] = []

for enc in events.get("encounters", []):
    all_event_rows.append(
        {
            "Date": enc.get("encounter_date", ""),
            "Type": "Encounter",
            "Detail": enc.get("encounter_type", ""),
            "Provider": enc.get("provider_specialty", ""),
        }
    )

for med in events.get("medications", []):
    all_event_rows.append(
        {
            "Date": med.get("start_date", ""),
            "Type": "Medication",
            "Detail": med.get("display", ""),
            "Provider": med.get("drug_class", ""),
        }
    )

for bm in events.get("biomarkers", []):
    all_event_rows.append(
        {
            "Date": bm.get("result_date", ""),
            "Type": "Biomarker",
            "Detail": f"{bm.get('biomarker_name', '')} = {bm.get('result', '')}",
            "Provider": bm.get("test_method", ""),
        }
    )

for prg in events.get("progressions", []):
    all_event_rows.append(
        {
            "Date": prg.get("event_date", ""),
            "Type": "Progression",
            "Detail": prg.get("progression_type", ""),
            "Provider": prg.get("evidence_source", ""),
        }
    )

if all_event_rows:
    event_df = pd.DataFrame(all_event_rows).sort_values("Date", na_position="last")
    st.dataframe(event_df, use_container_width=True, hide_index=True)
else:
    st.info("No events available for this patient.")

# ---------------------------------------------------------------------------
# Raw FHIR bundle
# ---------------------------------------------------------------------------
with st.expander("Raw FHIR Bundle (JSON)", expanded=False):
    bundle = load_fhir_bundle(selected_id)
    if bundle:
        st.json(bundle)
    else:
        st.info(
            "No FHIR bundle available for this patient. "
            "FHIR bundles are only generated for patients produced in FHIR format."
        )

# Need plotly import
