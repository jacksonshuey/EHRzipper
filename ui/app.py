"""EHRzipper — clinical data platform demo.

Main entrypoint. Run with:
    streamlit run ui/app.py
"""

import streamlit as st

st.set_page_config(
    page_title="EHRzipper | aNSCLC Cohort Platform",
    page_icon="🫁",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("EHRzipper -- aNSCLC Cohort Platform")
st.markdown(
    """
    Welcome to the **EHRzipper** clinical data platform demo. This application demonstrates a
    Flatiron-style real-world oncology data product built on synthetic advanced NSCLC patient
    data.

    Take messy oncology records from many hospital systems, reconcile them into
    one clean dataset with a full audit trail, and produce the real-world cancer
    outcomes that pharma companies buy. Use the sidebar to navigate:

    | Page | What it shows |
    |------|-------------|
    | **Import Data** | Upload or import EHR files (FHIR / HL7v2 / CSV) and reconcile them live |
    | **Cohort Builder** | Build an oncology cohort from reconciled multi-source data |
    | **Survival Analysis** | Real-world overall survival (Kaplan-Meier) by biomarker subgroup |
    | **Audit Trail** | Every schema decision, traceable — the append-only provenance log |
    """
)

st.info(
    "All patient data is **fully synthetic** -- no real PHI is present anywhere."
)
