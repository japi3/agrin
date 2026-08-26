"""
Validate the satellite canopy verdicts against a regional distribution.

The problem this solves
-----------------------
Every other model in this platform is checked against a published reference:
FAO-56 has worked examples, RothC has published rate equations, the water
balance must conserve mass. The canopy interpretation had no such check. Its
thresholds -- what counts as "on track" versus "behind" -- were set by
judgement, and judgement is exactly what a reviewer should not have to take
on trust.

Per-field ground truth would settle it, and we do not have any: no dataset
pairs a coordinate with a true sowing date and an observed outcome.

But there is a weaker check that is still worth a great deal. In an
intensively farmed region during its main season, **most fields are not
failing**. Punjab grows wheat on nearly the whole of its cultivated area
every rabi with assured irrigation, and average district yields are among the
highest in the world. If the model reports that most of those fields are
severely behind, the model is wrong -- no plausible reality makes it right.

So this samples real cropland across the region, runs the assessment with the
standard sowing window, and inspects the distribution of verdicts. It cannot
tell us whether any single verdict is correct. It can tell us whether the
thresholds are calibrated, which is the failure mode that actually matters:
a tool that cries "crop failing" at healthy fields gets ignored.

    python scripts/validate_canopy_distribution.py
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("packages/agronomy", "packages/geo"):
    sys.path.insert(0, str(ROOT / pkg))

from agronomy.canopy import (  # noqa: E402
    assess_canopy, calibrate_endpoints, looks_like_annual_cropland,
    representative_ndvi,
)
from geo.satellite import fetch_ndvi_series  # noqa: E402

# Punjab and Haryana wheat belt. Boxes deliberately avoid the major cities,
# but the urban and non-crop check below is what actually does the filtering.
REGIONS = {
    "Punjab wheat belt": (30.2, 31.4, 74.8, 76.2),
    "Haryana wheat belt": (29.2, 30.2, 75.8, 77.0),
}

# Rabi wheat in the north-western plains is sown from late October to late
# November; mid-November is the operational centre of that window and what
# state agriculture departments recommend.
WHEAT_SOWING = date(2025, 11, 15)
# Assessed in early March, when the crop is at grain fill and canopy is at or
# just past its peak -- the point at which a struggling crop is unmistakable.
ASSESS_ON = date(2026, 3, 5)


async def sample_field(lat: float, lon: float) -> dict | None:
    """Assess one point, or return None if it is not annual cropland."""
    try:
        series = await fetch_ndvi_series(
            lat, lon,
            start=date(2025, 4, 1), end=ASSESS_ON,
            # 12 scenes is enough to span a full seasonal cycle for
            # calibration while keeping each point to a manageable number of
            # windowed COG reads.
            buffer_m=100.0, max_scenes=12,
        )
    except Exception:
        return None

    if len(series.observations) < 8:
        return None

    history = [o.ndvi_mean for o in series.observations]
    if not looks_like_annual_cropland(history):
        return None

    # Only observations up to the assessment date, so this is what the tool
    # would have said on that day rather than hindsight.
    window = [(o.day, o.ndvi_mean) for o in series.observations
              if o.day <= ASSESS_ON]
    if len(window) < 6:
        return None

    judged = representative_ndvi(window, within_days=30)
    if judged is None:
        return None

    soil_ndvi, veg_ndvi = calibrate_endpoints(history)
    das = (ASSESS_ON - WHEAT_SOWING).days
    assessment = assess_canopy(
        "wheat_spring", das, judged,
        ndvi_soil=soil_ndvi, ndvi_veg=veg_ndvi,
    )
    if assessment is None:
        return None
    return {
        "lat": lat, "lon": lon, "ndvi": judged,
        "status": assessment.status.value,
        "cover": assessment.observed_cover,
        "expected": assessment.expected_cover,
    }


async def main(n: int, seed: int) -> int:
    rng = random.Random(seed)
    points: list[tuple[float, float]] = []
    per_region = max(1, n // len(REGIONS))
    for lat0, lat1, lon0, lon1 in REGIONS.values():
        for _ in range(per_region):
            points.append((rng.uniform(lat0, lat1), rng.uniform(lon0, lon1)))

    print(f"Sampling {len(points)} random points across the Punjab-Haryana "
          f"wheat belt.")
    print(f"Assessed as wheat sown {WHEAT_SOWING}, evaluated {ASSESS_ON} "
          f"({(ASSESS_ON - WHEAT_SOWING).days} days after sowing).")
    print("Non-cropland points are filtered out and reported separately.\n")

    # Points are independent, so sample them concurrently. Sequentially this
    # runs about fifty windowed COG reads per point at several seconds each,
    # which put a twenty-point survey into the hours and made the check
    # something nobody would ever run. Concurrency is bounded so we stay a
    # well-behaved client of a free service.
    results: list[dict] = []
    skipped = 0
    done = 0
    gate = asyncio.Semaphore(6)
    lock = asyncio.Lock()

    async def sample_one(lat: float, lon: float) -> None:
        nonlocal skipped, done
        async with gate:
            outcome = await sample_field(lat, lon)
        async with lock:
            done += 1
            if outcome is None:
                skipped += 1
            else:
                results.append(outcome)
            if done % 5 == 0 or done == len(points):
                print(f"  {done}/{len(points)} sampled "
                      f"({len(results)} cropland, {skipped} skipped)", flush=True)

    await asyncio.gather(*(sample_one(lat, lon) for lat, lon in points))

    if not results:
        print("\nNo usable cropland points. Cannot validate.")
        return 1

    counts = Counter(r["status"] for r in results)
    total = len(results)

    print(f"\n{'=' * 66}")
    print(f"VERDICT DISTRIBUTION over {total} cropland points")
    print(f"{'=' * 66}")
    order = ["ahead_of_expected", "on_track", "slightly_behind", "behind",
             "severely_behind", "senescing_normally", "not_emerged"]
    for status in order:
        c = counts.get(status, 0)
        if not c:
            continue
        bar = "#" * int(c / total * 40)
        print(f"  {status:20s} {c:3d}  {c / total * 100:5.1f}%  {bar}")

    healthy = sum(counts.get(s, 0) for s in
                  ("ahead_of_expected", "on_track", "slightly_behind"))
    alarming = counts.get("severely_behind", 0)

    print(f"\n  Reported healthy or near-healthy: {healthy / total * 100:.1f}%")
    print(f"  Reported severely behind:         {alarming / total * 100:.1f}%")

    mean_ndvi = sum(r["ndvi"] for r in results) / total
    mean_cover = sum(r["cover"] for r in results) / total
    mean_expected = sum(r["expected"] for r in results) / total
    print(f"\n  Mean NDVI at assessment:  {mean_ndvi:.3f}")
    print(f"  Mean modelled cover:      {mean_cover * 100:.1f}%")
    print(f"  Mean expected cover:      {mean_expected * 100:.1f}%")

    print(f"\n{'=' * 66}")
    print("INTERPRETATION")
    print(f"{'=' * 66}")
    # Punjab and Haryana rabi wheat is irrigated, input-intensive and among
    # the highest-yielding in the world. A large majority of fields being
    # reported as failing would be a calibration error, not a discovery.
    if alarming / total > 0.30:
        print("  FAIL: more than 30% of one of the world's most productive")
        print("  wheat regions is reported as severely behind. That is a")
        print("  threshold calibration error, not a finding. The expected-")
        print("  cover curve or the NDVI-to-cover scaling needs correcting.")
        return 1
    if healthy / total < 0.55:
        print("  MARGINAL: fewer than 55% of fields read as healthy. Plausible")
        print("  in a bad season, but suspicious in this region. Worth")
        print("  re-running against another season before trusting verdicts.")
        return 1
    print("  PASS: the distribution is consistent with a productive region.")
    print("  This validates that the thresholds are calibrated, NOT that any")
    print("  individual verdict is correct. Per-field accuracy still needs")
    print("  ground truth this project does not have.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.n, args.seed)))
