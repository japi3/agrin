# How AgriN is put together

One rule shapes every layer:

> **The language model never computes agronomy.**

Gemini routes, translates and explains. Every number a farmer acts on comes
from a validated model running on real measurements. That is not a stylistic
preference — an LLM asked for an irrigation depth returns a fluent,
confident, unfalsifiable number, indistinguishable from a correct one to the
person standing in the field. Everything below exists so it never has to
guess, and so that when it does guess anyway, something notices.

---

## 1. The shape of it

Seven layers. Dependencies point **downward only** — the web app knows
nothing of agronomy, the agronomy package knows nothing of HTTP, and the
data clients know nothing of the language model.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  1  CLIENT        apps/web — React PWA, 66 kB gzipped        │
  └───────────────┬─────────────────────────────────────────────┘
                  │  HTTP + Server-Sent Events
  ┌───────────────▼─────────────────────────────────────────────┐
  │  2  TRANSPORT     apps/api/main.py — FastAPI, 14 endpoints   │
  │                   serves the built frontend from the same    │
  │                   process: one container, one port           │
  └───────────────┬─────────────────────────────────────────────┘
                  │
  ┌───────────────▼─────────────────────────────────────────────┐
  │  3  ORCHESTRATOR  orchestrator.py — the tool-calling loop,   │
  │                   and the only place that talks to Gemini    │
  │                   about a conversation                       │
  └──┬──────────────────────────────────────┬───────────────────┘
     │                                      │
  ┌──▼───────────────────────┐   ┌──────────▼──────────────────┐
  │  4  TOOL LAYER           │   │  4b  PROVIDER    llm.py      │
  │  tools.py + schemas.py   │   │  keys, models, cooldowns,    │
  │  13 tools — the hard     │   │  the 16-pair fallback chain  │
  │  boundary                │   └──────────────────────────────┘
  └──┬───────────┬───────────┬──────────────┐
     │           │           │              │
  ┌──▼────────┐ ┌▼─────────┐ ┌▼───────────┐ ┌▼──────────────────┐
  │ 5 AGRONOMY│ │ 5 GEO    │ │ 5 RAG      │ │ 6 STORAGE         │
  │ pure      │ │ network  │ │ retrieval  │ │ SQLite, 8 tables  │
  │ functions │ │ clients  │ │ + grounding│ │                   │
  └───────────┘ └────┬─────┘ └─────┬──────┘ └───────────────────┘
                     │             │
              ┌──────▼─────────────▼──────────────────────────┐
              │  7  OUTSIDE WORLD                              │
              │  SoilGrids · Open-Meteo · Sentinel-2 ·         │
              │  Agmarknet · Nominatim · Vikaspedia corpus     │
              └────────────────────────────────────────────────┘

  ┌────────────────────────────────────────────────────────────┐
  │  FEDERATION  five country containers, off the request path  │
  └────────────────────────────────────────────────────────────┘
```

---

## 2. A question, all the way through

Take: *"ਕਣਕ ਦੀ ਬਿਜਾਈ ਤੋਂ ਪਹਿਲਾਂ ਬੀਜ ਦਾ ਇਲਾਜ ਕੀ ਹੈ?"* — spoken, in Punjabi.

**a. Sound becomes text.** `POST /api/transcribe`. An RMS silence guard runs
*before* the model: a recording with no speech in it is rejected outright,
because a transcription model handed silence invents a plausible sentence,
and a farmer whose recording failed would have had that fabrication answered.

**b. The script is decided in code.** `prompts.dominant_script()` counts
characters against Unicode ranges and picks the majority. The result is
stated to the model as a *rule*, not a preference. This exists because
instructing the model alone lost to conversation history — an English
question in a Punjabi thread came back in Punjabi. Deciding it outside the
model took the matter out of the model's judgement.

**c. The loop opens.** `POST /api/chat` returns an SSE stream immediately.
The orchestrator assembles the system prompt, the conversation history from
SQLite, the farmer's field, and all 13 tool schemas, then streams from
Gemini.

**d. The model routes.** It emits a `function_call` for
`look_up_official_guidance` — seed treatment is written down, not computed,
and the schema descriptions are what taught it that distinction. The
orchestrator emits `tool_start` so the UI can say *"Reading the government
advisory library"* while it works.

**e. The tool runs.** It embeds the question with `gemini-embedding-001`
(rotating keys so a key cooling down from chat does not also take retrieval
out), searches 3,968 passages by cosine similarity, applies a **0.62 floor**,
and returns the passages themselves — plus the list of quantities they
contain, plus an instruction not to state any other.

If nothing clears the floor it returns an abstention whose text tells the
model, in words, not to fall back on recall.

**f. Results flow back two ways.** To the browser as a `card` event (the
sources panel with openable links), and to the model as a `function_response`
for the next round.

**g. The model answers**, streaming as `text` events the browser renders
token by token.

**h. The answer is checked.** Before `done`, `_grounding_warning()` runs.
See §4 — this is the stage that does not exist in most systems of this shape.

**i. It is read aloud.** `POST /api/speak`, in progressively growing chunks
so the voice does not stall mid-answer.

---

## 3. What each layer may and may not do

| Layer | May | May not |
|---|---|---|
| Client | render, play audio, collect input | compute anything agronomic |
| Transport | validate, persist, stream | decide what to answer |
| Orchestrator | call tools, enforce bounds, check output | do arithmetic on results |
| Tool layer | compose domain calls, attach evidence | reach the network directly |
| `agronomy` | compute | perform I/O of any kind |
| `geo` | fetch, cache, report provenance | interpret agronomically |
| `rag` | retrieve, verify grounding | generate text |

The prohibitions matter more than the permissions. `agronomy` has no network
imports at all, which is why its ~250 tests run offline and why a reviewer
can check the FAO-56 implementation against the paper without a key.

---

## 4. The grounding check

Until retrieval was added, the architecture policed **inputs**: the model
never computes, and every number it states comes from a tool result. Nothing
inspected what the model actually wrote.

Retrieval broke that assumption, in a way that is worth stating plainly
because it is the most instructive failure in this project.

Asked for a deworming schedule for a buffalo calf, the assistant retrieved
**genuine** ICAR passages giving Albendazole at 10 mg/kg — and then wrote
back a schedule of day 14, day 35 and day 56, monthly until six months, plus
a second drug at a dose. None of it appeared in any passage. It told the
farmer the government advisory said so.

Retrieval had not removed the invention. It had lent it a citation, which is
worse: the citation is what makes an answer look checked. Someone can dose
an animal on that.

Two rounds of prompt-writing did not stop it, and there is a reason to
expect that. An instruction competes with everything else the model is doing
— be helpful, be complete, sound like it knows — and it competes afresh on
every token. A check does not compete. It runs after the answer exists.

So the orchestrator now closes a turn like this:

```
model stops emitting calls
        │
        ▼
  did this turn quote published guidance?
        │
        ├── no  ──────────────────────────────►  "done"
        │        (a computed answer carries its own provenance;
        │         its numbers came from the models, not recall)
        │
        └── yes ──►  rag.grounding.unsupported_quantities(
                         answer, state.quoted_passages)
                          │
                          ├── empty ──────────►  "done"
                          │
                          └── anything ───────►  append warning,
                                                 emit "grounding",
                                                 then "done"
```

The comparison is **forgiving about form and strict about value**.
`10mg/kg`, `10 mg / kg` and `10 mg per kg` are one quantity; 7.5 and 10 are
two. Ordinals (`14th day`), spelled-out units (`milligrams per kilogram`) and
ranges (`7.5 to 10 mg/kg`) are all normalised — each of those was added
because the real fabricated answer slipped past an earlier version.

It is deliberately narrow. Prose cannot be verified this way: paraphrase is
legitimate, and "spray again after a fortnight" for a source saying "14 days"
is translation, not invention — so fortnights are normalised rather than
flagged. Quantities are different. They are what a farmer acts on, they are
what an invented answer gets wrong, and they are comparable without
understanding the sentence around them.

Crying wolf is how a check like this gets switched off, so a clean answer
must stay clean. That is tested both ways.

The warning is **appended, not substituted**. By the time it runs the text
has streamed; and more importantly most such an answer is usually correct —
the Albendazole dose was real, only the schedule around it was not.
Withholding everything trades one harm for another. Naming who to confirm
with is what a careful person would do.

**A net, not a cure.** On that question the assistant now refuses outright,
so the check stays silent. It exists for the next question nobody tested.

---

## 5. How a failure travels

The same discipline appears at every layer, which is what makes the system
coherent rather than merely layered:

| Where | What it refuses |
|---|---|
| Microphone | silence never becomes words |
| Soil client | a masked cell is "no data", not a nearby guess |
| Water balance | an uncalibrated crop is named as uncalibrated |
| Diagnosis | a photo that cannot support a verdict is declined |
| Prices | no forecast, ever — today's rate and the MSP floor only |
| Retrieval | below 0.62, nothing is quoted |
| **Output** | **a figure not in the source raises a warning** |

A tool that cannot answer returns `abstain_reason`, the model is instructed
to pass it on verbatim rather than paper over it, and the UI renders it. The
failure reaches the farmer as a sentence they can act on — *"the soil map is
uncertain here, a KVK soil test would be firmer"* — rather than as a blank
screen or a confident wrong number.

---

## 6. Cross-cutting machinery

**Provider layer (`llm.py`).** Three API keys × several models = 16
`(key, model)` pairs tried in order. Cooldowns are persisted to disk with
absolute expiry, so an exhausted daily quota survives a restart instead of
being rediscovered request by request. Generation and embedding are metered
*differently* — 20/day/model/key versus 1,000/day/key — which is why the
advisory corpus is built by a resumable batch script over several days and
never at runtime.

**Caching.** `geo/cache.py` writes to `AGRIN_CACHE_DIR`. The India soil map
is a stronger form of the same idea: built once by
`scripts/build_india_soil.py`, baked into the image at `/app/soil`, turning a
26–115 second network call into a ~6 ms disk read. The advisory index at
`/app/advisory` follows exactly that pattern — same reasoning, same shape.

**Language.** 24 languages, pre-translated into
`apps/web/public/i18n/<lang>.json` at build time by
`scripts/build_ui_translations.py`. Doing it ahead of time means choosing a
language is instant and spends no quota; doing it lazily left a first
Punjabi visit half in English for minutes.

**Federation.** Five country containers, entirely off the request path.
Nodes publish 209 model parameters per round and zero field records —
enforced by tests that pin the route set exactly and assert that payload size
does not vary with dataset size, since a response that grows with record
count is carrying records whatever it is named.

---

## 7. Where the numbers come from

| Answer | Traces to |
|---|---|
| Irrigation depth and timing | FAO-56 daily root-zone water balance |
| Yield and what it is worth | FAO-33 Ky on the season's actual water stress |
| Soil carbon under a practice | RothC-26.3, IPCC Tier 3 |
| Disease pressure | Smith Periods · Analytis · Magarey |
| Crop health verdict | Sentinel-2 NDVI, Carlson & Ripley canopy scaling |
| Soil properties | ISRIC SoilGrids, 1 km, carried locally |
| Weather | Open-Meteo forecast and ERA5 reanalysis |
| Today's price, the MSP floor | Agmarknet; CACP, verified against PIB releases |
| Variety, seed rate, spacing, treatment | quoted from Vikaspedia, with the link |
| Anything else | the model's own words, and no citation attached |

The last two rows are the distinction the whole system turns on: the
second-to-last may carry a source, and the last may not.
