"""
Pre-warm the soil cache across India's agricultural districts.

Why this exists
---------------
ISRIC SoilGrids is a free public service and is genuinely slow: a single
point query runs 5-15 seconds, and a pin that lands inside the urban mask
triggers a ring search costing several times that. Measured cold latency for
a first irrigation question is 25-60 seconds. Warm, it is effectively zero.

A farmer will not wait a minute for their first answer, and the first answer
is the one that decides whether they ever come back. So the cache is seeded
ahead of time rather than filled reactively.

This is also what "designed to scale across states, not one city" means in
practice. The grid below covers the whole country at roughly district
spacing, weighted toward the intensively farmed belts, so the platform is
equally responsive in Vidarbha and in Ludhiana.

Cost and courtesy
-----------------
Runs once. Results are cached for a year (soil does not change between
seasons). Concurrency is bounded by the semaphore in the SoilGrids client, so
this stays within fair use of a free scientific service. Expect 20-40 minutes
for the full grid; it is resumable, because anything already cached is
skipped without a network call.

    python scripts/prewarm_india.py            # full grid
    python scripts/prewarm_india.py --step 1.0 # coarser, faster
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "geo"))

import httpx  # noqa: E402

from geo.soilgrids import fetch_soil_profile_resilient  # noqa: E402

# Bounding boxes of India's major agro-climatic regions. A uniform national
# grid would spend most of its queries on the Thar desert, the Himalaya and
# the ocean; these boxes concentrate effort where crops actually grow.
REGIONS: dict[str, tuple[float, float, float, float]] = {
    # name: (lat_min, lat_max, lon_min, lon_max)
    "indo_gangetic_plain":   (25.0, 32.0, 74.0, 88.0),
    "punjab_haryana":        (28.5, 32.5, 74.0, 77.5),
    "deccan_plateau":        (15.0, 21.0, 74.0, 80.0),
    "vidarbha_marathwada":   (17.5, 21.5, 75.0, 80.5),
    "gujarat_saurashtra":    (20.5, 24.5, 68.5, 74.0),
    "coastal_andhra":        (13.5, 19.0, 77.0, 84.0),
    "tamil_nadu":            (8.0, 13.5, 76.5, 80.5),
    "karnataka":             (12.0, 18.0, 74.0, 78.5),
    "kerala":                (8.2, 12.8, 74.8, 77.3),
    "madhya_pradesh":        (21.0, 26.5, 74.0, 82.5),
    "rajasthan_irrigated":   (24.0, 29.5, 70.0, 77.0),
    "eastern_plateau":       (19.0, 25.0, 81.0, 87.0),
    "west_bengal_odisha":    (19.0, 27.0, 84.0, 89.0),
    "assam_brahmaputra":     (24.0, 27.5, 89.5, 96.0),
    "bihar_jharkhand":       (22.0, 27.5, 83.0, 88.5),
}


def grid_points(step: float) -> list[tuple[float, float, str]]:
    """Generate grid points over the agricultural regions, de-duplicated."""
    seen: set[tuple[float, float]] = set()
    points: list[tuple[float, float, str]] = []
    for name, (lat0, lat1, lon0, lon1) in REGIONS.items():
        lat = lat0
        while lat <= lat1:
            lon = lon0
            while lon <= lon1:
                key = (round(lat, 3), round(lon, 3))
                if key not in seen:
                    seen.add(key)
                    points.append((lat, lon, name))
                lon += step
            lat += step
    return points


async def warm(points: list[tuple[float, float, str]], concurrency: int = 4) -> None:
    done = 0
    hits = 0
    misses = 0
    started = time.time()
    total = len(points)
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=45.0) as client:

        async def one(lat: float, lon: float, region: str) -> None:
            nonlocal done, hits, misses
            try:
                profile = await fetch_soil_profile_resilient(
                    lat, lon, client=client, max_search_km=5.0
                )
                ok = profile.has_data
            except Exception:
                ok = False
            async with lock:
                done += 1
                if ok:
                    hits += 1
                else:
                    misses += 1
                if done % 25 == 0 or done == total:
                    elapsed = time.time() - started
                    rate = done / elapsed if elapsed else 0
                    remaining = (total - done) / rate if rate else 0
                    print(
                        f"  {done}/{total}  mapped={hits} unmapped={misses}  "
                        f"{rate:.1f}/s  ~{remaining/60:.0f} min left",
                        flush=True,
                    )

        # The SoilGrids client holds its own semaphore; this one bounds how
        # many ring searches are in flight at once.
        gate = asyncio.Semaphore(concurrency)

        async def guarded(lat, lon, region):
            async with gate:
                await one(lat, lon, region)

        await asyncio.gather(*(guarded(*p) for p in points))

    elapsed = time.time() - started
    print(
        f"\nDone in {elapsed/60:.1f} min. "
        f"{hits} points mapped, {misses} unmapped (water, desert, or masked)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--step", type=float, default=0.5,
        help="Grid spacing in degrees. 0.5 is roughly 55 km (default).",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    points = grid_points(args.step)
    print(
        f"Pre-warming {len(points)} points across {len(REGIONS)} agricultural "
        f"regions at {args.step} degree spacing.\n"
        f"Already-cached points are skipped without a network call, so this "
        f"is resumable.\n"
    )
    asyncio.run(warm(points, args.concurrency))


if __name__ == "__main__":
    main()
