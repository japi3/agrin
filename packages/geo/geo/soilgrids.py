"""
ISRIC SoilGrids client.

SoilGrids (https://soilgrids.org) is a 250 m global gridded soil property
dataset produced by ISRIC - World Soil Information using machine learning over
~240,000 profile observations. It is the only openly licensed soil dataset
with genuinely global coverage, which is what makes a single platform usable
across all BRICS members without per-country data agreements.

Reference:
    Poggio, L., de Sousa, L.M., Batjes, N.H., Heuvelink, G.B.M., Kempen, B.,
    Ribeiro, E., Rossiter, D. (2021). "SoilGrids 2.0: producing soil
    information for the globe with quantified spatial uncertainty."
    SOIL, 7, 217-240. https://doi.org/10.5194/soil-7-217-2021

Two things this client takes seriously:

1. **Units.** SoilGrids returns integers in conventional mapped units that are
   not the units of the property (clay in g/kg, not %; bulk density in
   cg/cm3, not g/cm3; SOC in dg/kg). Every property carries an explicit
   conversion factor, applied once, here. Getting this wrong silently
   produces soil water capacities that are off by an order of magnitude.

2. **Uncertainty.** SoilGrids publishes 5th and 95th percentile predictions
   alongside the mean. We fetch and retain them, because a farmer being told
   their soil is clay when the model is barely distinguishing clay from loam
   deserves to know that.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# property -> (divisor to reach the stated unit, unit label, human label)
# Source: https://www.isric.org/explore/soilgrids/faq-soilgrids  (units table)
PROPERTY_CONVERSIONS: dict[str, tuple[float, str, str]] = {
    "clay":  (10.0,  "%",      "Clay content"),
    "sand":  (10.0,  "%",      "Sand content"),
    "silt":  (10.0,  "%",      "Silt content"),
    "phh2o": (10.0,  "pH",     "Soil pH in water"),
    "soc":   (10.0,  "g/kg",   "Soil organic carbon"),
    "nitrogen": (100.0, "g/kg", "Total nitrogen"),
    "cec":   (10.0,  "cmol/kg", "Cation exchange capacity"),
    "bdod":  (100.0, "g/cm3",  "Bulk density"),
    "cfvo":  (10.0,  "%",      "Coarse fragments"),
}

DEFAULT_PROPERTIES = ["clay", "sand", "silt", "phh2o", "soc", "bdod", "nitrogen", "cec"]

# SoilGrids standard depth intervals. The 0-30 cm band is what agronomy cares
# about for annual crops, so we request the three layers spanning it.
DEFAULT_DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]

# Thickness of each standard interval, for depth-weighted averaging.
DEPTH_THICKNESS_CM = {
    "0-5cm": 5.0, "5-15cm": 10.0, "15-30cm": 15.0,
    "30-60cm": 30.0, "60-100cm": 40.0, "100-200cm": 100.0,
}


@dataclass
class SoilLayer:
    """One property at one depth interval, in converted units."""
    property_name: str
    depth: str
    mean: float | None
    q05: float | None
    q95: float | None
    unit: str
    label: str

    @property
    def uncertainty_range(self) -> float | None:
        """Width of the 90% prediction interval, in the property's units."""
        if self.q05 is None or self.q95 is None:
            return None
        return self.q95 - self.q05

    @property
    def is_confident(self) -> bool:
        """Whether the prediction interval is tight enough to act on.

        Heuristic: an interval wider than the mean itself means the model is
        essentially uninformative at this location, which happens in regions
        with sparse profile coverage. The assistant is required to say so
        rather than quote the mean as fact.
        """
        if self.mean is None or self.uncertainty_range is None:
            return False
        if self.mean == 0:
            return False
        return self.uncertainty_range < abs(self.mean)


@dataclass
class SoilProfile:
    """A full SoilGrids query result for one point, with provenance."""
    latitude: float
    longitude: float
    layers: list[SoilLayer] = field(default_factory=list)
    source: str = "ISRIC SoilGrids 2.0"
    source_url: str = "https://soilgrids.org"
    licence: str = "CC BY 4.0"
    resolution_m: int = 250
    # Set when the requested point was masked and data came from nearby.
    displaced_km: float | None = None
    displaced_from: tuple[float, float] | None = None
    displacement_bearing: float | None = None
    search_exhausted: bool = False

    @property
    def has_data(self) -> bool:
        """Whether any layer carries an actual value.

        SoilGrids answers 200 OK with an all-null body over masked cells, so
        HTTP status is not a usable success signal.
        """
        return any(layer.mean is not None for layer in self.layers)

    def get(self, property_name: str, depth: str) -> SoilLayer | None:
        for layer in self.layers:
            if layer.property_name == property_name and layer.depth == depth:
                return layer
        return None

    def depth_weighted(self, property_name: str, depths: list[str] | None = None) -> float | None:
        """Thickness-weighted mean of a property over several depth intervals.

        A plain average across 0-5, 5-15 and 15-30 cm would over-weight the
        thin surface layer threefold. Root-zone properties must be weighted by
        the thickness each layer represents.
        """
        depths = depths or DEFAULT_DEPTHS
        total_thickness = 0.0
        weighted_sum = 0.0
        for depth in depths:
            layer = self.get(property_name, depth)
            if layer is None or layer.mean is None:
                continue
            thickness = DEPTH_THICKNESS_CM.get(depth, 0.0)
            weighted_sum += layer.mean * thickness
            total_thickness += thickness
        if total_thickness == 0:
            return None
        return weighted_sum / total_thickness

    @property
    def texture_fractions(self) -> tuple[float, float, float] | None:
        """(sand, silt, clay) percentages over the 0-30 cm root zone."""
        sand = self.depth_weighted("sand")
        silt = self.depth_weighted("silt")
        clay = self.depth_weighted("clay")
        if None in (sand, silt, clay):
            return None
        return (sand, silt, clay)

    def evidence(self) -> dict[str, Any]:
        """Provenance record for the Evidence Ledger."""
        return {
            "source": self.source,
            "source_url": self.source_url,
            "licence": self.licence,
            "resolution_m": self.resolution_m,
            "queried_point": {"lat": self.latitude, "lon": self.longitude},
            "citation": (
                "Poggio et al. (2021), SoilGrids 2.0, SOIL 7:217-240"
            ),
            "layers_returned": len(self.layers),
            "displaced_km": (
                round(self.displaced_km, 2) if self.displaced_km else None
            ),
            "displacement_note": (
                f"The requested point falls inside a SoilGrids mask (built-up "
                f"land or water). These values are from the nearest mapped "
                f"soil, {self.displaced_km:.1f} km away."
                if self.displaced_km else None
            ),
            "low_confidence_properties": sorted(
                {l.property_name for l in self.layers if not l.is_confident}
            ),
        }


class SoilGridsError(RuntimeError):
    pass


async def fetch_soil_profile(
    latitude: float,
    longitude: float,
    properties: list[str] | None = None,
    depths: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> SoilProfile:
    """Fetch a soil profile for one point.

    SoilGrids is a public service with no key and modest rate limits, so this
    is deliberately a single batched request for all properties and depths
    rather than one request per property.
    """
    properties = properties or DEFAULT_PROPERTIES
    depths = depths or DEFAULT_DEPTHS

    params: list[tuple[str, str]] = [
        ("lon", f"{longitude}"),
        ("lat", f"{latitude}"),
    ]
    for p in properties:
        params.append(("property", p))
    for d in depths:
        params.append(("depth", d))
    for v in ("mean", "Q0.05", "Q0.95"):
        params.append(("value", v))

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.get(SOILGRIDS_URL, params=params)
        if response.status_code != 200:
            raise SoilGridsError(
                f"SoilGrids returned {response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
    except httpx.HTTPError as exc:
        raise SoilGridsError(f"SoilGrids request failed: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    return _parse(payload, latitude, longitude)


def _parse(payload: dict, latitude: float, longitude: float) -> SoilProfile:
    """Convert the SoilGrids response into converted-unit layers.

    The response nests layers -> depths -> values, and the numeric values are
    integers in mapped units that must be divided by a per-property factor.

    The divisor is taken from the response's own `unit_measure.d_factor`
    where present, falling back to our table only if the field is missing.
    ISRIC publishes the factor alongside the data precisely because it has
    changed between releases; trusting a hardcoded constant is how a future
    SoilGrids update would silently corrupt every soil figure we quote.

    Nulls are preserved as None rather than coerced to zero -- SoilGrids masks
    built-up land and open water, and a pH of 0 is nonsense a downstream
    water-balance model would consume without complaint.
    """
    profile = SoilProfile(latitude=latitude, longitude=longitude)
    layers = payload.get("properties", {}).get("layers", [])

    for layer in layers:
        name = layer.get("name")
        if name not in PROPERTY_CONVERSIONS:
            continue
        fallback_divisor, unit, label = PROPERTY_CONVERSIONS[name]
        unit_measure = layer.get("unit_measure") or {}
        divisor = float(unit_measure.get("d_factor") or fallback_divisor)
        unit = unit_measure.get("target_units") or unit

        for depth_entry in layer.get("depths", []):
            depth_label = depth_entry.get("label")
            values = depth_entry.get("values", {}) or {}

            def convert(key: str) -> float | None:
                raw = values.get(key)
                if raw is None:
                    return None
                return raw / divisor

            profile.layers.append(
                SoilLayer(
                    property_name=name,
                    depth=depth_label,
                    mean=convert("mean"),
                    q05=convert("Q0.05"),
                    q95=convert("Q0.95"),
                    unit=unit,
                    label=label,
                )
            )
    return profile

# --------------------------------------------------------------------------
# Masked cells: built-up land and open water
# --------------------------------------------------------------------------

# Offsets tried when the requested point returns no data, ordered by distance.
# SoilGrids is a 250 m grid, but urban masks span whole settlements, so the
# search has to reach several kilometres to clear a town.
_SEARCH_RING_KM = [1.0, 2.5, 5.0, 10.0, 20.0]
_SEARCH_BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315]


def _offset_point(lat: float, lon: float, distance_km: float, bearing_deg: float
                  ) -> tuple[float, float]:
    """Displace a point by a distance and bearing on a spherical Earth.

    Uses the standard great-circle destination formula rather than a flat
    degree offset, because a fixed degree step in longitude covers wildly
    different ground distances at Punjab's latitude versus the equator.
    """
    import math
    R = 6371.0
    br = math.radians(bearing_deg)
    lat1, lon1 = math.radians(lat), math.radians(lon)
    d = distance_km / R
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points [km]."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


async def fetch_soil_profile_resilient(
    latitude: float,
    longitude: float,
    properties: list[str] | None = None,
    depths: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    max_search_km: float = 20.0,
) -> SoilProfile:
    """Fetch a soil profile, searching outward if the point itself is masked.

    SoilGrids returns nulls over built-up land and open water. This matters
    in practice far more than it sounds: a farmer dropping a pin on their
    village -- the landmark they actually know -- lands inside the urban mask
    and gets nothing, while their fields two kilometres away are fully mapped.

    So a masked point triggers a ring search outward to `max_search_km`, and
    the substitution is recorded in `displaced_km` / `displaced_from` so the
    Evidence Ledger can state plainly that the soil figures describe a nearby
    location rather than the exact pin. Silently substituting nearby data
    without disclosing it would be the wrong trade.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        profile = await fetch_soil_profile(
            latitude, longitude, properties, depths, client=client
        )
        if profile.has_data:
            return profile

        # Rings are searched nearest-first, but the eight bearings within a
        # ring are issued concurrently: a serial sweep costs up to 40 sequential
        # round-trips and pushes a farmer's first answer past ten seconds.
        # Concurrency is capped at one ring (8 requests) at a time to stay
        # within ISRIC's fair-use expectations for a free public service.
        for radius in _SEARCH_RING_KM:
            if radius > max_search_km:
                break

            targets = [
                (bearing, *_offset_point(latitude, longitude, radius, bearing))
                for bearing in _SEARCH_BEARINGS
            ]
            results = await asyncio.gather(
                *(
                    fetch_soil_profile(lat2, lon2, properties, depths, client=client)
                    for _, lat2, lon2 in targets
                ),
                return_exceptions=True,
            )

            # Prefer the closest hit in this ring; ties broken by bearing order.
            best: tuple[float, SoilProfile, float] | None = None
            for (bearing, lat2, lon2), candidate in zip(targets, results):
                if isinstance(candidate, BaseException) or not candidate.has_data:
                    continue
                distance = haversine_km(latitude, longitude, lat2, lon2)
                if best is None or distance < best[0]:
                    best = (distance, candidate, bearing)

            if best is not None:
                distance, candidate, bearing = best
                candidate.displaced_km = distance
                candidate.displaced_from = (latitude, longitude)
                candidate.displacement_bearing = bearing
                return candidate

        # Nothing found: return the empty profile rather than inventing soil.
        profile.search_exhausted = True
        return profile
    finally:
        if owns_client:
            await client.aclose()
