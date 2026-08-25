"""
Indian mandi (APMC) price client, via the Agmarknet feed on data.gov.in.

Source
------
data.gov.in resource 9ef84268-d588-465a-a308-a864a43d0070, "Current Daily
Price of Various Commodities from Various Markets (Mandi)", published by the
Directorate of Marketing & Inspection, Ministry of Agriculture & Farmers
Welfare. Updated daily from Agmarknet, covering roughly 3,000 regulated
markets.

Why price belongs in an agronomy platform
-----------------------------------------
Every other tool here answers "what will grow". Price answers "what is worth
growing", and for a smallholder those are not the same question. A farmer
deciding between paddy and maize is making a revenue decision under water
constraints, and an advisory that discusses yield without price is answering
half of it.

What this module is careful about
---------------------------------
**Prices are per quintal, not per kilogram.** Agmarknet quotes rupees per
quintal (100 kg). Reporting the figure without the unit, or silently treating
it as per-kg, is a hundred-fold error in a number a farmer would act on.

**Modal, not average.** Agmarknet gives min, max and modal price. The modal
price is the rate most transactions actually cleared at, and it is the one a
farmer will be offered. The min-max spread reflects grade and lot quality,
so it is reported alongside rather than averaged away.

**Today's rate is not a forecast.** These are spot prices from one day's
arrivals. The module reports what was quoted and does not extrapolate;
predicting mandi prices is a genuinely hard problem and a confident guess
here would be worse than silence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from .cache import cache_key, get_cache

AGMARKNET_RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_URL = f"https://api.data.gov.in/resource/{AGMARKNET_RESOURCE}"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# data.gov.in publishes a shared demonstration key in its own API docs. It is
# rate-limited and intended for exactly this: getting a project working before
# registering. Deployments should set DATA_GOV_IN_KEY to their own key.
DEMO_API_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"

# data.gov.in does not answer requests carrying httpx's default User-Agent.
# It does not refuse them either -- the connection simply hangs until the
# client times out, which reads as a network fault rather than a rejection and
# is correspondingly annoying to diagnose. Any identifying User-Agent works;
# the same request returns in under three seconds with one set.
HTTP_HEADERS = {
    "User-Agent": "AgriN/0.1 (agricultural advisory platform)",
    "Accept": "application/json",
}

# Our crop keys mapped to Agmarknet commodity names. Agmarknet uses trade
# names with regional spellings, so this mapping is hand-built rather than
# derived -- "Bengal Gram(Gram)(Whole)" is not something a slug transform
# produces from "chickpea".
CROP_TO_COMMODITY: dict[str, list[str]] = {
    "rice_paddy": ["Paddy(Dhan)(Common)", "Paddy(Dhan)(Basmati)", "Rice"],
    "wheat_winter": ["Wheat"],
    "wheat_spring": ["Wheat"],
    "maize_grain": ["Maize"],
    "soybean": ["Soyabean"],
    "cotton": ["Cotton"],
    "sugarcane": ["Sugarcane"],
    "chickpea": ["Bengal Gram(Gram)(Whole)", "Bengal Gram Dal (Chana Dal)"],
    "mustard": ["Mustard", "Rape Seed"],
    "groundnut": ["Groundnut", "Groundnut (Split)"],
    "pearl_millet": ["Bajra(Pearl Millet/Cumbu)"],
    "sorghum": ["Jowar(Sorghum)"],
    "potato": ["Potato"],
    "sunflower": ["Sunflower"],
    "barley": ["Barley (Jau)"],
}

QUINTAL_KG = 100.0


@dataclass
class MandiQuote:
    """One commodity's price at one market on one day. Rupees per quintal."""
    state: str
    district: str
    market: str
    commodity: str
    variety: str
    grade: str
    arrival_date: date | None
    min_price: float
    max_price: float
    modal_price: float

    @property
    def modal_per_kg(self) -> float:
        return self.modal_price / QUINTAL_KG

    @property
    def spread(self) -> float:
        """Max minus min: how much grade and lot quality are worth here."""
        return self.max_price - self.min_price


@dataclass
class MandiReport:
    commodity_searched: list[str]
    state: str | None
    district: str | None
    quotes: list[MandiQuote] = field(default_factory=list)
    as_of: date | None = None
    # "state"       the farmer's own state had arrivals
    # "national"    the search widened; usually out of season locally
    # "none"        the service answered, and nothing traded anywhere today
    # "unavailable" the service could not be reached at all
    scope: str = "state"
    failure_reason: str | None = None

    @property
    def best(self) -> MandiQuote | None:
        return max(self.quotes, key=lambda q: q.modal_price) if self.quotes else None

    @property
    def local(self) -> MandiQuote | None:
        """The quote in the farmer's own district, if there is one."""
        if not self.district:
            return None
        matches = [
            q for q in self.quotes
            if q.district.lower().strip() == self.district.lower().strip()
        ]
        return max(matches, key=lambda q: q.modal_price) if matches else None

    def evidence(self) -> dict[str, Any]:
        return {
            "source": "Agmarknet via data.gov.in",
            "publisher": (
                "Directorate of Marketing & Inspection, Ministry of "
                "Agriculture & Farmers Welfare, Government of India"
            ),
            "resource_id": AGMARKNET_RESOURCE,
            "licence": "Government Open Data License - India",
            "unit": "Indian rupees per quintal (100 kg)",
            "markets_reported": len({q.market for q in self.quotes}),
            "scope": self.scope,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "note": (
                "Spot prices from one day's arrivals at regulated APMC "
                "markets. Not a forecast, and rates move daily with arrivals."
            ),
        }


class MandiError(RuntimeError):
    """A mandi lookup failed for a reason that is not 'no arrivals today'."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        # Transient means the service was busy or broken, NOT that the market
        # had no trade. Conflating those two is the bug this flag exists to
        # prevent: telling a farmer their crop is out of season when in fact
        # we were rate limited is a confident falsehood about their livelihood.
        self.transient = transient


def _parse_price(raw: Any) -> float | None:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    # Agmarknet uses 0 and occasionally negative sentinels for "not reported".
    return value if value > 0 else None


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    return None


async def reverse_geocode_india(
    latitude: float, longitude: float, client: httpx.AsyncClient | None = None
) -> dict[str, str | None]:
    """Resolve a point to its Indian state and district.

    Mandi data is indexed by administrative name, not coordinates, so a
    district lookup is the bridge between "where the farmer's field is" and
    "which markets serve them".

    Uses OpenStreetMap Nominatim, which is free and requires only a
    identifying User-Agent under its usage policy. Results are cached for a
    month; district boundaries do not move.
    """
    cache = get_cache()
    key = cache_key(lat=latitude, lon=longitude, kind="reverse")
    cached = cache.get("geocode", key)
    if cached is not None:
        return cached

    owns = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await client.get(
            NOMINATIM_URL,
            params={
                "lat": latitude, "lon": longitude, "format": "json",
                "zoom": 8, "addressdetails": 1,
            },
            headers={"User-Agent": "AgriN/0.1 (agricultural advisory platform)"},
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MandiError(f"Reverse geocoding failed: {exc}") from exc
    finally:
        if owns:
            await client.aclose()

    address = payload.get("address", {}) or {}
    result = {
        "state": address.get("state"),
        # Nominatim varies the key by country and zoom level.
        "district": (
            address.get("state_district")
            or address.get("county")
            or address.get("district")
        ),
        "country_code": address.get("country_code"),
        "display_name": payload.get("display_name"),
    }
    # Districts are commonly returned as "Moga Tahsil"; Agmarknet uses "Moga".
    if result["district"]:
        for suffix in (" Tahsil", " Tehsil", " District", " Taluk", " Taluka"):
            if result["district"].endswith(suffix):
                result["district"] = result["district"][: -len(suffix)].strip()
    cache.set("geocode", key, result)
    return result


async def fetch_prices(
    commodity: str,
    state: str | None = None,
    district: str | None = None,
    limit: int = 200,
    client: httpx.AsyncClient | None = None,
) -> list[MandiQuote]:
    """Fetch today's quotes for one commodity, optionally scoped to a region."""
    api_key = os.environ.get("DATA_GOV_IN_KEY", "").strip() or DEMO_API_KEY

    params: dict[str, Any] = {
        "api-key": api_key,
        "format": "json",
        "limit": limit,
        "filters[commodity]": commodity,
    }
    if state:
        params["filters[state.keyword]"] = state
    if district:
        params["filters[district]"] = district

    cache = get_cache()
    key = cache_key(commodity=commodity, state=state, district=district, limit=limit)
    cached = cache.get("mandi", key)
    if cached is None:
        owns = client is None
        client = client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.get(
                DATA_GOV_URL, params=params, headers=HTTP_HEADERS
            )
            if response.status_code == 429:
                raise MandiError(
                    "data.gov.in rate limit reached. The shared demonstration "
                    "key is throttled across everyone using it; register a "
                    "free key at https://data.gov.in/user/register and set "
                    "DATA_GOV_IN_KEY.",
                    transient=True,
                )
            if response.status_code >= 500:
                raise MandiError(
                    f"data.gov.in returned {response.status_code}",
                    transient=True,
                )
            if response.status_code != 200:
                raise MandiError(
                    f"data.gov.in returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
            cached = response.json()
        except httpx.TimeoutException as exc:
            raise MandiError(
                f"data.gov.in did not respond in time: {exc}", transient=True
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise MandiError(
                f"Mandi price request failed: {exc}", transient=True
            ) from exc
        finally:
            if owns:
                await client.aclose()

        # Only cache responses that actually carried records. Caching an
        # empty body would pin "no arrivals" for six hours -- so a single
        # rate-limited moment would tell every farmer for the rest of the
        # afternoon that their crop is out of season.
        if (cached.get("records") or []):
            cache.set("mandi", key, cached)

    quotes: list[MandiQuote] = []
    for record in cached.get("records", []) or []:
        modal = _parse_price(record.get("modal_price"))
        if modal is None:
            # A record with no modal price carries no usable signal.
            continue
        lo = _parse_price(record.get("min_price")) or modal
        hi = _parse_price(record.get("max_price")) or modal
        quotes.append(
            MandiQuote(
                state=record.get("state", ""),
                district=record.get("district", ""),
                market=record.get("market", ""),
                commodity=record.get("commodity", ""),
                variety=record.get("variety", ""),
                grade=record.get("grade", ""),
                arrival_date=_parse_date(record.get("arrival_date")),
                min_price=lo, max_price=hi, modal_price=modal,
            )
        )
    return quotes


async def prices_for_crop(
    crop_key: str,
    latitude: float | None = None,
    longitude: float | None = None,
    state: str | None = None,
    district: str | None = None,
) -> MandiReport:
    """Get mandi prices for one of our crops near a field.

    Searches the state first. Agmarknet reports only markets that had
    arrivals that day, so a district may legitimately have no quote -- during
    the off-season for that crop, or simply because the mandi was closed.
    Widening to the state rather than returning nothing is what makes the
    answer useful on most days.
    """
    commodities = CROP_TO_COMMODITY.get(crop_key)
    if not commodities:
        return MandiReport(commodity_searched=[], state=state, district=district)

    if (state is None or district is None) and latitude is not None:
        try:
            place = await reverse_geocode_india(latitude, longitude)
            if place.get("country_code") == "in":
                state = state or place.get("state")
                district = district or place.get("district")
        except MandiError:
            pass

    quotes: list[MandiQuote] = []
    scope = "state"
    transient_failure: str | None = None

    async with httpx.AsyncClient(timeout=25.0) as client:
        # Search the farmer's own state first.
        for commodity in commodities:
            try:
                found = await fetch_prices(commodity, state=state, client=client)
            except MandiError as exc:
                if getattr(exc, "transient", False):
                    transient_failure = str(exc)
                continue
            if found:
                quotes = found
                break

        # Nothing locally. Widen to the whole country rather than reporting
        # "no data", because the usual reason is seasonal: Agmarknet lists
        # only markets with arrivals that day, and a crop three months from
        # harvest has none in its own growing region. A farmer asking what
        # paddy is fetching in August is asking what to expect, and national
        # rates answer that. The scope is returned so the assistant can say
        # plainly that these are not local rates.
        if not quotes:
            scope = "national"
            for commodity in commodities:
                try:
                    found = await fetch_prices(commodity, client=client)
                except MandiError as exc:
                    if getattr(exc, "transient", False):
                        transient_failure = str(exc)
                    continue
                if found:
                    quotes = found
                    break

    if not quotes:
        # "The service was unavailable" and "no market traded this crop
        # today" are completely different answers and must never be merged.
        scope = "unavailable" if transient_failure else "none"

    dates = [q.arrival_date for q in quotes if q.arrival_date]
    return MandiReport(
        commodity_searched=commodities,
        state=state, district=district,
        quotes=quotes,
        as_of=max(dates) if dates else None,
        scope=scope,
        failure_reason=transient_failure,
    )


# --------------------------------------------------------------------------
# Forward geocoding
# --------------------------------------------------------------------------

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"


def _relax_query(query: str) -> list[str]:
    """Progressively simpler forms of a place query, most specific first.

    Nominatim indexes many Indian villages but not all, and it matches poorly
    against the way people actually write an address -- "Dharamgarh Bohli,
    district Jind, Haryana" returns nothing, while "Dharamgarh Bohli, Jind"
    resolves. Small hamlets may be absent entirely, in which case the
    district is still a far better answer than failing: soil, weather and
    market data at district resolution are genuinely useful, and the
    alternative is telling a farmer their village does not exist.

    So the query is relaxed step by step rather than tried once and abandoned.
    """
    raw = query.strip()
    # Strip administrative qualifiers that hurt matching.
    cleaned = raw
    for word in ("district ", "distt ", "dist ", "tehsil ", "tahsil ",
                 "village ", "block ", "po ", "p.o. "):
        cleaned = cleaned.replace(word, "").replace(word.title(), "")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    candidates = [raw, cleaned]
    # Village + state, dropping the middle administrative level.
    if len(parts) >= 3:
        candidates.append(f"{parts[0]}, {parts[-1]}")
    # Progressively drop the leading (most local) component, so a missing
    # hamlet falls back to its district and then its state.
    for i in range(1, len(parts)):
        candidates.append(", ".join(parts[i:]))

    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        key = c.strip().lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(c.strip())
    return ordered


async def geocode_place(
    query: str,
    country_codes: str = "in",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Resolve a place name to coordinates.

    This is the bridge between how farmers describe where they are and what
    every model in this platform needs. Nobody says "my field is at 29.31
    north, 76.31 east"; they say "Dharamgarh Bohli, Jind". Without forward
    geocoding the assistant has to keep asking for something the farmer does
    not have, which is exactly the interrogation the interface is meant to
    avoid.

    Restricted to India by default and cached for a month -- villages do not
    move, and Nominatim's usage policy expects heavy consumers to cache.
    """
    cache = get_cache()
    key = cache_key(q=query.strip().lower(), cc=country_codes, kind="forward")
    cached = cache.get("geocode", key)
    # An empty result is deliberately NOT treated as a cache hit. Caching a
    # miss makes a transient upstream failure permanent for a month, and a
    # place that "does not exist" is exactly the answer a farmer would retry.
    if cached:
        return cached

    owns = client is None
    client = client or httpx.AsyncClient(timeout=20.0)
    payload: list = []
    matched_query = query
    try:
        for candidate in _relax_query(query):
            response = await client.get(
                NOMINATIM_SEARCH,
                params={
                    "q": candidate, "format": "json", "addressdetails": 1,
                    "limit": 5, "countrycodes": country_codes,
                },
                headers={"User-Agent": "AgriN/0.1 (agricultural advisory platform)"},
            )
            found = response.json()
            if found:
                payload = found
                matched_query = candidate
                break
    except (httpx.HTTPError, ValueError) as exc:
        raise MandiError(f"Place lookup failed: {exc}") from exc
    finally:
        if owns:
            await client.aclose()

    results = []
    for item in payload:
        address = item.get("address", {}) or {}
        district = (
            address.get("state_district") or address.get("county")
            or address.get("district")
        )
        if district:
            for suffix in (" Tahsil", " Tehsil", " District", " Taluk", " Taluka"):
                if district.endswith(suffix):
                    district = district[: -len(suffix)].strip()
        results.append({
            "display_name": item.get("display_name"),
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
            "village": (
                address.get("village") or address.get("hamlet")
                or address.get("town") or address.get("city")
            ),
            "district": district,
            "state": address.get("state"),
            "type": item.get("type"),
            # Records which form of the query actually matched, so the
            # assistant can tell the farmer when it fell back to the district
            # rather than pinning their village exactly.
            "matched_query": matched_query,
            "exact_query_matched": matched_query.strip().lower() == query.strip().lower(),
        })
    if results:
        cache.set("geocode", key, results)
    return results
