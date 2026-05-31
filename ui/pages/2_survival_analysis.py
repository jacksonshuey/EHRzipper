"""Page 3 — Survival Analysis.

Kaplan-Meier overall survival curves for the aNSCLC cohort, stratified by
EGFR status. Survival times are derived from advanced diagnosis date to
date of death (or last known alive date for censored patients).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.components.theme import chart, header, setup_page
from ui.data.loader import load_patients

setup_page("Survival Analysis")

header(
    "Survival Analysis",
    "Kaplan-Meier real-world overall survival, measured from advanced diagnosis "
    "to death, with living patients censored at last known alive date. Toggle to "
    "stratify by EGFR mutation status.",
)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
all_patients = load_patients()
df = pd.DataFrame(all_patients)

# ---------------------------------------------------------------------------
# Compute survival times
# ---------------------------------------------------------------------------


def _months_between(start: str, end: str) -> float | None:
    """Return approximate months between two partial-date strings (YYYY-MM[-DD])."""
    try:
        s_str = start[:10] if len(start) >= 10 else start + "-01"
        e_str = end[:10] if len(end) >= 10 else end + "-01"
        s = pd.to_datetime(s_str)
        e = pd.to_datetime(e_str)
        days: float = float((e - s).days)
        return max(0.0, days / 30.44)
    except Exception:
        return None


survival_rows: list[dict[str, Any]] = []
for _, row in df.iterrows():
    adv_date = str(row.get("advanced_diagnosis_date", "") or "")
    if not adv_date:
        continue

    vital = str(row.get("vital_status", "unknown"))
    event = 1 if vital == "deceased" else 0

    if vital == "deceased" and row.get("date_of_death"):
        end_date = str(row["date_of_death"])
    else:
        end_date = str(row.get("last_known_alive_date") or row.get("data_cutoff_date") or "")

    if not end_date:
        continue

    t = _months_between(adv_date, end_date)
    if t is None or t < 0:
        continue

    survival_rows.append(
        {
            "patient_id": row.get("patient_id"),
            "time_months": t,
            "event": event,
            "egfr_status": str(row.get("egfr_status", "unknown")),
        }
    )

surv_df = pd.DataFrame(survival_rows)

if surv_df.empty:
    st.warning("Insufficient data to compute survival curves.")
    st.stop()

# ---------------------------------------------------------------------------
# KM estimator (pure Python — no lifelines dependency)
# ---------------------------------------------------------------------------


def kaplan_meier(
    times: list[float], events: list[int]
) -> tuple[list[float], list[float]]:
    """Compute KM survival estimate.

    Args:
        times: List of observation times.
        events: List of event indicators (1=event, 0=censored).

    Returns:
        (time_points, survival_probabilities)
    """
    paired = sorted(zip(times, events, strict=False), key=lambda x: x[0])
    n = len(paired)
    km_times: list[float] = [0.0]
    km_surv: list[float] = [1.0]
    s = 1.0
    i = 0
    while i < n:
        t = paired[i][0]
        # Collect all at this time
        d = sum(1 for tt, ee in paired[i:] if tt == t and ee == 1)
        c = sum(1 for tt, _ in paired[i:] if tt == t)
        at_risk = n - i
        if d > 0 and at_risk > 0:
            s *= 1.0 - d / at_risk
        km_times.append(t)
        km_surv.append(s)
        i += c
    return km_times, km_surv


def median_os(times: list[float], surv: list[float]) -> float | None:
    """Return median OS (time when survival crosses 0.5)."""
    for i in range(1, len(surv)):
        if surv[i] <= 0.5:
            return times[i]
    return None


def at_risk_table(
    times: list[float], events: list[int], checkpoints: list[float]
) -> list[int]:
    """Return number at risk at each checkpoint time."""
    result = []
    for cp in checkpoints:
        n_at_risk = sum(1 for t, _ in zip(times, events, strict=False) if t >= cp)
        result.append(n_at_risk)
    return result


# ---------------------------------------------------------------------------
# Toggle: overall vs stratified
# ---------------------------------------------------------------------------
stratify = st.checkbox("Stratify by EGFR status", value=True)

COLORS: dict[str, str] = {
    "positive": "#00A8A8",
    "negative": "#1B3A6B",
    "not_tested": "#888888",
    "equivocal": "#E67E22",
    "unknown": "#AAAAAA",
    "all": "#00A8A8",
}

fig = go.Figure()

checkpoints: list[float] = [0.0, 6.0, 12.0, 18.0, 24.0, 36.0, 48.0]
at_risk_rows: list[dict[str, Any]] = []

if stratify:
    groups = surv_df["egfr_status"].unique().tolist()
    for grp in sorted(groups):
        gdf = surv_df[surv_df["egfr_status"] == grp]
        if gdf.empty:
            continue
        km_t, km_s = kaplan_meier(
            gdf["time_months"].tolist(), gdf["event"].tolist()
        )
        m_os = median_os(km_t, km_s)
        color = COLORS.get(grp, "#AAAAAA")

        # Step function: repeat each time point to make steps
        step_t: list[float] = []
        step_s: list[float] = []
        for i in range(len(km_t)):
            step_t.append(km_t[i])
            step_s.append(km_s[i])
            if i + 1 < len(km_t):
                step_t.append(km_t[i + 1])
                step_s.append(km_s[i])

        fig.add_trace(
            go.Scatter(
                x=step_t,
                y=step_s,
                mode="lines",
                name=(
                    f"EGFR {grp} (N={len(gdf)}, mOS={m_os:.1f}mo)"
                    if m_os
                    else f"EGFR {grp} (N={len(gdf)})"
                ),
                line={"color": color, "width": 2},
            )
        )
        ar = at_risk_table(
            gdf["time_months"].tolist(), gdf["event"].tolist(), checkpoints
        )
        at_risk_rows.append({
            "Subgroup": f"EGFR {grp}",
            **{str(cp): n for cp, n in zip(checkpoints, ar, strict=False)},
        })
else:
    km_t, km_s = kaplan_meier(
        surv_df["time_months"].tolist(), surv_df["event"].tolist()
    )
    m_os = median_os(km_t, km_s)

    step_t = []
    step_s = []
    for i in range(len(km_t)):
        step_t.append(km_t[i])
        step_s.append(km_s[i])
        if i + 1 < len(km_t):
            step_t.append(km_t[i + 1])
            step_s.append(km_s[i])

    fig.add_trace(
        go.Scatter(
            x=step_t,
            y=step_s,
            mode="lines",
            name=f"All patients (N={len(surv_df)})",
            line={"color": "#00A8A8", "width": 2},
        )
    )
    ar = at_risk_table(
        surv_df["time_months"].tolist(), surv_df["event"].tolist(), checkpoints
    )
    at_risk_rows.append({
        "Subgroup": "All",
        **{str(cp): n for cp, n in zip(checkpoints, ar, strict=False)},
    })

fig.add_hline(y=0.5, line_dash="dash", line_color="#8A93A0", annotation_text="50%")
fig.update_layout(
    title="Kaplan-Meier Overall Survival",
    xaxis_title="Time from Advanced Diagnosis (months)",
    yaxis_title="Survival Probability",
    yaxis={"range": [0, 1.05]},
    legend={"orientation": "h", "yanchor": "bottom", "y": -0.3},
)
chart(fig, height=460)

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
n_events = int(surv_df["event"].sum())
n_censored = int((surv_df["event"] == 0).sum())
median_follow = float(surv_df["time_months"].median())

m1, m2, m3 = st.columns(3)
m1.metric("Events (deaths)", n_events)
m2.metric("Censored", n_censored)
m3.metric("Median follow-up (months)", f"{median_follow:.1f}")

# ---------------------------------------------------------------------------
# At-risk table
# ---------------------------------------------------------------------------
st.subheader("At-Risk Table")
st.caption("Number of patients remaining at risk at each time point (months).")

if at_risk_rows:
    ar_df = pd.DataFrame(at_risk_rows)
    st.dataframe(ar_df, width="stretch", hide_index=True)
