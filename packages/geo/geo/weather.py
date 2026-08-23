"""
Open-Meteo weather client: forecast, historical reanalysis, and agro-variables.

Open-Meteo (https://open-meteo.com) aggregates national weather services and
ECMWF products behind one free, key-less, globally available API under
CC BY 4.0. That combination is unusual and is why it anchors this platform:
a farmer in Bihar, Mato Grosso or Limpopo hits the same endpoint with no
per-country contract, no key provisioning, and no rate ceiling that a public
extension service would have to budget for.

Two endpoints are used:

  - Forecast API: up to 16 days ahead, from the highest-resolution model
    available at the location (ICON-D2 at 2 km over Europe, IFS/GFS at 9-25 km
    elsewhere).
  - Archive API: ERA5 and ERA5-Land reanalysis back to 1940, which is what
    makes longitudinal "compared to a normal year" statements possible.

Open-Meteo also computes FAO-56 reference evapotranspiration itself. We fetch
it and compare it against our own implementation rather than simply consuming
it -- an independent agreement check on the most consequential number in the
system, run against live data on every request. Divergence beyond tolerance
is surfaced rather than hidden.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from .cache import cache_key, get_cache

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Daily variables needed to drive FAO-56 and the water balance.
DAILY_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "dew_point_2m_mean",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "precipitation_sum",
    "rain_sum",
    "shortwave_radiation_sum",
    "wind_speed_10m_max",
    "wind_speed_10m_mean",
    "et0_fao_evapotranspiration",
]


# Hourly variables needed by the disease infection models. Leaf wetness is
# inferred from hourly relative humidity, so daily aggregates are not enough:
# a day averaging 70 percent RH may have spent twelve night hours above 90,
# which is precisely the window a fungal spore needs.
HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "precipitation",
]


@dataclass
class WeatherDay:
    """One day of daily-aggregated weather at a point."""
    day: date
    t_max: float | None
    t_min: float | None
    t_mean: float | None
    dewpoint_mean: float | None
    rh_max: float | None
    rh_min: float | None
    precipitation_mm: float | None
    rain_mm: float | None
    solar_radiation_mj: float | None
    wind_max_ms: float | None
    wind_mean_ms: float | None
    et0_openmeteo_mm: float | None
    # 24 hourly relative humidity values, when hourly data was requested.
    hourly_rh: list[float] = field(default_factory=list)
    hourly_temp: list[float] = field(default_factory=list)

    @property
    def day_of_year(self) -> int:
        return self.day.timetuple().tm_yday

    @property
    def is_usable_for_et0(self) -> bool:
        """Whether this day has the minimum inputs for Penman-Monteith."""
        return (
            self.t_max is not None
            and self.t_min is not None
            and (self.dewpoint_mean is not None
                 or (self.rh_max is not None and self.rh_min is not None))
        )


@dataclass
class WeatherSeries:
    """A time series of daily weather at one point, with provenance."""
    latitude: float
    longitude: float
    elevation_m: float
    timezone: str
    days: list[WeatherDay] = field(default_factory=list)
    source: str = "Open-Meteo"
    source_url: str = "https://open-meteo.com"
    licence: str = "CC BY 4.0"
    endpoint: str = "forecast"
    model_note: str = ""

    def evidence(self) -> dict[str, Any]:
        """Provenance record for the Evidence Ledger."""
        return {
            "source": self.source,
            "source_url": self.source_url,
            "licence": self.licence,
            "endpoint": self.endpoint,
            "queried_point": {"lat": self.latitude, "lon": self.longitude},
            "elevation_m": self.elevation_m,
            "timezone": self.timezone,
            "days_returned": len(self.days),
            "date_range": (
                [self.days[0].day.isoformat(), self.days[-1].day.isoformat()]
                if self.days else None
            ),
            "citation": (
                "Zippenfenig, P. (2023). Open-Meteo.com Weather API. "
                "https://doi.org/10.5281/zenodo.7970649"
            ),
        }

    def total_rain_mm(self) -> float:
        return sum(d.precipitation_mm or 0.0 for d in self.days)


class WeatherError(RuntimeError):
    pass


def _parse(payload: dict, endpoint: str) -> WeatherSeries:
    """Convert an Open-Meteo daily response into WeatherDay records.

    Open-Meteo returns parallel arrays keyed by variable name, with nulls for
    gaps. Zipping them by index is only safe because the API guarantees equal
    length and a shared `time` axis; we assert that rather than assume it,
    because a silent off-by-one here would misalign rainfall with the day it
    fell on and corrupt every irrigation decision downstream.
    """
    daily = payload.get("daily") or {}
    times = daily.get("time") or []

    for name, values in daily.items():
        if len(values) != len(times):
            raise WeatherError(
                f"Open-Meteo returned {len(values)} values for '{name}' but "
                f"{len(times)} timestamps; refusing to zip misaligned series"
            )

    def col(name: str) -> list:
        return daily.get(name) or [None] * len(times)

    cols = {name: col(name) for name in DAILY_VARIABLES}

    days: list[WeatherDay] = []
    for i, t in enumerate(times):
        days.append(
            WeatherDay(
                day=date.fromisoformat(t),
                t_max=cols["temperature_2m_max"][i],
                t_min=cols["temperature_2m_min"][i],
                t_mean=cols["temperature_2m_mean"][i],
                dewpoint_mean=cols["dew_point_2m_mean"][i],
                rh_max=cols["relative_humidity_2m_max"][i],
                rh_min=cols["relative_humidity_2m_min"][i],
                precipitation_mm=cols["precipitation_sum"][i],
                rain_mm=cols["rain_sum"][i],
                solar_radiation_mj=cols["shortwave_radiation_sum"][i],
                wind_max_ms=cols["wind_speed_10m_max"][i],
                wind_mean_ms=cols["wind_speed_10m_mean"][i],
                et0_openmeteo_mm=cols["et0_fao_evapotranspiration"][i],
            )
        )

    # Bucket hourly values onto their day. Open-Meteo returns hourly
    # timestamps as ISO strings in the requested timezone, so the date prefix
    # is a safe key.
    hourly = payload.get("hourly") or {}
    hourly_times = hourly.get("time") or []
    if hourly_times:
        rh_series = hourly.get("relative_humidity_2m") or []
        t_series = hourly.get("temperature_2m") or []
        by_day: dict[str, dict[str, list]] = {}
        for i, stamp in enumerate(hourly_times):
            day_key = stamp[:10]
            bucket = by_day.setdefault(day_key, {"rh": [], "t": []})
            if i < len(rh_series):
                bucket["rh"].append(rh_series[i])
            if i < len(t_series):
                bucket["t"].append(t_series[i])
        for d in days:
            bucket = by_day.get(d.day.isoformat())
            if bucket:
                d.hourly_rh = bucket["rh"]
                d.hourly_temp = bucket["t"]

    return WeatherSeries(
        latitude=payload.get("latitude", 0.0),
        longitude=payload.get("longitude", 0.0),
        elevation_m=payload.get("elevation", 0.0),
        timezone=payload.get("timezone", "UTC"),
        days=days,
        endpoint=endpoint,
    )


async def _request(
    url: str, params: dict, namespace: str, client: httpx.AsyncClient | None,
    timeout: float,
) -> dict:
    """Issue a cached GET against Open-Meteo."""
    cache = get_cache()
    key = cache_key(url=url, **params)
    cached = cache.get(namespace, key)
    if cached is not None:
        return cached

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.get(url, params=params)
        if response.status_code != 200:
            raise WeatherError(
                f"Open-Meteo returned {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
    except httpx.HTTPError as exc:
        raise WeatherError(f"Open-Meteo request failed: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    cache.set(namespace, key, payload)
    return payload


async def fetch_forecast(
    latitude: float,
    longitude: float,
    days_ahead: int = 14,
    past_days: int = 30,
    client: httpx.AsyncClient | None = None,
    timeout: float = 20.0,
    include_hourly: bool = False,
) -> WeatherSeries:
    """Fetch the forecast, optionally with recent observed days prepended.

    `past_days` is what lets a single call serve the irrigation scheduler:
    the balance needs observed weather to establish today's soil depletion
    and forecast weather to project forward. Open-Meteo serves both from one
    endpoint with a consistent model chain, which avoids the discontinuity
    you get from stitching an archive series onto a forecast series.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_VARIABLES),
        "forecast_days": min(days_ahead, 16),
        "past_days": min(past_days, 92),
        "timezone": "auto",
        "wind_speed_unit": "ms",
    }
    # Hourly data roughly quadruples the response size, so it is opt-in:
    # only the disease models need it, and the irrigation path does not.
    if include_hourly:
        params["hourly"] = ",".join(HOURLY_VARIABLES)

    payload = await _request(
        FORECAST_URL, params, "weather_forecast", client, timeout
    )
    series = _parse(payload, "forecast")
    series.model_note = (
        f"{min(past_days, 92)} observed days + "
        f"{min(days_ahead, 16)} forecast days"
    )
    return series


async def fetch_archive(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    client: httpx.AsyncClient | None = None,
    timeout: float = 40.0,
) -> WeatherSeries:
    """Fetch historical daily weather from ERA5 reanalysis.

    ERA5 lags real time by about five days, so requests for the recent past
    are clamped; asking for yesterday returns an empty series otherwise, which
    is a confusing failure mode to debug from a chat transcript.
    """
    latest_available = date.today() - timedelta(days=6)
    if end > latest_available:
        end = latest_available
    if start > end:
        raise WeatherError(
            f"ERA5 reanalysis lags by ~5 days; no archive data exists for "
            f"the requested window (latest available: {latest_available})"
        )

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "auto",
        "wind_speed_unit": "ms",
    }
    payload = await _request(ARCHIVE_URL, params, "weather_archive", client, timeout)
    series = _parse(payload, "archive")
    series.model_note = "ERA5 / ERA5-Land reanalysis"
    return series


async def fetch_climate_normals(
    latitude: float,
    longitude: float,
    years: int = 20,
    client: httpx.AsyncClient | None = None,
) -> dict[int, dict[str, float]]:
    """Monthly climate normals from the last `years` complete years of ERA5.

    Used for two things: the RothC forcing pattern, which needs a
    representative year rather than a specific one, and the "is this season
    unusual?" comparisons that make longitudinal advice meaningful. A farmer
    is told the monsoon is late relative to *their* location's own history,
    not relative to a national average.
    """
    end = date(date.today().year - 1, 12, 31)
    start = date(end.year - years + 1, 1, 1)
    series = await fetch_archive(latitude, longitude, start, end, client=client)

    buckets: dict[int, dict[str, list[float]]] = {
        m: {"t": [], "rain": [], "et0": []} for m in range(1, 13)
    }
    for d in series.days:
        b = buckets[d.day.month]
        if d.t_mean is not None:
            b["t"].append(d.t_mean)
        if d.precipitation_mm is not None:
            b["rain"].append(d.precipitation_mm)
        if d.et0_openmeteo_mm is not None:
            b["et0"].append(d.et0_openmeteo_mm)

    normals: dict[int, dict[str, float]] = {}
    n_years = max(years, 1)
    for month, b in buckets.items():
        normals[month] = {
            "mean_temp_c": sum(b["t"]) / len(b["t"]) if b["t"] else 0.0,
            # Rain and ET0 are summed per month then averaged across years.
            "total_rain_mm": sum(b["rain"]) / n_years if b["rain"] else 0.0,
            "total_et0_mm": sum(b["et0"]) / n_years if b["et0"] else 0.0,
            "observations": len(b["t"]),
        }
    return normals
