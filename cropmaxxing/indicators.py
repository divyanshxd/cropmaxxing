"""Climate indicators computed from the daily POWER series.

Each function is deliberately simple, explainable and testable - a hackathon
judge should be able to read the formula and trust it.

Indicators produced per season year:
  season_rain_mm   total rainfall in the monsoon window (Jun-Sep)
  onset_doy        day-of-year when the monsoon effectively started
  dry_spell_days   longest run of dry days inside the monsoon window
  heat_days        days above the crop heat-stress threshold
  spi              Standardised Precipitation Index (1 = normal)
  rain_anomaly_pct season rainfall vs the site's long-term mean
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Monsoon window used for kharif crops in central India.
SEASON_START_MONTH = 6
SEASON_END_MONTH = 9

# A full Jun-Sep window is 30+31+31+30 = 122 days. A season with all of them
# present is "complete"; anything less is partial and is flagged as such.
EXPECTED_SEASON_DAYS = 122

# Onset rule (simplified IMD-style): first day of a wet spell where
# cumulative rain over the next 7 days reaches this many mm.
ONSET_WINDOW_DAYS = 7
ONSET_THRESHOLD_MM = 30.0

# A day counts as "dry" below this rainfall.
DRY_DAY_MM = 2.5


def season_slice(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Return the monsoon-window rows for a given year."""
    mask = (
        (df.index.year == year)
        & (df.index.month >= SEASON_START_MONTH)
        & (df.index.month <= SEASON_END_MONTH)
    )
    return df.loc[mask]


def season_rain_mm(df: pd.DataFrame, year: int) -> float:
    s = season_slice(df, year)["rain_mm"]
    return float(s.sum()) if not s.empty else float("nan")


def onset_doy(df: pd.DataFrame, year: int) -> float:
    """Day-of-year of monsoon onset, or NaN if it never really arrives."""
    s = season_slice(df, year)
    if s.empty:
        return float("nan")
    roll = s["rain_mm"].rolling(ONSET_WINDOW_DAYS, min_periods=ONSET_WINDOW_DAYS).sum()
    hit = roll[roll >= ONSET_THRESHOLD_MM]
    if hit.empty:
        return float("nan")
    return float(hit.index[0].dayofyear)


def longest_dry_spell(df: pd.DataFrame, year: int) -> int:
    """Longest consecutive run of dry days within the monsoon window."""
    s = season_slice(df, year)
    if s.empty:
        return 0
    dry = (s["rain_mm"] < DRY_DAY_MM).astype(int).to_numpy()
    best = cur = 0
    for v in dry:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return int(best)


def heat_stress_days(df: pd.DataFrame, year: int, threshold_c: float = 35.0) -> int:
    """Days inside the season where max temperature exceeds the threshold."""
    s = season_slice(df, year)
    if s.empty:
        return 0
    return int((s["tmax_c"] > threshold_c).sum())


def _spi_from_series(season_totals: pd.Series, value: float) -> float:
    """Standardised index: (x - mean) / std over the historical record.

    This is the simpler cousin of the gamma-fitted SPI. We use the normal
    approximation because it is transparent and robust on short records.
    We clamp to [-3, 3] so a single odd year cannot dominate the ranking.
    """
    clean = season_totals.dropna()
    if len(clean) < 3:
        return 0.0
    mu, sd = float(clean.mean()), float(clean.std(ddof=1))
    if sd == 0:
        return 0.0
    z = (value - mu) / sd
    return float(np.clip(z, -3.0, 3.0))


# ---------------------------------------------------------------------------
# Temperature indicators
# ---------------------------------------------------------------------------

def mean_season_temp(df: pd.DataFrame, year: int) -> float:
    """Mean air temperature across the monsoon season (deg C)."""
    s = season_slice(df, year)["tmean_c"]
    return float(s.mean()) if not s.empty else float("nan")


def growing_degree_days(df: pd.DataFrame, year: int,
                        base_c: float = 10.0) -> float:
    """Accumulated heat above a base temperature across the season.

    GDD is the standard agronomic heat-accumulation measure: the total of
    (mean_temp - base) for every day the mean exceeds base. It drives crop
    development rate, so two seasons with identical rainfall but different GDD
    suit different crops.
    """
    s = season_slice(df, year)["tmean_c"]
    if s.empty:
        return 0.0
    excess = (s - base_c).clip(lower=0.0)
    return float(excess.sum())


def cold_days(df: pd.DataFrame, year: int, threshold_c: float = 12.0) -> int:
    """Days where the season mean temperature falls below a cold threshold."""
    s = season_slice(df, year)["tmean_c"]
    if s.empty:
        return 0
    return int((s < threshold_c).sum())


def temp_anomaly_c(df: pd.DataFrame, year: int,
                   baseline: pd.Series | None = None) -> float:
    """Season mean temperature departure from the site's own mean."""
    cur = mean_season_temp(df, year)
    if np.isnan(cur):
        return float("nan")
    if baseline is None or baseline.empty:
        return 0.0
    return float(cur - baseline.mean())


# ---------------------------------------------------------------------------
# Vegetation indicators
# ---------------------------------------------------------------------------

def vegetation_vigour(df: pd.DataFrame, year: int) -> float:
    """A 0-1 vegetation-vigour index for the season, from climate signals.

    True vegetation condition comes from satellite NDVI (Sentinel-2 / MODIS).
    Absent an Earth Engine connection we compute a physically grounded
    **proxy** from the drivers of canopy development, all of which POWER
    supplies:

        moisture factor : season rainfall adequacy
        heat factor     : how close season mean temp is to the ~25 C optimum
        stress factor   : dry spell and heat day penalties

    The product is expressed 0-1 and is clearly labelled a proxy in the UI.
    When NDVI is supplied by the caller it overrides this entirely.
    """
    s = season_slice(df, year)
    if s.empty:
        return float("nan")

    rain = float(s["rain_mm"].sum())
    tmean = float(s["tmean_c"].mean())

    # Moisture: 1.0 at 800 mm (comfortable for most kharif crops), tapering
    # toward 0.35 at zero and falling again above 1400 mm (waterlogging).
    if rain <= 800.0:
        moisture = 0.35 + 0.65 * min(1.0, rain / 800.0)
    else:
        moisture = max(0.55, 1.0 - (rain - 800.0) / 1200.0)

    # Heat: bell curve around a 25 C growing optimum, width 8 C.
    heat = float(np.exp(-((tmean - 25.0) ** 2) / (2 * 8.0 ** 2)))

    # Stress: longest dry spell and heat days inside the season.
    dry = (s["rain_mm"] < DRY_DAY_MM).astype(int).to_numpy()
    best = cur = 0
    for v in dry:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    dry_factor = max(0.3, 1.0 - best / 45.0)
    heat_days = int((s["tmax_c"] > 35.0).sum())
    heat_factor = max(0.3, 1.0 - heat_days / 90.0)

    vigour = moisture * heat * dry_factor * heat_factor
    return float(np.clip(vigour, 0.0, 1.0))


def vigour_label(v: float) -> str:
    """Human label for a 0-1 vigour index."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "unknown"
    if v >= 0.72:
        return "strong"
    if v >= 0.55:
        return "moderate"
    if v >= 0.38:
        return "weak"
    return "poor"



def build_indicator_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per season year with every indicator computed.

    Adds two provenance columns so a partial year can never be silently
    mistaken for a complete one:

      season_days     days actually present inside the Jun-Sep window
      season_complete True only when all ~122 monsoon days are present

    A year with at least 100 days overall is still evaluated, because the
    monsoon window is what drives these indicators and it closes in October.
    """
    if df.empty:
        return pd.DataFrame()

    years = sorted({y for y in df.index.year
                    if (df.index.year == y).sum() >= 100})
    rows = []
    for y in years:
        s = season_slice(df, y)
        rows.append({
            "year": y,
            "season_rain_mm": season_rain_mm(df, y),
            "onset_doy": onset_doy(df, y),
            "dry_spell_days": longest_dry_spell(df, y),
            "heat_days": heat_stress_days(df, y),
            "season_days": int(len(s)),
            "season_complete": bool(len(s) >= EXPECTED_SEASON_DAYS),
            # --- temperature ---
            "mean_temp_c": mean_season_temp(df, y),
            "gdd": growing_degree_days(df, y),
            "cold_days": cold_days(df, y),
            # --- vegetation (proxy index, 0-1) ---
            "vigour": vegetation_vigour(df, y),
        })

    t = pd.DataFrame(rows).set_index("year").sort_index()
    if t.empty:
        return t

    totals = t["season_rain_mm"]
    mean_total = float(totals.dropna().mean()) if totals.notna().any() else float("nan")

    t["spi"] = [
        _spi_from_series(totals, v) if pd.notna(v) else 0.0 for v in totals
    ]
    t["rain_anomaly_pct"] = (
        (totals - mean_total) / mean_total * 100 if mean_total else 0.0
    )
    # Temperature departure from the site's own mean season temperature.
    temp_series = t["mean_temp_c"]
    temp_mean = float(temp_series.dropna().mean()) if temp_series.notna().any() else 0.0
    t["temp_anomaly_c"] = (temp_series - temp_mean).round(2)
    return t.round(2)


def onset_label(doy: float) -> str:
    """Human-readable date for an onset day-of-year."""
    if doy is None or (isinstance(doy, float) and np.isnan(doy)):
        return "no clear onset"
    d = pd.Timestamp("2001-01-01") + pd.Timedelta(days=int(doy) - 1)
    return d.strftime("%d %b")
