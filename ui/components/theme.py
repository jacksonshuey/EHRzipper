"""Shared visual theme for the EHRzipper UI.

One place for the brand palette, page setup (wide layout, expanded sidebar,
and CSS that removes Streamlit's dev chrome and tightens the look), the product
header, and Plotly styling — so every page and every chart reads as one
coherent product rather than a stack of stock widgets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------
NAVY = "#0B2E4F"
NAVY_SOFT = "#1B3A6B"
TEAL = "#00A8A8"
TEAL_BRIGHT = "#16C7C7"
INK = "#15212B"
MUTED = "#5B6B7A"
LINE = "#E3E8EF"
CANVAS = "#F4F7FA"

# Distinct, on-brand sequence for categorical charts.
CATEGORICAL = [TEAL, NAVY_SOFT, "#E6883C", "#7B61C9", "#3FA66A", "#C0566B", "#8A93A0"]
# Light → brand ramp for heatmaps.
SEQUENTIAL = [[0.0, "#EAF4F4"], [0.5, TEAL], [1.0, NAVY]]

_FONT = "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif"

_GLOBAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Hide Streamlit's dev chrome so it reads as a product, not a notebook. */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{
    display: none !important;
}}
[data-testid="stHeader"] {{ background: transparent; height: 0; }}

html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
    font-family: {_FONT};
    color: {INK};
}}

/* Reclaim the big default top padding. */
[data-testid="stMainBlockContainer"] {{
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1320px;
}}

/* Thin brand accent across the very top of the page. */
[data-testid="stAppViewContainer"] > .main::before {{
    content: "";
    display: block;
    height: 4px;
    background: linear-gradient(90deg, {NAVY} 0%, {TEAL} 100%);
}}

h1, h2, h3, h4 {{ color: {NAVY}; font-weight: 700; letter-spacing: -0.01em; }}
h1 {{ font-size: 2.1rem; }}

/* Product header band. */
.ehz-header {{
    border-bottom: 1px solid {LINE};
    padding: 0.2rem 0 1.1rem 0;
    margin-bottom: 1.4rem;
}}
.ehz-header .ehz-title {{
    font-size: 2.05rem; font-weight: 700; color: {NAVY};
    letter-spacing: -0.02em; line-height: 1.1;
}}
.ehz-header .ehz-title .ehz-accent {{ color: {TEAL}; }}
.ehz-header .ehz-sub {{
    font-size: 1.02rem; color: {MUTED}; margin-top: 0.35rem; max-width: 60ch;
}}

/* Metrics as quiet cards. */
[data-testid="stMetric"] {{
    background: #FFFFFF;
    border: 1px solid {LINE};
    border-radius: 12px;
    padding: 1rem 1.1rem;
    box-shadow: 0 1px 2px rgba(15, 35, 55, 0.04);
}}
[data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; }}
[data-testid="stMetricLabel"] {{ color: {MUTED}; }}

/* Dataframes: softer border, rounded. */
[data-testid="stDataFrame"] {{
    border: 1px solid {LINE};
    border-radius: 12px;
    overflow: hidden;
}}

/* Sidebar: subtle brand surface + branded heading. */
[data-testid="stSidebar"] {{
    background: {CANVAS};
    border-right: 1px solid {LINE};
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2 {{ font-size: 1.05rem; }}

/* Primary buttons in brand teal. */
.stButton > button[kind="primary"], .stDownloadButton > button {{
    background: {TEAL}; border: none; font-weight: 600;
}}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button:hover {{
    background: {TEAL_BRIGHT};
}}

/* Tidy the radio/segment row on the import page. */
[role="radiogroup"] label {{ font-weight: 500; }}
</style>
"""


def setup_page(title: str, icon: str = "🫁") -> None:
    """Configure the page and inject the shared look.

    Call once at the top of every page, before other Streamlit calls.
    """
    st.set_page_config(
        page_title=f"{title} | EHRzipper",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str) -> None:
    """Render the branded product header (title + one-line subtitle)."""
    accent_html = title.replace(
        "zipper", "<span class='ehz-accent'>zipper</span>", 1
    )
    st.markdown(
        f"""
        <div class="ehz-header">
          <div class="ehz-title">{accent_html}</div>
          <div class="ehz-sub">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def style_fig(
    fig: go.Figure,
    height: int = 360,
    show_legend: bool = True,
    grid: bool = True,
) -> go.Figure:
    """Apply the shared chart styling and return the figure.

    Transparent backgrounds so charts sit on the page canvas, brand font and
    colorway, restrained gridlines, and sane margins.
    """
    has_title = bool(getattr(fig.layout.title, "text", None))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": _FONT, "color": INK, "size": 13},
        colorway=CATEGORICAL,
        margin={"l": 48, "r": 24, "t": 52 if has_title else 16, "b": 44},
        height=height,
        legend={
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": MUTED, "size": 12},
        },
        hoverlabel={"font": {"family": _FONT}},
    )
    if has_title:
        fig.update_layout(title={"font": {"family": _FONT, "color": NAVY, "size": 17}})
    else:
        fig.update_layout(title_text="")
    fig.update_xaxes(
        showgrid=False, zeroline=False, linecolor=LINE,
        ticks="outside", tickcolor=LINE, title_font={"color": MUTED},
    )
    fig.update_yaxes(
        showgrid=grid, gridcolor=LINE, zeroline=False, linecolor=LINE,
        title_font={"color": MUTED},
    )
    if not show_legend:
        fig.update_layout(showlegend=False)
    return fig


def chart(
    fig: go.Figure,
    height: int = 360,
    show_legend: bool = True,
    grid: bool = True,
) -> None:
    """Style a figure and render it full-width."""
    styled = style_fig(fig, height=height, show_legend=show_legend, grid=grid)
    st.plotly_chart(styled, width="stretch")
