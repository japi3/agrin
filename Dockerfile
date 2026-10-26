# ---------------------------------------------------------------------------
# AgriN — single-container deployment
#
# Multi-stage: the frontend is built with Node, then served as static files by
# the same FastAPI process that serves the API. One container, one port, no
# reverse proxy to configure.
#
# That choice is deliberate. The realistic first deployment of this platform
# is a state agriculture department or an FPO with no platform team, and a
# system that needs an ingress controller and a separate CDN before it answers
# one question does not get deployed. It runs identically on Cloud Run, on a
# bare VPS, and on a laptop.
# ---------------------------------------------------------------------------

FROM node:22-slim AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# The soil map, fetched rather than committed.
#
# The 165 MB GeoTIFF cannot live in git -- GitHub rejects blobs that size and
# the clone would be unusable anyway -- so it is a release asset. It used to
# arrive only via `COPY data/soil/`, which works on a laptop that has built
# the map and silently does nothing on a deployment, because a git checkout
# of this repository contains that directory's README and nothing else.
#
# The cost of it silently doing nothing was not a missing feature. Every soil
# lookup fell through to the live ISRIC service, which this codebase has
# measured at 26s, 75s, and sometimes a timeout -- so the field panel took
# three minutes and came back with no soil at all. Against 6 ms from the
# local map.
#
# Downloading in a stage of its own keeps curl and its certificate chain out
# of the runtime image. The checksum is pinned: a half-downloaded GeoTIFF
# would otherwise be baked into the image and fail one coordinate at a time
# at runtime, which is far harder to diagnose than a failed build.
FROM debian:bookworm-slim AS soilmap
ARG SOIL_URL=https://github.com/japi3/agrin/releases/download/soil-v1/india_soilgrids_1km.tif
ARG SOIL_SHA256=5bf29e7256f70b40b5a3f9a44303fbb29eb1fe777427c3cd3e01be5dd31d0b2a
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fSL --retry 5 --retry-delay 5 --retry-all-errors \
         -o /india_soilgrids_1km.tif "$SOIL_URL" \
    && echo "$SOIL_SHA256  /india_soilgrids_1km.tif" | sha256sum -c -


FROM python:3.12-slim AS runtime

# GDAL runtime libraries are needed by rasterio for the Sentinel-2 COG reads.
# Installed from the slim base rather than using a GDAL image, which is ~1 GB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a source change does not invalidate the layer.
COPY requirements.txt requirements-geo.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-geo.txt

COPY packages/ ./packages/
COPY apps/api/ ./apps/api/
COPY scripts/ ./scripts/

# The local soil map of India -- see scripts/build_india_soil.py. Not under
# /app/data, which is a mounted volume and would hide anything baked into
# the image at that path.
#
# The README comes from the build context; the map itself comes from the
# stage above, so that a deployment building from a git checkout gets the
# same map a laptop does instead of quietly falling back to the live service.
COPY data/soil/README.md ./soil/
COPY --from=soilmap /india_soilgrids_1km.tif ./soil/

# The advisory corpus -- passages of published Indian agricultural guidance
# and their embeddings, built by scripts/build_advisory_index.py. Same
# reasoning as the soil map: baked in, not under /app/data, so the running
# service embeds only the incoming question and never crawls at runtime.
# Absent in a fresh checkout, and the assistant simply loses one tool.
COPY data/advisory/ ./advisory/

# The built frontend is served from where main.py expects it.
COPY --from=web /build/dist ./apps/web/dist

# Soil and satellite responses are cached to disk. On Cloud Run this is the
# container's ephemeral filesystem, so the cache warms per instance; for a
# persistent cache across revisions, mount a volume here.
ENV AGRIN_CACHE_DIR=/app/.cache \
    AGRIN_DB=/app/data/agrin.db \
    PYTHONPATH=/app/packages/agronomy:/app/packages/geo:/app/packages/rag:/app/apps/api \
    PYTHONUNBUFFERED=1
RUN mkdir -p /app/.cache /app/data

# Cloud Run injects PORT; default to 8080 for local runs.
ENV PORT=8080
EXPOSE 8080

# Run as a non-root user.
#
# Ownership changes only where the app writes. chown -R over all of /app
# rewrote every file into a fresh layer, which meant a second full copy of
# the 165 MB soil map in the image. The code and the map need only be
# readable, which they are; the cache and the database are the only paths
# written at runtime, and both are mounted volumes in any real deployment.
RUN useradd --create-home --uid 1000 agrin && chown -R agrin:agrin /app/.cache /app/data
USER agrin

# One worker: the workload is I/O-bound (waiting on SoilGrids, Open-Meteo,
# Gemini) and handled with asyncio, so extra workers multiply memory without
# adding throughput. Cloud Run scales by adding instances instead.
CMD ["sh", "-c", "exec uvicorn agrin_api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
