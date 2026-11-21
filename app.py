from __future__ import annotations
import os
import sys
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from croptime import crop_model, data_fetch, indicators, soil

st.set_page_config(
    page_title="CROPMAXXING",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Palettes
ACCENT = "#2E7D32"
HEAT = "#C2410C"
GOLD = "#B7791F"
BG = "#FFFFFF"
PANEL = "#F4F6FB"
INK = "#1A2233"
MUTED = "#5A6478"
LINE = "#D6DCE9"
GRID = "#E6EAF2"
BARMUTE = "#A7B3CC"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BG}; }}
    h1, h2, h3, h4 {{ color: {INK}; }}
    .ct-hero {{
        background: linear-gradient(90deg, rgba(46,125,50,0.10), rgba(194,65,12,0.07));
        border-left: 6px solid {ACCENT};
        border-radius: 10px; padding: 18px 24px; margin-bottom: 18px;
    }}
    .ct-hero h1 {{ margin: 0; font-size: 2.3rem; letter-spacing: -0.5px; color: {INK}; }}
    .ct-hero p {{ margin: 6px 0 0 0; color: {MUTED}; font-size: 1.02rem; }}
    .ct-card {{
        background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px;
        padding: 16px 18px; color: {INK};
    }}
    .ct-flag {{
        border-radius: 10px; padding: 16px 20px; font-size: 1.15rem;
        font-weight: 600; border-left: 8px solid; color: {INK};
    }}
    .ct-small {{ color: {MUTED}; font-size: 0.85rem; }}
    div[data-testid="stMetricValue"] {{ color: {INK}; }}
    div[data-testid="stMetricLabel"] {{ color: {MUTED}; }}

    /* Hide the Streamlit toolbar, the Deploy button and the "⋮" main menu.
       config.toml already sets toolbarMode="minimal"; this is a belt-and-
       braces fallback for versions/embeds where the toolbar still renders. */
    header[data-testid="stHeader"] {{ display: none !important; }}
    div[data-testid="stToolbar"] {{ display: none !important; visibility: hidden !important; }}
    div[data-testid="stToolbarActions"] {{ display: none !important; }}
    div[data-testid="stMainMenu"] {{ display: none !important; }}
    div[data-testid="stStatusWidget"] {{ display: none !important; }}
    div[data-testid="stDecoration"] {{ display: none !important; }}
    #MainMenu {{ display: none !important; visibility: hidden !important; }}
    .stDeployButton {{ display: none !important; }}
    .stAppDeployButton {{ display: none !important; }}
    footer {{ display: none !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def style_chart(fig, **layout):

    for axis in ("xaxis", "yaxis", "yaxis2"):
        spec = dict(layout.pop(axis, {}) or {})
        spec.setdefault("gridcolor", GRID)
        spec.setdefault("linecolor", LINE)
        spec.setdefault("zerolinecolor", LINE)
        if axis == "yaxis2":
            spec.setdefault("showgrid", False)
        tf = dict(spec.get("tickfont") or {})
        tf.setdefault("color", MUTED)
        spec["tickfont"] = tf
        ttf = dict(spec.get("title_font") or {})
        ttf.setdefault("color", MUTED)
        spec["title_font"] = ttf
        layout[axis] = spec

    legend = dict(layout.pop("legend", {}) or {})
    lf = dict(legend.get("font") or {})
    lf.setdefault("color", INK)
    legend["font"] = lf
    layout["legend"] = legend

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK),
        title_font=dict(color=INK),
        **layout,
    )

    fig.update_xaxes(gridcolor=GRID, linecolor=LINE, tickfont=dict(color=MUTED),
                     title_font=dict(color=MUTED), zerolinecolor=LINE)
    fig.update_yaxes(gridcolor=GRID, linecolor=LINE, tickfont=dict(color=MUTED),
                     title_font=dict(color=MUTED), zerolinecolor=LINE)
    return fig

PRESETS = {
    "Bhopal, Madhya Pradesh (central plateau)": (23.26, 77.41),
    "Nandurbar, Maharashtra (rain-fed cotton/tur belt)": (21.37, 74.24),
    "Anantapur, Andhra Pradesh (semi-arid, drought-prone)": (14.68, 77.60),
    "Ludhiana, Punjab (high-rainfall north)": (30.90, 75.85),
    "Nagpur, Maharashtra (Vidarbha cotton belt)": (21.15, 79.09),
    "Jodhpur, Rajasthan (arid)": (26.24, 73.02),
    "Bundelkhand - Jhansi, Uttar Pradesh": (25.45, 78.57),
    "Marathwada - Parbhani, Maharashtra": (19.27, 76.77),
}


@st.cache_data(show_spinner=False, ttl=3600)
def load_site(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    return data_fetch.fetch_daily(lat, lon, start, end)


def rain_bar_colours(values: pd.Series) -> list[str]:
    mean = float(values.mean())
    return [HEAT if v < mean * 0.90 else ACCENT for v in values]


st.markdown(
    """
    <div class="ct-hero">
      <h1>✨ CropMaxxing</h1>
      <p>How land’s productivity has changed over time and now which crop one to boost</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------
# Configuration panel (replaces the former sidebar, now inline on the page)
# ----------------------------------------------------------------------------
with st.container(border=True):
    st.markdown("### ⚙️ Your config")

    cfg1, cfg2, cfg3 = st.columns([1.6, 1, 1])

    with cfg1:
        preset_name = st.selectbox("Choose place", list(PRESETS.keys()))
        p_lat, p_lon = PRESETS[preset_name]

        cc1, cc2 = st.columns(2)
        lat = cc1.number_input("Latitude", -90.0, 90.0, float(p_lat), 0.01,
                               format="%.4f")
        lon = cc2.number_input("Longitude", -180.0, 180.0, float(p_lon), 0.01,
                               format="%.4f")

    with cfg2:
        years = st.slider("Years of history", 10, 25, 20)

        include_current = st.checkbox(
            "Include current year (year-to-date)", value=True,
            help="The monsoon window (Jun–Sep) closes in October, so the "
                 "current season's indicators are usable before the calendar "
                 "year ends.",
        )

    with cfg3:
        soil_mode = st.radio(
            "Soil data source",
            ["Auto (SoilGrids → regional)", "Custom"],
            help="Auto queries ISRIC SoilGrids at the point and falls back to "
                 "a labelled regional soil type if the service has a gap. "
                 "Choose Custom to enter your own soil test values.",
        )

        clay = sand = ph = None
        if soil_mode == "Custom":
            clay = st.slider("Clay %", 0, 80, 30, 1)
            sand = st.slider("Sand %", 0, 95, 45, 1)
            ph = st.slider("Soil pH", 4.5, 9.5, 7.2, 0.1)

    start, end = data_fetch.default_range(years=years,
                                          include_current_year=include_current)

    bc1, bc2 = st.columns([1, 3])
    with bc1:
        run = st.button("→ Search New", type="primary",
                        use_container_width=True)
    with bc2:
        st.caption(f"Record window: **{start[:4]} – {end[:4]}**")

if not run and "loaded" not in st.session_state:
    st.info("Pick your config to begin!!")
    st.stop()

# -------------------------------------------------------------------------------------------
try:
    with st.spinner("Fetching satellite-derived records"):
        df = load_site(lat, lon, start, end)
except Exception as exc:
    st.error(f"Can't run this shit {exc}")
    st.stop()

ind = indicators.build_indicator_table(df)

# Resolve soil for this point, then thread it through every crop score.
if soil_mode == "Custom":
    soil_profile = soil.manual_soil(clay, sand, ph)
else:
    soil_profile = soil.get_soil(lat, lon)
soil_info = soil_profile.as_dict()

scores = crop_model.score_all(ind, soil=soil_info)
ranking = crop_model.rank_crops(scores)
factors = crop_model.factor_matrix(ind, soil=soil_info)

if ind.empty or ranking.empty:
    st.error("Not enough complete years in this window to compute indicators.")
    st.stop()

st.session_state["loaded"] = True

# -------------------------------------------------------------------------

fresh = data_fetch.data_freshness(df)
if fresh["latest"] is not None:
    cy = fresh["current_year"]
    cy_in_record = cy in ind.index
    if fresh["monsoon_complete"] and cy_in_record:
        st.success(
            f"**Data current to {fresh['latest_str']}** — {fresh['current_year_days']} "
            f"days of {cy} loaded, and the {cy} monsoon window (Jun–Sep) is complete, "
            f"so this season's indicators are final.",
            icon="🛰",
        )
    elif cy_in_record:
        st.warning(
            f"**Data current to {fresh['latest_str']}** — {cy} monsoon window is "
            f"**not yet complete**, so the {cy} season is shown as provisional.",
            icon="🛰",
        )
    else:
        st.info(f"**Data current to {fresh['latest_str']}** — no {cy} season in "
                f"this window.", icon="🛰")

# -------------------------------------------------------------------------

latest = int(ind.index.max())
first = int(ind.index.min())
rain_now = ind.loc[latest, "season_rain_mm"]
rain_mean = float(ind["season_rain_mm"].mean())
top = ranking.iloc[0]

k1, k2, k3, k4 = st.columns(4)
k1.metric("Record", f"{first}–{latest}", f"{len(ind)} seasons")
k2.metric(f"Rain in {latest}", f"{rain_now:,.0f} mm",
          f"{ind.loc[latest,'rain_anomaly_pct']:+.0f}% vs mean")
k3.metric(f"Mean temp {latest}", f"{ind.loc[latest,'mean_temp_c']:.1f} °C",
          f"{ind.loc[latest,'temp_anomaly_c']:+.1f} °C vs mean")
k4.metric("Top crop", top["crop"].split(" (")[0],
          f"{top['rank_score']:.0f} decision score")

st.markdown("---")