"""
RothC-26.3 soil organic carbon turnover model.

Implements the Rothamsted Carbon Model as published in:

    Coleman, K. & Jenkinson, D.S. (1996). "RothC-26.3 - A Model for the
    turnover of carbon in soil." In: Evaluation of Soil Organic Matter Models,
    NATO ASI Series I vol. 38, Springer, pp. 237-246.
    Coleman, K. & Jenkinson, D.S. (2014). RothC - A Model for the Turnover of
    Carbon in Soil: Model Description and Users Guide. Rothamsted Research.

RothC is the model underpinning national soil carbon inventories and is
accepted under the IPCC 2019 Refinement as a Tier 3 method. That matters here
for a specific reason: regenerative practice advice is worth little to a
farmer unless the resulting carbon gain is quantified with a method a carbon
registry will accept. An LLM asserting "cover cropping builds soil carbon" is
not fundable. A RothC projection with stated inputs is.

The model runs on a monthly time step over five pools:

    DPM  decomposable plant material     k = 10.0 /yr
    RPM  resistant plant material        k =  0.3 /yr
    BIO  microbial biomass               k =  0.66 /yr
    HUM  humified organic matter         k =  0.02 /yr
    IOM  inert organic matter            does not decompose

All pool sizes are in t C/ha.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

# Annual decomposition rate constants, RothC-26.3 Table 1 [per year]
K_DPM = 10.0
K_RPM = 0.3
K_BIO = 0.66
K_HUM = 0.02

# Of the material that does not leave as CO2, this fraction becomes biomass;
# the remainder becomes humus. Coleman & Jenkinson (2014), section 2.2.
BIO_FRACTION_OF_RETAINED = 0.46

# DPM:RPM ratio of incoming plant material, by land cover.
# Coleman & Jenkinson (2014), Table 2.
DPM_RPM_RATIO = {
    "agricultural_crop": 1.44,
    "improved_grassland": 1.44,
    "unimproved_grassland": 0.67,
    "deciduous_woodland": 0.25,
    "tropical_woodland": 0.25,
}


@dataclass(frozen=True)
class CarbonPools:
    """Soil organic carbon partitioned into the five RothC pools [t C/ha]."""
    dpm: float
    rpm: float
    bio: float
    hum: float
    iom: float

    @property
    def total(self) -> float:
        return self.dpm + self.rpm + self.bio + self.hum + self.iom

    @property
    def active(self) -> float:
        """Carbon that can actually change. IOM is inert on human timescales."""
        return self.dpm + self.rpm + self.bio + self.hum


def inert_organic_matter(total_soc: float) -> float:
    """Inert organic matter [t C/ha] from total SOC. Falloon et al. (1998).

        IOM = 0.049 * SOC^1.139

    IOM is radiocarbon-dead charcoal and highly condensed material. It is a
    substantial share of SOC in the burned-residue systems common across
    northern India and the Brazilian cerrado, and treating it as active would
    make the model predict carbon losses that cannot physically occur.
    """
    if total_soc <= 0:
        return 0.0
    return 0.049 * (total_soc ** 1.139)


def rate_modifying_factor_temperature(t_celsius: float) -> float:
    """Temperature rate modifier `a`. Coleman & Jenkinson (2014) Eq. 1.

        a = 47.91 / (1 + exp(106.06 / (T + 18.27)))

    Undefined at T = -18.27 C and effectively zero below it; decomposition is
    clamped to zero for frozen soil, which is the correct behaviour for the
    Russian and northern Chinese winters in scope here.
    """
    if t_celsius <= -18.27:
        return 0.0
    return 47.91 / (1.0 + math.exp(106.06 / (t_celsius + 18.27)))


def maximum_tsmd(clay_percent: float, depth_cm: float = 23.0, vegetated: bool = True) -> float:
    """Maximum topsoil moisture deficit [mm], a negative quantity.

    Coleman & Jenkinson (2014) Eq. 2. Bare soil dries further than covered
    soil, hence the 1.8 divisor -- which is precisely the mechanism by which
    keeping the ground covered slows decomposition and builds carbon.
    """
    max_deficit = -(20.0 + 1.3 * clay_percent - 0.01 * clay_percent ** 2) * (
        depth_cm / 23.0
    )
    if not vegetated:
        max_deficit = max_deficit / 1.8
    return max_deficit


def rate_modifying_factor_moisture(
    accumulated_tsmd: float, max_tsmd: float
) -> float:
    """Moisture rate modifier `b`. Coleman & Jenkinson (2014) Eq. 3.

    b = 1.0 while the soil is wetter than 0.444 * maxTSMD, then falls
    linearly to a floor of 0.2 in fully dry soil.
    """
    threshold = 0.444 * max_tsmd
    if accumulated_tsmd > threshold:
        return 1.0
    if max_tsmd >= threshold:
        return 0.2
    return 0.2 + (1.0 - 0.2) * (max_tsmd - accumulated_tsmd) / (max_tsmd - threshold)


def rate_modifying_factor_cover(vegetated: bool) -> float:
    """Soil cover rate modifier `c`. Coleman & Jenkinson (2014) section 2.4.

    Decomposition is slower under a growing crop (0.6) than on bare soil
    (1.0). Combined with the moisture effect, this is the quantitative
    argument for cover cropping.
    """
    return 0.6 if vegetated else 1.0


def co2_to_biohum_ratio(clay_percent: float) -> float:
    """The CO2 : (BIO + HUM) partition ratio x. Coleman & Jenkinson (2014) Eq. 4.

        x = 1.67 * (1.85 + 1.60 * exp(-0.0786 * clay%))

    Clay protects organic matter physically, so clay-rich soils retain a
    larger share of decomposed carbon rather than respiring it. This is why
    the same practice change yields a different carbon outcome on a Punjab
    loam and a Vertisol in Madhya Pradesh -- and why a generic answer is
    inadequate.
    """
    return 1.67 * (1.85 + 1.60 * math.exp(-0.0786 * clay_percent))


@dataclass(frozen=True)
class MonthlyInput:
    """One month of forcing data for RothC."""
    mean_temp_c: float
    rainfall_mm: float
    open_pan_evaporation_mm: float
    carbon_input_t_ha: float
    is_vegetated: bool
    farmyard_manure_t_ha: float = 0.0


def step_month(
    pools: CarbonPools,
    forcing: MonthlyInput,
    clay_percent: float,
    accumulated_tsmd: float,
    dpm_rpm_ratio: float = 1.44,
    depth_cm: float = 23.0,
) -> tuple[CarbonPools, float]:
    """Advance the pools by one month.

    Returns the new pools and the updated accumulated TSMD.

    Farmyard manure is partitioned 49/49/2 into DPM/RPM/HUM rather than by the
    DPM:RPM ratio used for fresh residues, per Coleman & Jenkinson (2014)
    section 2.6 -- manure is already partly humified, and treating it as
    fresh residue would overstate its short-term decomposition.
    """
    # --- Rate modifiers -------------------------------------------------
    a = rate_modifying_factor_temperature(forcing.mean_temp_c)

    max_def = maximum_tsmd(clay_percent, depth_cm, forcing.is_vegetated)
    # Open pan evaporation is converted to potential ET at 0.75, per the
    # RothC user guide.
    net_moisture = forcing.rainfall_mm - 0.75 * forcing.open_pan_evaporation_mm
    tsmd = accumulated_tsmd + net_moisture
    # Deficit cannot exceed the maximum, and the soil cannot hold more than
    # field capacity (TSMD of zero).
    tsmd = max(max_def, min(0.0, tsmd))

    b = rate_modifying_factor_moisture(tsmd, max_def)
    c = rate_modifying_factor_cover(forcing.is_vegetated)

    combined_rate = a * b * c

    # --- Decomposition of each active pool ------------------------------
    def decayed(amount: float, k: float) -> float:
        return amount * (1.0 - math.exp(-combined_rate * k / 12.0))

    d_dpm = decayed(pools.dpm, K_DPM)
    d_rpm = decayed(pools.rpm, K_RPM)
    d_bio = decayed(pools.bio, K_BIO)
    d_hum = decayed(pools.hum, K_HUM)
    total_decomposed = d_dpm + d_rpm + d_bio + d_hum

    # --- Partition the decomposed carbon --------------------------------
    x = co2_to_biohum_ratio(clay_percent)
    retained_fraction = 1.0 / (x + 1.0)
    to_bio = total_decomposed * retained_fraction * BIO_FRACTION_OF_RETAINED
    to_hum = total_decomposed * retained_fraction * (1.0 - BIO_FRACTION_OF_RETAINED)

    # --- Fresh inputs ----------------------------------------------------
    input_dpm = forcing.carbon_input_t_ha * (dpm_rpm_ratio / (1.0 + dpm_rpm_ratio))
    input_rpm = forcing.carbon_input_t_ha * (1.0 / (1.0 + dpm_rpm_ratio))

    fym = forcing.farmyard_manure_t_ha
    input_dpm += 0.49 * fym
    input_rpm += 0.49 * fym
    fym_hum = 0.02 * fym

    new_pools = CarbonPools(
        dpm=pools.dpm - d_dpm + input_dpm,
        rpm=pools.rpm - d_rpm + input_rpm,
        bio=pools.bio - d_bio + to_bio,
        hum=pools.hum - d_hum + to_hum + fym_hum,
        iom=pools.iom,
    )
    return new_pools, tsmd


def initialise_pools(
    total_soc_t_ha: float, clay_percent: float, land_use: str = "agricultural_crop"
) -> CarbonPools:
    """Split a measured total SOC into RothC pools at steady state.

    A single SOC measurement (which is all SoilGrids gives us) does not
    determine the pool split, so we distribute the active carbon in the
    proportions RothC converges to under long-term arable management.
    These are the equilibrium shares reported in the RothC user guide for
    temperate arable soils; they are an assumption, and the API surfaces
    them as such rather than presenting the result as measured.
    """
    iom = inert_organic_matter(total_soc_t_ha)
    active = max(0.0, total_soc_t_ha - iom)
    return CarbonPools(
        dpm=active * 0.015,
        rpm=active * 0.180,
        bio=active * 0.025,
        hum=active * 0.780,
        iom=iom,
    )


@dataclass
class CarbonProjection:
    """Result of a multi-year RothC run."""
    years: list[int]
    soc_by_year: list[float]
    initial_soc: float
    final_soc: float
    clay_percent: float
    annual_input_t_ha: float

    @property
    def delta_soc(self) -> float:
        return self.final_soc - self.initial_soc

    @property
    def co2e_sequestered_t_ha(self) -> float:
        """Change in SOC expressed as CO2 equivalent [t CO2e/ha].

        Multiplied by 44/12, the molar mass ratio of CO2 to C. This is the
        number a carbon registry transacts in.
        """
        return self.delta_soc * (44.0 / 12.0)


def project(
    initial_soc_t_ha: float,
    clay_percent: float,
    monthly_forcing: list[MonthlyInput],
    years: int,
    land_use: str = "agricultural_crop",
    depth_cm: float = 23.0,
) -> CarbonProjection:
    """Project SOC forward, repeating the 12-month forcing pattern each year.

    Args:
        monthly_forcing: exactly 12 entries, January to December.
        years: number of years to simulate.

    RothC responds slowly by design -- HUM turns over at 2% per year -- so
    honest projections show small annual changes. Any tool claiming a farmer
    will double soil carbon in three seasons is not using a validated model.
    """
    if len(monthly_forcing) != 12:
        raise ValueError("monthly_forcing must contain exactly 12 months")

    pools = initialise_pools(initial_soc_t_ha, clay_percent, land_use)
    ratio = DPM_RPM_RATIO.get(land_use, 1.44)
    tsmd = 0.0

    year_list: list[int] = []
    soc_list: list[float] = []

    for year in range(1, years + 1):
        for month in monthly_forcing:
            pools, tsmd = step_month(
                pools, month, clay_percent, tsmd,
                dpm_rpm_ratio=ratio, depth_cm=depth_cm,
            )
        year_list.append(year)
        soc_list.append(pools.total)

    annual_input = sum(m.carbon_input_t_ha + m.farmyard_manure_t_ha for m in monthly_forcing)

    return CarbonProjection(
        years=year_list,
        soc_by_year=soc_list,
        initial_soc=initial_soc_t_ha,
        final_soc=pools.total,
        clay_percent=clay_percent,
        annual_input_t_ha=annual_input,
    )


def soc_percent_to_t_ha(
    soc_percent: float, bulk_density_g_cm3: float, depth_cm: float = 30.0
) -> float:
    """Convert SOC concentration [%] to a stock [t C/ha].

        stock = concentration * bulk density * depth * 100

    SoilGrids reports organic carbon as g/kg and bulk density as cg/cm3, so
    this conversion sits directly between the data source and the model. It
    is a frequent source of order-of-magnitude errors, hence its own test.
    """
    return (soc_percent / 100.0) * bulk_density_g_cm3 * depth_cm * 100.0
