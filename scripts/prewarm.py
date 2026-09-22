"""
Warm the slow caches: geocoding and soil for places farmers name, and the
satellite read for fields already on record.

SoilGrids is the slowest thing this system depends on, and on a bad day it is
slow enough to matter. Measured on 20 September 2026, one query for the eight
properties across three depths took 26 seconds at best and 91-115 seconds at
worst, with occasional read timeouts and a 503. A pin that has never been
queried waits through that, and a pin inside the urban mask -- which is what
happens when someone names the village they know -- waits through it once per
ring until the search finds soil.

Soil does not change between seasons, so the cache holds for a year. Warming
it ahead of time moves that wait off the farmer.

Why this warms place NAMES rather than a list of coordinates: the soil cache
is keyed on the coordinate rounded to four decimals, about eleven metres, so
warming an arbitrary point near a district would never be hit by a real
request. But a farmer does not supply coordinates at all -- they name a place,
the app geocodes it, and geocoding is deterministic. Warming the same names
through the same geocoder produces exactly the coordinates a real request will
produce, so the cache actually gets hit. It warms the geocode cache too.

This does not help a farmer whose location comes from their phone's GPS, which
is an arbitrary point. Nothing can pre-warm that; it is what the timeout and
the ring search are for.

The satellite pass is the one that matters most on a demo day. A cold NDVI
read takes about fifty-three seconds, measured, against a tenth of a second
for the water balance beside it -- so "how is my field doing", which asks for
both, spends essentially all of its time waiting on Sentinel-2. The result is
cached, but the cache key carries today's date, so it expires every midnight
however recently it was warmed. Run this in the morning of any day the app
will be shown.

Run it inside the container, so the cache lands in the mounted volume and
survives an image rebuild:

    docker exec -i agrin python - < scripts/prewarm.py

Run it two or three times. A probe that fails is not cached -- only a real
answer is, masked or not -- so a pass that hit a slow patch leaves gaps that
look warm from the outside: the place resolves, but the ring probes behind it
are still cold and get retried on every real request. Measured here, the
first pass left Indore at 43 seconds and Guntur at 64; the second brought all
but two to nothing; the third finished the job. Re-running is cheap, because
everything already warm returns immediately.
"""

from __future__ import annotations

import asyncio
import sys
import time

# Places a farmer or a reviewer would plausibly type, spread across the major
# agricultural belts. Written the way someone would say them, because that is
# what gets geocoded.
PLACES: list[str] = [
    # Punjab and Haryana -- wheat and rice, and the districts already demoed.
    "Tarn Taran, Punjab",
    "Patiala, Punjab",
    "Ludhiana, Punjab",
    "Karnal, Haryana",
    # The Gangetic plain.
    "Meerut, Uttar Pradesh",
    "Gorakhpur, Uttar Pradesh",
    "Muzaffarpur, Bihar",
    "Bardhaman, West Bengal",
    # Central and western India.
    "Indore, Madhya Pradesh",
    "Rajkot, Gujarat",
    "Nashik, Maharashtra",
    "Yavatmal, Maharashtra",
    # The south.
    "Warangal, Telangana",
    "Guntur, Andhra Pradesh",
    "Belagavi, Karnataka",
    "Thanjavur, Tamil Nadu",
    "Palakkad, Kerala",
    # East.
    "Cuttack, Odisha",
]


# Warming is allowed to be patient in a way a live request is not.
PREWARM_BUDGET_S = 1800.0


async def main() -> int:
    from geo.mandi import geocode_place
    from geo.soilgrids import fetch_soil_profile_resilient

    # Deliberately sequential. These queries are heavy and ISRIC sheds load
    # when several arrive at once -- running them in parallel is how a slow
    # warm-up becomes a failed one.
    warmed = failed = 0
    for place in PLACES:
        started = time.perf_counter()
        try:
            matches = await geocode_place(place)
        except Exception as exc:                          # noqa: BLE001
            print(f"  {place:28} geocode FAILED  {type(exc).__name__}", flush=True)
            failed += 1
            continue
        if not matches:
            print(f"  {place:28} not found by geocoder", flush=True)
            failed += 1
            continue

        lat = float(matches[0]["latitude"])
        lon = float(matches[0]["longitude"])
        try:
            # A live request gives up after three minutes, because a farmer
            # waiting on a screen is better told "I cannot get soil here"
            # than left hanging. Warming has the opposite trade: nobody is
            # waiting, and a search abandoned early caches nothing, so the
            # next real request pays the whole cost again. Indore needed
            # fourteen minutes to find soil five kilometres out, and that
            # result is now permanent.
            profile = await fetch_soil_profile_resilient(
                lat, lon, budget_s=PREWARM_BUDGET_S
            )
        except Exception as exc:                          # noqa: BLE001
            print(f"  {place:28} soil FAILED  {type(exc).__name__}", flush=True)
            failed += 1
            continue

        elapsed = time.perf_counter() - started
        layers = sum(1 for layer in profile.layers if layer.mean is not None)
        if layers:
            displaced = profile.displaced_km
            note = f", soil from {displaced:.1f} km away" if displaced else ""
            print(f"  {place:28} {elapsed:6.1f}s  {layers} layers{note}", flush=True)
            warmed += 1
        else:
            print(f"  {place:28} {elapsed:6.1f}s  no soil found", flush=True)
            failed += 1

    print(f"\nWarmed {warmed} of {len(PLACES)} places.")
    if failed:
        print(f"{failed} still cold -- re-running retries only those, "
              f"since warmed places are served from cache.")

    failed += await _warm_satellite()
    return 1 if failed else 0


async def _warm_satellite() -> int:
    """Read the satellite view once for every field that has a crop on it.

    Only fields with a crop, because that is what "how is my field doing"
    needs, and only distinct coordinates, because the cache is keyed on
    position rather than on which field record points at it.
    """
    from agrin_api import storage
    from agrin_api.tools import get_crop_health

    with storage.connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT ROUND(f.latitude, 4), ROUND(f.longitude, 4)
               FROM field f JOIN season s ON s.field_id = f.id"""
        ).fetchall()

    if not rows:
        print("\nNo fields with a crop on record; nothing to warm.")
        return 0

    print(f"\nSatellite, {len(rows)} field location(s):", flush=True)
    failed = 0
    for lat, lon in rows:
        started = time.perf_counter()
        try:
            result = await get_crop_health(float(lat), float(lon))
        except Exception as exc:                          # noqa: BLE001
            print(f"  {lat}, {lon}  FAILED  {type(exc).__name__}", flush=True)
            failed += 1
            continue
        elapsed = time.perf_counter() - started
        if result.get("ok"):
            print(f"  {lat}, {lon}  {elapsed:6.1f}s", flush=True)
        else:
            reason = str(result.get("abstain_reason", ""))[:60]
            print(f"  {lat}, {lon}  {elapsed:6.1f}s  no reading ({reason})", flush=True)
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
