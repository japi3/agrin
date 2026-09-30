# 🌾 Saathi (ਸਾਥੀ / साथी) — AgriN

**Voice-first multilingual AI farming assistant for Indian farmers**
Validated agronomy (FAO-56 · FAO-33 · RothC) on live soil, weather and satellite data, with grounded advisory RAG (dense + BM25 + Reciprocal Rank Fusion) and an answer-checking layer that catches the model inventing figures.

**🚀 Live app: https://saathi-cwm2.onrender.com/**
*(Free hosting sleeps when idle: the first request after a quiet spell takes about a minute.)*

A farmer opens a blank chat box, speaks or types in their own language, and gets advice about their specific field. No dashboard, no forms, no tour.

---

## The one design decision everything follows from

> **The language model never computes agronomy.**

Gemini routes, translates and explains. Every number a farmer acts on comes from a validated model running on real measurements — FAO-56 Penman-Monteith for evapotranspiration, a daily FAO-56 root-zone water balance for irrigation, RothC-26.3 for soil carbon, published epidemiological models for disease pressure.

This is not architectural preference. An LLM asked to estimate an irrigation depth produces a fluent, confident, unfalsifiable number, and it is indistinguishable from a correct one to the person standing in the field.

---

## ✨ Features

- **Irrigation guidance** — a daily root-zone water balance on *this* field, not a calendar rule. Answers "water today or wait", and how much, in inches and pump-hours before millimetres.
- **Crop health from satellite** — Sentinel-2 NDVI compared against what the crop should have at this growth stage, calibrated per field.
- **Disease from a photograph** — Gemini multimodal names the likely problem, weighted by weather-driven infection pressure from Smith Periods, Analytis and Magarey models. **No dose is ever emitted** — the response schema has no field for one.
- **Soil profile anywhere in India** — ISRIC SoilGrids, with a 1 km map of India carried locally so every coordinate answers in ~6 ms instead of 26–115 s.
- **Crop value** — yield from the season's actual water stress (FAO-33 Ky), at today's mandi rate and the announced MSP floor. **No price forecasting**, ever.
- **Published guidance, quoted** — varieties, seed rates, spacing, seed treatment and scheme paperwork retrieved from Government of India advisory material and quoted with a link to the source page.
- **Banned-pesticide guardrail** — the CIBRC list (46 banned actives, 4 formulations, 8 withdrawn, 9 restricted) checked against both question and answer, in Gurmukhi and Devanagari as well as Latin, and by the trade names printed on the packet.
- **Government schemes** — PM-KISAN, PMFBY, KCC, Soil Health Card, PMKSY, e-NAM, with the screening questions to check before travelling. Navigation, never an eligibility ruling.
- **BRICS federation** — five country nodes train locally and publish model weights only. Field records transmitted: zero.
- **24 languages, voice in and out** — script detection happens in code before the model sees the question, so Gurmukhi in means Gurmukhi out.
- **Anything else** — it is a capable assistant, not a crop bot.

---

## 🤖 Google AI models & providers

| Component | Provider / Model | Needs | Behaviour when not configured |
|---|---|---|---|
| Conversation & tool routing | **Gemini 3.7 Flash** (`AGRIN_MODEL`) | `GEMINI_API_KEY` | The service reports it is not configured rather than guessing |
| Photo diagnosis | **Gemini multimodal**, structured output | same key | Diagnosis unavailable; other tools unaffected |
| Speech to text | **Gemini audio understanding** | same key | Typing still works; an RMS silence guard runs first so an empty recording never becomes an invented sentence |
| Text to speech | **Gemini TTS**, 24 languages | same key | Browser speech only where it genuinely has a voice for the language — never an English voice reading Gurmukhi |
| Retrieval embeddings | **`gemini-embedding-001`**, 768-dim | same key | The guidance tool abstains and says the library is unavailable |
| Production credentials | **Vertex AI** | `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` | Falls back to an AI Studio key; identical code either way |
| Satellite | **Google Earth Engine** (server-side reduction) | `GOOGLE_CLOUD_PROJECT` + credentials | Planetary Computer STAC, so it works with no Google account at all |
| Deployment | **Cloud Run** (`deploy/cloudrun.sh`) | a GCP project | Runs identically on a laptop, a VPS, Render or Hugging Face |

**Model fallback chain.** Sixteen `(key, model)` pairs are tried in order, and what is spent is remembered on disk so an exhausted daily quota is not rediscovered every request. A capacity error (503/504) is recorded against *every* key, because it is about the model; a quota error against one, because that is about the key.

---

## 🚀 Architecture

```
Farmer (voice · text · crop photo)
   │
   ├── Voice ──► [Gemini speech-to-text] ──► RMS silence guard ──► transcript
   │
   ▼
[Script detection in code]  (apps/api/agrin_api/prompts.py)
   │   Gurmukhi in → Gurmukhi out, decided before the model sees the question
   ▼
[Orchestrator — Gemini 3.7 Flash function calling]  (agrin_api/orchestrator.py)
   │   13 tools · runs concurrently · 16 key-and-model fallback pairs
   │
   ├─► COMPUTED ─────────────────────────────────────────────────────────┐
   │   irrigation · crop health · disease · carbon · crop value · soil   │
   │   [packages/agronomy]  FAO-56 · FAO-33 · RothC-26.3 · epidemiology  │
   │   [packages/geo]       SoilGrids · Open-Meteo · Sentinel-2 · mandi  │
   │                                                                      │
   ├─► RETRIEVED ────────────────────────────────────────────────────────┤
   │   [packages/rag]  dense cosine + BM25, fused by RRF (k=60)          │
   │   0.62 similarity floor → below it, nothing is quoted               │
   │                                                                      │
   └─► REMEMBERED ───────────────────────────────────────────────────────┘
       [agrin_api/storage.py]  SQLite: field, season, notes, photos
   │
   ▼
[Validation — the only stage that reads the model's own output back]
   ├── Grounding check: every figure matched against the quoted passages
   ├── CIBRC banned-pesticide scan  (packages/agronomy/pesticides.py)
   └── Refusals passed through verbatim, never papered over
   │
   ▼
[Answer in the farmer's script] ──► [Gemini TTS] ──► spoken aloud
       + evidence ledger · pictorial cards · source links
```

Full write-up, including what each layer may and may not do: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Diagram: **[deck/Saathi-architecture.png](deck/Saathi-architecture.png)**.

---

## 📂 Repository structure

```
agrin/
├── apps/
│   ├── api/agrin_api/
│   │   ├── main.py               # FastAPI: 14 endpoints, serves the built PWA
│   │   ├── orchestrator.py       # Tool-calling loop, cards, grounding check
│   │   ├── tools.py              # The 13 tools exposed to the model
│   │   ├── schemas.py            # Tool definitions — the descriptions are load-bearing
│   │   ├── llm.py                # Keys, models, cooldowns, the fallback chain
│   │   ├── prompts.py            # System prompt, script detection
│   │   ├── vision.py             # Crop photo diagnosis
│   │   ├── speech.py             # TTS and STT, with the silence guard
│   │   ├── storage.py            # SQLite: 8 tables, no ORM
│   │   └── i18n.py               # 24-language interface strings
│   └── web/                      # React 19 + TypeScript + Vite PWA (66 kB gzipped)
├── packages/
│   ├── agronomy/agronomy/
│   │   ├── fao56.py              # Penman-Monteith ET₀, dual crop coefficient
│   │   ├── waterbalance.py       # Daily root-zone balance, mass-conserving
│   │   ├── carbon.py             # RothC-26.3, IPCC Tier 3
│   │   ├── canopy.py             # NDVI → fractional cover (Carlson & Ripley)
│   │   ├── disease.py            # Smith Periods · Analytis · Magarey
│   │   ├── economics.py          # FAO-33 yield response, MSP floor
│   │   ├── pesticides.py         # CIBRC banned / withdrawn / restricted
│   │   ├── crops.py, schemes.py  # 16 calibrated crops, 6 schemes
│   │   └── data/                 # msp.json, pesticides.json — both cited and dated
│   ├── geo/geo/
│   │   ├── soilgrids.py          # ISRIC, with the local 1 km India map
│   │   ├── weather.py            # Open-Meteo forecast + ERA5 reanalysis
│   │   ├── satellite.py          # Sentinel-2 via Earth Engine / Planetary Computer
│   │   ├── mandi.py              # Agmarknet prices (data.gov.in)
│   │   └── cache.py              # Disk cache with provenance
│   └── rag/rag/
│       ├── extract.py            # Vikaspedia page → ordered blocks of text
│       ├── chunking.py           # Blocks → passages that can be quoted
│       ├── embedding.py          # gemini-embedding-001, inside a rationed quota
│       ├── bm25.py               # Okapi BM25 + Reciprocal Rank Fusion
│       ├── index.py              # NumPy brute-force cosine, no vector database
│       └── grounding.py          # Does the answer only say what the source said?
├── data/
│   ├── advisory/                 # chunks.jsonl.gz + vectors.npy + manifest.json
│   └── soil/                     # india_soilgrids_1km.tif (built, not committed)
├── federation/                   # Five country nodes, coordinator, FedAvg
├── eval/                         # Retrieval test set and measured results
├── scripts/                      # Corpus builder, evaluation, smoke test, release check
├── deploy/                       # cloudrun.sh, huggingface/
├── docs/ARCHITECTURE.md
├── deck/                         # Slide deck + architecture diagram
├── Dockerfile                    # One container: API + PWA
├── render.yaml                   # Render blueprint (free plan)
└── requirements.txt              # + requirements-geo.txt for GDAL/satellite
```

---

## 🛠️ Quickstart

### 1. Install

```bash
pip install -r requirements.txt -r requirements-geo.txt
```

`requirements-geo.txt` is split out because it pulls GDAL. Every import of it is inside a function, so leaving it out costs exactly one tool — satellite crop health — and the local soil map.

### 2. Configure

Copy `.env.example` to `.env`:

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | One AI Studio key — everything works with just this |
| `GEMINI_API_KEYS` | Comma-separated. The free tier meters per project, so a second key is a second full allowance |
| `DATA_GOV_IN_KEY` | Mandi prices. A shared demo key is used if unset, and it is rate-limited across everyone |
| `AGRIN_MODEL` | Default `gemini-3.7-flash` |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` plus `GOOGLE_CLOUD_PROJECT` to use Vertex instead of AI Studio |
| `AGRIN_INDIA_SOIL` | Path to the local soil map, if built |

### 3. Run

```bash
uvicorn agrin_api.main:app --reload --port 8080   # API + built PWA
cd apps/web && npm install && npm run dev          # frontend with hot reload
```

### 4. Build the advisory corpus (optional)

```bash
python scripts/build_advisory_index.py --languages en
```

Crawls the agriculture domain of Vikaspedia, chunks it, and embeds each passage. **Resumable**: embedding is capped at 1,000 texts per key per day, so a full corpus takes several days on one key. Most-useful-first, so a partial index is the useful part.

```bash
python scripts/check_rag.py        # is retrieval working? three questions, a verdict
```

### 5. Build the local soil map (optional, ~190 MB)

```bash
python scripts/build_india_soil.py
```

Turns every soil lookup in India from a 26–115 s network call into a ~6 ms disk read.

### 6. Tests

```bash
pytest -q                          # 490 tests, no network required
python scripts/smoke_test.py       # live end-to-end against a running server
python scripts/release_check.py    # pre-ship checks, several languages
```

---

## 📊 Evaluation

### Retrieval

`scripts/evaluate_retrieval.py` scores the advisory corpus on 35 on-topic questions in English, Hindi, Punjabi and Hinglish, 6 that name a variety code or a molecule, and 8 off-topic questions whose only correct outcome is silence (`eval/retrieval_set.json`). Measured on 4,640 passages:

| Metric | Dense only | Hybrid (dense + BM25 + RRF) |
|---|---|---|
| Right subject ranked 1st | 29/35 | 29/35 |
| Right subject in top 3 | 33/35 | 33/35 |
| Off-topic questions abstained | **8/8** | **8/8** |
| Typed token present in top passage | 5/6 | **6/6** |
| Margin at the floor | +0.043 | +0.026 |
| Search time (median) | 0.1 ms | 0.6 ms |

Hybrid buys exact tokens — a variety code or a molecule name, where being wrong is worst — and costs margin. Both abstain on everything off-topic.

```bash
python scripts/evaluate_retrieval.py                # hybrid, as deployed
python scripts/evaluate_retrieval.py --dense-only   # the comparison
```

Full reports: [eval/results_hybrid.md](eval/results_hybrid.md), [eval/results_dense.md](eval/results_dense.md). The questions were written by the team, not collected from farmers; a field test set is future work.

### Agronomy

| Component | Standard | How it is checked |
|---|---|---|
| Reference ET | FAO-56 (Allen et al. 1998) | Reproduces the paper's worked Example 18 including every intermediate term → ET₀ = 3.9 mm/day |
| Reference ET, live | — | **MAE 0.228 mm/day** against an independent implementation, 264 station-days, all five BRICS founding members |
| Water balance | FAO-56 Ch. 8 | Mass conservation closes to **< 0.5 mm over a full season**, irrigated and rainfed, sand to clay |
| Soil carbon | RothC-26.3 | Published rate-modifier equations; normalisation check *a* ≈ 1 at 9.25 °C |
| Canopy from NDVI | Carlson & Ripley (1997) | Verdict distribution against 22 real Punjab–Haryana wheat fields |
| Federation | McMahan et al. (2017) | Measured transfer experiment; sovereignty asserted as tests |

**490 automated tests** — ≈250 agronomy, 80 API, 73 retrieval, 19 federation, 15 data-layer. No network required.

### BRICS cooperation, measured

| | RMSE (mm of seasonal irrigation) |
|---|---|
| A local model on its **own** fields | 51 |
| A local model on **another country's** fields | **212** ← the cooperation problem |
| The federated model, anywhere | 59 |
| Federated, then fine-tuned locally | **50** |

**Field records transmitted: zero.** 209 model parameters per node per round. What holds between five countries holds between five states.

```bash
python federation/run_experiment.py
```

---

## 🧯 Honesty as a feature

Every claim carries provenance one tap away in the Evidence Ledger. More importantly, the system is built to say no:

- A photograph that cannot support a diagnosis is **refused**, with instructions for a better one.
- **No pesticide dose is ever emitted.** The response schema has no field for one.
- **A banned pesticide is named as banned** — and monocrotophos, which is *restricted* rather than banned, is described exactly that way, because overstating the law spends the credibility the real warnings depend on.
- **No price forecasting.** Today's rate and the MSP floor, which is a floor and not a prediction.
- Soil data displaced by the urban mask **discloses the displacement**.
- Below 0.62 similarity, **nothing is quoted**.
- **A figure absent from its source raises a warning** naming who to confirm with.

### Known limitations, stated plainly

- The advisory corpus is **4,640 of 6,396 passages** indexed, crop-production first. Embedding is rationed at 1,000 texts per key per day.
- **Retrieval does not stop the model inventing; a check does.** Asked how to deworm a buffalo calf, the assistant retrieved genuine ICAR passages giving Albendazole at 10 mg/kg, then added a dosing schedule and a second drug that appear in no passage. Two rounds of prompt-writing did not stop it; the grounding check did. It is a net, not a cure.
- Satellite **verdict thresholds** are validated at the population level, not per field. 22 real fields give 77% on track, 9% behind, 9% severely behind — the shape a productive region should have. That shows the thresholds are calibrated; it does not show any individual verdict is right.
- Federation training data is **generated, not collected** — from real soil, real climate and a validated water balance, but generated.
- A federation node holding a **single record** publishes aggregates that are that record. Production needs a k-anonymity floor. There is a test that says so.
- The advisory corpus is **English only** so far. Cross-language retrieval already works, so this costs fidelity rather than coverage.
- The retrieval **score floor is calibrated against a written test set**, not a published benchmark — none exists for Indian agricultural advisory retrieval.
- On the free Render deployment the **soil map is absent** (158 MB, not in the repository), so soil falls back to ISRIC's live service and the field panel is slow. The container carries the map; the free host cannot.

---

## 🌐 Data sources

All open-licensed, all globally available, none requiring a per-country agreement — which is what makes one platform work across every BRICS member.

| Source | Use | Licence |
|---|---|---|
| ISRIC SoilGrids 2.0 | Soil texture, pH, SOC, bulk density, CEC @ 250 m | CC BY 4.0 |
| Open-Meteo | Forecast + ERA5 reanalysis to 1940 | CC BY 4.0 |
| Copernicus Sentinel-2 | NDVI crop health, 10 m, ~5-day revisit | Copernicus open |
| Agmarknet via data.gov.in | Daily mandi prices, ~3,000 APMC markets | GODL-India |
| OpenStreetMap Nominatim | Place name → coordinates | ODbL |
| Vikaspedia (C-DAC, MeitY) | Published advisory passages, quoted with attribution | GODL-India |
| CACP / CIBRC | MSP floors; banned-pesticide list — both verified against PIB releases and dated in the data files | GODL-India |

---

## 🐳 Running with Docker

One container serves the API and the PWA. No reverse proxy to configure — the realistic first deployment is a state agriculture department or an FPO with no platform team.

```bash
docker build -t agrin .
docker run -p 8080:8080 --env-file .env agrin
```

Then open http://localhost:8080.

---

## ☁️ Deploying

### Render (free, what the live link runs on)

`render.yaml` is a blueprint: [dashboard.render.com/blueprints](https://dashboard.render.com/blueprints) → New Blueprint Instance → this repository. It prompts for `GEMINI_API_KEYS` and `DATA_GOV_IN_KEY` rather than anything being committed. Free instances sleep after 15 minutes idle and take about a minute to wake.

### Google Cloud Run (the production path)

```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
./deploy/cloudrun.sh
```

Deploys to `asia-south1` (Mumbai) — an Indian agricultural service, so latency and data residency both argue for keeping it in-country. Scale-to-zero means an off-season district costs nothing. Set `GOOGLE_GENAI_USE_VERTEXAI=true` to run against Vertex AI with workload identity instead of an API key, so there is nothing to rotate.

---

## 💸 It costs nothing to run

Every service the platform depends on is free, and that is a design constraint rather than an accident. The realistic first deployment is a state agriculture department or a farmer producer organisation, and anything that needs a purchase order before it answers one question does not get deployed.
