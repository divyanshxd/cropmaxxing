"""Crop suitability and risk-adjusted ranking.

For each candidate crop we define a simple agronomic envelope: the season
rainfall band the crop tolerates, how much dry spell it can take, whether
heat hurts it, and how late an onset it can survive.

Each season year is scored 0-100 for each crop. We then aggregate:
  mean_score    average suitability across the record  ("can it grow here?")
  reliability   share of years scoring >= 55            ("how often?")
  rank_score    weighted blend of mean, reliability and recent years

The key product insight: a crop with a high average but low reliability is
a gamble. The rank_score makes that visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

GOOD_YEAR_SCORE = 55.0  # threshold for "this year worked for this crop"


@dataclass
class CropProfile:
    name: str
    rain_lo: float                 # mm, season total lower tolerance
    rain_hi: float                 # mm, season total upper tolerance
    rain_opt_lo: float             # comfortable band inside the tolerance
    rain_opt_hi: float
    max_dry_spell: int             # longest dry spell tolerated (days)
    heat_sensitive: bool = False
    heat_tolerance_days: int = 45
    late_onset_ok_doy: int = 185   # latest onset (day-of-year) tolerated
    # --- temperature envelope ---
    temp_opt_c: float = 27.0       # optimum season mean temperature
    temp_range_c: float = 6.0      # tolerance half-width around the optimum
    gdd_lo: float = 1500.0         # minimum season heat accumulation needed
    gdd_hi: float = 3200.0         # upper heat accumulation tolerated
    # --- soil envelope ---
    soil_ph_lo: float = 6.0
    soil_ph_hi: float = 8.0
    soil_clay_max: float = 55.0    # drainage limit: heavy clay drowns the crop
    water_need: str = "medium"     # "low" | "medium" | "high"
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# Envelopes are intentionally broad and illustrative for a prototype. They are
# editable: a real deployment would calibrate against district yield statistics
# and agronomy extension bulletins.
CROPS: list[CropProfile] = [
    CropProfile("Sorghum (Jowar)", rain_lo=350, rain_hi=900,
                rain_opt_lo=450, rain_opt_hi=800, max_dry_spell=25,
                late_onset_ok_doy=190,
                temp_opt_c=28.0, temp_range_c=6.0, gdd_lo=1500, gdd_hi=3400,
                soil_ph_lo=5.8, soil_ph_hi=8.2, soil_clay_max=60,
                water_need="low",
                notes="Drought-tolerant millet; strong fit for erratic rainfall.",
                tags=("millet", "drought-tolerant", "kharif")),
    CropProfile("Pearl Millet (Bajra)", rain_lo=250, rain_hi=750,
                rain_opt_lo=350, rain_opt_hi=650, max_dry_spell=30,
                late_onset_ok_doy=195,
                temp_opt_c=29.0, temp_range_c=6.5, gdd_lo=1550, gdd_hi=3600,
                soil_ph_lo=6.0, soil_ph_hi=8.4, soil_clay_max=50,
                water_need="low",
                notes="Very drought-hardy; suits low and late rainfall years.",
                tags=("millet", "drought-tolerant", "kharif")),
    CropProfile("Pigeonpea (Tur)", rain_lo=400, rain_hi=1000,
                rain_opt_lo=500, rain_opt_hi=900, max_dry_spell=20,
                late_onset_ok_doy=185,
                temp_opt_c=27.0, temp_range_c=5.5, gdd_lo=1600, gdd_hi=3200,
                soil_ph_lo=6.0, soil_ph_hi=8.0, soil_clay_max=65,
                water_need="medium",
                notes="Long-duration pulse; rewards a well-spread monsoon.",
                tags=("pulse", "kharif")),
    CropProfile("Cotton", rain_lo=500, rain_hi=1100,
                rain_opt_lo=600, rain_opt_hi=1000, max_dry_spell=18,
                late_onset_ok_doy=182,
                temp_opt_c=28.0, temp_range_c=5.0, gdd_lo=1800, gdd_hi=3400,
                soil_ph_lo=6.2, soil_ph_hi=8.6, soil_clay_max=72,
                water_need="medium",
                notes="Cash crop; needs good early moisture and a dry harvest. "
                      "Tolerates heavy black-cotton soils well.",
                tags=("cash", "kharif")),
    CropProfile("Soybean", rain_lo=550, rain_hi=1050,
                rain_opt_lo=650, rain_opt_hi=950, max_dry_spell=12,
                heat_sensitive=True, heat_tolerance_days=35,
                late_onset_ok_doy=180,
                temp_opt_c=26.0, temp_range_c=4.5, gdd_lo=1500, gdd_hi=2900,
                soil_ph_lo=6.0, soil_ph_hi=7.5, soil_clay_max=50,
                water_need="high",
                notes="Sensitive to mid-season dry spells; the classic failure case.",
                tags=("oilseed", "kharif")),
    CropProfile("Maize", rain_lo=450, rain_hi=1000,
                rain_opt_lo=550, rain_opt_hi=900, max_dry_spell=15,
                heat_sensitive=True, heat_tolerance_days=30,
                late_onset_ok_doy=180,
                temp_opt_c=26.5, temp_range_c=4.5, gdd_lo=1700, gdd_hi=3100,
                soil_ph_lo=5.8, soil_ph_hi=7.8, soil_clay_max=55,
                water_need="high",
                notes="Responsive to moisture; hurt by both heat and dry spells.",
                tags=("cereal", "kharif")),
    CropProfile("Rice (upland)", rain_lo=700, rain_hi=1600,
                rain_opt_lo=850, rain_opt_hi=1400, max_dry_spell=10,
                late_onset_ok_doy=178,
                temp_opt_c=28.0, temp_range_c=5.0, gdd_lo=2000, gdd_hi=3600,
                soil_ph_lo=5.5, soil_ph_hi=7.8, soil_clay_max=85,
                water_need="high",
                notes="Needs assured water; risky on purely rain-fed land.",
                tags=("cereal", "water-intensive", "kharif")),
    CropProfile("Groundnut", rain_lo=450, rain_hi=950,
                rain_opt_lo=550, rain_opt_hi=850, max_dry_spell=18,
                heat_sensitive=True, heat_tolerance_days=35,
                late_onset_ok_doy=183,
                temp_opt_c=27.5, temp_range_c=5.0, gdd_lo=1650, gdd_hi=3100,
                soil_ph_lo=6.0, soil_ph_hi=7.6, soil_clay_max=38,
                water_need="medium",
                notes="Good fit for medium rainfall with light, sandy soils; "
                      "heavy clay causes pod rot.",
                tags=("oilseed", "kharif")),
    CropProfile("Chickpea (Chana)", rain_lo=0, rain_hi=600,
                rain_opt_lo=150, rain_opt_hi=450, max_dry_spell=40,
                heat_sensitive=True, heat_tolerance_days=20,
                late_onset_ok_doy=200,
                temp_opt_c=23.0, temp_range_c=5.0, gdd_lo=1300, gdd_hi=2600,
                soil_ph_lo=6.2, soil_ph_hi=8.4, soil_clay_max=65,
                water_need="low",
                notes="Rabi pulse; sown on residual moisture after the monsoon.",
                tags=("pulse", "rabi")),
]


def _ramp(value: float, lo: float, hi: float) -> float:
    """0 -> 1 linear ramp between lo and hi, clamped."""
    if hi == lo:
        return 1.0 if value >= hi else 0.0
    return float(np.clip((value - lo) / (hi - lo), 0.0, 1.0))


def rain_score(total: float, c: CropProfile) -> float:
    """0-100 score from season rainfall vs the crop's tolerance band."""
    if pd.isna(total):
        return 0.0
    if total < c.rain_lo:
        # Too little rain: score falls off below the tolerance floor.
        # We keep a floor of 25 so a drought-hardy crop is not scored as
        # totally hopeless in a dry year - it is still the better bet.
        return max(25.0, 100.0 * _ramp(total, c.rain_lo * 0.45, c.rain_lo))
    if total > c.rain_hi:
        return 100.0 * (1.0 - _ramp(total, c.rain_hi, c.rain_hi * 1.35))
    if c.rain_opt_lo <= total <= c.rain_opt_hi:
        return 100.0
    if total < c.rain_opt_lo:
        return 70.0 + 30.0 * _ramp(total, c.rain_lo, c.rain_opt_lo)
    return 100.0 - 30.0 * _ramp(total, c.rain_opt_hi, c.rain_hi)


def stress_score(dry_days: int, heat_days: int, c: CropProfile) -> float:
    """0-1 multiplier for dry spells and heat. 1.0 = no stress."""
    dry_factor = 1.0 - 0.75 * _ramp(float(dry_days),
                                    float(c.max_dry_spell),
                                    float(c.max_dry_spell) * 2.0)
    heat_factor = 1.0
    if c.heat_sensitive:
        heat_factor = 1.0 - 0.5 * _ramp(float(heat_days),
                                        float(c.heat_tolerance_days),
                                        float(c.heat_tolerance_days) * 2.2)
    return float(np.clip(dry_factor * heat_factor, 0.0, 1.0))


def onset_penalty(onset: float, c: CropProfile) -> float:
    """0-1 multiplier for a late monsoon onset."""
    if pd.isna(onset):
        return 0.6  # no clear onset: a poor year for any kharif crop
    if onset <= c.late_onset_ok_doy:
        return 1.0
    overshoot = (onset - c.late_onset_ok_doy) / 10.0
    return float(np.clip(1.0 - 0.15 * overshoot, 0.35, 1.0))

# ---------------------------------------------------------------------------
# New factor scorers: temperature, vegetation, soil
# ---------------------------------------------------------------------------

def temp_score(mean_temp: float, gdd: float, c: CropProfile) -> float:
    """0-100 thermal suitability for one season.

    Two independent thermal constraints:

    * **Level** - how close the season mean temperature sits to the crop's
      optimum, modelled as a Gaussian so the crop is penalised symmetrically
      for being too hot or too cold.
    * **Accumulation** - growing degree days. A cool season can have the right
      average but too little accumulated heat for a long-duration crop to
      finish grain fill. Below `gdd_lo` we penalise; above `gdd_hi` we
      penalise for heat-driven sterility.
    """
    if pd.isna(mean_temp):
        return 50.0  # unknown: neutral, do not distort the ranking

    sigma = max(0.5, c.temp_range_c / 2.0)
    level = float(np.exp(-((mean_temp - c.temp_opt_c) ** 2) / (2 * sigma ** 2)))

    if pd.isna(gdd) or gdd <= 0:
        accum = 0.75
    elif gdd < c.gdd_lo:
        accum = float(np.clip(0.45 + 0.55 * (gdd / c.gdd_lo), 0.45, 1.0))
    elif gdd <= c.gdd_hi:
        accum = 1.0
    else:
        accum = float(np.clip(1.0 - 0.5 * (gdd - c.gdd_hi) / c.gdd_hi, 0.45, 1.0))

    return float(np.clip(100.0 * (0.65 * level + 0.35 * accum), 0.0, 100.0))


def veg_score(vigour: float, c: CropProfile) -> float:
    """0-100 vegetation-condition suitability.

    Vegetation vigour tells us whether the canopy actually developed in the
    season. Crops with a high water requirement depend on sustained canopy
    growth and are hit harder when vigour is low; drought-hardy crops keep
    yielding on a thin canopy.
    """
    if pd.isna(vigour):
        return 50.0  # unknown: neutral

    base = 20.0 + 80.0 * float(np.clip(vigour, 0.0, 1.0))
    sensitivity = {"low": 0.75, "medium": 1.0, "high": 1.30}
    s = sensitivity.get(c.water_need, 1.0)
    adjusted = 60.0 + (base - 60.0) * s
    return float(np.clip(adjusted, 0.0, 100.0))


def soil_score(clay_pct: float, ph: float, water_holding: float,
               c: CropProfile) -> float:
    """0-100 soil suitability from texture, pH and water-holding capacity.

    Three agronomic constraints:

    * **pH** - each crop has a pH window. Outside it, nutrient availability
      collapses (iron chlorosis in alkaline soils, aluminium toxicity in acid
      ones), so we ramp down toward a floor.
    * **Drainage** - a crop has a maximum clay fraction it tolerates. Excess
      clay means waterlogging and root disease; groundnut is far stricter
      than cotton here.
    * **Water-holding match** - a high-water-need crop on a sandy soil cannot
      hold moisture; a low-need crop on heavy clay risks fungal disease.
    """
    if pd.isna(clay_pct) or pd.isna(ph):
        return 60.0  # unknown: mildly positive neutral

    if c.soil_ph_lo <= ph <= c.soil_ph_hi:
        ph_f = 1.0
    elif ph < c.soil_ph_lo:
        ph_f = float(np.clip(1.0 - (c.soil_ph_lo - ph) / 1.5, 0.35, 1.0))
    else:
        ph_f = float(np.clip(1.0 - (ph - c.soil_ph_hi) / 1.5, 0.35, 1.0))

    if clay_pct <= c.soil_clay_max:
        drain_f = 1.0
    else:
        excess = (clay_pct - c.soil_clay_max) / 25.0
        drain_f = float(np.clip(1.0 - 0.6 * excess, 0.30, 1.0))

    opt = {"low": (0.20, 0.50), "medium": (0.40, 0.75), "high": (0.60, 1.00)}
    lo, hi = opt.get(c.water_need, (0.40, 0.75))
    if lo <= water_holding <= hi:
        wh_f = 1.0
    elif water_holding < lo:
        wh_f = float(np.clip(1.0 - (lo - water_holding) / 0.35, 0.45, 1.0))
    else:
        wh_f = float(np.clip(1.0 - (water_holding - hi) / 0.35, 0.45, 1.0))

    return float(np.clip(100.0 * ph_f * drain_f * wh_f, 0.0, 100.0))


# Weights for the composite suitability score. Rainfall and drought remain the
# dominant drivers for rain-fed Indian kharif cropping, but temperature,
# vegetation condition and soil now each carry real weight.
FACTOR_WEIGHTS = {
    "rain": 0.35,
    "temp": 0.22,
    "veg": 0.20,
    "soil": 0.23,
}


def factor_breakdown(row: pd.Series, c: CropProfile,
                     soil: dict | None = None) -> dict[str, float]:
    """Per-factor 0-100 scores for one crop in one season."""
    soil = soil or {}
    return {
        "rain": float(rain_score(row["season_rain_mm"], c)),
        "temp": float(temp_score(row.get("mean_temp_c", float("nan")),
                                 row.get("gdd", float("nan")), c)),
        "veg": float(veg_score(row.get("vigour", float("nan")), c)),
        "soil": float(soil_score(soil.get("clay_pct", float("nan")),
                                 soil.get("ph", float("nan")),
                                 soil.get("water_holding", float("nan")), c)),
    }




def score_year(row: pd.Series, c: CropProfile,
               soil: dict | None = None) -> float:
    """Overall 0-100 suitability for one crop in one season.

    Combines the four factor scores by weight, then applies the seasonal
    stress and onset multipliers that capture timing effects.
    """
    fb = factor_breakdown(row, c, soil)
    base = sum(FACTOR_WEIGHTS[k] * fb[k] for k in FACTOR_WEIGHTS)

    mult = stress_score(row["dry_spell_days"], row["heat_days"], c)
    mult *= onset_penalty(row["onset_doy"], c)
    return float(np.clip(base * mult, 0.0, 100.0))


def score_all(indicators: pd.DataFrame, crops: list[CropProfile] = CROPS,
              soil: dict | None = None) -> pd.DataFrame:
    """Per-year, per-crop score matrix (years as rows, crops as columns)."""
    if indicators.empty:
        return pd.DataFrame()
    data = {}
    for c in crops:
        data[c.name] = [score_year(row, c, soil) for _, row in indicators.iterrows()]
    return pd.DataFrame(data, index=indicators.index).round(1)


def factor_matrix(indicators: pd.DataFrame, crops: list[CropProfile] = CROPS,
                  soil: dict | None = None) -> pd.DataFrame:
    """Latest-season factor scores per crop, for the breakdown view.

    Returns rows indexed by crop with columns rain/temp/veg/soil and a weighted
    `composite` column, all on a 0-100 scale.
    """
    if indicators.empty:
        return pd.DataFrame()
    latest = int(indicators.index.max())
    row = indicators.loc[latest]
    rows = []
    for c in crops:
        fb = factor_breakdown(row, c, soil)
        fb["composite"] = sum(FACTOR_WEIGHTS[k] * fb[k] for k in FACTOR_WEIGHTS)
        fb["crop"] = c.name
        fb["season"] = latest
        rows.append(fb)
    out = pd.DataFrame(rows).set_index("crop")
    return out.round(1)


def rank_crops(score_matrix: pd.DataFrame,
               crops: list[CropProfile] = CROPS) -> pd.DataFrame:
    """Aggregate per-year scores into a risk-adjusted ranking."""
    if score_matrix.empty:
        return pd.DataFrame()

    rows = []
    for c in crops:
        s = score_matrix[c.name]
        mean_score = float(s.mean())
        reliability = float((s >= GOOD_YEAR_SCORE).mean())
        recent = s.tail(5)
        recent_mean = float(recent.mean()) if not recent.empty else mean_score
        # Weight recent seasons more heavily: the climate is shifting.
        rank_score = (0.45 * mean_score + 0.35 * (100.0 * reliability)
                      + 0.20 * recent_mean)
        rows.append({
            "crop": c.name,
            "mean_score": round(mean_score, 1),
            "recent_score": round(recent_mean, 1),
            "reliability_pct": round(reliability * 100.0, 0),
            "good_years": int((s >= GOOD_YEAR_SCORE).sum()),
            "years": int(len(s)),
            "rank_score": round(rank_score, 1),
            "worst_year_score": round(float(s.min()), 1),
            "notes": c.notes,
        })

    out = pd.DataFrame(rows).sort_values("rank_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out.reset_index(drop=True)


def current_season_status(indicators: pd.DataFrame,
                          score_matrix: pd.DataFrame,
                          crop: str) -> dict:
    """Compare the latest year for one crop against its own history."""
    if indicators.empty or score_matrix.empty or crop not in score_matrix.columns:
        return {}
    latest_year = int(indicators.index.max())
    row = indicators.loc[latest_year]
    hist = score_matrix[crop].drop(latest_year)
    score_now = float(score_matrix.loc[latest_year, crop])
    mean_hist = float(hist.mean()) if not hist.empty else score_now

    if score_now >= 70:
        flag, colour = "Favourable", "green"
    elif score_now >= 50:
        flag, colour = "Watch", "orange"
    else:
        flag, colour = "At risk", "red"

    # A high absolute score that has fallen sharply still deserves attention:
    # the season is markedly worse than this site is used to. Demote the flag
    # rather than letting a good crop envelope mask a bad year.
    delta = score_now - mean_hist
    if colour == "green" and delta <= -15:
        flag, colour = "Watch", "orange"
    if colour == "orange" and delta <= -25:
        flag, colour = "At risk", "red"

    return {
        "year": latest_year,
        "score": round(score_now, 1),
        "hist_mean": round(mean_hist, 1),
        "delta": round(score_now - mean_hist, 1),
        "flag": flag,
        "colour": colour,
        "rain_mm": round(float(row["season_rain_mm"]), 0),
        "onset": float(row["onset_doy"]),
        "spi": float(row["spi"]),
        "dry_spell": int(row["dry_spell_days"]),
        "heat_days": int(row["heat_days"]),
    }

