# AgriN — Regenerative Agricultural Intelligence

**Track 4 · AgriN & Regenerative Agricultural Intelligence · BRICS theme: Cooperation**

A farmer opens a blank chat box, speaks or types in their own language, and
gets advice about their specific field. No dashboard, no forms, no tour. What
they get back is grounded in validated agronomic models running on real
satellite, soil, weather and market data.

---

## The one design decision everything follows from

**The language model never computes agronomy.**

Gemini routes, translates and explains. Every number a farmer acts on comes
from a validated model — FAO-56 Penman-Monteith for evapotranspiration, a
daily FAO-56 root-zone water balance for irrigation, RothC-26.3 for soil
carbon, published epidemiological models for disease pressure.

This is not architectural preference. An LLM asked to estimate an irrigation
depth will produce a fluent, confident, unfalsifiable number, and it is
indistinguishable from a correct one to the person acting on it. Everything
below exists so the model never has to guess.

It also meant that when the project had to move from one model family to
another mid-build, the swap touched **one file**.

---

## Verification

This is the part we would want a judge to check first.

### Reference evapotranspiration reproduces the published standard

The FAO-56 implementation reproduces **Example 18 from the FAO paper's own
annex** — end-to-end, including every intermediate term: slope of the vapour
pressure curve, psychrometric constant, saturation and actual vapour
pressure, extraterrestrial radiation, clear-sky radiation, net shortwave and
longwave radiation, net radiation, and the final ET₀ of 3.9 mm/day.

```bash
cd packages/agronomy && PYTHONPATH=. pytest tests/ -q
```

### And agrees with an independent implementation on live data

Open-Meteo computes FAO-56 ET₀ separately, with its own code. Across six
sites spanning all five BRICS founding members:

**Mean absolute error 0.228 mm/day over 264 station-days.**

```bash
python scripts/validate_et0_live.py
```

### The water balance conserves mass

Every millimetre entering the root zone leaves as evapotranspiration,
drainage, or stored depletion. Closure is asserted to **< 0.5 mm over a full
season**, under irrigation and rainfed, on soils from sand to clay.

### Verification summary

| Component | Standard | How it is checked |
|---|---|---|
| Reference ET | FAO-56 (Allen et al. 1998) | Reproduces the paper's worked Example 18 including all intermediates |
| Reference ET, live | — | MAE 0.228 mm/day vs an independent implementation, 264 station-days |
| Water balance | FAO-56 Ch. 8 | Mass conservation closes < 0.5 mm per season |
| Soil carbon | RothC-26.3 (Coleman & Jenkinson) | Published rate-modifier equations; normalisation check *a* ≈ 1 at 9.25 °C |
| Disease pressure | Smith (1956), Analytis (1977), Magarey (2005) | Seasonal realism per Indian cropping calendar |
| Soil texture | USDA Handbook 18 | Nine reference points on the textural triangle |
| Canopy from NDVI | Carlson & Ripley (1997) | Per-field local scaling (Gutman & Ignatov 1998); verdict distribution checked against 22 real Punjab–Haryana wheat fields |
| Federation | McMahan et al. (2017) | Measured transfer experiment; sovereignty asserted as tests |

**197 unit tests, no network required. 19 federation tests. 18 end-to-end checks.**

---

## What it does

| Capability | Grounded in |
|---|---|
| **Irrigation** — water today or wait, and how much | FAO-56 daily root-zone water balance over real observed and forecast weather |
| **Soil** — texture, pH, carbon, water-holding capacity | ISRIC SoilGrids at 250 m |
| **Crop health** — canopy vs what this stage should have | Sentinel-2 NDVI, cloud-masked, calibrated per field |
| **Disease** — ranked diagnosis from a photograph | Gemini vision, conditioned on weather-driven infection pressure |
| **Soil carbon** — what practice changes are worth | RothC-26.3, the IPCC Tier 3 accepted method |
| **Prices** — today's mandi rates and where to sell | Agmarknet, ~3,000 regulated markets |
| **Government schemes** | PM-KISAN, PMFBY, KCC, Soil Health Card, PMKSY, e-NAM — navigation, never an eligibility ruling |
| **Published guidance** — varieties, seed rates, spacing, seed treatment, scheme paperwork | Retrieval over 17,000 passages of Government of India advisory material, quoted and linked |
| **Anything else** | It is a capable assistant, not a crop bot |

---

## Built for people who may not read

- **Voice in and out** in 24 languages, synthesised and transcribed
  server-side through Gemini. The browser's own speech is used only where it
  genuinely has a voice for the language: on most devices it has none for
  most Indian languages and silently substitutes an English voice, so spoken
  Punjabi came out as an English speaker reading Gurmukhi phonetically.
- The assistant is named in each language —
  Saathi, ਸਾਥੀ, 农友, Parceiro, Umngane. The Punjabi greeting is
  *ਸਤ ਸ੍ਰੀ ਅਕਾਲ*, not a translated "hello".
- **A pictogram grammar** with fixed slot order — state → duration → action →
  quantity — so the pattern is learned once and every later advisory is
  readable.
- **Familiar units first.** Water is quoted in inches and pump-hours before
  millimetres. Prices always carry "per quintal", because a farmer hearing a
  per-kg figure when it is per-quintal is out by a hundredfold.
- **Decision first.** Cards lead with "No water needed this week"; the
  numbers sit underneath for whoever wants them.
- **66 kB of JavaScript**, gzipped.

---

## Honesty as a feature

Every claim carries provenance — dataset, resolution, licence, method — one
tap away in the Evidence Ledger. More importantly, the system is built to
say no:

- A photograph that cannot support a diagnosis is **refused**, with
  instructions for a better one. Gemini correctly identified a synthetic test
  image as a drawing rather than a leaf and declined.
- **No pesticide dose is ever emitted.** The response schema has no field for
  one. Doses depend on formulation and equipment, are printed on the label,
  and are set by state agriculture departments.
- A crop with no market arrivals returns "out of season", and a **rate-limited
  price service returns something different** — conflating those two was a bug
  we found and fixed.
- Soil data displaced by the urban mask **discloses the displacement**.
- Satellite verdicts state that they depend on the sowing date being right.
- **No price forecasting.** Predicting mandi rates is genuinely hard; a
  confident guess is worse than silence.
- **Published details are quoted, never recalled.** See below.

### Answers that are written down rather than computed

The agronomic models cover what physics and measurement can settle — water,
carbon, yield response, disease pressure. A great deal of farming they cannot
touch: which variety suits a district, the seed rate per acre, the spacing,
the seed treatment and its dose, how long to wait after spraying, what
documents a scheme wants.

Asked from memory, a language model answers all of these fluently and some of
them wrongly. An invented variety name, a dose off by a factor of ten, a
waiting period that is too short — each reads as authoritative, and the
person acting on it has no way to check.

So these are retrieved instead. 6,396 passages of Government of India
advisory material, from the agriculture domain of Vikaspedia, embedded with
`gemini-embedding-001` and searched by cosine similarity at query time. The
model is handed the passages themselves and the instruction to state only
what they say, and the interface shows the source links beside the answer so
a farmer — or the extension officer they show the phone to — can open the
original page.

Two properties make this worth having rather than merely present:

- **It refuses.** Similarity search always returns its best matches; for a
  question the corpus does not cover, those are simply the least irrelevant
  passages, ranked just as confidently as a real answer. A score floor
  (0.62 cosine, calibrated against on- and off-topic questions that land at
  0.71–0.79 and 0.50–0.55 respectively) turns that into an abstention, and
  the tool tells the model in plain words not to fall back on its own recall.
- **It crosses languages.** The corpus is largely English; the farmers are
  not. A question typed in Hindi retrieves the English passage that answers
  it at 0.76 cosine, in Punjabi at 0.71, and the reply comes back in the
  language it was asked in.

No vector database. At this size the index is a 27 MB array and the search is
one matrix-vector multiply — a few milliseconds, with nothing extra to run.

### Known limitations, stated plainly

- The satellite **verdict thresholds** are validated at the population level
  but not per field. Sampling 22 real fields across the Punjab–Haryana wheat
  belt gives 77% on track, 9% behind and 9% severely behind — the shape a
  productive region should have. That shows the thresholds are calibrated; it
  does not show that any individual verdict is right. Per-field accuracy still
  needs ground truth this project does not have.
- Federation training data is **generated, not collected** — from real soil,
  real climate and a validated water balance, but generated. There is no
  shared BRICS farm dataset, which is the problem it exists to address.
- A federation node holding a **single record** publishes aggregates that are
  that record. Production needs a k-anonymity floor. There is a test that
  says so.
- The advisory corpus is currently **English only**, and Vikaspedia publishes
  the same material in 22 more languages. Cross-language retrieval already
  works, so this costs fidelity rather than coverage: a Marathi farmer gets a
  correct answer translated from an English passage instead of the Marathi
  passage that exists. The builder takes `--languages`; the gap is embedding
  time on a free quota, not design.
- The retrieval **score floor is calibrated by hand**, against questions
  chosen to be clearly on or off topic. There is no Indian agricultural
  advisory retrieval benchmark to tune it against, so it is set strict and
  stated rather than optimised.
- **Retrieval does not stop the model inventing; a check does.** Asked how to
  deworm a buffalo calf, the assistant retrieved genuine ICAR passages giving
  Albendazole at 10 mg/kg, then added a dosing schedule and a second drug
  that appear in no passage — and attributed all of it to the government
  advisory. Retrieval had not removed the invention, it had lent it a
  citation. Two rounds of prompt-writing did not stop it, so every answer
  that quotes a source now has its quantities compared against the passages
  it quoted, and unsupported figures raise a warning naming who to confirm
  with.

  On that question the assistant now refuses outright — "I cannot give you
  these figures from memory because an incorrect dose can be harmful to your
  animal", and sends the farmer to a vet or a KVK — and the check stays
  silent, because there is nothing unsupported to flag. Both halves of that
  matter: the refusal is what should happen, and a check that fired on a
  clean answer would teach people to ignore it.

  What has not been observed in the running app is the check firing on a real
  invented answer, because the model has stopped producing one to catch. It
  is verified against the recorded fabrication and its passages at both
  layers instead. Treat it as a net under a model that may still invent, not
  as proof that it cannot.

---

## BRICS cooperation, measured

Cross-border agricultural cooperation founders on data sovereignty, not on
technology. So rather than assert that federated learning solves it, we
measured it — five country nodes, each a container holding data it will not
release.

| | RMSE (mm of seasonal irrigation) |
|---|---|
| A local model on its **own** fields | 51 |
| A local model on **another country's** fields | **212** ← the cooperation problem |
| The federated model, anywhere | 59 |
| Federated, then fine-tuned locally | **50** |

The transfer matrix is the clearest statement: the diagonal runs 37–77 mm,
the off-diagonal 85–404 mm. Russia's model mispredicts Brazilian fields by
404 mm.

**Field records transmitted: zero.** 209 model parameters per node per round.

Sovereignty is enforced by tests, not prose: the node's route set is asserted
exactly, and training payload size must not vary with dataset size — a
response that grows with record count is carrying records whatever it is
named.

```bash
python federation/run_experiment.py          # the measured result
docker compose -f federation/docker-compose.yml up -d
python federation/coordinator.py             # over the network
```

---

## Google AI integration

| Service | Use |
|---|---|
| **Gemini 3.7 Flash** | Conversation, tool orchestration, 24-language generation |
| **Gemini multimodal** | Crop disease diagnosis from photographs, structured output |
| **Gemini TTS** | Reading advice aloud in the farmer's language |
| **Gemini audio understanding** | Transcribing spoken questions |
| **`gemini-embedding-001`** | Retrieval over the advisory corpus, including across languages |
| **Vertex AI** | Production path — IAM, VPC-SC, audit logging, `asia-south1` residency |
| **Cloud Run** | Deployment target, scale-to-zero |

Both credential paths work from identical code: an AI Studio key for zero
setup, or Vertex AI with workload identity so there is no key to rotate.

Model selection falls back down a chain on capacity errors, because flagship
capacity is genuinely tight and a farmer deciding whether to irrigate cannot
be told the model is busy.

---

## It costs nothing to run

Every service the platform depends on is free, and that is a design
constraint rather than an accident. The realistic first deployment is a state
agriculture department or a farmer producer organisation, and anything
requiring a procurement cycle before it answers one question does not get
deployed.

| Service | Cost | Key needed |
|---|---|---|
| Gemini API (AI Studio) | Free tier | Yes, free, no card |
| ISRIC SoilGrids | Free | No |
| Open-Meteo (forecast + ERA5) | Free | No |
| Microsoft Planetary Computer (Sentinel-2) | Free | No |
| OpenStreetMap Nominatim | Free | No |
| data.gov.in (Agmarknet) | Free | Yes, free, no card |

No billing account. No credit card. Nothing that requires a purchase order.

The one limit worth knowing is that the Gemini free tier allows **20 requests
per minute**, and a single conversation turn costs several. That is fine for
a farmer and tight for a live demo where someone clicks quickly, so the model
chain degrades to a slightly older Flash model rather than failing.

**Vertex AI is opt-in and off by default.** It is the right production
posture at national scale — IAM, VPC-SC, audit logging, regional data
residency — and `deploy/cloudrun.sh` is written and ready for it, but nothing
requires it and the platform is fully functional without ever enabling it.

## Data sources

All open-licensed, all globally available, none requiring a per-country
agreement — which is what makes one platform work across every BRICS member.

| Source | Use | Licence |
|---|---|---|
| ISRIC SoilGrids 2.0 | Soil texture, pH, SOC, bulk density, CEC @ 250 m | CC BY 4.0 |
| Open-Meteo | Forecast + ERA5 reanalysis to 1940 | CC BY 4.0 |
| Copernicus Sentinel-2 | NDVI crop health, 10 m, ~5-day revisit | Copernicus open |
| Agmarknet via data.gov.in | Daily mandi prices, ~3,000 APMC markets | GODL-India |
| OpenStreetMap Nominatim | Place name → coordinates | ODbL |
| Vikaspedia (C-DAC, MeitY) | Published advisory passages, quoted with attribution | GODL-India |

Satellite reads use **Google Earth Engine** when credentials are present
(server-side reduction) and fall back to Planetary Computer STAC otherwise,
so the platform works with no account at all.

---

## Running it

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Open http://localhost:8080. Only `GEMINI_API_KEY` is required — free from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Soil,
weather and satellite need no key at all.

Mandi prices work without a key too, but fall back to data.gov.in's shared
demonstration key, which is throttled across every project using it. Set
`DATA_GOV_IN_KEY` to your own (free, from data.gov.in → My Account) and the
rate limiting disappears.

Deploy to Cloud Run:

```bash
export GOOGLE_CLOUD_PROJECT=your-project
./deploy/cloudrun.sh
```

Verify a running instance:

```bash
python scripts/smoke_test.py
```

### Built for India, at India's scale

`scripts/prewarm_india.py` seeds the soil cache across 15 agricultural
regions at district spacing, so a farmer's first question is never cold
anywhere in the country. 269 points are cached; the script is resumable.

---

## Layout

```
packages/agronomy/   Validated agronomic models + 197 tests
packages/geo/        Data clients, caching, provenance
packages/rag/        Advisory corpus: extraction, chunking, retrieval
apps/api/            Gemini orchestrator, tool layer, vision
apps/web/            Conversation-first interface
federation/          Five-node BRICS federated learning
deploy/              Cloud Run and on-premise
scripts/             Live validation, smoke test, India prewarm
```
