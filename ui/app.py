"""EHRzipper — clinical data platform demo.

Main entrypoint. Run with:
    streamlit run ui/app.py
"""

import streamlit as st

from ui.components.theme import header, setup_page

setup_page("aNSCLC Cohort Platform")

header(
    "EHRzipper",
    "A Flatiron-style real-world oncology data product. Reconcile messy "
    "multi-source EHR records into one clean, audited dataset — and produce the "
    "real-world cancer outcomes that pharma companies buy.",
)

st.markdown(
    """
    Built on **fully synthetic** advanced NSCLC patient data. Use the sidebar to navigate:

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
