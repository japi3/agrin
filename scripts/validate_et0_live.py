"""
Live cross-validation of our FAO-56 implementation against Open-Meteo's.

Open-Meteo computes FAO-56 reference evapotranspiration independently, from
the same underlying meteorology, using its own code. Comparing the two on
live data at six sites spanning all five BRICS founding members is a far
stronger check than any fixture-based test: it exercises the real API
contract, real units, real edge cases, and catches drift in either
implementation.

Run:  python scripts/validate_et0_live.py

Interpretation: reference ET typically runs 3-6 mm/day, so a mean absolute
error below ~0.3 mm/day is agreement at the level of the input data's own
precision. Residual difference is expected and explainable -- Open-Meteo
integrates hourly and we work from daily aggregates, so wind and radiation
are averaged differently within the day.

This is a network test and is intentionally NOT part of the unit suite;
`pytest` must pass with no internet.
"""

import asyncio, sys, statistics
sys.path.insert(0, "packages/geo")
sys.path.insert(0, "packages/agronomy")
from geo.weather import fetch_forecast
from agronomy.fao56 import et0_from_daily_weather

SITES = {
 "Ludhiana, Punjab IN":      (30.90, 75.68),
 "Vidarbha, Maharashtra IN": (20.00, 77.00),
 "Sorriso, Mato Grosso BR":  (-12.36, -55.71),
 "Krasnodar krai RU":        (45.30, 39.20),
 "N China Plain CN":         (34.75, 113.95),
 "Free State ZA":            (-28.80, 26.50),
}

async def main():
    all_err = []
    print(f"{'site':28s} {'n':>3s} {'ours':>7s} {'openmeteo':>10s} {'MAE':>7s} {'max err':>8s}")
    print("-"*72)
    for name,(lat,lon) in SITES.items():
        s = await fetch_forecast(lat, lon, days_ahead=14, past_days=30)
        ours, theirs = [], []
        for d in s.days:
            if not d.is_usable_for_et0 or d.et0_openmeteo_mm is None: continue
            if d.wind_mean_ms is None or d.solar_radiation_mj is None: continue
            r = et0_from_daily_weather(
                t_max=d.t_max, t_min=d.t_min, latitude_deg=s.latitude,
                elevation_m=s.elevation_m, day_of_year=d.day_of_year,
                wind_ms=d.wind_mean_ms, wind_height_m=10.0,
                dewpoint_c=d.dewpoint_mean,
                solar_radiation_mj=d.solar_radiation_mj)
            ours.append(r.et0_mm_day); theirs.append(d.et0_openmeteo_mm)
        errs = [abs(a-b) for a,b in zip(ours,theirs)]
        all_err += errs
        print(f"{name:28s} {len(ours):3d} {statistics.mean(ours):7.2f} "
              f"{statistics.mean(theirs):10.2f} {statistics.mean(errs):7.3f} {max(errs):8.3f}")
    print("-"*72)
    print(f"overall MAE across {len(all_err)} station-days: {statistics.mean(all_err):.3f} mm/day")
    print(f"95th percentile abs error: {sorted(all_err)[int(len(all_err)*0.95)]:.3f} mm/day")
asyncio.run(main())
