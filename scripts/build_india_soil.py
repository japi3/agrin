"""
Build a local soil map of India, so no soil lookup ever waits on the network.

Every soil answer used to be a live query to ISRIC's SoilGrids service, and
that one dependency was behind most of the slowness and most of the failures
this system has had. Measured on 20 September 2026 a single query took 26 to
115 seconds and sometimes timed out entirely; a pin inside the urban mask
paid that once per ring of the search; and pre-warming could only ever cover
places someone thought to list, because the cache keys to eleven metres and
India is 3.29 million square kilometres -- some 27 billion possible keys.

So instead of asking about points, this downloads the map. ISRIC publishes
SoilGrids pre-aggregated to 1 km as cloud-optimised GeoTIFFs, tiled and with
overviews, so reading just the India window fetches only the tiles that
cover India rather than the planet. Every coordinate in the country then
answers from local disk in milliseconds -- a pin in a Mizoram hill field or
on Car Nicobar included.

What this gives up, stated plainly:

  - Resolution. 1 km rather than 250 m. Less than it sounds: the 250 m
    product is itself interpolated from sparse profiles and carries wide
    prediction intervals, so a 1 km average discards little real
    information about any single field.
  - Uncertainty bands. The aggregated product publishes means only, no
    Q0.05 or Q0.95. The app used those to decide when to say the soil map
    is uncertain. Local readings are therefore always reported as regional
    estimates, which is the honest description of a 1 km average anyway.

Outside India, or where the local map has no data, the app falls back to the
live service exactly as before.

Run it inside the container, where the network and rasterio both work:

    docker exec -i agrin python - < scripts/build_india_soil.py

then copy the result into the repository so the image build picks it up:

    docker cp agrin:/app/.cache/india_soilgrids_1km.tif data/soil/

Takes around 25 minutes. Safe to re-run; it overwrites the output.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

# The whole of India including both island groups and Ladakh, with a small
# margin. Lakshadweep sets the west edge, Nicobar the south, Arunachal the
# east and Ladakh the north.
WEST, SOUTH, EAST, NORTH = 68.0, 6.5, 97.5, 37.5

# 30 arc-seconds: the conventional "1 km" geographic grid, and slightly finer
# than the source so no source cell is skipped by nearest-neighbour sampling.
RES = 1 / 120

# Must match geo.soilgrids.DEFAULT_PROPERTIES and DEFAULT_DEPTHS, and in the
# same order, because the reader finds a layer by its band number.
PROPERTIES = ["clay", "sand", "silt", "phh2o", "soc", "bdod", "nitrogen", "cec"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]

SOURCE = ("https://files.isric.org/soilgrids/latest/data_aggregated/1000m/"
          "{prop}/{prop}_{depth}_mean_1000.tif")
OUTPUT = os.environ.get("AGRIN_INDIA_SOIL_OUT", "/app/.cache/india_soilgrids_1km.tif")
NODATA = -32768


def main() -> int:
    width = round((EAST - WEST) / RES)
    height = round((NORTH - SOUTH) / RES)
    transform = from_origin(WEST, NORTH, RES, RES)
    bands = [(p, d) for p in PROPERTIES for d in DEPTHS]

    print(f"India soil map: {width} x {height} cells, {len(bands)} layers", flush=True)

    tmp = OUTPUT + ".partial"
    profile = dict(
        driver="GTiff", width=width, height=height, count=len(bands),
        dtype="int16", crs="EPSG:4326", transform=transform, nodata=NODATA,
        tiled=True, blockxsize=256, blockysize=256,
        compress="deflate", predictor=2, zlevel=9,
        # Band-interleaved, and this matters more than it looks. The first
        # build used pixel interleaving, so that one point read would return
        # every layer from a single block -- and came out at 2,177 MB rather
        # than the 190 or so a one-layer test had predicted. The horizontal
        # predictor compresses by differencing neighbouring values, and with
        # pixel interleaving the neighbours are different properties at the
        # same spot: clay beside sand beside pH. Differencing unrelated
        # quantities predicts nothing and compression collapsed. By band, the
        # neighbours are the same property at adjacent spots, which is what
        # the predictor is for: 165 MB, identical values. The cost is 24 small
        # reads per point instead of one, all from local disk.
        interleave="band",
        BIGTIFF="IF_SAFER",
    )

    env = dict(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        GDAL_HTTP_MULTIRANGE="YES",
        GDAL_HTTP_MAX_RETRY="4",
        GDAL_HTTP_RETRY_DELAY="5",
        GDAL_CACHEMAX=512,
    )

    started = time.perf_counter()
    with rasterio.Env(**env), rasterio.open(tmp, "w", **profile) as out:
        for index, (prop, depth) in enumerate(bands, start=1):
            t = time.perf_counter()
            url = "/vsicurl/" + SOURCE.format(prop=prop, depth=depth)
            with rasterio.open(url) as src, WarpedVRT(
                src, crs="EPSG:4326", transform=transform,
                width=width, height=height,
                resampling=Resampling.nearest, nodata=NODATA,
            ) as vrt:
                data = vrt.read(1)
            out.write(data.astype(np.int16), index)
            out.set_band_description(index, f"{prop}_{depth}")
            land = float((data != NODATA).mean()) * 100
            print(f"  [{index:2}/{len(bands)}] {prop:9} {depth:8} "
                  f"{time.perf_counter() - t:5.0f}s  {land:.0f}% with data",
                  flush=True)

    os.replace(tmp, OUTPUT)
    size_mb = os.path.getsize(OUTPUT) / 1e6
    print(f"\nWrote {OUTPUT} ({size_mb:.0f} MB) in "
          f"{(time.perf_counter() - started) / 60:.0f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
