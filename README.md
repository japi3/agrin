# AgriN — Regenerative Agricultural Intelligence for the BRICS AgriN Initiative

A conversation-first agricultural platform. A farmer opens a blank chat box,
speaks or types in their own language, and gets field-specific advice grounded
in validated agronomic models running on real satellite, soil and weather data.

## The design commitment

**The language model never computes agronomy.** It routes, translates and
explains. Every number a farmer acts on comes from a validated model:
FAO-56 Penman-Monteith for evapotranspiration, a daily FAO-56 root-zone water
balance for irrigation, RothC-26.3 for soil carbon. An LLM asked to estimate
an irrigation depth produces a fluent, plausible, unfalsifiable number. This
architecture exists to prevent that.

## Verification status

| Component | Standard | Verification |
|---|---|---|
| Reference ET | FAO-56 (Allen et al. 1998) | Reproduces the paper's worked Example 18 end-to-end incl. every intermediate term |
| Reference ET, live | — | MAE **0.228 mm/day** vs Open-Meteo's independent implementation across 264 station-days, 6 sites, all 5 BRICS founders |
| Water balance | FAO-56 Ch. 8 | Mass conservation closes to <0.5 mm over a full season |
| Soil carbon | RothC-26.3 (Coleman & Jenkinson) | Published rate-modifier equations; normalisation check a≈1 at 9.25 °C |
| Soil texture | USDA Handbook 18 | 9 reference points on the textural triangle |

Unit suite: **111 tests, no network required.**

```bash
cd packages/agronomy && PYTHONPATH=. pytest tests/ -q
```

Live cross-validation (requires internet):

```bash
python scripts/validate_et0_live.py
```

## Data sources

All open-licensed, all globally available, none requiring a per-country agreement.

| Source | Use | Licence |
|---|---|---|
| ISRIC SoilGrids 2.0 | Soil texture, pH, SOC, bulk density, CEC @250 m | CC BY 4.0 |
| Open-Meteo | Forecast + ERA5 reanalysis back to 1940 | CC BY 4.0 |
| Copernicus Sentinel-2 | NDVI crop health, 10 m, ~5 day revisit | Copernicus open |
| Agmarknet via data.gov.in | Daily mandi prices, ~3,000 APMC markets | GODL-India |
| OpenStreetMap Nominatim | District lookup from coordinates | ODbL |

Satellite reads go through Google Earth Engine when credentials are present
(server-side reduction, one request per season) and fall back to Planetary
Computer STAC otherwise, so the platform works with no account at all.

## Running it

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Then open http://localhost:8080. Only `GEMINI_API_KEY` is required
(free from https://aistudio.google.com/apikey); soil, weather, satellite and
mandi prices all work without keys.

Deploy to Cloud Run:

```bash
export GOOGLE_CLOUD_PROJECT=your-project
./deploy/cloudrun.sh
```

Defaults to `asia-south1` (Mumbai) for latency and in-country data
residency. With no `GEMINI_API_KEY` set it configures Vertex AI against the
service account's own identity instead, so there is no key to rotate or leak.

## Layout

```
packages/agronomy/   Validated agronomic models + test suite
packages/geo/        Upstream data clients, caching, provenance
apps/api/            Tool layer exposed to the orchestrator
scripts/             Live validation
```
