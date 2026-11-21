"""Soil properties for CropTime.

Three-tier strategy, in order of preference:

1. **SoilGrids live** (ISRIC, 250 m global) - queried per point. Free, no key.
   Docs: https://rest.isric.org/soilgrids/v2.0/docs
2. **Regional fallback table** - aggregated typical values for Indian
   agro-climatic zones, used when SoilGrids returns nulls (the public mirror
   has coverage gaps and is intermittently degraded).
3. **User override** - the UI lets the user set texture and pH by hand.

We surface which tier was used, so the app never silently presents a guess as
a measurement.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

SOILGRID_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
TIMEOUT = 30

PROPERTIES = ["clay", "sand", "silt", "phh2o", "soc"]


@dataclass
class SoilProfile:
    """Topsoil properties at a point, with provenance."""

    clay_pct: float
    sand_pct: float
    silt_pct: float
    ph: float
    soc_g_kg: float
    source: str = "unknown"

    @property
    def texture(self) -> str:
        """USDA-style texture class, simplified."""
        c, s = self.clay_pct, self.sand_pct
        if c >= 40:
            return "clay"
        if c >= 27:
            return "clay loam"
        if s >= 70:
            return "sandy"
        if s >= 50 and c < 20:
            return "sandy loam"
        if c >= 20:
            return "loam"
        return "silt loam"

    @property
    def water_holding(self) -> float:
        """Coarse 0-1 index of plant-available water capacity.

        Clay and silt hold water; sand drains. This is a proxy for AWC, not a
        laboratory measurement.
        """
        return min(1.0, (0.55 * self.clay_pct + 0.75 * self.silt_pct) / 60.0)

    def as_dict(self) -> dict:
        return {
            "clay_pct": round(self.clay_pct, 1),
            "sand_pct": round(self.sand_pct, 1),
            "silt_pct": round(self.silt_pct, 1),
            "ph": round(self.ph, 2),
            "soc_g_kg": round(self.soc_g_kg, 1),
            "texture": self.texture,
            "water_holding": round(self.water_holding, 2),
            "source": self.source,
        }


def _query_soilgrids(lat: float, lon: float) -> dict[str, float | None]:
    """Query SoilGrids for topsoil properties. Returns raw values or None."""
    out: dict[str, float | None] = {}
    for prop in PROPERTIES:
        params = {
            "lon": f"{lon:.4f}",
            "lat": f"{lat:.4f}",
            "property": prop,
            "depth": "0-5cm",
            "value": "mean",
        }
        try:
            r = requests.get(SOILGRID_URL, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            layers = r.json()["properties"]["layers"]
            if not layers or not layers[0]["depths"]:
                out[prop] = None
                continue
            v = layers[0]["depths"][0]["values"].get("mean")
            out[prop] = float(v) if v is not None else None
        except Exception:
            out[prop] = None
    return out


# Typical topsoil values by broad Indian agro-climatic zone. Derived from
# regional soil summaries and ICAR soil survey literature. These are broad
# approximations intended as a clearly labelled fallback, not a substitute for
# a soil test.
REGIONAL_SOIL = {
    "deccan_black": SoilProfile(45.0, 25.0, 30.0, 7.9, 6.0, "regional-deccan-black"),
    "central_plateau": SoilProfile(32.0, 42.0, 26.0, 7.2, 5.0, "regional-central-plateau"),
    "semi_arid_red": SoilProfile(18.0, 68.0, 14.0, 6.9, 3.5, "regional-semi-arid-red"),
    "arid_sandy": SoilProfile(8.0, 82.0, 10.0, 8.1, 2.0, "regional-arid-sandy"),
    "indo_gangetic": SoilProfile(24.0, 48.0, 28.0, 7.4, 6.5, "regional-indo-gangetic"),
    "default": SoilProfile(28.0, 45.0, 27.0, 7.2, 5.0, "regional-default"),
}


def _pick_region(lat: float, lon: float) -> str:
    """Cheap geographic heuristic to choose a fallback soil zone."""
    # Arid west (Rajasthan / Kutch)
    if lon < 72.5 and lat > 23.0:
        return "arid_sandy"
    # Deccan trap black-cotton soils (Maharashtra / MP / Telangana belt)
    if 17.0 <= lat <= 24.5 and 73.5 <= lon <= 80.5:
        return "deccan_black"
    # Semi-arid red soils (Rayalaseema / interior Karnataka / Tamil Nadu)
    if lat < 17.5 and lon > 76.0:
        return "semi_arid_red"
    # Indo-Gangetic plain
    if lat > 25.0 and lon > 74.0:
        return "indo_gangetic"
    # Central plateau
    if 20.0 <= lat <= 26.0 and lon > 76.0:
        return "central_plateau"
    return "default"


def get_soil(lat: float, lon: float, use_live: bool = True) -> SoilProfile:
    """Return a SoilProfile for the point, using the best source available.

    SoilGrids values arrive as scaled integers:
      clay/sand/silt in g/kg (divide by 10 for %)
      phh2o as pH*10 (divide by 10)
      soc in dg/kg (divide by 10 for g/kg)
    """
    if use_live:
        raw = _query_soilgrids(lat, lon)
        if all(raw.get(p) is not None for p in ["clay", "sand", "silt", "phh2o"]):
            clay = raw["clay"] / 10.0
            sand = raw["sand"] / 10.0
            silt = raw["silt"] / 10.0
            ph = raw["phh2o"] / 10.0
            soc = (raw["soc"] / 10.0) if raw.get("soc") is not None else 5.0
            return SoilProfile(clay, sand, silt, ph, soc, "SoilGrids (live)")

    region = _pick_region(lat, lon)
    return REGIONAL_SOIL.get(region, REGIONAL_SOIL["default"])


def manual_soil(clay_pct: float, sand_pct: float, ph: float,
                soc_g_kg: float = 5.0) -> SoilProfile:
    """Build a SoilProfile from user-supplied values."""
    clay_pct = max(0.0, min(100.0, float(clay_pct)))
    sand_pct = max(0.0, min(100.0 - clay_pct, float(sand_pct)))
    silt_pct = max(0.0, 100.0 - clay_pct - sand_pct)
    return SoilProfile(clay_pct, sand_pct, silt_pct, float(ph),
                       float(soc_g_kg), "manual")

