# Deck brief — paste this whole document into ChatGPT

---

## INSTRUCTION TO THE AI

Build a 10-slide presentation for a hackathon submission. Everything you need
is below: the facts, the numbers, the palette and the tone. Use only what is
here — **do not invent statistics, features or results.** If a number is not
in this brief, leave it out.

This project is built and running, not a proposal. Write in the past and
present tense ("we built", "it does"), never "we will" or "we plan to".

---

## 1. IDENTITY

- **Project:** AgriN — the assistant is called **Saathi** (Hindi/Punjabi for
  "companion"; ਸਾਥੀ in Gurmukhi)
- **Track:** Track 4 · AgriN & Regenerative Agricultural Intelligence
- **Theme:** BRICS Cooperation
- **Team:** Harnoor Singh, Japleen Kaur
- **Institution:** Thapar Institute of Engineering and Technology
- **Repository:** github.com/japi3/agrin
- **One-line description:** A voice-first AI farming assistant for Indian
  farmers, in 24 languages, where every number comes from a validated
  agronomic model rather than from the language model.

---

## 2. DESIGN SYSTEM

**Palette (use exactly these — warm dark earth tones, not generic tech blue):**

| Role | Hex |
|---|---|
| Background (deep) | `1A1611` |
| Surface / card | `241F18` |
| Text (cream) | `F2ECE1` |
| Muted text | `B3A288` |
| Primary accent (green) | `7CB86A` |
| Deep green | `4E8C3F` |
| Warning / caution | `C2703D` |
| Border | `3A3226` |

**Rules:**
- Dark background throughout. Cream text. Green accent used sparingly for
  emphasis, orange only for honesty/limitation content.
- Serif headings (Cambria or Georgia), sans body (Calibri or Arial).
- No decorative colour bars, no accent stripes under titles, no stock photos
  of smiling farmers.
- Every slide needs a visual element: a stat callout, an icon row, a table, a
  diagram. No plain title-and-bullets slides.
- Big numbers are the main visual device — 54–72pt figures with small labels.

**Tone:** plain, factual, unhurried. The project's whole argument is honesty,
so the deck must not oversell. No exclamation marks. No "revolutionary",
"cutting-edge", "game-changing".

---

## 3. THE CORE ARGUMENT (the spine of the whole deck)

> **The language model never computes agronomy.**
>
> Gemini routes, translates and explains. Every number a farmer acts on comes
> from a validated model — FAO-56 for evapotranspiration, a daily FAO-56
> root-zone water balance for irrigation, RothC-26.3 for soil carbon,
> published epidemiological models for disease.
>
> This is not architectural preference. An LLM asked to estimate an irrigation
> depth produces a fluent, confident, unfalsifiable number, and it is
> indistinguishable from a correct one to the person acting on it.

Every slide should trace back to this.

---

## SLIDE-BY-SLIDE CONTENT

### Slide 1 — Title

- **AgriN / Saathi**
- Subtitle: *Regenerative agricultural intelligence, in the farmer's own voice*
- Track 4 · AgriN & Regenerative Agricultural Intelligence · BRICS theme: Cooperation
- Harnoor Singh · Japleen Kaur · Thapar Institute of Engineering and Technology
- github.com/japi3/agrin

### Slide 2 — The problem

Three points, each with a visual:

1. **Advice does not reach the field.** India has roughly one extension
   worker for thousands of farmers. The advice that does arrive is general to
   a district, not specific to a field.
2. **The farmer may not read.** Most agricultural software assumes literacy,
   a smartphone habit and English. That excludes the people who most need it.
3. **An AI that guesses is worse than nothing.** A confident, invented
   irrigation depth or pesticide dose is indistinguishable from a correct one
   to the person acting on it, and they cannot afford to be wrong.

### Slide 3 — What we built

A farmer opens a blank chat box, speaks or types in their own language, and
gets advice about their specific field. No dashboard, no forms, no tour.

Big stat row:
- **24** languages, voice in and out
- **13** tools the model can call
- **428** automated tests
- **₹0** running cost — every service on a free tier

### Slide 4 — Capabilities (table or icon rows)

| Question a farmer asks | What answers it |
|---|---|
| Should I irrigate? | FAO-56 daily root-zone water balance on their field |
| How is my crop doing? | Sentinel-2 NDVI against what the crop should have at this stage |
| What is wrong with this plant? | Gemini vision, weighted by weather-driven infection pressure |
| What is my soil like? | ISRIC SoilGrids, 1 km map of India carried locally |
| What is it worth? | Yield from the season's water balance, at today's mandi rate |
| What am I entitled to? | Six government schemes, with screening questions |
| What does the book say? | Published government guidance, quoted and linked |
| Anything else | It is a capable assistant, not a crop bot |

### Slide 5 — Architecture

Use the diagram file `Saathi-architecture.png` if it can be attached.
Otherwise describe eight blocks left to right, top to bottom:

1. **Farmer** — speaks, types or photographs a leaf; 24 languages
2. **Saathi PWA** — conversation first, farm panel beside it; installs on a
   phone; 66 kB of JavaScript gzipped
3. **Speech in** — Gemini speech-to-text, with an RMS silence guard
4. **Orchestrator** — script detector (decides the reply's script in code,
   before the model sees it), Gemini 3.7 Flash function calling over 13
   tools, a fallback chain of 16 key-and-model pairs, refusals as first-class
5. **What comes back** — the answer in the farmer's own script, an evidence
   ledger, pictorial cards, Gemini text-to-speech
6. **Validated agronomy** — FAO-56, FAO-33, RothC-26.3, disease epidemiology
7. **Live data and published guidance** — soil, weather, satellite, market,
   and the advisory corpus
8. **BRICS federation** — five country nodes

### Slide 6 — Verification (the most important slide)

Headline: *This is the part we would want a judge to check first.*

| Component | Standard | How it is checked |
|---|---|---|
| Reference ET | FAO-56 (Allen et al. 1998) | Reproduces the paper's worked Example 18, including every intermediate term, to ET₀ = 3.9 mm/day |
| Reference ET, live | — | Mean absolute error **0.228 mm/day** against an independent implementation, over **264 station-days**, across all five BRICS founding members |
| Water balance | FAO-56 Ch. 8 | Mass conservation closes to **< 0.5 mm over a full season**, irrigated and rainfed, on soils from sand to clay |
| Soil carbon | RothC-26.3 | Published rate-modifier equations |
| Canopy from NDVI | Carlson & Ripley (1997) | Verdict distribution checked against 22 real Punjab–Haryana wheat fields |

**428 automated tests** — roughly 250 agronomy, 80 API, 56 retrieval, 19
federation, 15 data-layer. No network required for the unit tests.

### Slide 7 — Quoting sources instead of recalling them (the RAG slide)

The agronomic models cover what physics and measurement can settle. A great
deal of farming they cannot touch: which variety suits a district, the seed
rate per acre, the spacing, the seed treatment and its dose, how long to wait
after spraying, what documents a scheme wants.

Asked from memory, a language model answers all of these fluently and some of
them wrongly. An invented variety name or a dose off by a factor of ten reads
as authoritative, and the person acting on it cannot check.

So they are retrieved instead:

- **6,396 passages** from the agriculture domain of **Vikaspedia**, published
  by C-DAC under the Ministry of Electronics and IT — crawled from 1,570
  articles
- Embedded with **`gemini-embedding-001`**, searched by cosine similarity
- The model is handed the passages and told to state only what they say; the
  interface shows the source links beside the answer
- **It refuses.** A 0.62 similarity floor turns "nothing close enough" into
  an abstention. On-topic questions land at 0.71–0.79; off-topic at
  0.50–0.55.
- **It crosses languages.** A question in Hindi retrieves the English passage
  that answers it at 0.76; Punjabi at 0.71 — and the reply comes back in the
  language it was asked in.
- No vector database. One matrix-vector multiply, a few milliseconds.

### Slide 8 — BRICS cooperation, measured

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

- Russia's model mispredicts Brazilian fields by **404 mm**.
- **Field records transmitted: zero.** 209 model parameters per node per round.
- Sovereignty is enforced by tests, not prose: the node's route set is
  asserted exactly, and training payload size must not vary with dataset size
  — a response that grows with record count is carrying records whatever it
  is named.

### Slide 9 — Built for people who may not read

- **Voice in and out** in 24 languages, synthesised server-side. The
  browser's own speech is used only where it genuinely has a voice for the
  language — on most devices spoken Punjabi came out as an English speaker
  reading Gurmukhi phonetically.
- The assistant is **named in each language** — Saathi, ਸਾਥੀ, 农友, Parceiro,
  Umngane. The Punjabi greeting is *ਸਤ ਸ੍ਰੀ ਅਕਾਲ*, not a translated "hello".
- **A pictogram grammar** with fixed slot order: state → duration → action →
  quantity, so the pattern is learned once.
- **Familiar units first.** Water in inches and pump-hours before
  millimetres. Prices always carry "per quintal" — a farmer hearing a per-kg
  figure when it is per-quintal is out by a hundredfold.
- **Decision first.** Cards lead with "No water needed this week"; numbers sit
  underneath.

### Slide 10 — Honesty, and what we do not claim

Split the slide: what the system refuses, and what we admit.

**It is built to say no:**
- A photograph that cannot support a diagnosis is refused, with instructions
  for a better one.
- **No pesticide dose is ever emitted.** The response schema has no field for
  one — doses depend on formulation and equipment and are set by state
  agriculture departments.
- **No price forecasting.** Predicting mandi rates is genuinely hard; a
  confident guess is worse than silence.
- Soil data displaced by the urban mask discloses the displacement.

**What we do not claim:**
- Satellite verdict thresholds are validated at the population level, not per
  field. 22 real fields give 77% on track, 9% behind, 9% severely behind —
  the shape a productive region should have. That shows the thresholds are
  calibrated; it does not show any individual verdict is right.
- Federation training data is generated, not collected — from real soil, real
  climate and a validated water balance, but generated.
- The advisory corpus is English only so far; Vikaspedia publishes the same
  material in 22 more languages.

---

## 4. TECHNOLOGY LIST (for a footer, appendix, or the architecture slide)

**Google AI:** Gemini 3.7 Flash (conversation, tool orchestration, 24-language
generation) · Gemini multimodal (disease from photographs) · Gemini TTS ·
Gemini audio understanding (speech to text) · `gemini-embedding-001`
(retrieval) · Vertex AI (production path, `asia-south1` residency) · Cloud Run

**Data sources, all open-licensed:**

| Source | Use | Licence |
|---|---|---|
| ISRIC SoilGrids 2.0 | Soil texture, pH, organic carbon, bulk density @ 250 m | CC BY 4.0 |
| Open-Meteo | Forecast + ERA5 reanalysis to 1940 | CC BY 4.0 |
| Copernicus Sentinel-2 | NDVI crop health, 10 m, ~5-day revisit | Copernicus open |
| Agmarknet via data.gov.in | Daily mandi prices, ~3,000 APMC markets | GODL-India |
| OpenStreetMap Nominatim | Place name → coordinates | ODbL |
| Vikaspedia (C-DAC, MeitY) | Published advisory passages | GODL-India |

**Stack:** React 19 · TypeScript · Vite · Tailwind · FastAPI · Python 3.12 ·
NumPy · rasterio · Docker. One container serves both API and frontend — it
runs on a laptop, a VPS or Cloud Run unchanged.

**Models and standards:** FAO-56 Penman-Monteith (Allen et al. 1998) · FAO-33
yield response to water (Doorenbos & Kassam 1979) · RothC-26.3 (Coleman &
Jenkinson) · Smith Periods (1956) · Analytis (1977) · Magarey et al. (2005) ·
Carlson & Ripley (1997) · FedAvg (McMahan et al. 2017)

---

## 5. NUMBERS TO RE-CHECK BEFORE PRESENTING

These were true when this brief was written (28 September 2026). Verify
before the deck is shown:

- **Advisory passages indexed: 992 of 6,396.** The corpus is being embedded
  over several days against a free-tier daily quota. If the build has since
  completed, say 6,396; otherwise say "6,396 passages, indexed in priority
  order" and do not claim the whole corpus is live.
- **UI translations: 11 of 24 languages** carry the newest interface strings.
  The other 13 fall back to English for four labels only.
- **MSP (minimum support price) figures were verified on 28 September 2026**
  against the Cabinet's own press releases -- PIB 2260617 (kharif MS 2026-27)
  and PIB 2173567 (rabi RMS 2026-27). They are current and may be presented
  as such. Re-check after the next Cabinet revision (kharif ~May, rabi ~Oct).
- Mandi prices depend on data.gov.in, which was returning 503 recently.

---

## 6. WHAT NOT TO DO

- Do not add a "future roadmap" slide unless asked — the argument is that
  this is built.
- Do not use generic AI-in-agriculture stock imagery or clip art.
- Do not describe accuracy the project has not measured. Per-field satellite
  accuracy in particular is explicitly *not* claimed.
- Do not soften the limitations slide. It is the point of the deck.
- Do not round the verification numbers. 0.228 mm/day and 212 mm RMSE are
  exact and checkable.
