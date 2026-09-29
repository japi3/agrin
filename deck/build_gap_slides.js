// Three slides that were running half empty in the Canva deck.
//
// Same visual language as build_deck.js -- pixel strip, mono eyebrow, serif
// title, rounded cards, footer rule -- with the gold the Canva version uses
// for its left-hand card headers, so these drop in beside the existing nine
// without looking imported.
//
// Each slide keeps the two cards it already had and gains a full-width band
// plus a closing row, which is what fills the dead space under them. The
// band is where the argument goes and the row is where the evidence goes;
// two cards side by side had nowhere to put either.
//
//   node deck/build_gap_slides.js   ->  deck/Saathi-gap-slides.pptx

const pptxgen = require("pptxgenjs");

const BG     = "1A1611";
const RAISED = "241F18";
const BORDER = "3A3226";
const TEXT   = "F2ECE1";
const MUTED  = "B3A288";
const ACCENT = "7CB86A";   // green, right-hand card headers
const GOLD   = "D8A657";   // the Canva deck's amber, left-hand card headers
const WARN   = "C2703D";

const SERIF = "Cambria";
const SANS  = "Calibri";
const MONO  = "Courier New";

const W = 13.33, H = 7.5;
const M = 0.62;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Harnoor Singh, Japleen Kaur";
pres.title = "Saathi — added slides";

function pixelStrip(slide, seed) {
  const palette = [GOLD, TEXT, BORDER, MUTED, ACCENT, BORDER];
  let n = seed;
  const rand = () => { n = (n * 1103515245 + 12345) % 2147483648; return n / 2147483648; };
  for (let i = 0; i < 46; i++) {
    if (rand() > 0.55) continue;
    const s = 0.11 + rand() * 0.08;
    slide.addShape(pres.ShapeType.rect, {
      x: 0.2 + i * 0.28, y: rand() * 0.24, w: s, h: s,
      fill: { color: palette[Math.floor(rand() * palette.length)] },
      line: { type: "none" },
    });
  }
}

function chrome(slide, pageLabel, seed) {
  slide.background = { color: BG };
  pixelStrip(slide, seed);
  slide.addText("✳  SAATHI", {
    x: M, y: 0.42, w: 3, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 12, bold: true, color: TEXT,
  });
  slide.addText(pageLabel, {
    x: W - M - 4, y: 0.42, w: 4, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, color: MUTED, align: "right",
  });
  slide.addShape(pres.ShapeType.line, {
    x: M, y: H - 0.72, w: W - M * 2, h: 0,
    line: { color: BORDER, width: 0.75 },
  });
  slide.addText("github.com/japi3/agrin  ↗", {
    x: M, y: H - 0.6, w: 6, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: TEXT,
  });
}

function heading(slide, eyebrow, title) {
  slide.addText(eyebrow, {
    x: M, y: 0.98, w: 8, h: 0.26, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 11, bold: true, color: GOLD, charSpacing: 1.5,
  });
  slide.addText(title, {
    x: M, y: 1.24, w: W - M * 2, h: 0.72, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 36, color: TEXT,
  });
}

// A card. `lines` are bulleted; `paras` are plain paragraphs.
function card(slide, { x, y, w, h, label, tone, lines = [], paras = [] }) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.05,
    fill: { color: RAISED }, line: { color: BORDER, width: 1 },
  });
  slide.addText(label, {
    x: x + 0.26, y: y + 0.18, w: w - 0.52, h: 0.26, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11.5, bold: true, color: tone, charSpacing: 1.1,
  });
  const body = lines.length
    ? lines.map((t, i) => ({
        text: t,
        options: { bullet: true, breakLine: i !== lines.length - 1 },
      }))
    : paras.map((t, i) => ({
        text: t, options: { breakLine: i !== paras.length - 1 },
      }));
  slide.addText(body, {
    x: x + 0.26, y: y + 0.54, w: w - 0.52, h: h - 0.74,
    isTextBox: true, margin: 0, fontFace: SANS, fontSize: 12,
    color: MUTED, lineSpacing: 16, paraSpaceAfter: 4,
  });
}

// The full-width band under the two cards: one idea, stated once.
function band(slide, { y, h, label, tone, text, columns }) {
  slide.addShape(pres.ShapeType.roundRect, {
    x: M, y, w: W - M * 2, h, rectRadius: 0.05,
    fill: { color: RAISED }, line: { color: tone, width: 1 },
  });
  slide.addText(label, {
    x: M + 0.26, y: y + 0.16, w: W - M * 2 - 0.52, h: 0.26,
    isTextBox: true, margin: 0, fontFace: SANS, fontSize: 11.5,
    bold: true, color: tone, charSpacing: 1.1,
  });
  if (text) {
    slide.addText(text, {
      x: M + 0.26, y: y + 0.5, w: W - M * 2 - 0.52, h: h - 0.68,
      isTextBox: true, margin: 0, fontFace: SANS, fontSize: 12.5,
      color: MUTED, lineSpacing: 17,
    });
  }
  if (columns) {
    const colW = (W - M * 2 - 0.62) / columns.length;
    columns.forEach((col, i) => {
      slide.addText(
        col.map((t, j) => ({
          text: t, options: { bullet: true, breakLine: j !== col.length - 1 },
        })),
        {
          x: M + 0.26 + i * colW, y: y + 0.5, w: colW - 0.2, h: h - 0.68,
          isTextBox: true, margin: 0, fontFace: SANS, fontSize: 11.5,
          color: MUTED, lineSpacing: 15, paraSpaceAfter: 2,
        },
      );
    });
  }
}

// Four figures across the bottom. Evidence, not decoration: each one is
// checkable and appears somewhere in the repository.
function stats(slide, y, items) {
  const colW = (W - M * 2) / items.length;
  items.forEach(([figure, caption], i) => {
    const x = M + i * colW;
    if (i > 0) {
      slide.addShape(pres.ShapeType.line, {
        x, y: y + 0.08, w: 0, h: 0.82, line: { color: BORDER, width: 0.75 },
      });
    }
    slide.addText(figure, {
      x: x + 0.22, y, w: colW - 0.3, h: 0.5, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 30, color: GOLD,
    });
    slide.addText(caption, {
      x: x + 0.22, y: y + 0.52, w: colW - 0.3, h: 0.42, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 10.5, color: MUTED, lineSpacing: 12,
    });
  });
}

/* ---------------------------------------------------------------- 04 */
{
  const s = pres.addSlide();
  chrome(s, "04 · How it works", 59);
  heading(s, "TECHNICAL APPROACH", "How it works");

  card(s, {
    x: M, y: 2.06, w: 6.0, h: 1.82, label: "MODELS", tone: GOLD,
    lines: [
      "Gemini 3.7 Flash routes, translates and explains.",
      "Gemini multimodal handles crop photographs.",
      "Gemini audio understanding handles speech-to-text.",
      "Gemini TTS returns spoken answers.",
      "gemini-embedding-001 supports retrieval.",
    ],
  });
  card(s, {
    x: M + 6.25, y: 2.06, w: 5.84, h: 1.82,
    label: "VALIDATED AGRONOMY + DATA", tone: ACCENT,
    lines: [
      "FAO-56 Penman-Monteith, daily root-zone water balance.",
      "FAO-33 yield response to water.",
      "RothC-26.3 soil carbon, IPCC Tier 3.",
      "Disease epidemiology and NDVI crop assessment.",
      "Soil, weather, satellite, market, published advisory.",
    ],
  });

  band(s, {
    y: 4.04, h: 1.42, label: "THE RULE EVERYTHING FOLLOWS FROM", tone: GOLD,
    text:
      "The language model never computes agronomy. It routes, translates and "
      + "explains — every number a farmer acts on comes from a validated model "
      + "running on real measurements. This is not architectural preference. An "
      + "LLM asked for an irrigation depth returns a fluent, confident, "
      + "unfalsifiable number, and it is indistinguishable from a correct one to "
      + "the person standing in the field.",
  });

  stats(s, 5.66, [
    ["13", "tools the model can call"],
    ["24", "languages, voice in and out"],
    ["448", "automated tests"],
    ["66 kB", "JavaScript, gzipped"],
  ]);
  s.addNotes("The rule in the band is the thesis of the whole project. "
    + "Everything else on this slide is how it is enforced.");
}

/* ---------------------------------------------------------------- 08 */
{
  const s = pres.addSlide();
  chrome(s, "08 · How we keep AI grounded", 91);
  heading(s, "RAG + FEDERATION", "How we keep AI grounded");

  card(s, {
    x: M, y: 2.06, w: 6.0, h: 1.82, label: "SOURCE-BACKED GUIDANCE", tone: GOLD,
    paras: [
      "6,396 agriculture passages from Vikaspedia, published by C-DAC under "
        + "MeitY, embedded with gemini-embedding-001.",
      "A 0.62 similarity floor turns weak retrieval into abstention. On-topic "
        + "questions score 0.71–0.79; off-topic 0.50–0.55.",
      "Hindi and Punjabi questions retrieve English passages and answer in the "
        + "language asked.",
    ],
  });
  card(s, {
    x: M + 6.25, y: 2.06, w: 5.84, h: 1.82, label: "BRICS FEDERATION", tone: ACCENT,
    paras: [
      "Five country nodes train locally and publish weights only.",
      "A local model on another country's fields: 212 mm RMSE. The federated "
        + "model, anywhere: 59 mm. Federated then fine-tuned locally: 50 mm.",
      "Field records transmitted: zero. 209 parameters per node per round.",
    ],
  });

  band(s, {
    y: 4.04, h: 1.42, label: "THE CHECK THAT READS THE ANSWER BACK", tone: WARN,
    text:
      "Retrieval does not stop a model inventing — it lends the invention a "
      + "citation. Asked how to deworm a buffalo calf, the assistant retrieved "
      + "genuine ICAR passages giving Albendazole at 10 mg/kg, then added a "
      + "dosing schedule and a second drug that appear in no passage, and said "
      + "the government advisory recommended it. Two rounds of prompt-writing "
      + "did not stop it. Every figure in a sourced answer is now matched "
      + "against the passages it came from; unmatched figures raise a warning "
      + "naming who to confirm with. It now refuses the question outright.",
  });

  stats(s, 5.66, [
    ["0.62", "similarity floor, below which nothing is quoted"],
    ["212 → 50", "mm RMSE: a foreign model, then federated + local"],
    ["209", "parameters shared per node, per round"],
    ["0", "farm records ever transmitted"],
  ]);
  s.addNotes("The band is the strongest evidence in the deck: we found our own "
    + "worst failure and engineered a guard around it, rather than trusting a "
    + "prompt.");
}

/* ---------------------------------------------------------------- 09 */
{
  const s = pres.addSlide();
  chrome(s, "09 · Built for real farmers", 123);
  heading(s, "ACCESSIBILITY + SAFETY", "Built for real farmers");

  card(s, {
    x: M, y: 2.06, w: 6.0, h: 1.82,
    label: "BUILT FOR PEOPLE WHO MAY NOT READ", tone: GOLD,
    lines: [
      "Voice in and out in 24 languages, synthesised server-side.",
      "Named in each language — Saathi, ਸਾਥੀ, 农友, Parceiro, Umngane.",
      "Pictogram grammar: state → duration → action → quantity.",
      "Familiar units first; prices always carry “per quintal”.",
      "Decision first; the numbers sit underneath.",
    ],
  });
  card(s, {
    x: M + 6.25, y: 2.06, w: 5.84, h: 1.82, label: "HONESTY IS A FEATURE", tone: ACCENT,
    lines: [
      "Unusable crop photographs are refused, with instructions.",
      "No pesticide dose is emitted — the schema has no field for one.",
      "No price forecasting, ever.",
      "Urban-mask soil displacement is disclosed.",
      "Satellite thresholds are not claimed to be per-field accurate.",
    ],
  });

  band(s, {
    y: 4.04, h: 1.42, label: "WHAT IT REFUSES, AT EVERY LAYER", tone: WARN,
    columns: [
      [
        "Microphone — silence never becomes words",
        "Soil — a masked cell is “no data”, not a nearby guess",
        "Water balance — an uncalibrated crop is named, not guessed",
        "Diagnosis — a photo that cannot support a verdict is declined",
      ],
      [
        "Prices — today's rate and the MSP floor, never a forecast",
        "Retrieval — below 0.62 similarity, nothing is quoted",
        "Output — a figure absent from the source raises a warning",
        "Schemes — navigation, never an eligibility ruling",
      ],
    ],
  });

  slideQuote(s);
  function slideQuote(sl) {
    sl.addText(
      "A farmer told “the soil map is uncertain here — a KVK soil test would be "
      + "firmer” has been served well. One given a confident wrong number has "
      + "been harmed.",
      {
        x: M + 0.9, y: 5.68, w: W - M * 2 - 1.8, h: 0.78, isTextBox: true,
        margin: 0, fontFace: SERIF, fontSize: 15, italic: true,
        color: TEXT, align: "center", lineSpacing: 20,
      },
    );
  }
  s.addNotes("Close on the quote. The argument of the whole deck is that "
    + "refusing well is a feature, not a gap.");
}

pres.writeFile({ fileName: __dirname + "/Saathi-gap-slides.pptx" })
  .then((f) => console.log("wrote " + f));
