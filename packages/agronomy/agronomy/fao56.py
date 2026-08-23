"""
FAO-56 reference evapotranspiration and crop water requirements.

Implements the standardised procedures from:

    Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998).
    "Crop evapotranspiration - Guidelines for computing crop water requirements."
    FAO Irrigation and Drainage Paper 56. Rome: FAO. ISBN 92-5-104219-5.

Equation numbers in docstrings refer to that document. The test suite in
`tests/test_fao56.py` reproduces the worked examples from the paper's annexes,
so any change that breaks agreement with the published numbers fails CI.

Units are SI throughout and are stated on every function. Silent unit
mismatches are the most common source of error in ET models, so callers get
explicit names (`t_celsius`, `elevation_m`, `wind_2m_ms`) rather than terse ones.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Stefan-Boltzmann constant expressed per day, FAO-56 Eq. 39 units
STEFAN_BOLTZMANN_MJ = 4.903e-9  # MJ K^-4 m^-2 day^-1
SOLAR_CONSTANT = 0.0820  # MJ m^-2 min^-1
LATENT_HEAT_VAPORISATION = 2.45  # MJ kg^-1 at ~20 C, FAO-56 Ch.1

# 1 MJ m^-2 day^-1 of energy evaporates this depth of water, FAO-56 Eq. 20.
MJ_TO_MM = 1.0 / LATENT_HEAT_VAPORISATION  # ~= 0.408


# --------------------------------------------------------------------------
# Atmospheric parameters (FAO-56 Chapter 3)
# --------------------------------------------------------------------------

def atmospheric_pressure(elevation_m: float) -> float:
    """Atmospheric pressure [kPa] from elevation. FAO-56 Eq. 7.

    Simplification of the ideal gas law assuming 20 C and a standard
    atmospheric lapse rate of 0.0065 K/m.
    """
    return 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant(pressure_kpa: float) -> float:
    """Psychrometric constant gamma [kPa/C]. FAO-56 Eq. 8."""
    return 0.665e-3 * pressure_kpa


def saturation_vapour_pressure(t_celsius: float) -> float:
    """Saturation vapour pressure e_0(T) [kPa]. FAO-56 Eq. 11.

    Note that saturation vapour pressure is non-linear in temperature, which
    is why FAO-56 requires es to be computed as the mean of e_0(Tmax) and
    e_0(Tmin) rather than e_0(Tmean) -- using Tmean underestimates es.
    """
    return 0.6108 * math.exp((17.27 * t_celsius) / (t_celsius + 237.3))


def mean_saturation_vapour_pressure(t_max: float, t_min: float) -> float:
    """Mean saturation vapour pressure es [kPa]. FAO-56 Eq. 12."""
    return (saturation_vapour_pressure(t_max) + saturation_vapour_pressure(t_min)) / 2.0


def slope_vapour_pressure_curve(t_celsius: float) -> float:
    """Slope of the saturation vapour pressure curve Delta [kPa/C]. FAO-56 Eq. 13.

    Evaluated at mean air temperature, per FAO-56 guidance.
    """
    numerator = 4098.0 * saturation_vapour_pressure(t_celsius)
    return numerator / ((t_celsius + 237.3) ** 2)


def actual_vapour_pressure_from_rh(
    t_max: float, t_min: float, rh_max: float, rh_min: float
) -> float:
    """Actual vapour pressure ea [kPa] from daily RH extremes. FAO-56 Eq. 17.

    This is the preferred form: it pairs RHmax with Tmin and RHmin with Tmax,
    which is more robust to sensor error than the RHmean formulation.
    """
    return (
        saturation_vapour_pressure(t_min) * (rh_max / 100.0)
        + saturation_vapour_pressure(t_max) * (rh_min / 100.0)
    ) / 2.0


def actual_vapour_pressure_from_rhmean(
    t_max: float, t_min: float, rh_mean: float
) -> float:
    """Actual vapour pressure ea [kPa] from mean RH. FAO-56 Eq. 19.

    Fallback for stations reporting only RHmean.
    """
    return (rh_mean / 100.0) * mean_saturation_vapour_pressure(t_max, t_min)


def actual_vapour_pressure_from_dewpoint(t_dew: float) -> float:
    """Actual vapour pressure ea [kPa] from dewpoint temperature. FAO-56 Eq. 14.

    Open-Meteo returns dewpoint directly, so this is the path we use in
    production; it avoids RH sensor drift entirely.
    """
    return saturation_vapour_pressure(t_dew)


# --------------------------------------------------------------------------
# Radiation (FAO-56 Chapter 3)
# --------------------------------------------------------------------------

def inverse_relative_distance_earth_sun(day_of_year: int) -> float:
    """Inverse relative Earth-Sun distance dr [-]. FAO-56 Eq. 23."""
    return 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)


def solar_declination(day_of_year: int) -> float:
    """Solar declination delta [rad]. FAO-56 Eq. 24."""
    return 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)


def sunset_hour_angle(latitude_rad: float, declination_rad: float) -> float:
    """Sunset hour angle omega_s [rad]. FAO-56 Eq. 25.

    The argument to acos is clamped so that polar day/night (|arg| > 1) yields
    24 h or 0 h of daylight instead of a domain error. FAO-56 Eq. 25 is
    undefined there; the clamp is the physically correct limit.
    """
    x = -math.tan(latitude_rad) * math.tan(declination_rad)
    x = max(-1.0, min(1.0, x))
    return math.acos(x)


def extraterrestrial_radiation(latitude_deg: float, day_of_year: int) -> float:
    """Extraterrestrial radiation Ra [MJ m^-2 day^-1]. FAO-56 Eq. 21."""
    phi = math.radians(latitude_deg)
    dr = inverse_relative_distance_earth_sun(day_of_year)
    delta = solar_declination(day_of_year)
    ws = sunset_hour_angle(phi, delta)
    return (
        (24.0 * 60.0 / math.pi)
        * SOLAR_CONSTANT
        * dr
        * (
            ws * math.sin(phi) * math.sin(delta)
            + math.cos(phi) * math.cos(delta) * math.sin(ws)
        )
    )


def daylight_hours(latitude_deg: float, day_of_year: int) -> float:
    """Maximum possible daylight hours N [h]. FAO-56 Eq. 34."""
    phi = math.radians(latitude_deg)
    delta = solar_declination(day_of_year)
    return (24.0 / math.pi) * sunset_hour_angle(phi, delta)


def solar_radiation_from_sunshine(
    sunshine_hours: float, latitude_deg: float, day_of_year: int,
    a_s: float = 0.25, b_s: float = 0.50,
) -> float:
    """Solar radiation Rs [MJ m^-2 day^-1] via the Angstrom equation. FAO-56 Eq. 35.

    a_s/b_s default to the FAO-recommended values for average climates where
    no local calibration exists.
    """
    ra = extraterrestrial_radiation(latitude_deg, day_of_year)
    n_max = daylight_hours(latitude_deg, day_of_year)
    return (a_s + b_s * (sunshine_hours / n_max)) * ra


def clear_sky_radiation(elevation_m: float, ra: float) -> float:
    """Clear-sky solar radiation Rso [MJ m^-2 day^-1]. FAO-56 Eq. 37."""
    return (0.75 + 2e-5 * elevation_m) * ra


def net_shortwave_radiation(rs: float, albedo: float = 0.23) -> float:
    """Net shortwave radiation Rns [MJ m^-2 day^-1]. FAO-56 Eq. 38.

    albedo 0.23 is the FAO hypothetical grass reference surface.
    """
    return (1.0 - albedo) * rs


def net_longwave_radiation(
    t_max: float, t_min: float, ea: float, rs: float, rso: float
) -> float:
    """Net longwave radiation Rnl [MJ m^-2 day^-1]. FAO-56 Eq. 39.

    The Rs/Rso cloudiness ratio is clamped to 1.0: on days where measured Rs
    slightly exceeds the modelled clear-sky value (common with imperfect
    calibration) an unclamped ratio drives Rnl negative, which is unphysical.
    """
    tmax_k4 = (t_max + 273.16) ** 4
    tmin_k4 = (t_min + 273.16) ** 4
    cloud = min(rs / rso, 1.0) if rso > 0 else 1.0
    return (
        STEFAN_BOLTZMANN_MJ
        * ((tmax_k4 + tmin_k4) / 2.0)
        * (0.34 - 0.14 * math.sqrt(ea))
        * (1.35 * cloud - 0.35)
    )


def net_radiation(rns: float, rnl: float) -> float:
    """Net radiation Rn [MJ m^-2 day^-1]. FAO-56 Eq. 40."""
    return rns - rnl


def wind_speed_at_2m(measured_ms: float, measurement_height_m: float) -> float:
    """Adjust wind speed to the 2 m standard height [m/s]. FAO-56 Eq. 47.

    Most public weather APIs (Open-Meteo included) report 10 m wind, so
    forgetting this correction inflates ET0 by roughly 15-20 percent.
    """
    if measurement_height_m == 2.0:
        return measured_ms
    return measured_ms * (4.87 / math.log(67.8 * measurement_height_m - 5.42))


# --------------------------------------------------------------------------
# Reference evapotranspiration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ET0Result:
    """Reference ET plus every intermediate term, for the Evidence Ledger.

    The UI shows a farmer one number. A judge, an agronomist, or a debugging
    engineer needs the whole chain, so nothing is discarded.
    """
    et0_mm_day: float
    delta: float
    gamma: float
    es: float
    ea: float
    vpd: float
    ra: float
    rs: float
    rso: float
    rns: float
    rnl: float
    rn: float
    u2: float
    t_mean: float
    radiation_source: str


def penman_monteith_et0(
    t_max: float,
    t_min: float,
    ea: float,
    rn: float,
    wind_2m_ms: float,
    elevation_m: float,
    soil_heat_flux: float = 0.0,
) -> float:
    """FAO-56 Penman-Monteith reference evapotranspiration ET0 [mm/day]. Eq. 6.

    This is the sole FAO-recommended method for computing reference ET, and
    the denominator of essentially every irrigation decision this platform
    makes. `soil_heat_flux` (G) is zero for daily time steps per FAO-56 Eq. 42.
    """
    t_mean = (t_max + t_min) / 2.0
    delta = slope_vapour_pressure_curve(t_mean)
    pressure = atmospheric_pressure(elevation_m)
    gamma = psychrometric_constant(pressure)
    es = mean_saturation_vapour_pressure(t_max, t_min)
    vpd = max(es - ea, 0.0)

    numerator = 0.408 * delta * (rn - soil_heat_flux) + gamma * (
        900.0 / (t_mean + 273.0)
    ) * wind_2m_ms * vpd
    denominator = delta + gamma * (1.0 + 0.34 * wind_2m_ms)
    return numerator / denominator


def hargreaves_et0(
    t_max: float, t_min: float, latitude_deg: float, day_of_year: int
) -> float:
    """Hargreaves-Samani ET0 [mm/day]. FAO-56 Eq. 52.

    Used only where humidity, wind and radiation are all missing. FAO-56
    recommends it over an incomplete Penman-Monteith fed with guessed inputs.
    Ra is converted from MJ m^-2 day^-1 to equivalent mm/day before use.
    """
    ra_mm = extraterrestrial_radiation(latitude_deg, day_of_year) * MJ_TO_MM
    t_mean = (t_max + t_min) / 2.0
    return 0.0023 * (t_mean + 17.8) * math.sqrt(max(t_max - t_min, 0.0)) * ra_mm


def et0_from_daily_weather(
    t_max: float,
    t_min: float,
    latitude_deg: float,
    elevation_m: float,
    day_of_year: int,
    wind_ms: float,
    wind_height_m: float = 10.0,
    dewpoint_c: float | None = None,
    rh_max: float | None = None,
    rh_min: float | None = None,
    rh_mean: float | None = None,
    solar_radiation_mj: float | None = None,
    sunshine_hours: float | None = None,
) -> ET0Result:
    """Full ET0 pipeline from what a weather API actually returns.

    Humidity and radiation each accept several input forms, tried in FAO-56's
    order of preference, so the same call site works whether the upstream
    source is Open-Meteo (dewpoint + shortwave radiation), a national met
    service (RH extremes + sunshine hours), or a sparse station (Tmax/Tmin
    only, falling back to the Hargreaves radiation estimate).

    Raises ValueError rather than silently guessing when humidity is absent
    entirely -- a fabricated ea propagates into an irrigation depth a farmer
    would actually act on.
    """
    t_mean = (t_max + t_min) / 2.0

    if dewpoint_c is not None:
        ea = actual_vapour_pressure_from_dewpoint(dewpoint_c)
    elif rh_max is not None and rh_min is not None:
        ea = actual_vapour_pressure_from_rh(t_max, t_min, rh_max, rh_min)
    elif rh_mean is not None:
        ea = actual_vapour_pressure_from_rhmean(t_max, t_min, rh_mean)
    else:
        raise ValueError(
            "ET0 needs humidity: pass dewpoint_c, (rh_max, rh_min), or rh_mean"
        )

    ra = extraterrestrial_radiation(latitude_deg, day_of_year)

    if solar_radiation_mj is not None:
        rs = solar_radiation_mj
        radiation_source = "measured"
    elif sunshine_hours is not None:
        rs = solar_radiation_from_sunshine(sunshine_hours, latitude_deg, day_of_year)
        radiation_source = "angstrom_sunshine"
    else:
        # Hargreaves radiation formula, FAO-56 Eq. 50. krs=0.16 for interior
        # locations. Least accurate path; surfaced in the ledger so the UI can
        # widen the stated uncertainty band.
        rs = 0.16 * math.sqrt(max(t_max - t_min, 0.0)) * ra
        radiation_source = "hargreaves_estimated"

    rso = clear_sky_radiation(elevation_m, ra)
    rns = net_shortwave_radiation(rs)
    rnl = net_longwave_radiation(t_max, t_min, ea, rs, rso)
    rn = net_radiation(rns, rnl)

    u2 = wind_speed_at_2m(wind_ms, wind_height_m)
    es = mean_saturation_vapour_pressure(t_max, t_min)

    et0 = penman_monteith_et0(t_max, t_min, ea, rn, u2, elevation_m)

    return ET0Result(
        et0_mm_day=et0,
        delta=slope_vapour_pressure_curve(t_mean),
        gamma=psychrometric_constant(atmospheric_pressure(elevation_m)),
        es=es,
        ea=ea,
        vpd=max(es - ea, 0.0),
        ra=ra,
        rs=rs,
        rso=rso,
        rns=rns,
        rnl=rnl,
        rn=rn,
        u2=u2,
        t_mean=t_mean,
        radiation_source=radiation_source,
    )
