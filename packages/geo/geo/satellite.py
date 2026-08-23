"""
Sentinel-2 vegetation indices for a field, with pluggable providers.

Providers
---------
**Earth Engine** (preferred). Computation happens on Google's servers, so a
season of NDVI for a polygon costs one request and no pixel transfer. This is
the right production path and the one the platform targets, but it requires
`earthengine authenticate` plus a registered Cloud project -- an interactive
OAuth step that cannot be automated.

**Planetary Computer STAC** (fallback, no credentials). Reads Cloud-Optimized
GeoTIFF windows directly over HTTP. Slower, because pixels cross the network,
but it needs no account at all, so the platform is never dead in the water
while credentials are being arranged.

Both return an identical `NDVISeries`, so nothing downstream knows or cares
which was used -- except the Evidence Ledger, which records it.

What is actually computed
-------------------------
NDVI = (NIR - Red) / (NIR + Red), from Sentinel-2 bands B08 and B04 at 10 m.

Two details that are easy to get wrong and that matter:

1. **Cloud masking.** Sentinel-2 L2A ships a Scene Classification Layer
   (SCL) marking cloud, shadow, snow and water per pixel. Skipping it means
   a cloud over the field reads as a sudden NDVI collapse -- indistinguishable
   from crop failure, and far more alarming.

2. **SCL is 20 m, the bands are 10 m.** The arrays therefore have different
   shapes and cannot be masked element-wise without resampling. Ignoring this
   either crashes or, worse, silently misaligns the mask with the pixels it
   is supposed to be masking.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from .cache import cache_key, get_cache

warnings.filterwarnings("ignore", category=RuntimeWarning)

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Sentinel-2 L2A radiometric scaling.
#
# From ESA processing baseline 04.00 (25 January 2022) onward, L2A products
# carry a BOA_ADD_OFFSET of -1000 which must be applied before the digital
# numbers mean reflectance:
#
#     reflectance = (DN + BOA_ADD_OFFSET) / QUANTIFICATION_VALUE
#
# This is easy to miss and it does NOT cancel out of NDVI. The offset appears
# in both bands, so it cancels in the numerator (NIR - Red) but survives in
# the denominator (NIR + Red), which is therefore inflated by twice the
# offset. The result is a systematic *depression* of NDVI: a Punjab wheat
# field at full canopy in February reads 0.49 uncorrected against 0.71
# corrected.
#
# Left unfixed this makes every healthy crop on the platform look stressed --
# a silent, uniform, entirely plausible-looking error, which is the worst
# kind. Verified against scene S2C_MSIL2A_20260225T053811 over Moga, Punjab.
BOA_ADD_OFFSET = -1000.0
QUANTIFICATION_VALUE = 10000.0
BASELINE_WITH_OFFSET = 4.00

# Sentinel-2 SCL classes to exclude. ESA S2 L2A Product Definition, Table 3.
SCL_INVALID = {
    0,   # no data
    1,   # saturated or defective
    3,   # cloud shadow
    8,   # cloud, medium probability
    9,   # cloud, high probability
    10,  # thin cirrus
    11,  # snow or ice
}


@dataclass
class NDVIObservation:
    """One cloud-screened satellite pass over the field."""
    day: date
    ndvi_mean: float
    ndvi_p10: float
    ndvi_p90: float
    ndvi_std: float
    valid_fraction: float
    scene_cloud_percent: float
    scene_id: str

    @property
    def uniformity(self) -> float:
        """1 minus the coefficient of variation, clipped to [0, 1].

        Within-field uniformity is often more actionable to a farmer than the
        mean: a uniformly moderate crop is a fertility or water ceiling, while
        a patchy one points at a specific, findable cause -- a blocked
        channel, a salinity patch, a pest focus they can walk to.
        """
        if self.ndvi_mean <= 0:
            return 0.0
        cv = self.ndvi_std / self.ndvi_mean
        return max(0.0, min(1.0, 1.0 - cv))


@dataclass
class NDVISeries:
    latitude: float
    longitude: float
    observations: list[NDVIObservation] = field(default_factory=list)
    provider: Literal["earth_engine", "planetary_computer"] = "planetary_computer"
    buffer_m: float = 100.0

    @property
    def latest(self) -> NDVIObservation | None:
        return self.observations[-1] if self.observations else None

    def trend(self, days: int = 30) -> float | None:
        """Change in NDVI over the last `days`, per day.

        Direction matters more than magnitude here: a falling NDVI during a
        stage when the canopy should still be expanding is the earliest
        remote signal of trouble a farmer can act on.
        """
        if len(self.observations) < 2:
            return None
        cutoff = self.observations[-1].day - timedelta(days=days)
        window = [o for o in self.observations if o.day >= cutoff]
        if len(window) < 2:
            window = self.observations[-2:]
        span = (window[-1].day - window[0].day).days
        if span <= 0:
            return None
        return (window[-1].ndvi_mean - window[0].ndvi_mean) / span

    def evidence(self) -> dict[str, Any]:
        provider_name = (
            "Google Earth Engine (Sentinel-2 L2A)"
            if self.provider == "earth_engine"
            else "Microsoft Planetary Computer STAC (Sentinel-2 L2A)"
        )
        return {
            "source": provider_name,
            "mission": "Copernicus Sentinel-2 (ESA), 10 m, ~5 day revisit",
            "licence": "Copernicus open data",
            "index": "NDVI = (B08 - B04) / (B08 + B04)",
            "cloud_masking": "Sentinel-2 L2A Scene Classification Layer (SCL)",
            "observations": len(self.observations),
            "date_range": (
                [self.observations[0].day.isoformat(),
                 self.observations[-1].day.isoformat()]
                if self.observations else None
            ),
            "field_buffer_m": self.buffer_m,
            "note": (
                "Each value is the mean over a "
                f"{int(self.buffer_m * 2)} m box centred on the field point, "
                "after removing cloud, shadow and snow pixels."
            ),
        }


class SatelliteError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Planetary Computer provider
# --------------------------------------------------------------------------

def _fetch_stac_sync(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    buffer_m: float,
    max_cloud: float,
    max_scenes: int,
) -> NDVISeries:
    """Blocking STAC + COG read. Run in a thread by the async wrapper.

    rasterio and pystac-client are synchronous and GDAL holds the GIL during
    HTTP reads, so this is offloaded rather than blocking the event loop --
    otherwise one farmer's satellite query stalls every other request on the
    server.
    """
    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    # Convert the metre buffer to degrees. Longitude degrees shrink with
    # latitude, so the box stays square on the ground rather than becoming a
    # rectangle that is far too wide in Punjab and too narrow near the equator.
    d_lat = buffer_m / 111_320.0
    import math
    d_lon = buffer_m / (111_320.0 * max(0.1, math.cos(math.radians(latitude))))
    bbox = [longitude - d_lon, latitude - d_lat, longitude + d_lon, latitude + d_lat]

    catalog = Client.open(STAC_URL, modifier=pc.sign_inplace)
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )
    items = sorted(search.items(), key=lambda i: i.datetime)
    if not items:
        return NDVISeries(latitude, longitude, [], "planetary_computer", buffer_m)

    # Subsample evenly across the requested window rather than keeping the
    # tail.
    #
    # Taking the most recent N scenes seems reasonable and is wrong for the
    # calibration path: it samples only recent months, so a year-long request
    # over a rabi-kharif rotation misses both the winter canopy peak and the
    # pre-monsoon bare-soil trough -- exactly the two extremes the per-field
    # NDVI scaling is calibrated against. At Moga that produced endpoints of
    # 0.28 and 0.68 in place of the true 0.13 and 0.80.
    #
    # Even spacing keeps the seasonal cycle intact at a fraction of the cost;
    # the most recent scene is always retained, since "how is my crop right
    # now" depends on it.
    if len(items) > max_scenes:
        step = len(items) / max_scenes
        picked = [items[int(i * step)] for i in range(max_scenes)]
        if picked[-1] is not items[-1]:
            picked[-1] = items[-1]
        items = picked

    observations: list[NDVIObservation] = []
    for item in items:
        # Scenes processed before baseline 04.00 carry no offset. Applying
        # one to them would break older imagery in the opposite direction, so
        # the baseline is read per scene rather than assumed.
        try:
            baseline_raw = item.properties.get("s2:processing_baseline")
            baseline = float(baseline_raw) if baseline_raw else 0.0
        except (TypeError, ValueError):
            baseline = 0.0
        offset = BOA_ADD_OFFSET if baseline >= BASELINE_WITH_OFFSET else 0.0

        try:
            def read(asset: str, out_shape=None):
                with rasterio.open(item.assets[asset].href) as src:
                    b = transform_bounds("EPSG:4326", src.crs, *bbox)
                    window = from_bounds(*b, transform=src.transform)
                    kwargs = {"window": window, "boundless": True, "fill_value": 0}
                    if out_shape is not None:
                        kwargs["out_shape"] = out_shape
                        kwargs["resampling"] = Resampling.nearest
                    return src.read(1, **kwargs).astype("float32")

            red = read("B04")
            nir = read("B08")
            if red.size == 0 or red.shape != nir.shape:
                continue

            # Convert digital numbers to surface reflectance before the index.
            red = (red + offset) / QUANTIFICATION_VALUE
            nir = (nir + offset) / QUANTIFICATION_VALUE

            # SCL is 20 m against 10 m bands, so it is resampled to the band
            # grid with nearest-neighbour -- class labels must not be averaged
            # into meaningless intermediate values.
            scl = read("SCL", out_shape=red.shape)

            valid = ~np.isin(scl.astype("int16"), list(SCL_INVALID))
            # Reflectance can go slightly negative over dark water after the
            # offset; those pixels are not usable vegetation signal.
            valid &= (nir + red) > 0.01

            valid_fraction = float(valid.sum()) / float(valid.size) if valid.size else 0.0
            # Below half usable pixels the mean says more about the cloud
            # edge than the crop.
            if valid_fraction < 0.5:
                continue

            ndvi = np.where(valid, (nir - red) / (nir + red + 1e-6), np.nan)
            finite = ndvi[np.isfinite(ndvi)]
            if finite.size < 4:
                continue

            observations.append(
                NDVIObservation(
                    day=item.datetime.date(),
                    ndvi_mean=float(np.mean(finite)),
                    ndvi_p10=float(np.percentile(finite, 10)),
                    ndvi_p90=float(np.percentile(finite, 90)),
                    ndvi_std=float(np.std(finite)),
                    valid_fraction=valid_fraction,
                    scene_cloud_percent=float(
                        item.properties.get("eo:cloud_cover", 0.0)
                    ),
                    scene_id=item.id,
                )
            )
        except Exception:
            # One unreadable scene must not lose the whole series.
            continue

    return NDVISeries(
        latitude, longitude, observations, "planetary_computer", buffer_m
    )


# --------------------------------------------------------------------------
# Earth Engine provider
# --------------------------------------------------------------------------

def _fetch_earth_engine_sync(
    latitude: float, longitude: float, start: date, end: date,
    buffer_m: float, max_cloud: float,
) -> NDVISeries:
    """Blocking Earth Engine reduction.

    Computation runs server-side: the whole series is reduced on Google's
    infrastructure and only the statistics come back, which is why this is
    the preferred provider once credentials exist.
    """
    import ee

    point = ee.Geometry.Point([longitude, latitude])
    region = point.buffer(buffer_m).bounds()

    # S2_SR_HARMONIZED is used rather than S2_SR precisely because it
    # back-corrects the post-baseline-04.00 radiometric offset, so the
    # Earth Engine path needs no equivalent of the STAC offset handling.
    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(start.isoformat(), end.isoformat())
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
    )

    def add_ndvi(image):
        scl = image.select("SCL")
        # Same SCL exclusions as the STAC path, expressed as a server-side mask.
        mask = (
            scl.neq(0).And(scl.neq(1)).And(scl.neq(3))
            .And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        )
        ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        return ndvi.updateMask(mask).copyProperties(
            image, ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"]
        )

    with_ndvi = collection.map(add_ndvi)

    def reduce_image(image):
        stats = ee.Image(image).reduceRegion(
            reducer=(
                ee.Reducer.mean()
                .combine(ee.Reducer.stdDev(), sharedInputs=True)
                .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True)
                .combine(ee.Reducer.count(), sharedInputs=True)
            ),
            geometry=region, scale=10, maxPixels=1e8,
        )
        return ee.Feature(None, stats).set({
            "date": ee.Date(ee.Image(image).get("system:time_start"))
                      .format("YYYY-MM-dd"),
            "cloud": ee.Image(image).get("CLOUDY_PIXEL_PERCENTAGE"),
        })

    features = with_ndvi.map(reduce_image).getInfo()["features"]

    observations: list[NDVIObservation] = []
    for f in features:
        p = f["properties"]
        mean = p.get("NDVI_mean")
        if mean is None:
            continue
        observations.append(
            NDVIObservation(
                day=date.fromisoformat(p["date"]),
                ndvi_mean=float(mean),
                ndvi_p10=float(p.get("NDVI_p10") or mean),
                ndvi_p90=float(p.get("NDVI_p90") or mean),
                ndvi_std=float(p.get("NDVI_stdDev") or 0.0),
                valid_fraction=1.0,
                scene_cloud_percent=float(p.get("cloud") or 0.0),
                scene_id=f.get("id", ""),
            )
        )
    observations.sort(key=lambda o: o.day)
    return NDVISeries(latitude, longitude, observations, "earth_engine", buffer_m)


def earth_engine_available() -> bool:
    """Whether Earth Engine is authenticated and initialised."""
    import os
    try:
        import ee
        project = os.environ.get("EARTHENGINE_PROJECT", "").strip()
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

async def fetch_ndvi_series(
    latitude: float,
    longitude: float,
    start: date | None = None,
    end: date | None = None,
    buffer_m: float = 100.0,
    max_cloud: float = 40.0,
    max_scenes: int = 12,
    prefer: Literal["auto", "earth_engine", "planetary_computer"] = "auto",
) -> NDVISeries:
    """Fetch a cloud-screened NDVI time series for a field.

    Cached for a day: Sentinel-2 revisits every ~5 days, so re-reading COGs
    on every question is pure cost. The COG path takes 10-30 seconds
    uncached, which is far too long to repeat.
    """
    end = end or date.today()
    start = start or (end - timedelta(days=120))

    cache = get_cache()
    key = cache_key(
        lat=latitude, lon=longitude, start=start.isoformat(),
        end=end.isoformat(), buffer=buffer_m, cloud=max_cloud, prefer=prefer,
    )
    cached = cache.get("stac_search", key)
    if cached is not None:
        series = NDVISeries(
            latitude, longitude, [], cached.get("provider", "planetary_computer"),
            buffer_m,
        )
        series.observations = [
            NDVIObservation(
                day=date.fromisoformat(o["day"]), ndvi_mean=o["ndvi_mean"],
                ndvi_p10=o["ndvi_p10"], ndvi_p90=o["ndvi_p90"],
                ndvi_std=o["ndvi_std"], valid_fraction=o["valid_fraction"],
                scene_cloud_percent=o["scene_cloud_percent"],
                scene_id=o["scene_id"],
            )
            for o in cached.get("observations", [])
        ]
        return series

    use_ee = prefer == "earth_engine" or (
        prefer == "auto" and earth_engine_available()
    )

    loop = asyncio.get_running_loop()
    if use_ee:
        try:
            series = await loop.run_in_executor(
                None, _fetch_earth_engine_sync,
                latitude, longitude, start, end, buffer_m, max_cloud,
            )
        except Exception:
            # Fall through to the keyless provider rather than failing.
            series = await loop.run_in_executor(
                None, _fetch_stac_sync,
                latitude, longitude, start, end, buffer_m, max_cloud, max_scenes,
            )
    else:
        series = await loop.run_in_executor(
            None, _fetch_stac_sync,
            latitude, longitude, start, end, buffer_m, max_cloud, max_scenes,
        )

    cache.set("stac_search", key, {
        "provider": series.provider,
        "observations": [
            {
                "day": o.day.isoformat(), "ndvi_mean": o.ndvi_mean,
                "ndvi_p10": o.ndvi_p10, "ndvi_p90": o.ndvi_p90,
                "ndvi_std": o.ndvi_std, "valid_fraction": o.valid_fraction,
                "scene_cloud_percent": o.scene_cloud_percent,
                "scene_id": o.scene_id,
            }
            for o in series.observations
        ],
    })
    return series
