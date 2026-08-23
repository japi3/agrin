"""
Crop parameter database and the FAO-56 dual-stage crop coefficient model.

Parameters are transcribed from FAO Irrigation and Drainage Paper 56:
  - Kc values and stage lengths: Table 11 (lengths) and Table 12 (Kc)
  - Rooting depth Zr and depletion fraction p: Table 22
  - Yield response factor Ky: FAO I&D Paper 33, Table 24 of FAO-56

Where FAO-56 gives a range, the value used is the mid-point of the range for
the sub-humid reference condition (RHmin ~= 45%, u2 ~= 2 m/s), and Kc_mid /
Kc_end are then climate-adjusted at runtime by `adjust_kc_for_climate`
following FAO-56 Eq. 62 -- the adjustment matters a great deal in the arid
and semi-arid zones that dominate BRICS cropping, where the unadjusted table
value can be 10-15 percent low.

Stage lengths are given for the dominant planting window of each crop's main
BRICS-region production zone; they are a default, not a claim about a
specific farm. Any field with an observed sowing date and phenology
observations should override them via `CropCycle.from_observations`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class GrowthStage(str, Enum):
    """FAO-56 Chapter 6 growth stages."""
    INITIAL = "initial"
    DEVELOPMENT = "development"
    MID_SEASON = "mid_season"
    LATE_SEASON = "late_season"


@dataclass(frozen=True)
class CropParameters:
    """Agronomic constants for one crop, per FAO-56.

    Attributes:
        key: stable machine identifier, used as the DB and API key.
        name_en: English common name.
        kc_ini/kc_mid/kc_end: crop coefficients for the three FAO-56 anchor
            points. Kc during development and late season is interpolated.
        stage_days: days in (initial, development, mid, late) season.
        root_depth_m: maximum effective rooting depth Zr [m], FAO-56 Table 22.
        depletion_fraction: p, the fraction of TAW that can be depleted before
            the crop experiences water stress, at an ETc of 5 mm/day.
        yield_response_factor: Ky, the slope relating relative yield loss to
            relative ET deficit (FAO-56 Eq. 90). Ky > 1 means the crop is
            disproportionately sensitive to water stress.
        base_temp_c: base temperature for growing-degree-day accumulation.
        gdd_to_maturity: thermal time from emergence to maturity [degree-days].
        is_paddy: flooded rice behaves differently -- it is not modelled with
            a soil-water-depletion balance but with a ponded-depth balance.
    """
    key: str
    name_en: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    stage_days: tuple[int, int, int, int]
    root_depth_m: float
    depletion_fraction: float
    yield_response_factor: float
    base_temp_c: float
    gdd_to_maturity: float
    is_paddy: bool = False
    # Months (1-12) in which this crop is normally sown, by hemisphere.
    # Seasonal water supply MUST be accumulated over the actual growing
    # months rather than prorated from an annual total: in monsoon climates
    # a kharif crop receives most of the year's rain and a rabi crop almost
    # none, and linear prorating scores them identically -- which is how a
    # tool ends up recommending rainfed wheat in a place it would fail.
    sowing_months_north: tuple[int, ...] = ()
    sowing_months_south: tuple[int, ...] = ()

    @property
    def total_days(self) -> int:
        return sum(self.stage_days)

    def growing_months(self, latitude: float) -> list[int]:
        """Calendar months this crop occupies, for the given hemisphere.

        Returns month numbers 1-12, wrapping across the new year for rabi and
        winter crops (a wheat crop sown in November occupies Nov-Apr).
        """
        windows = (
            self.sowing_months_north if latitude >= 0
            else self.sowing_months_south
        )
        if not windows:
            return list(range(1, 13))
        start = windows[0]
        n_months = max(1, round(self.total_days / 30.4))
        return [((start - 1 + i) % 12) + 1 for i in range(n_months)]


# FAO-56 Tables 11, 12 and 22. Crops chosen for coverage of the staple and
# cash cropping systems of the BRICS member states: India (rice, wheat,
# cotton, sugarcane, chickpea, mustard, millet, groundnut), China (rice,
# wheat, maize, cotton, soybean, potato), Brazil (soybean, maize, sugarcane,
# cotton, coffee), Russia (wheat, barley, sunflower, potato), South Africa
# (maize, sugarcane, sunflower, wheat).
CROPS: dict[str, CropParameters] = {
    "rice_paddy": CropParameters(
        key="rice_paddy", name_en="Rice (paddy)",
        kc_ini=1.05, kc_mid=1.20, kc_end=0.90,
        stage_days=(30, 30, 60, 30),
        root_depth_m=0.50, depletion_fraction=0.20,
        yield_response_factor=1.10, base_temp_c=10.0, gdd_to_maturity=2000.0,
        is_paddy=True,
        sowing_months_north=(6, 7),
        sowing_months_south=(11, 12),
    ),
    "wheat_winter": CropParameters(
        key="wheat_winter", name_en="Wheat (winter)",
        kc_ini=0.70, kc_mid=1.15, kc_end=0.30,
        stage_days=(30, 140, 40, 30),
        root_depth_m=1.65, depletion_fraction=0.55,
        yield_response_factor=1.00, base_temp_c=0.0, gdd_to_maturity=2100.0,
        sowing_months_north=(10, 11),
        sowing_months_south=(4, 5),
    ),
    "wheat_spring": CropParameters(
        key="wheat_spring", name_en="Wheat (spring)",
        kc_ini=0.40, kc_mid=1.15, kc_end=0.30,
        stage_days=(20, 25, 60, 30),
        root_depth_m=1.65, depletion_fraction=0.55,
        yield_response_factor=1.00, base_temp_c=0.0, gdd_to_maturity=1800.0,
        sowing_months_north=(11, 12),
        sowing_months_south=(5, 6),
    ),
    "maize_grain": CropParameters(
        key="maize_grain", name_en="Maize (grain)",
        kc_ini=0.30, kc_mid=1.20, kc_end=0.50,
        stage_days=(25, 40, 45, 30),
        root_depth_m=1.40, depletion_fraction=0.55,
        yield_response_factor=1.25, base_temp_c=10.0, gdd_to_maturity=1500.0,
        sowing_months_north=(6, 7),
        sowing_months_south=(10, 11),
    ),
    "soybean": CropParameters(
        key="soybean", name_en="Soybean",
        kc_ini=0.40, kc_mid=1.15, kc_end=0.50,
        stage_days=(20, 30, 60, 25),
        root_depth_m=1.10, depletion_fraction=0.50,
        yield_response_factor=0.85, base_temp_c=10.0, gdd_to_maturity=1400.0,
        sowing_months_north=(6, 7),
        sowing_months_south=(10, 11),
    ),
    "cotton": CropParameters(
        key="cotton", name_en="Cotton",
        kc_ini=0.35, kc_mid=1.18, kc_end=0.60,
        stage_days=(30, 50, 60, 55),
        root_depth_m=1.40, depletion_fraction=0.65,
        yield_response_factor=0.85, base_temp_c=15.0, gdd_to_maturity=2200.0,
        sowing_months_north=(5, 6),
        sowing_months_south=(11, 12),
    ),
    "sugarcane": CropParameters(
        key="sugarcane", name_en="Sugarcane",
        kc_ini=0.40, kc_mid=1.25, kc_end=0.75,
        stage_days=(35, 60, 190, 120),
        root_depth_m=1.80, depletion_fraction=0.65,
        yield_response_factor=1.20, base_temp_c=12.0, gdd_to_maturity=4000.0,
        sowing_months_north=(2, 3),
        sowing_months_south=(9, 10),
    ),
    "chickpea": CropParameters(
        key="chickpea", name_en="Chickpea (gram)",
        kc_ini=0.40, kc_mid=1.00, kc_end=0.35,
        stage_days=(20, 30, 40, 20),
        root_depth_m=0.80, depletion_fraction=0.50,
        yield_response_factor=0.90, base_temp_c=5.0, gdd_to_maturity=1300.0,
        sowing_months_north=(10, 11),
        sowing_months_south=(4, 5),
    ),
    "mustard": CropParameters(
        key="mustard", name_en="Mustard / Rapeseed",
        kc_ini=0.35, kc_mid=1.10, kc_end=0.35,
        stage_days=(25, 35, 45, 25),
        root_depth_m=1.20, depletion_fraction=0.60,
        yield_response_factor=0.90, base_temp_c=5.0, gdd_to_maturity=1500.0,
        sowing_months_north=(10, 11),
        sowing_months_south=(4, 5),
    ),
    "groundnut": CropParameters(
        key="groundnut", name_en="Groundnut (peanut)",
        kc_ini=0.40, kc_mid=1.10, kc_end=0.60,
        stage_days=(25, 35, 45, 25),
        root_depth_m=0.70, depletion_fraction=0.50,
        yield_response_factor=0.70, base_temp_c=10.0, gdd_to_maturity=1600.0,
        sowing_months_north=(6, 7),
        sowing_months_south=(11, 12),
    ),
    "pearl_millet": CropParameters(
        key="pearl_millet", name_en="Pearl millet (bajra)",
        kc_ini=0.35, kc_mid=1.00, kc_end=0.30,
        stage_days=(15, 25, 40, 25),
        root_depth_m=1.50, depletion_fraction=0.55,
        yield_response_factor=1.00, base_temp_c=10.0, gdd_to_maturity=1400.0,
        sowing_months_north=(6, 7),
        sowing_months_south=(11, 12),
    ),
    "sorghum": CropParameters(
        key="sorghum", name_en="Sorghum (jowar)",
        kc_ini=0.35, kc_mid=1.05, kc_end=0.55,
        stage_days=(20, 35, 40, 30),
        root_depth_m=1.50, depletion_fraction=0.55,
        yield_response_factor=0.90, base_temp_c=10.0, gdd_to_maturity=1600.0,
        sowing_months_north=(6, 7),
        sowing_months_south=(11, 12),
    ),
    "potato": CropParameters(
        key="potato", name_en="Potato",
        kc_ini=0.50, kc_mid=1.15, kc_end=0.75,
        stage_days=(25, 30, 45, 30),
        root_depth_m=0.50, depletion_fraction=0.35,
        yield_response_factor=1.10, base_temp_c=7.0, gdd_to_maturity=1200.0,
        sowing_months_north=(10, 11),
        sowing_months_south=(4, 5),
    ),
    "sunflower": CropParameters(
        key="sunflower", name_en="Sunflower",
        kc_ini=0.35, kc_mid=1.05, kc_end=0.35,
        stage_days=(25, 35, 45, 25),
        root_depth_m=1.30, depletion_fraction=0.45,
        yield_response_factor=0.95, base_temp_c=8.0, gdd_to_maturity=1600.0,
        sowing_months_north=(1, 2),
        sowing_months_south=(8, 9),
    ),
    "barley": CropParameters(
        key="barley", name_en="Barley",
        kc_ini=0.30, kc_mid=1.15, kc_end=0.25,
        stage_days=(15, 25, 50, 30),
        root_depth_m=1.30, depletion_fraction=0.55,
        yield_response_factor=1.00, base_temp_c=0.0, gdd_to_maturity=1600.0,
        sowing_months_north=(10, 11),
        sowing_months_south=(4, 5),
    ),
}


def adjust_kc_for_climate(
    kc_table: float, rh_min: float, wind_2m_ms: float, plant_height_m: float
) -> float:
    """Climate-adjust a tabulated Kc value. FAO-56 Eq. 62.

    FAO-56 Table 12 values assume a sub-humid climate (RHmin = 45%,
    u2 = 2 m/s). In the arid cropping zones of Rajasthan, the North China
    Plain or the South African Highveld, actual Kc_mid runs materially higher
    because the crop canopy is rougher than the grass reference and the air is
    drier. Skipping this step systematically under-irrigates exactly the
    farmers with the least margin for error.

    Only applied to Kc_mid and Kc_end (and only when Kc_end > 0.45), per
    FAO-56; Kc_ini is governed by wetting frequency instead.
    """
    return kc_table + (
        0.04 * (wind_2m_ms - 2.0) - 0.004 * (rh_min - 45.0)
    ) * (plant_height_m / 3.0) ** 0.3


def crop_coefficient(crop: CropParameters, days_after_sowing: int) -> tuple[float, GrowthStage]:
    """Kc and growth stage for a given day of the season. FAO-56 Figure 25.

    Kc is constant during the initial and mid-season stages and interpolates
    linearly across the development and late-season stages.
    """
    l_ini, l_dev, l_mid, l_late = crop.stage_days
    d = days_after_sowing

    if d < 0:
        return crop.kc_ini, GrowthStage.INITIAL
    if d <= l_ini:
        return crop.kc_ini, GrowthStage.INITIAL
    if d <= l_ini + l_dev:
        frac = (d - l_ini) / l_dev
        return crop.kc_ini + frac * (crop.kc_mid - crop.kc_ini), GrowthStage.DEVELOPMENT
    if d <= l_ini + l_dev + l_mid:
        return crop.kc_mid, GrowthStage.MID_SEASON
    if d <= crop.total_days:
        frac = (d - l_ini - l_dev - l_mid) / l_late
        return crop.kc_mid + frac * (crop.kc_end - crop.kc_mid), GrowthStage.LATE_SEASON
    return crop.kc_end, GrowthStage.LATE_SEASON


# --------------------------------------------------------------------------
# Soil water holding capacity
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SoilWaterProperties:
    """Water retention constants for a soil.

    field_capacity and wilting_point are volumetric water contents [m3/m3].
    These come from SoilGrids texture fractions via `from_texture` when no
    measured values exist.
    """
    field_capacity: float
    wilting_point: float
    saturation: float
    texture_class: str

    @property
    def available_water_fraction(self) -> float:
        """Plant-available water per metre of soil [m3/m3]."""
        return self.field_capacity - self.wilting_point


# FAO-56 Table 19: typical water retention by USDA texture class.
TEXTURE_WATER: dict[str, tuple[float, float, float]] = {
    # texture: (field capacity, wilting point, saturation)
    "sand": (0.12, 0.05, 0.40),
    "loamy_sand": (0.16, 0.07, 0.42),
    "sandy_loam": (0.22, 0.10, 0.44),
    "loam": (0.28, 0.14, 0.46),
    "silt_loam": (0.32, 0.15, 0.48),
    "silt": (0.33, 0.14, 0.48),
    "silty_clay_loam": (0.35, 0.19, 0.50),
    "clay_loam": (0.33, 0.19, 0.49),
    "sandy_clay": (0.31, 0.20, 0.48),
    "silty_clay": (0.37, 0.22, 0.51),
    "clay": (0.38, 0.24, 0.52),
}


def usda_texture_class(sand_pct: float, silt_pct: float, clay_pct: float) -> str:
    """Classify a soil into a USDA texture class from its particle fractions.

    Implements the USDA textural triangle decision rules (Soil Survey Manual,
    USDA Handbook 18). SoilGrids returns sand/silt/clay percentages for every
    point on Earth, so this is what turns a raw SoilGrids query into a
    water-holding capacity a farmer's irrigation depth depends on.

    The rules are order-sensitive: clay classes are tested before loams
    because the triangle's regions overlap on single-fraction thresholds.
    """
    total = sand_pct + silt_pct + clay_pct
    if total <= 0:
        raise ValueError("texture fractions must sum to a positive value")
    # Normalise: SoilGrids fractions occasionally sum to 99 or 101.
    sand = sand_pct / total * 100.0
    silt = silt_pct / total * 100.0
    clay = clay_pct / total * 100.0

    if clay >= 40.0:
        if silt >= 40.0:
            return "silty_clay"
        if sand >= 45.0:
            return "sandy_clay"
        return "clay"
    if clay >= 27.0:
        if sand >= 45.0:
            return "clay_loam"
        if silt >= 40.0:
            return "silty_clay_loam"
        return "clay_loam"
    if silt >= 80.0 and clay < 12.0:
        return "silt"
    if silt >= 50.0:
        return "silt_loam"
    if sand >= 85.0:
        return "sand"
    if sand >= 70.0:
        return "loamy_sand"
    if sand >= 43.0 and clay < 20.0:
        return "sandy_loam"
    return "loam"


def soil_from_texture(sand_pct: float, silt_pct: float, clay_pct: float) -> SoilWaterProperties:
    """Build water retention properties from SoilGrids texture fractions."""
    texture = usda_texture_class(sand_pct, silt_pct, clay_pct)
    fc, wp, sat = TEXTURE_WATER[texture]
    return SoilWaterProperties(
        field_capacity=fc, wilting_point=wp, saturation=sat, texture_class=texture
    )


def total_available_water(soil: SoilWaterProperties, root_depth_m: float) -> float:
    """Total available soil water TAW [mm] in the root zone. FAO-56 Eq. 82."""
    return 1000.0 * soil.available_water_fraction * root_depth_m


def readily_available_water(taw: float, depletion_fraction: float, etc_mm_day: float) -> float:
    """Readily available water RAW [mm]. FAO-56 Eq. 83, with the Table 22 note.

    The tabulated depletion fraction p applies at ETc = 5 mm/day; FAO-56
    adjusts it for other rates, because a crop under high evaporative demand
    starts to suffer at a shallower depletion than the same crop in mild
    weather. p is clamped to [0.1, 0.8] as FAO-56 directs.
    """
    p_adjusted = depletion_fraction + 0.04 * (5.0 - etc_mm_day)
    p_adjusted = max(0.1, min(0.8, p_adjusted))
    return p_adjusted * taw


def water_stress_coefficient(depletion_mm: float, taw: float, raw: float) -> float:
    """Water stress reduction coefficient Ks [0-1]. FAO-56 Eq. 84.

    Ks = 1 while the root zone holds readily available water; beyond that
    point transpiration falls off linearly to zero at the wilting point.
    """
    if depletion_mm <= raw:
        return 1.0
    if taw <= raw:
        return 0.0
    ks = (taw - depletion_mm) / (taw - raw)
    return max(0.0, min(1.0, ks))


def yield_loss_from_water_deficit(
    ky: float, actual_et: float, potential_et: float
) -> float:
    """Relative yield loss [0-1] from an ET deficit. FAO-56 Eq. 90.

        (1 - Ya/Ym) = Ky * (1 - ETa/ETc)

    This is what converts "your soil is dry" into "you will lose about a
    fifth of your crop" -- the form of the statement a farmer can act on.
    """
    if potential_et <= 0:
        return 0.0
    deficit_ratio = 1.0 - (actual_et / potential_et)
    return max(0.0, min(1.0, ky * deficit_ratio))
