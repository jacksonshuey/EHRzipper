"""Page 4 — Data Dictionary.

Auto-generated from the canonical schema seed CSV. Browse, search, and
filter all canonical fields with their FHIR mappings and controlled vocabularies.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Data Dictionary | EHRzipper", layout="wide")

st.title("Data Dictionary")
st.markdown(
    """
    This page is auto-generated from `methodology/canonical-schema-seed.csv`. It lists every
    canonical field in the EHRzipper schema with its data type, description, FHIR mapping, and
    controlled vocabulary. Use the search box or semantic-tag filter to navigate the schema.
    """
)

# ---------------------------------------------------------------------------
# Load schema seed CSV
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
SCHEMA_CSV = _PROJECT_ROOT / "methodology" / "canonical-schema-seed.csv"


def load_schema() -> pd.DataFrame:
    """Load canonical schema from CSV."""
    if not SCHEMA_CSV.exists():
        return pd.DataFrame(
            columns=["name", "data_type", "description", "semantic_tags",
                     "fhir_resource", "fhir_path", "controlled_vocabulary"]
        )
    rows = []
    with SCHEMA_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(dict(row))
    return pd.DataFrame(rows)


df = load_schema()

if df.empty:
    st.error("Schema seed CSV not found. Expected at methodology/canonical-schema-seed.csv")
    st.stop()

# Rename columns for display
display_cols = {
    "name": "Field Name",
    "data_type": "Data Type",
    "description": "Description",
    "semantic_tags": "Semantic Tags",
    "fhir_resource": "FHIR Resource",
    "fhir_path": "FHIR Path",
    "controlled_vocabulary": "Controlled Vocabulary",
}
df_display = df.rename(columns=display_cols)

# ---------------------------------------------------------------------------
# Collect all semantic tags for filter
# ---------------------------------------------------------------------------
all_tags: set[str] = set()
for tags_str in df["semantic_tags"].dropna():
    for t in str(tags_str).split("|"):
        t = t.strip()
        if t:
            all_tags.add(t)
sorted_tags = sorted(all_tags)

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
col_search, col_tag = st.columns([2, 1])

with col_search:
    search_term = st.text_input(
        "Search fields",
        placeholder="e.g. egfr, biomarker, stage...",
    )

with col_tag:
    sel_tag = st.selectbox(
        "Filter by semantic tag",
        options=["(all)", *sorted_tags],
    )

# Apply filters
mask = pd.Series([True] * len(df))

if search_term:
    term_lower = search_term.lower()
    mask = mask & (
        df["name"].str.lower().str.contains(term_lower, na=False)
        | df["description"].str.lower().str.contains(term_lower, na=False)
        | df.get("controlled_vocabulary", pd.Series(dtype=str))
          .str.lower().str.contains(term_lower, na=False)
    )

if sel_tag and sel_tag != "(all)":
    mask = mask & df["semantic_tags"].str.contains(sel_tag, na=False)

filtered = df_display[mask].copy()
st.caption(f"Showing {len(filtered)} of {len(df)} fields")

# ---------------------------------------------------------------------------
# Main table
# ---------------------------------------------------------------------------
st.dataframe(
    filtered[
        [c for c in display_cols.values() if c in filtered.columns]
    ],
    use_container_width=True,
    hide_index=True,
)

# ---------------------------------------------------------------------------
# Download button
# ---------------------------------------------------------------------------
csv_buf = io.StringIO()
filtered.to_csv(csv_buf, index=False)
st.download_button(
    label="Download filtered schema as CSV",
    data=csv_buf.getvalue(),
    file_name="ehrzipper_schema.csv",
    mime="text/csv",
)
