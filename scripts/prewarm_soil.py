"""
Warm the geocoding and soil caches for places farmers are likely to name.

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

Run it inside the container, so the cache lands in the mounted volume and
survives an image rebuild:

    docker exec -i agrin python - < scripts/prewarm_soil.py

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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
