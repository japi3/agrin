"""
The tool surface exposed to the language model.

Design principle: **the model never computes agronomy.** It routes, it
translates, it explains, and it decides which tool to call -- but every
number a farmer acts on comes from a validated model in `packages/agronomy`
running on real data from `packages/geo`. An LLM asked to estimate an
irrigation depth will produce a fluent, plausible, unfalsifiable number. That
is the failure mode this architecture exists to prevent.

Each tool therefore returns a structured result plus an `evidence` block
recording where every input came from. The chat layer renders the result; the
Evidence Ledger renders the provenance; and the model is instructed that it
may not state a quantity that does not appear in a tool result.

Tools also return an explicit `confidence` and, where warranted, an
`abstain_reason`. A tool that cannot answer well says so, and the model is
required to pass that on rather than paper over it.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# The agronomy and geo packages are separate installables; in development
# they are resolved from the repo root.
_ROOT = Path(__file__).resolve().parents[3]
for pkg in ("packages/agronomy", "packages/geo"):
    p = str(_ROOT / pkg)
    if p not in sys.path:
        sys.path.insert(0, p)

from agronomy.carbon import (  # noqa: E402
    MonthlyInput, manure_carbon_from_fresh_weight, project, soc_percent_to_t_ha,
)
from agronomy.crops import (  # noqa: E402
    CROPS, soil_from_texture, total_available_water,
)
from agronomy.canopy import (  # noqa: E402
    assess_canopy, calibrate_endpoints, looks_like_annual_cropland,
    reconcile_sowing_date, representative_ndvi,
)
from agronomy.fao56 import et0_from_daily_weather  # noqa: E402
from agronomy.schemes import SCHEMES, schemes_for_situation  # noqa: E402
from agronomy.waterbalance import (  # noqa: E402
    DailyWeather, next_irrigation_advice, simulate,
)
from geo.mandi import geocode_place, prices_for_crop  # noqa: E402
from geo.satellite import fetch_ndvi_series  # noqa: E402
from geo.soilgrids import fetch_soil_profile_resilient  # noqa: E402
from geo.weather import (  # noqa: E402
    fetch_climate_normals, fetch_forecast,
)


class ToolError(RuntimeError):
    """Raised when a tool cannot produce a trustworthy result."""


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

async def _soil_and_weather(latitude: float, longitude: float):
    """Fetch soil and weather concurrently -- they are independent."""
    soil_task = fetch_soil_profile_resilient(latitude, longitude)
    weather_task = fetch_forecast(latitude, longitude, days_ahead=14, past_days=60)
    return await asyncio.gather(soil_task, weather_task)


def _to_daily_weather(series, elevation_m: float, latitude: float) -> list[DailyWeather]:
    """Convert an Open-Meteo series into water-balance driving data.

    ET0 is recomputed with our own FAO-56 code rather than taken from
    Open-Meteo's `et0_fao_evapotranspiration` field. The two agree to about
    0.23 mm/day (see scripts/validate_et0_live.py), but computing it
    ourselves means the Evidence Ledger can show the full Penman-Monteith
    chain -- net radiation, vapour pressure deficit, wind -- rather than an
    opaque number from a third party.
    """
    out: list[DailyWeather] = []
    for d in series.days:
        if not d.is_usable_for_et0:
            continue
        try:
            r = et0_from_daily_weather(
                t_max=d.t_max, t_min=d.t_min, latitude_deg=latitude,
                elevation_m=elevation_m, day_of_year=d.day_of_year,
                wind_ms=d.wind_mean_ms if d.wind_mean_ms is not None else 2.0,
                wind_height_m=10.0,
                dewpoint_c=d.dewpoint_mean,
                rh_max=d.rh_max, rh_min=d.rh_min,
                solar_radiation_mj=d.solar_radiation_mj,
            )
            et0 = r.et0_mm_day
        except ValueError:
            # Fall back to Open-Meteo's own figure if humidity is missing.
            if d.et0_openmeteo_mm is None:
                continue
            et0 = d.et0_openmeteo_mm
        out.append(
            DailyWeather(
                day=d.day, et0_mm=et0,
                rain_mm=d.precipitation_mm or 0.0,
                t_max=d.t_max, t_min=d.t_min,
            )
        )
    return out


# --------------------------------------------------------------------------
# Tool: soil profile
# --------------------------------------------------------------------------

async def get_soil_profile(latitude: float, longitude: float) -> dict[str, Any]:
    """Look up soil properties and derived water-holding capacity for a field."""
    profile = await fetch_soil_profile_resilient(latitude, longitude)

    if not profile.has_data:
        return {
            "ok": False,
            "abstain_reason": (
                "No soil survey data is mapped within 20 km of this point. "
                "This usually means the location is open water, permanent ice, "
                "or dense urban land. Please check the pin."
            ),
            "evidence": profile.evidence(),
        }

    tex = profile.texture_fractions
    if tex is None:
        return {
            "ok": False,
            "abstain_reason": "Soil texture could not be resolved at this point.",
            "evidence": profile.evidence(),
        }

    sand, silt, clay = tex
    soil = soil_from_texture(sand, silt, clay)
    ph = profile.depth_weighted("phh2o")
    soc_g_kg = profile.depth_weighted("soc")
    bulk_density = profile.depth_weighted("bdod")
    nitrogen = profile.depth_weighted("nitrogen")
    cec = profile.depth_weighted("cec")

    soc_stock = None
    if soc_g_kg is not None and bulk_density is not None:
        soc_stock = soc_percent_to_t_ha(soc_g_kg / 10.0, bulk_density, 30.0)

    # pH interpretation drives real, expensive interventions (liming,
    # gypsum), so the bands are the standard USDA/ICAR agronomic classes
    # rather than an ad-hoc split.
    ph_class = None
    if ph is not None:
        if ph < 5.5:
            ph_class = "strongly_acidic"
        elif ph < 6.5:
            ph_class = "slightly_acidic"
        elif ph <= 7.5:
            ph_class = "neutral"
        elif ph <= 8.5:
            ph_class = "alkaline"
        else:
            ph_class = "strongly_alkaline"

    return {
        "ok": True,
        "texture": {
            "sand_percent": round(sand, 1),
            "silt_percent": round(silt, 1),
            "clay_percent": round(clay, 1),
            "usda_class": soil.texture_class,
        },
        "water_holding": {
            "field_capacity_vol": soil.field_capacity,
            "wilting_point_vol": soil.wilting_point,
            "available_water_mm_per_m": round(
                total_available_water(soil, 1.0), 1
            ),
        },
        "chemistry": {
            "ph": round(ph, 1) if ph is not None else None,
            "ph_class": ph_class,
            "organic_carbon_g_per_kg": round(soc_g_kg, 1) if soc_g_kg else None,
            "organic_carbon_stock_t_per_ha_0_30cm": (
                round(soc_stock, 1) if soc_stock else None
            ),
            "total_nitrogen_g_per_kg": round(nitrogen, 2) if nitrogen else None,
            "cec_cmol_per_kg": round(cec, 1) if cec else None,
            "bulk_density_g_per_cm3": (
                round(bulk_density, 2) if bulk_density else None
            ),
        },
        "confidence": (
            "low" if profile.evidence()["low_confidence_properties"] else "good"
        ),
        "evidence": profile.evidence(),
    }


# --------------------------------------------------------------------------
# Tool: weather
# --------------------------------------------------------------------------

async def get_weather(
    latitude: float, longitude: float, days_ahead: int = 14
) -> dict[str, Any]:
    """Fetch recent and forecast weather, with reference ET computed locally."""
    series = await fetch_forecast(
        latitude, longitude, days_ahead=days_ahead, past_days=14
    )
    today = date.today()

    forecast_days = []
    for d in series.days:
        if d.day < today:
            continue
        et0 = None
        if d.is_usable_for_et0 and d.wind_mean_ms is not None:
            try:
                et0 = et0_from_daily_weather(
                    t_max=d.t_max, t_min=d.t_min, latitude_deg=series.latitude,
                    elevation_m=series.elevation_m, day_of_year=d.day_of_year,
                    wind_ms=d.wind_mean_ms, wind_height_m=10.0,
                    dewpoint_c=d.dewpoint_mean, rh_max=d.rh_max, rh_min=d.rh_min,
                    solar_radiation_mj=d.solar_radiation_mj,
                ).et0_mm_day
            except ValueError:
                et0 = d.et0_openmeteo_mm
        forecast_days.append({
            "date": d.day.isoformat(),
            "t_max_c": d.t_max,
            "t_min_c": d.t_min,
            "rain_mm": d.precipitation_mm,
            "reference_et_mm": round(et0, 2) if et0 is not None else None,
        })

    past = [d for d in series.days if d.day < today]
    rain_14d = sum(d.precipitation_mm or 0.0 for d in past)
    rain_next_7 = sum(
        (f["rain_mm"] or 0.0) for f in forecast_days[:7]
    )

    return {
        "ok": True,
        "elevation_m": series.elevation_m,
        "timezone": series.timezone,
        "rain_last_14_days_mm": round(rain_14d, 1),
        "rain_next_7_days_mm": round(rain_next_7, 1),
        "forecast": forecast_days,
        "evidence": series.evidence(),
    }


# --------------------------------------------------------------------------
# Tool: irrigation advice
# --------------------------------------------------------------------------

async def get_irrigation_advice(
    latitude: float,
    longitude: float,
    crop: str,
    sowing_date: str,
    irrigation_efficiency: float = 0.75,
) -> dict[str, Any]:
    """Decide whether this field needs irrigating, and how much water to apply."""
    if crop not in CROPS:
        return {
            "ok": False,
            "abstain_reason": (
                f"'{crop}' is not in the calibrated crop set. Available crops: "
                f"{', '.join(sorted(CROPS))}. Advice for an uncalibrated crop "
                f"would be guesswork."
            ),
        }
    crop_params = CROPS[crop]

    try:
        sow = date.fromisoformat(sowing_date)
    except ValueError:
        return {"ok": False, "abstain_reason": f"Unparseable sowing date: {sowing_date}"}

    soil_profile, weather_series = await _soil_and_weather(latitude, longitude)

    if not soil_profile.has_data or soil_profile.texture_fractions is None:
        return {
            "ok": False,
            "abstain_reason": (
                "Soil texture is unavailable at this location, and irrigation "
                "depth depends entirely on how much water the soil can hold. "
                "Rather than guess, please confirm the field location."
            ),
            "evidence": soil_profile.evidence(),
        }

    soil = soil_from_texture(*soil_profile.texture_fractions)
    driving = _to_daily_weather(
        weather_series, weather_series.elevation_m, weather_series.latitude
    )
    today = date.today()
    history = [w for w in driving if w.day < today]
    forecast = [w for w in driving if w.day >= today]

    if not history:
        return {
            "ok": False,
            "abstain_reason": "No usable observed weather for this field.",
        }

    advice = next_irrigation_advice(
        crop_params, soil, sow, history, forecast,
        irrigation_efficiency=irrigation_efficiency,
    )

    das = (today - sow).days
    advice.update({
        "ok": advice.get("verdict") != "insufficient_data",
        "days_after_sowing": das,
        "crop_name": crop_params.name_en,
        "season_length_days": crop_params.total_days,
        "evidence": {
            "soil": soil_profile.evidence(),
            "weather": weather_series.evidence(),
            "method": (
                "FAO-56 dual-stage crop coefficient with a daily root-zone "
                "water balance (Allen et al. 1998, Ch. 6-8). Runoff by the "
                "USDA-SCS curve number method."
            ),
            "assumptions": [
                f"Irrigation application efficiency assumed {irrigation_efficiency:.0%}",
                f"Soil water retention inferred from SoilGrids texture "
                f"({soil.texture_class}), not measured on-farm",
                "Rooting depth follows the FAO-56 growth curve for this crop",
            ],
        },
    })
    return advice


# --------------------------------------------------------------------------
# Tool: regenerative practice / soil carbon
# --------------------------------------------------------------------------

async def compare_regenerative_practices(
    latitude: float,
    longitude: float,
    years: int = 20,
) -> dict[str, Any]:
    """Project soil carbon under alternative management, using RothC."""
    soil_profile = await fetch_soil_profile_resilient(latitude, longitude)
    if not soil_profile.has_data or soil_profile.texture_fractions is None:
        return {
            "ok": False,
            "abstain_reason": "Soil data unavailable; RothC cannot be initialised.",
            "evidence": soil_profile.evidence(),
        }

    sand, silt, clay = soil_profile.texture_fractions
    soc_g_kg = soil_profile.depth_weighted("soc")
    bulk_density = soil_profile.depth_weighted("bdod")
    if soc_g_kg is None or bulk_density is None:
        return {
            "ok": False,
            "abstain_reason": "Soil carbon or bulk density unavailable.",
            "evidence": soil_profile.evidence(),
        }

    initial_soc = soc_percent_to_t_ha(soc_g_kg / 10.0, bulk_density, 30.0)
    normals = await fetch_climate_normals(latitude, longitude, years=20)

    def forcing(carbon_input: float, vegetated_months: int,
                fym_fresh_t_ha: float = 0.0):
        # Manure is quoted, carted and applied by fresh weight, but RothC
        # consumes carbon. Converting here rather than at the call site keeps
        # the scenario definitions readable in the units a farmer uses.
        fym_carbon = manure_carbon_from_fresh_weight(fym_fresh_t_ha)
        months = []
        for m in range(1, 13):
            n = normals[m]
            # Open pan evaporation approximated from reference ET at the
            # RothC user guide's 0.75 conversion, applied in reverse.
            pan = n["total_et0_mm"] / 0.75 if n["total_et0_mm"] else 100.0
            vegetated = m <= vegetated_months
            months.append(MonthlyInput(
                mean_temp_c=n["mean_temp_c"],
                rainfall_mm=n["total_rain_mm"],
                open_pan_evaporation_mm=pan,
                carbon_input_t_ha=(
                    carbon_input / max(vegetated_months, 1) if vegetated else 0.0
                ),
                is_vegetated=vegetated,
                farmyard_manure_c_t_ha=fym_carbon / 12.0,
            ))
        return months

    # Four managements a farmer can actually choose between. Carbon input
    # rates are residue-return estimates from IPCC 2019 Refinement Vol.4 Ch.5
    # for cereal systems; they are assumptions and are labelled as such.
    scenarios = {
        "residue_burned_or_removed": {
            "label": "Residue burned or removed, bare fallow",
            "input": 0.5, "months": 6, "fym": 0.0,
        },
        "residue_retained": {
            "label": "Crop residue retained on the field",
            "input": 3.5, "months": 6, "fym": 0.0,
        },
        "residue_plus_cover_crop": {
            "label": "Residue retained plus a cover crop in the fallow",
            "input": 5.5, "months": 11, "fym": 0.0,
        },
        "residue_cover_and_manure": {
            "label": "Residue, cover crop, and 8 t/ha farmyard manure",
            "input": 5.5, "months": 11, "fym": 8.0,
        },
    }

    results = {}
    for key, s in scenarios.items():
        p = project(
            initial_soc, clay,
            forcing(s["input"], s["months"], s["fym"]),
            years=years,
        )
        results[key] = {
            "label": s["label"],
            "final_soc_t_per_ha": round(p.final_soc, 2),
            "change_t_per_ha": round(p.delta_soc, 2),
            "co2e_t_per_ha": round(p.co2e_sequestered_t_ha, 2),
            "annual_rate_t_per_ha": round(p.delta_soc / years, 3),
            "trajectory": [round(v, 2) for v in p.soc_by_year],
        }

    baseline = results["residue_burned_or_removed"]["final_soc_t_per_ha"]
    best_key = max(results, key=lambda k: results[k]["final_soc_t_per_ha"])

    return {
        "ok": True,
        "initial_soc_t_per_ha": round(initial_soc, 2),
        "clay_percent": round(clay, 1),
        "years_projected": years,
        "scenarios": results,
        "best_scenario": best_key,
        "gain_over_burning_t_co2e_per_ha": round(
            (results[best_key]["final_soc_t_per_ha"] - baseline) * 44.0 / 12.0, 2
        ),
        "evidence": {
            "soil": soil_profile.evidence(),
            "method": (
                "RothC-26.3 (Coleman & Jenkinson 1996), the model accepted "
                "under the IPCC 2019 Refinement as a Tier 3 method for "
                "cropland soil carbon."
            ),
            "climate_forcing": "20-year ERA5 monthly normals via Open-Meteo",
            "assumptions": [
                "Carbon input rates are IPCC 2019 Refinement defaults for "
                "cereal residue return, not farm-measured biomass",
                "Initial pool split assumes long-term arable equilibrium",
                "Projection holds climate constant at present-day normals",
            ],
        },
    }


# --------------------------------------------------------------------------
# Tool: crop suitability / what to plant
# --------------------------------------------------------------------------

async def assess_crop_suitability(
    latitude: float, longitude: float, candidate_crops: list[str] | None = None
) -> dict[str, Any]:
    """Score candidate crops against this field's soil and climate.

    This is deliberately conservative: it screens on constraints that are
    genuinely disqualifying (pH outside a crop's tolerance, thermal time
    insufficient to reach maturity, water demand far exceeding supply) rather
    than producing a confident ranking the underlying data cannot support.
    """
    soil_profile, weather_series = await _soil_and_weather(latitude, longitude)
    if not soil_profile.has_data or soil_profile.texture_fractions is None:
        return {"ok": False, "abstain_reason": "Soil data unavailable."}

    sand, silt, clay = soil_profile.texture_fractions
    soil = soil_from_texture(sand, silt, clay)
    ph = soil_profile.depth_weighted("phh2o")
    normals = await fetch_climate_normals(latitude, longitude, years=20)

    annual_rain = sum(normals[m]["total_rain_mm"] for m in range(1, 13))
    annual_et0 = sum(normals[m]["total_et0_mm"] for m in range(1, 13))
    mean_temp = sum(normals[m]["mean_temp_c"] for m in range(1, 13)) / 12.0

    # Growing degree days available in a year, above each crop's base temp.
    def annual_gdd(base: float) -> float:
        total = 0.0
        for m in range(1, 13):
            days = 30.4
            excess = normals[m]["mean_temp_c"] - base
            if excess > 0:
                total += excess * days
        return total

    # pH tolerance ranges, ICAR / FAO EcoCrop.
    PH_RANGE = {
        "rice_paddy": (5.0, 8.0), "wheat_winter": (6.0, 8.0),
        "wheat_spring": (6.0, 8.0), "wheat_rabi": (6.0, 8.5), "maize_grain": (5.5, 8.0),
        "soybean": (6.0, 7.5), "cotton": (6.0, 8.5),
        "sugarcane": (5.5, 8.0), "chickpea": (6.0, 8.5),
        "mustard": (6.0, 8.0), "groundnut": (5.5, 7.5),
        "pearl_millet": (6.0, 8.5), "sorghum": (5.5, 8.5),
        "potato": (5.0, 7.0), "sunflower": (6.0, 8.0), "barley": (6.5, 8.5),
    }

    keys = candidate_crops or list(CROPS)
    assessments = []
    for key in keys:
        if key not in CROPS:
            continue
        c = CROPS[key]
        constraints: list[str] = []
        remediable: list[dict] = []
        score = 100.0

        # Constraints are separated into those a farmer can correct with a
        # known input and those set by climate. Conflating them is a real
        # modelling error with a real consequence: the Brazilian cerrado is
        # strongly acidic and *every* crop scores badly on raw pH, yet liming
        # is routine practice there and the region is one of the world's
        # great soy producers. A hard pH penalty would tell a cerrado farmer
        # to grow nothing.
        lo, hi = PH_RANGE.get(key, (5.0, 8.5))
        if ph is not None:
            if ph < lo:
                gap = lo - ph
                # Agricultural lime requirement, rule of thumb from ICAR /
                # Embrapa liming guides: roughly 2 t/ha of CaCO3 equivalent
                # per pH unit on a medium-textured soil, more on clays.
                lime_t_ha = round(gap * 2.0 * (1.0 + clay / 100.0), 1)
                constraints.append(
                    f"Soil pH {ph:.1f} is below this crop's range ({lo}-{hi}). "
                    f"Correctable: about {lime_t_ha} t/ha of agricultural lime "
                    f"would raise it into range."
                )
                remediable.append({
                    "issue": "soil_acidity", "input": "agricultural lime",
                    "quantity_t_per_ha": lime_t_ha,
                })
                score -= min(15.0, gap * 8.0)
            elif ph > hi:
                gap = ph - hi
                constraints.append(
                    f"Soil pH {ph:.1f} is above this crop's range ({lo}-{hi}). "
                    f"Partly correctable with gypsum and organic matter, but "
                    f"a more tolerant crop is usually the cheaper answer."
                )
                remediable.append({
                    "issue": "soil_alkalinity", "input": "gypsum",
                    "quantity_t_per_ha": round(gap * 2.5, 1),
                })
                score -= min(20.0, gap * 12.0)

        gdd = annual_gdd(c.base_temp_c)
        if gdd < c.gdd_to_maturity:
            constraints.append(
                f"Hard limit: only about {gdd:.0f} growing degree-days are "
                f"available per year against {c.gdd_to_maturity:.0f} needed to "
                f"reach maturity. No input corrects insufficient heat."
            )
            score -= 40
        elif gdd < c.gdd_to_maturity * 1.3:
            constraints.append("Thermal time is adequate but leaves little margin")
            score -= 10

        # Seasonal water demand against rainfall that actually falls while
        # the crop is in the ground. Accumulating over the crop's real
        # growing months (hemisphere-aware) rather than prorating the annual
        # total is essential in monsoon climates: kharif and rabi crops in
        # the same field see completely different water supplies.
        months = c.growing_months(latitude)
        seasonal_rain = sum(normals[m]["total_rain_mm"] for m in months)
        seasonal_et0 = sum(normals[m]["total_et0_mm"] for m in months)
        # Season-average Kc weighted by stage length, not a flat mean of the
        # three anchor points -- mid-season is usually the longest stage and
        # carries the highest Kc, so a flat mean understates demand.
        l_ini, l_dev, l_mid, l_late = c.stage_days
        weighted_kc = (
            c.kc_ini * l_ini
            + ((c.kc_ini + c.kc_mid) / 2.0) * l_dev
            + c.kc_mid * l_mid
            + ((c.kc_mid + c.kc_end) / 2.0) * l_late
        ) / c.total_days
        water_need = seasonal_et0 * weighted_kc
        deficit = water_need - seasonal_rain
        if deficit > 0:
            # Scored against the crop's own requirement, not an absolute mm
            # figure: a 200 mm shortfall is minor for sugarcane and fatal for
            # a 90-day millet crop.
            shortfall_ratio = deficit / max(water_need, 1.0)
            if shortfall_ratio > 0.6:
                constraints.append(
                    f"Severe rainfed deficit: about {deficit:.0f} mm short of "
                    f"the {water_need:.0f} mm this crop needs. Assured "
                    f"irrigation is essential."
                )
            else:
                constraints.append(
                    f"Rainfed deficit of about {deficit:.0f} mm against a "
                    f"{water_need:.0f} mm requirement; supplemental "
                    f"irrigation would be needed"
                )
            score -= min(45.0, shortfall_ratio * 60.0)
        else:
            constraints.append(
                f"Rainfall over the growing season (~{seasonal_rain:.0f} mm) "
                f"covers the crop's {water_need:.0f} mm requirement"
            )

        if c.is_paddy and soil.texture_class in {"sand", "loamy_sand", "sandy_loam"}:
            constraints.append(
                "Paddy on a coarse-textured soil loses very large volumes to "
                "percolation; puddling or a different crop is advisable"
            )
            score -= 25

        assessments.append({
            "crop": key,
            "name": c.name_en,
            "score": round(max(0.0, min(100.0, score)), 1),
            "constraints": constraints,
            "correctable_with_inputs": remediable,
            "season_days": c.total_days,
            "growing_months": months,
            "estimated_water_need_mm": round(water_need),
            "estimated_seasonal_rain_mm": round(seasonal_rain),
            "rainfed_viable": deficit <= 0,
        })

    assessments.sort(key=lambda a: a["score"], reverse=True)

    return {
        "ok": True,
        "site": {
            "soil_texture": soil.texture_class,
            "ph": round(ph, 1) if ph else None,
            "annual_rain_mm": round(annual_rain),
            "annual_reference_et_mm": round(annual_et0),
            "mean_temp_c": round(mean_temp, 1),
            "aridity_index": round(annual_rain / annual_et0, 2) if annual_et0 else None,
        },
        "assessments": assessments,
        "evidence": {
            "soil": soil_profile.evidence(),
            "weather": weather_series.evidence(),
            "method": (
                "Constraint screening on pH tolerance (ICAR/FAO EcoCrop), "
                "thermal time to maturity, and seasonal water balance. This "
                "screens out unsuitable crops; it does not predict yield."
            ),
        },
    }


# --------------------------------------------------------------------------
# Tool: satellite crop health
# --------------------------------------------------------------------------

async def get_crop_health(
    latitude: float,
    longitude: float,
    crop: str | None = None,
    sowing_date: str | None = None,
    field_size_m: float = 200.0,
) -> dict[str, Any]:
    """Read the crop's condition from Sentinel-2 and compare it to expectation.

    Returns raw NDVI history plus, when the crop and sowing date are known,
    an interpretation: how much canopy the field actually has against how
    much a healthy crop should have at this growth stage.

    That comparison is the whole point. NDVI 0.45 is healthy for maize three
    weeks after sowing and alarming at tasselling; handing a farmer the
    number alone asks them to supply the agronomy themselves.
    """
    buffer_m = max(50.0, min(field_size_m / 2.0, 500.0))

    # A full year is fetched rather than one season: the extra history is
    # what allows the NDVI-to-cover scale to be calibrated against this
    # field's own bare soil and own full canopy, instead of global constants
    # that fit no particular field.
    series = await fetch_ndvi_series(
        latitude, longitude,
        start=date.today() - timedelta(days=365),
        buffer_m=buffer_m, max_scenes=18,
    )

    if not series.observations:
        return {
            "ok": False,
            "abstain_reason": (
                "No usable satellite images of this field in the last four "
                "months. Continuous cloud during the monsoon is the usual "
                "reason. Try again after a clear spell."
            ),
            "evidence": series.evidence(),
        }

    latest = series.latest
    trend = series.trend(days=30)

    history = [
        {
            "date": o.day.isoformat(),
            "ndvi": round(o.ndvi_mean, 3),
            "uniformity_percent": round(o.uniformity * 100, 1),
            "cloud_percent": round(o.scene_cloud_percent, 1),
            "usable_pixels_percent": round(o.valid_fraction * 100, 1),
        }
        for o in series.observations
    ]

    result: dict[str, Any] = {
        "ok": True,
        "latest_ndvi": round(latest.ndvi_mean, 3),
        "latest_date": latest.day.isoformat(),
        "uniformity_percent": round(latest.uniformity * 100, 1),
        "ndvi_trend_per_day": round(trend, 4) if trend is not None else None,
        "observations": len(series.observations),
        "history": history,
        "provider": series.provider,
        "evidence": series.evidence(),
    }

    # Interpretation requires knowing what is planted and when.
    if crop in CROPS and sowing_date:
        try:
            stated = date.fromisoformat(sowing_date)
        except ValueError:
            stated = None

        das = None
        if stated is not None:
            # Cross-check the stated sowing date against when the field
            # actually greened up. A date a few weeks out turns a healthy
            # crop into a false alarm.
            reconciled = reconcile_sowing_date(
                stated, [(o.day, o.ndvi_mean) for o in series.observations]
            )
            effective = reconciled["sowing_date"]
            das = (date.today() - effective).days
            result["sowing_date_used"] = effective.isoformat()
            result["sowing_date_source"] = reconciled["source"]
            if reconciled.get("note"):
                result["sowing_date_note"] = reconciled["note"]

        if das is not None and das >= 0:
            history_values = [o.ndvi_mean for o in series.observations]
            ndvi_soil, ndvi_veg = calibrate_endpoints(history_values)

            # Judge on the best recent pass rather than the single latest.
            # Haze and thin cirrus depress individual scenes, and a season
            # should not be condemned on one bad observation.
            judged_ndvi = representative_ndvi(
                [(o.day, o.ndvi_mean) for o in series.observations]
            ) or latest.ndvi_mean

            is_cropland = looks_like_annual_cropland(history_values)
            calibrated = (
                len(series.observations) >= 8
                and (ndvi_veg - ndvi_soil) >= 0.25
            )
            result["looks_like_annual_cropland"] = is_cropland

            assessment = assess_canopy(
                crop, das, judged_ndvi,
                uniformity=latest.uniformity, trend_per_day=trend,
                ndvi_soil=ndvi_soil, ndvi_veg=ndvi_veg,
                locally_calibrated=calibrated,
            ) if is_cropland else None

            if not is_cropland:
                # Report what was measured, withhold the stage verdict.
                result["note"] = (
                    "This location stays green all year rather than going "
                    "bare between seasons, which is what an orchard, "
                    "plantation, permanent grass or tree cover looks like "
                    "from orbit — not an annual crop field. I can report the "
                    "greenness but not judge it against a crop's growth "
                    "stage. If the field boundary is wrong, please set it "
                    "again."
                )
            if assessment:
                verdict = assessment.to_dict()
                # A behind-schedule verdict rests entirely on the sowing date
                # being right, and sowing dates are usually recalled weeks
                # later. Where the satellite has not independently confirmed
                # it, the model must say so rather than assert crop failure
                # on an unverified premise.
                behind = verdict["status"] in (
                    "behind", "severely_behind", "slightly_behind"
                )
                confirmed = result.get("sowing_date_source") in (
                    "satellite", "farmer_confirmed_by_satellite"
                )
                if behind and not confirmed:
                    verdict["depends_on"] = (
                        "This comparison assumes the sowing date given is "
                        "correct. If sowing was later than stated, the crop "
                        "may be fine. Confirm the sowing date before acting."
                    )
                # Canopy expectations are generic FAO-56 stage curves, not
                # variety-specific. Short-duration and hybrid varieties reach
                # canopy sooner than the table crop.
                verdict["caveat"] = (
                    "Expected canopy is a generic curve for this crop, not "
                    "for your specific variety or spacing."
                )
                result["assessment"] = verdict
                result["crop_name"] = CROPS[crop].name_en
                result["calibration"] = {
                    "ndvi_bare_soil": round(ndvi_soil, 3),
                    "ndvi_full_canopy": round(ndvi_veg, 3),
                    "calibrated_from_field_history": calibrated,
                }
                result["evidence"]["interpretation_method"] = (
                    "NDVI converted to fractional canopy cover (Carlson & "
                    "Ripley 1997) using endpoints calibrated from this "
                    "field's own 12-month NDVI range (local scaling, Gutman "
                    "& Ignatov 1998), then compared against the FAO-56 crop "
                    "coefficient development curve for this crop and stage."
                )
    else:
        result["note"] = (
            "Tell me which crop is planted and roughly when it was sown, and "
            "I can say whether this greenness is normal for its stage."
        )

    return result


# --------------------------------------------------------------------------
# Tool: mandi prices
# --------------------------------------------------------------------------

async def get_mandi_prices(
    crop: str,
    latitude: float | None = None,
    longitude: float | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Today's regulated-market (APMC) prices for a crop near the farmer.

    Reports the local rate, the best rate in range, and the spread between
    markets -- because the spread is often the actionable part. A farmer who
    learns a mandi two districts away is paying appreciably more can decide
    whether the transport is worth it; one who only sees a single number
    cannot.
    """
    if crop not in CROPS:
        return {
            "ok": False,
            "abstain_reason": (
                f"'{crop}' is not in the crop set, so I cannot look up its "
                f"market rate."
            ),
        }

    try:
        report = await prices_for_crop(
            crop, latitude=latitude, longitude=longitude, state=state
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "abstain_reason": (
                f"The mandi price service did not respond ({type(exc).__name__}). "
                f"Rates change daily, so please check Agmarknet or your local "
                f"mandi directly rather than relying on an older figure."
            ),
        }

    if not report.quotes:
        if report.scope == "unavailable":
            # Never dress a service outage as market information. Telling a
            # farmer their crop is out of season when we simply could not ask
            # is a confident falsehood about their income.
            return {
                "ok": False,
                "abstain_reason": (
                    "I could not reach the government mandi price service just "
                    "now, so I do not know today's rate. This is a problem at "
                    "our end, not a sign that no one is buying. Please check "
                    "with your mandi directly, or ask me again shortly."
                ),
                "operator_detail": report.failure_reason,
                "evidence": report.evidence(),
            }
        return {
            "ok": False,
            "abstain_reason": (
                f"No market anywhere in India reported {CROPS[crop].name_en} "
                f"arrivals today. Agmarknet lists only markets that actually "
                f"traded, so this usually means the crop is out of season. "
                f"Rates will appear as harvest arrivals begin."
            ),
            "evidence": report.evidence(),
        }

    modal_prices = sorted(q.modal_price for q in report.quotes)
    median = modal_prices[len(modal_prices) // 2]
    best = report.best
    local = report.local

    markets = [
        {
            "market": q.market,
            "district": q.district,
            "state": q.state,
            "variety": q.variety,
            "modal_rs_per_quintal": round(q.modal_price),
            "min_rs_per_quintal": round(q.min_price),
            "max_rs_per_quintal": round(q.max_price),
        }
        for q in sorted(report.quotes, key=lambda x: x.modal_price, reverse=True)[:8]
    ]

    result: dict[str, Any] = {
        "ok": True,
        "crop_name": CROPS[crop].name_en,
        "unit": "Indian rupees per quintal (100 kg)",
        "as_of": report.as_of.isoformat() if report.as_of else None,
        "scope": report.scope,
        "median_rs_per_quintal": round(median),
        "lowest_rs_per_quintal": round(modal_prices[0]),
        "highest_rs_per_quintal": round(modal_prices[-1]),
        "markets_reporting": len({q.market for q in report.quotes}),
        "top_markets": markets,
        "evidence": report.evidence(),
    }

    if best:
        result["best_market"] = {
            "market": best.market, "district": best.district,
            "state": best.state,
            "modal_rs_per_quintal": round(best.modal_price),
            "rs_per_kg": round(best.modal_per_kg, 1),
        }
    if local:
        result["local_market"] = {
            "market": local.market, "district": local.district,
            "modal_rs_per_quintal": round(local.modal_price),
        }
        if best and best.modal_price > local.modal_price:
            gap = best.modal_price - local.modal_price
            result["premium_elsewhere_rs_per_quintal"] = round(gap)
            # Stated per tonne as well: transport is costed by the load, and
            # a per-quintal gap looks trivially small until it is scaled up.
            result["premium_per_tonne_rs"] = round(gap * 10)
    elif report.scope == "state":
        result["note"] = (
            "No market in your own district reported arrivals of this crop "
            "today. These are the nearest reporting markets in your state."
        )

    if report.scope == "national":
        result["note"] = (
            f"No market in {report.state or 'your state'} reported this crop "
            f"today, which usually means it is out of season locally. These "
            f"are rates from elsewhere in India and are a guide to what to "
            f"expect, not what your mandi will pay today."
        )

    return result


# --------------------------------------------------------------------------
# Tool: find a place
# --------------------------------------------------------------------------

async def find_place(query: str) -> dict[str, Any]:
    """Turn a village, town or district name into coordinates.

    Every other tool needs latitude and longitude; farmers have place names.
    This closes that gap so the assistant never has to ask for something the
    farmer cannot supply.
    """
    if not query or not query.strip():
        return {"ok": False, "abstain_reason": "No place name given."}

    try:
        matches = await geocode_place(query)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "abstain_reason": (
                f"The place lookup service did not respond "
                f"({type(exc).__name__}). Ask the farmer to drop a pin using "
                f"the 'Set field' button instead."
            ),
        }

    if not matches:
        return {
            "ok": False,
            "abstain_reason": (
                f"No place in India matched '{query}'. Ask for the nearest "
                f"larger town or the district, or ask them to use the "
                f"'Set field' button to drop a pin."
            ),
        }

    return {
        "ok": True,
        "query": query,
        "best_match": matches[0],
        "other_matches": matches[1:4],
        # Village names repeat across India, so ambiguity is surfaced rather
        # than silently resolved to the first hit -- picking the wrong
        # Rampur would produce confidently wrong advice for another state.
        "ambiguous": len(matches) > 1 and len({
            m.get("district") for m in matches[:3]
        }) > 1,
        "evidence": {
            "source": "OpenStreetMap Nominatim",
            "licence": "ODbL",
            "matches_found": len(matches),
        },
    }


# --------------------------------------------------------------------------
# Tool: government schemes
# --------------------------------------------------------------------------

async def find_government_schemes(
    concern: str = "",
    owns_land: bool | None = None,
    has_water_source: bool | None = None,
    scheme_key: str | None = None,
) -> dict[str, Any]:
    """Find Indian government schemes relevant to a farmer's situation.

    Returns navigation, not entitlement. Whether this particular farmer
    qualifies is decided by their state agriculture department and by nobody
    else, least of all by an assistant reasoning from a description. So the
    result gives screening questions they can answer themselves, the things
    that most commonly disqualify people, and the official portal and
    helpline where the authoritative answer lives.

    Every record carries the date it was last checked, and stale records say
    so, because scheme rules change each financial year and a confidently
    quoted obsolete figure sends someone to an office for nothing.
    """
    if scheme_key:
        scheme = SCHEMES.get(scheme_key)
        if scheme is None:
            return {
                "ok": False,
                "abstain_reason": (
                    f"I do not have a record for '{scheme_key}'. I only cover "
                    f"{', '.join(s.short_name for s in SCHEMES.values())}. For "
                    f"anything else, myscheme.gov.in lists every central and "
                    f"state scheme."
                ),
            }
        ranked = [scheme]
    else:
        ranked = schemes_for_situation(
            owns_land=owns_land,
            has_water_source=has_water_source,
            concern=concern,
        )[:3]

    def render(s) -> dict[str, Any]:
        return {
            "name": s.name,
            "short_name": s.short_name,
            "what_it_does": s.what_it_does,
            "check_yourself": list(s.screening_questions),
            "commonly_disqualifies": list(s.common_exclusions),
            "key_facts": list(s.key_facts),
            "apply_through": s.apply_through,
            "documents": list(s.documents_usually_needed),
            "official_website": s.official_url,
            "helpline": s.helpline,
            "information_last_checked": s.last_verified.isoformat(),
            "may_be_out_of_date": s.is_stale(),
        }

    return {
        "ok": True,
        "schemes": [render(s) for s in ranked],
        "evidence": {
            "source": "Official scheme portals of the Government of India",
            "method": (
                "Curated scheme registry with screening criteria. This is "
                "navigation, not an eligibility determination."
            ),
            "authoritative_source": (
                "myscheme.gov.in lists every central and state scheme and is "
                "the place to check anything not covered here."
            ),
            "caveat": (
                "Scheme rules, amounts and cut-off dates change each "
                "financial year and differ by state. Always confirm on the "
                "official portal or with the village agriculture officer "
                "before acting."
            ),
        },
    }
