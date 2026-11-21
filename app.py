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
# -------------------------------------------------------------------------


st.markdown('---')
st.markdown('## 🕰 Time Machine — how the season has actually moved')

st.caption(
    "Each bar is one monsoon season (Jun–Sep). Orange bars are seasons well "
    "below the site's own long-term mean."
)

fig = go.Figure()
fig.add_bar(
    x=ind.index, y=ind["season_rain_mm"],
    marker_color=rain_bar_colours(ind["season_rain_mm"]),
    name="Season rainfall",
)
fig.add_scatter(
    x=ind.index, y=ind["season_rain_mm"].rolling(5, min_periods=1).mean(),
    mode="lines", name="5-yr rolling mean",
    line=dict(color=GOLD, width=3),
)
fig.add_hline(y=rain_mean, line_dash="dash", line_color=MUTED,
              annotation_text=f"mean {rain_mean:.0f} mm",
              annotation_font_color=MUTED)
style_chart(
    fig, height=380,
    yaxis_title="Season rainfall (mm)",
    legend=dict(orientation="h", y=1.12, font=dict(color=INK)),
    margin=dict(l=10, r=10, t=40, b=10),
)
st.plotly_chart(fig, use_container_width=True)

c1, c2 = st.columns(2)

with c1:
    st.markdown("**Monsoon onset and dry spells**")
    f2 = go.Figure()
    f2.add_bar(x=ind.index, y=ind["dry_spell_days"],
               name="Longest dry spell (days)", marker_color=HEAT)
    f2.add_scatter(x=ind.index, y=ind["onset_doy"], yaxis="y2",
                   mode="lines+markers", name="Onset (day of year)",
                   line=dict(color=ACCENT, width=2))
    style_chart(
        f2, height=320,
        yaxis=dict(title="Dry spell (days)", gridcolor=GRID,
                   tickfont=dict(color=MUTED)),
        yaxis2=dict(title="Onset DOY", overlaying="y", side="right",
                    showgrid=False, tickfont=dict(color=MUTED),
                    title_font=dict(color=MUTED)),
        legend=dict(orientation="h", y=1.16, font=dict(color=INK)),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(f2, use_container_width=True)

with c2:
    st.markdown("**Drought signal (SPI)**")
    colours = [ACCENT if v >= 0 else HEAT for v in ind["spi"]]
    f3 = go.Figure()
    f3.add_bar(x=ind.index, y=ind["spi"], marker_color=colours, name="SPI")
    f3.add_hline(y=0, line_color=MUTED, line_width=1)
    style_chart(
        f3, height=320,
        yaxis_title="SPI (0 = normal)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(f3, use_container_width=True)

st.markdown(
    f"<div class='ct-card'>"
    f"<b>Read this record in one line:</b> over {len(ind)} seasons the site averaged "
    f"<b>{rain_mean:,.0f} mm</b>, but the year-to-year spread ran from "
    f"<b>{ind['season_rain_mm'].min():,.0f}</b> to "
    f"<b>{ind['season_rain_mm'].max():,.0f} mm</b>. "
    f"Longest dry spell on record: <b>{int(ind['dry_spell_days'].max())} days</b>. "
    f"That spread — not the average — is what breaks a habit-based crop plan."
    f"</div>",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------------

st.markdown('---')
st.markdown('## 🏆 Crop ranking — what is still safe to grow')

st.caption(
    "Decision score = average suitability × how often the season succeeds, "
    "with recent seasons weighted more. A crop that averages well but fails "
    "often is ranked down."
)

show = ranking[["rank", "crop", "mean_score", "reliability_pct",
                "recent_score", "rank_score"]].copy()
show.columns = ["Rank", "Crop", "Mean score", "Reliable years %",
                "Last 5 yrs", "Decision score"]

st.dataframe(
    show, use_container_width=True, hide_index=True,
    column_config={
        "Rank": st.column_config.NumberColumn(width="small"),
        "Mean score": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f"),
        "Last 5 yrs": st.column_config.NumberColumn(format="%.1f"),
        "Decision score": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f"),
    },
)

st.markdown("**Suitability of every crop, every year**")
heat_fig = go.Figure(data=go.Heatmap(
    z=scores.T.values,
    x=[str(y) for y in scores.index],
    y=scores.columns,
    colorscale=[[0, HEAT], [0.55, GOLD], [1, ACCENT]],
    zmin=0, zmax=100,
    colorbar=dict(title="Score", tickfont=dict(color=MUTED),
                  title_font=dict(color=MUTED), outlinecolor=LINE),
    hovertemplate="%{y}<br>%{x}: %{z:.0f}<extra></extra>",
))
style_chart(heat_fig, height=380, margin=dict(l=10, r=10, t=20, b=10))
st.plotly_chart(heat_fig, use_container_width=True)
# --- Factor breakdown: exactly what drove the 2026 recommendation ---
st.markdown(f"**Why these crops? Factor scores for {latest}**")
st.caption(
    "Composite = "
    + " · ".join(f"{k} {v:.0%}" for k, v in crop_model.FACTOR_WEIGHTS.items())
    + ". Each factor is scored 0–100 per crop against that crop's own envelope."
)

fmap = {"rain": "Rain", "temp": "Temp", "veg": "Veg",
        "soil": "Soil", "composite": "Composite"}
fshow = factors[["rain", "temp", "veg", "soil", "composite"]].copy()
fshow.columns = [fmap[c] for c in fshow.columns]
fshow = fshow.sort_values("Composite", ascending=False)

st.dataframe(
    fshow, use_container_width=True,
    column_config={
        "Rain": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f"),
        "Temp": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f"),
        "Veg": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f"),
        "Soil": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f"),
        "Composite": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f"),
    },
)

# Grouped bar: the same numbers, easier to compare across factors.
fbar = go.Figure()
palette = {"Rain": ACCENT, "Temp": HEAT,
           "Veg": "#558B2F", "Soil": GOLD}
for col in ["Rain", "Temp", "Veg", "Soil"]:
    fbar.add_bar(name=col, x=fshow.index, y=fshow[col],
                 marker_color=palette[col])
style_chart(
    fbar, barmode="group", height=380,
    yaxis=dict(title="Factor score (0–100)", range=[0, 105],
               gridcolor=GRID, tickfont=dict(color=MUTED)),
    legend=dict(orientation="h", y=1.12, font=dict(color=INK)),
    margin=dict(l=10, r=10, t=40, b=10),
)
st.plotly_chart(fbar, use_container_width=True)

# Soil provenance, stated plainly.
st.markdown(
    f"<div class='ct-card'><b>Soil used:</b> {soil_info['texture']} "
    f"(clay {soil_info['clay_pct']}%, sand {soil_info['sand_pct']}%, "
    f"pH {soil_info['ph']}) · water-holding index "
    f"{soil_info['water_holding']} · <i>source: {soil_info['source']}</i>"
    f"</div>",
    unsafe_allow_html=True,
)



best = ranking.iloc[0]
worst = ranking.iloc[-1]
st.markdown(
    f"<div class='ct-card'>"
    f"<b>Recommendation for this site:</b> {best['crop']} is the most "
    f"defensible choice — mean score <b>{best['mean_score']:.0f}</b>, "
    f"successful in <b>{best['reliability_pct']:.0f}%</b> of seasons. "
    f"Avoid <b>{worst['crop']}</b> (reliable in only "
    f"{worst['reliability_pct']:.0f}% of years) unless irrigation is available."
    f"</div>",
    unsafe_allow_html=True,
)

# ============================================================================
# TAB 3 - This Season
# ============================================================================

st.markdown('---')
st.markdown('## ⚠ This season — early warning')

pick = st.selectbox("Check a crop", ranking["crop"].tolist())
stt = crop_model.current_season_status(ind, scores, pick)

colour = {"green": ACCENT, "orange": GOLD, "red": HEAT}[stt["colour"]]
st.markdown(
    f"<div class='ct-flag' style='border-left-color:{colour};"
    f"background:{PANEL};'>"
    f"{pick}: <span style='color:{colour}'>{stt['flag'].upper()}</span> "
    f"— season score {stt['score']:.0f}/100 "
    f"({stt['delta']:+.0f} vs history)</div>",
    unsafe_allow_html=True,
)
st.write("")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Season rain", f"{stt['rain_mm']:,.0f} mm")
m2.metric("Monsoon onset", indicators.onset_label(stt["onset"]))
m3.metric("Longest dry spell", f"{stt['dry_spell']} d")
m4.metric("Heat days >35C", f"{stt['heat_days']}")
m5.metric("SPI", f"{stt['spi']:+.2f}")

st.markdown("**Where this season sits in the record**")
comp = scores[pick]
bar_cols = [HEAT if y == latest else BARMUTE for y in comp.index]
fs = go.Figure()
fs.add_bar(x=[str(y) for y in comp.index], y=comp.values,
           marker_color=bar_cols, name=pick)
fs.add_hline(y=crop_model.GOOD_YEAR_SCORE, line_dash="dot",
             line_color=GOLD,
             annotation_text="good-year threshold",
             annotation_font_color=GOLD)
style_chart(
    fs, height=340,
    yaxis=dict(title="Suitability score", range=[0, 105],
               gridcolor=GRID, tickfont=dict(color=MUTED)),
    showlegend=False, margin=dict(l=10, r=10, t=20, b=10),
)
st.plotly_chart(fs, use_container_width=True)

st.caption(
    "Early warning is honest about its limits: it reads the season's climate "
    "signals (rain, onset, dry spell, heat), not crop condition from imagery "
    "on the ground. Treat 'At risk' as a prompt to check the field, "
    "not a verdict."
)

# ============================================================================
# TAB 4 - Details
# ============================================================================

st.markdown('---')
st.markdown('## 📋 Full record — download the numbers')

table = ind.copy()
table.index.name = "year"
table["onset_date"] = [indicators.onset_label(v) for v in table["onset_doy"]]
table["status"] = ["complete" if c else "partial"
                   for c in table["season_complete"]]
table = table[["season_rain_mm", "rain_anomaly_pct", "onset_doy",
               "onset_date", "dry_spell_days", "heat_days",
               "mean_temp_c", "temp_anomaly_c", "gdd", "vigour",
               "spi", "season_days", "status"]]
table.columns = ["Season rain (mm)", "Anomaly %", "Onset DOY",
                 "Onset date", "Dry spell (d)", "Heat days",
                 "Mean temp (C)", "Temp anomaly (C)", "GDD",
                 "Vigour (0-1)", "SPI", "Season days", "Status"]
st.dataframe(
    table.style.format({
        "Season rain (mm)": "{:,.0f}", "Anomaly %": "{:+.0f}",
        "Onset DOY": "{:.0f}", "SPI": "{:+.2f}",
        "Mean temp (C)": "{:.1f}", "Temp anomaly (C)": "{:+.1f}",
        "GDD": "{:,.0f}", "Vigour (0-1)": "{:.2f}",
    }),
    use_container_width=True,
)

st.caption(
    "Mean temp and GDD come from POWER air temperature; vigour is a "
    "climate-derived vegetation proxy (see About), not measured NDVI."
)

st.markdown("**Download**")
d1, d2 = st.columns(2)
d1.download_button(
    "⬇ Indicators CSV",
    table.to_csv().encode("utf-8"),
    file_name=f"croptime_indicators_{lat:.2f}_{lon:.2f}.csv",
    mime="text/csv", use_container_width=True,
)
d2.download_button(
    "⬇ Crop ranking CSV",
    ranking.to_csv(index=False).encode("utf-8"),
    file_name=f"croptime_ranking_{lat:.2f}_{lon:.2f}.csv",
    mime="text/csv", use_container_width=True,
)

with st.expander("Raw daily climate series (first 30 rows)"):
    st.dataframe(df.head(30), use_container_width=True)

# ============================================================================
# TAB 5 - About
# ============================================================================

st.markdown('---')
st.markdown('## ℹ About — data, method and limitations')

st.markdown(
    """

**What it does.** CropTime reads a satellite-derived climate record for one
point, measures how the season actually behaved each year, and ranks crops by
*reliability* — not just average yield. It then flags the current season if it
is diverging from the norm.

**Data.** [NASA POWER](https://power.larc.nasa.gov/) — free, public,
key-less, and derived from satellite observations and reanalysis. We pull daily
`PRECTOTCORR` (bias-corrected precipitation), `T2M`, `T2M_MAX` and `RH2M`.
Nothing proprietary is used, so any judge can reproduce every number.

**Indicators.**
   - Season rainfall: sum over the Jun–Sep monsoon window.
  -   Monsoon onset: first day whose following 7-day total reaches 30 mm
  (a simplified IMD-style rule).
- Dry spell: longest consecutive run of days below 2.5 mm inside the season.
- Heat stress: days with maximum temperature above 35 °C.
- Mean season temperature and its anomaly versus the site's own record.
- GDD:  growing degree days above a 10 °C base, the standard heat-accumulation
  measure that drives crop development rate.
- Vegetation vigour: a 0–1 index from the drivers of canopy growth (rainfall
  adequacy, distance from the ~25 °C optimum, dry-spell and heat penalties). 
- Soil: clay/sand/silt, pH and organic carbon, giving a texture class and a
  water  -   holding index.
- SPI: standardised rainfall index, mean-zero over the site's own record.  

**Scoring — four weighted factors.** Every crop has an agronomic envelope. Each   
season is scored 0–100 on four independent factors, then combined:

| Factor | Weight | What drives the score |
|---|---|---|
| Rain | 35 % | Season rainfall vs the crop's tolerance band |
| Temperature | 22 % | Gaussian fit to the crop's optimum mean temp, plus a GDD window |
| Vegetation | 20 % | Canopy vigour, weighted by the crop's water need |
| Soil | 23 % | pH window × clay/drainage limit × water  -  holding match |

The weighted composite is then multiplied by dry-spell and late-onset   
penalties, and finally aggregated into a decision score that weights average
suitability, reliability across years, and the five most recent seasons.

**Soil sources, in order.** ISRIC SoilGrids is queried live at the point. Where
SoilGrids has a coverage gap the app uses a labelled regional soil type for the
Indian agro-climatic zone, and the UI always states which source was used. You
can also enter soil values manually using the Custom option above.

**Honest limitations.**
  - POWER is a coarsely gridded product: it represents an area, not one field.
- SoilGrids' public mirror has coverage gaps and is intermittently degraded, so 
  some points fall back to a regional soil type rather than a measured value —
  the UI names the source so this is never hidden.
- Vegetation vigour is a **climate-derived proxy**, not measured NDVI. Wiring in   
  Sentinel-2 NDVI via Google Earth Engine would replace it with real canopy
  observations and is the natural next step.
- The crop envelopes are illustrative and would need calibration against
  district yield statistics before real advisory use.

**Built for ASTRA 2026** · Domain 2: Earth Observation & Satellite Applications
        """
    )
