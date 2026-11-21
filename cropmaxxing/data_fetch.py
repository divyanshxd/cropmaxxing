"""Data acquisition for CropTime.

Primary source: NASA POWER API (Prediction Of Worldwide Energy Resources).
POWER is free, public, key-less, and derived from satellite + reanalysis
products. It gives us daily/monthly rainfall and temperature for any
lat/lon on Earth back to 1981 - a genuine satellite-derived record.

We request:
  PRECTOTCORR  precipitation, bias corrected (mm/day)
  T2M          mean air temperature at 2 m (deg C)
  T2M_MAX      max air temperature at 2 m (deg C)
  RH2M         relative humidity at 2 m (%)

Docs: https://power.larc.nasa.gov/docs/services/api/
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass

import pandas as pd
import requests

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
TIMEOUT = 45


@dataclass
class SiteInfo:
    name: str
    lat: float
    lon: float


def _cache_path(lat: float, lon: float, start: str, end: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = f"power_{lat:.4f}_{lon:.4f}_{start}_{end}.csv"
    return os.path.join(CACHE_DIR, key)


def fetch_daily(lat: float, lon: float, start: str, end: str,
                use_cache: bool = True) -> pd.DataFrame:
    """Fetch daily climate series for one point.

    Returns a DataFrame indexed by date with columns:
      rain_mm, tmean_c, tmax_c, rh_pct

    Results are cached to disk so repeated runs (and offline demos) work.
    """
    path = _cache_path(lat, lon, start, end)
    if use_cache and os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
        if not df.empty:
            return df

    params = {
        "parameters": "PRECTOTCORR,T2M,T2M_MAX,RH2M",
        "community": "AG",
        "longitude": f"{lon:.4f}",
        "latitude": f"{lat:.4f}",
        "start": start.replace("-", ""),
        "end": end.replace("-", ""),
        "format": "JSON",
    }
    resp = requests.get(POWER_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    print(payload)

    block = payload["properties"]["parameter"]

    def series(name: str) -> dict[str, float]:
        raw = block.get(name, {})
        out = {}
        for k, v in raw.items():
            # POWER uses YYYYMMDD keys; skip the annual "YYYYMM" fillers.
            if len(k) != 8:
                continue
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = float("nan")
        return out

    rain = series("PRECTOTCORR")
    tmean = series("T2M")
    tmax = series("T2M_MAX")
    rh = series("RH2M")

    keys = sorted(set(rain) | set(tmean))
    if not keys:
        raise ValueError("NASA POWER returned no usable records for this point/range.")

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(keys, format="%Y%m%d"),
            "rain_mm": [rain.get(k, float("nan")) for k in keys],
            "tmean_c": [tmean.get(k, float("nan")) for k in keys],
            "tmax_c": [tmax.get(k, float("nan")) for k in keys],
            "rh_pct": [rh.get(k, float("nan")) for k in keys],
        }
    ).set_index("date").sort_index()

    # POWER uses large negative fills (-999) for missing; normalise to NaN.
    df = df.mask(df < -900)
    # Interpolate small gaps so indicator maths stays stable.
    df = df.interpolate(limit_direction="both")

    df.to_csv(path)
    return df


def default_range(years: int = 20,
                  include_current_year: bool = True) -> tuple[str, str]:
    """A sensible window for the site's climate record.

    By default the window runs up to *today*, so the current year is included
    as a partial, year-to-date record. This matters: the kharif monsoon window
    (Jun-Sep) is already complete from October onward, so the current season's
    indicators are valid even though the calendar year is not.

    Set include_current_year=False to reproduce the older behaviour of ending
    at the last fully closed calendar year.
    """
    today = dt.date.today()
    if include_current_year:
        end = today
    else:
        end = dt.date(today.year - 1, 12, 31)
    start = dt.date(end.year - years + 1, 1, 1)
    return start.isoformat(), end.isoformat()


def data_freshness(df: pd.DataFrame) -> dict:
    """Describe how current the loaded record is.

    Returns the latest date POWER returned, how many days of the current
    calendar year are present, and whether the monsoon window is complete.
    """
    if df is None or df.empty:
        return {"latest": None, "current_year_days": 0,
                "monsoon_complete": False, "current_year": None}

    latest = df.index.max()
    cy = int(latest.year)
    cy_days = int((df.index.year == cy).sum())

    # Monsoon window complete means every day from 1 Jun to 30 Sep of the
    # latest year is present in the record.
    want = pd.date_range(f"{cy}-06-01", f"{cy}-09-30", freq="D")
    have = df.loc[f"{cy}-06-01":f"{cy}-09-30"].index
    monsoon_complete = len(want) > 0 and len(have) >= len(want)

    return {
        "latest": latest,
        "latest_str": latest.strftime("%d %b %Y"),
        "current_year": cy,
        "current_year_days": cy_days,
        "monsoon_complete": bool(monsoon_complete),
    }


def save_meta(site: SiteInfo, start: str, end: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, "last_site.json"), "w", encoding="utf-8") as f:
        json.dump({"name": site.name, "lat": site.lat, "lon": site.lon,
                   "start": start, "end": end}, f, indent=2)


def load_meta() -> dict | None:
    p = os.path.join(CACHE_DIR, "last_site.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
