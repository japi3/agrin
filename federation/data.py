"""
Per-country training data for the federated experiment.

The honest bit first
--------------------
There is no shared BRICS dataset of farm records with measured irrigation
requirements. There cannot be -- that is precisely the problem this
architecture exists to solve. So the training data here is **generated, not
collected**, and nothing in this demo should be read as a result on real
farms.

What makes it a meaningful experiment anyway is that the generation is not
arbitrary. Each country's samples are built from:

  * that country's **real** climate normals (20 years of ERA5 via Open-Meteo)
    at real agricultural locations,
  * that country's **real** soil properties (ISRIC SoilGrids at those points),
  * the crops actually grown there, and
  * labels computed by running the **validated FAO-56 water balance** from
    `packages/agronomy` -- the same code verified against the published
    worked examples in the paper.

So the label is a real physical model's answer, and the feature
distributions differ between countries for genuinely agronomic reasons: a
Punjab clay loam under 550 mm of monsoon differs from a Mato Grosso Oxisol
under 1500 mm, and both differ from a Krasnodar chernozem. That regional
divergence is the whole point of the experiment, and it is not something we
invented -- it comes from the real soil and climate data underneath.

What the experiment then measures is whether a model trained on one
country's fields generalises to another's, and whether federated averaging
closes that gap without any field record crossing a border.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
for pkg in ("packages/agronomy", "packages/geo"):
    p = str(_ROOT / pkg)
    if p not in sys.path:
        sys.path.insert(0, p)

from agronomy.crops import CROPS, soil_from_texture  # noqa: E402
from agronomy.waterbalance import DailyWeather, simulate  # noqa: E402
from geo.soilgrids import fetch_soil_profile_resilient  # noqa: E402
from geo.weather import fetch_climate_normals  # noqa: E402


@dataclass
class CountryNode:
    """One federation participant."""
    code: str
    name: str
    # Real agricultural locations, chosen as production-region centroids.
    sites: list[tuple[float, float]]
    crops: list[str]
    # Sowing month for the dominant season at these latitudes.
    sowing_month: int


# The five BRICS founding members. Sites are real production regions, picked
# to be genuinely representative rather than convenient: the Indo-Gangetic
# plain and the Deccan for India, the cerrado and the south for Brazil, the
# black-earth belt for Russia, the North China Plain, and the Highveld.
NODES: list[CountryNode] = [
    CountryNode(
        code="IN", name="India",
        sites=[(30.70, 75.20), (26.85, 80.95), (20.00, 77.00), (17.40, 78.50)],
        crops=["rice_paddy", "wheat_spring", "cotton", "pearl_millet"],
        sowing_month=6,
    ),
    CountryNode(
        code="BR", name="Brazil",
        sites=[(-12.36, -55.71), (-18.20, -47.90), (-23.50, -51.50)],
        crops=["soybean", "maize_grain", "cotton", "sugarcane"],
        sowing_month=10,
    ),
    CountryNode(
        code="RU", name="Russia",
        sites=[(45.30, 39.20), (51.70, 39.20), (54.20, 45.20)],
        crops=["wheat_spring", "barley", "sunflower"],
        sowing_month=4,
    ),
    CountryNode(
        code="CN", name="China",
        sites=[(34.75, 113.95), (36.60, 117.00), (30.60, 114.30)],
        crops=["wheat_winter", "maize_grain", "rice_paddy", "soybean"],
        sowing_month=6,
    ),
    CountryNode(
        code="ZA", name="South Africa",
        sites=[(-26.70, 27.10), (-28.80, 26.50), (-25.60, 28.30)],
        crops=["maize_grain", "sunflower", "wheat_winter"],
        sowing_month=11,
    ),
]

# Feature order is fixed and shared across all nodes. Federated averaging
# requires every participant to agree on the feature space; a node that
# ordered its columns differently would poison the global model silently.
FEATURE_NAMES = [
    "clay_percent",
    "sand_percent",
    "organic_carbon_g_per_kg",
    "available_water_mm_per_m",
    "season_rain_mm",
    "season_et0_mm",
    "mean_temp_c",
    "season_length_days",
    "crop_kc_mid",
    "crop_root_depth_m",
    "crop_depletion_fraction",
]
TARGET_NAME = "seasonal_net_irrigation_mm"


def _monthly_to_daily(
    normals: dict, start: date, days: int, rng: np.random.Generator
) -> list[DailyWeather]:
    """Expand monthly climate normals into a plausible daily series.

    Monthly totals are disaggregated into wet and dry days rather than spread
    evenly, because an evenly-smeared month produces a soil that is never
    stressed and never saturated -- and the water balance would then report an
    irrigation requirement that no real season produces. Rain days per month
    are drawn from the monthly total, and daily rainfall is exponentially
    distributed, which is the standard stochastic-weather-generator treatment.
    """
    out: list[DailyWeather] = []
    for i in range(days):
        day = start + timedelta(days=i)
        month = normals.get(day.month) or {}
        month_rain = month.get("total_rain_mm", 0.0)
        month_et0 = month.get("total_et0_mm", 120.0)
        t_mean = month.get("mean_temp_c", 25.0)

        # More rain implies more rain days, saturating around 20 per month.
        rain_days = min(20.0, max(1.0, month_rain / 12.0))
        p_wet = rain_days / 30.4
        if rng.random() < p_wet:
            rain = float(rng.exponential(month_rain / max(rain_days, 1.0)))
        else:
            rain = 0.0

        et0 = max(0.4, month_et0 / 30.4 * float(rng.normal(1.0, 0.12)))
        # Diurnal range widens in dry months; this feeds nothing downstream
        # but keeps the record self-consistent.
        swing = 6.0 + (0.0 if month_rain > 100 else 4.0)
        out.append(
            DailyWeather(
                day=day, et0_mm=et0, rain_mm=rain,
                t_max=t_mean + swing, t_min=t_mean - swing,
            )
        )
    return out


async def build_country_dataset(
    node: CountryNode, samples_per_site: int = 60, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Build one country's local training set. Never leaves that country.

    Returns (X, y) with X shaped (n, len(FEATURE_NAMES)).
    """
    rng = np.random.default_rng(seed + hash(node.code) % 10_000)
    rows: list[list[float]] = []
    targets: list[float] = []

    for lat, lon in node.sites:
        try:
            profile = await fetch_soil_profile_resilient(lat, lon)
            normals = await fetch_climate_normals(lat, lon, years=20)
        except Exception:
            continue
        if not profile.has_data or profile.texture_fractions is None:
            continue

        sand, silt, clay = profile.texture_fractions
        soc = profile.depth_weighted("soc") or 8.0

        for _ in range(samples_per_site):
            crop_key = node.crops[rng.integers(len(node.crops))]
            crop = CROPS[crop_key]

            # Field-to-field variation within the district: real soils vary
            # over hundreds of metres, and a model trained on one texture
            # would not transfer even within a country.
            j_sand = float(np.clip(sand + rng.normal(0, 6), 2, 95))
            j_clay = float(np.clip(clay + rng.normal(0, 5), 2, 70))
            j_silt = max(1.0, 100.0 - j_sand - j_clay)
            j_soc = float(max(1.0, soc + rng.normal(0, 1.5)))

            soil = soil_from_texture(j_sand, j_silt, j_clay)

            year = 2025
            sow_month = node.sowing_month
            sow_day = int(rng.integers(1, 26))
            sow = date(year, sow_month, sow_day)
            weather = _monthly_to_daily(normals, sow, crop.total_days + 2, rng)

            # The label: what the validated FAO-56 balance says this field
            # actually needs. Not a guess, and not a formula the learner could
            # trivially invert -- it comes from a daily simulation.
            result = simulate(
                crop, soil, sow, weather,
                auto_irrigate=True, irrigation_efficiency=0.75,
            )
            net_irrigation = sum(d.irrigation_mm for d in result.days)

            season_rain = sum(w.rain_mm for w in weather)
            season_et0 = sum(w.et0_mm for w in weather)
            mean_temp = float(np.mean([(w.t_max + w.t_min) / 2 for w in weather]))

            rows.append([
                j_clay, j_sand, j_soc,
                soil.available_water_fraction * 1000.0,
                season_rain, season_et0, mean_temp,
                float(crop.total_days), crop.kc_mid,
                crop.root_depth_m, crop.depletion_fraction,
            ])
            targets.append(float(net_irrigation))

    if not rows:
        return np.zeros((0, len(FEATURE_NAMES))), np.zeros(0)
    return np.asarray(rows, dtype=np.float64), np.asarray(targets, dtype=np.float64)


async def build_all(
    samples_per_site: int = 60, seed: int = 0
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Build every country's dataset. Sequential, to stay polite to ISRIC."""
    datasets: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for node in NODES:
        X, y = await build_country_dataset(node, samples_per_site, seed)
        datasets[node.code] = (X, y)
        print(f"  {node.code} {node.name:14s} {X.shape[0]:4d} samples", flush=True)
    return datasets
