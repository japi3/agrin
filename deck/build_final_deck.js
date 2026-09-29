// Saathi — 12-slide submission deck.
//
// Restructured after a review against the judging rubric. The previous deck
// proved the engineering and left more than half the marks underdeveloped:
// it never said how big the problem was, never showed the product working,
// and never answered how this reaches India. Those are slides 2, 3, 11 and
// 12 here.
//
// One piece of the review is not followed. It suggests cutting the BRICS
// federation as a distraction, "unless explicitly required by the track" --
// and it is: the track is "AgriN & Regenerative Agricultural Intelligence,
// BRICS theme: Cooperation". Rather than cut it, slide 10 makes it carry
// weight for the India story, since the same argument that lets five
// countries train without sharing records lets five states do it.
//
// Nothing here claims a farmer we do not have. The pilot on slide 11 is
// labelled as a plan, and the impact column on slide 12 separates what has
// been measured from what would have to be.
//
//   node deck/build_final_deck.js   ->  deck/Saathi-final.pptx

const pptxgen = require("pptxgenjs");

const BG     = "1A1611";
const RAISED = "241F18";
const SUNKEN = "12100C";
const BORDER = "3A3226";
const TEXT   = "F2ECE1";
const MUTED  = "B3A288";
const ACCENT = "7CB86A";
const GOLD   = "D8A657";
const WARN   = "C2703D";

const SERIF = "Cambria";
const SANS  = "Calibri";
const MONO  = "Courier New";

const W = 13.33, H = 7.5, M = 0.62;
const FOOT = H - 0.72;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Harnoor Singh, Japleen Kaur";
pres.title = "Saathi — AgriN";

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

function chrome(slide, label, seed) {
  slide.background = { color: BG };
  pixelStrip(slide, seed);
  slide.addText("✳  SAATHI", {
    x: M, y: 0.42, w: 3, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 12, bold: true, color: TEXT,
  });
  slide.addText(label, {
    x: W - M - 5, y: 0.42, w: 5, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, color: MUTED, align: "right",
  });
  slide.addShape(pres.ShapeType.line, {
    x: M, y: FOOT, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.75 },
  });
  slide.addText("github.com/japi3/agrin  ↗", {
    x: M, y: H - 0.6, w: 6, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: TEXT,
  });
}

function heading(slide, eyebrow, title, y = 0.98) {
  slide.addText(eyebrow, {
    x: M, y, w: 9, h: 0.26, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 11, bold: true, color: GOLD, charSpacing: 1.5,
  });
  slide.addText(title, {
    x: M, y: y + 0.26, w: W - M * 2, h: 0.7, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 34, color: TEXT,
  });
}

function box(slide, { x, y, w, h, label, tone = BORDER, fill = RAISED,
                      lines = [], paras = [], size = 12 }) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.05,
    fill: { color: fill }, line: { color: tone, width: 1 },
  });
  let top = y + 0.18;
  if (label) {
    slide.addText(label, {
      x: x + 0.24, y: top, w: w - 0.48, h: 0.26, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, bold: true,
      color: tone === BORDER ? GOLD : tone, charSpacing: 1.1,
    });
    top += 0.36;
  }
  const body = lines.length
    ? lines.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i !== lines.length - 1 } }))
    : paras.map((t, i) => ({ text: t, options: { breakLine: i !== paras.length - 1 } }));
  if (body.length) {
    slide.addText(body, {
      x: x + 0.24, y: top, w: w - 0.48, h: y + h - top - 0.16,
      isTextBox: true, margin: 0, fontFace: SANS, fontSize: size,
      color: MUTED, lineSpacing: size + 4, paraSpaceAfter: 4,
    });
  }
}

function stats(slide, y, items, tone = GOLD) {
  const colW = (W - M * 2) / items.length;
  items.forEach(([figure, caption], i) => {
    const x = M + i * colW;
    if (i > 0) {
      slide.addShape(pres.ShapeType.line, {
        x, y: y + 0.06, w: 0, h: 0.86, line: { color: BORDER, width: 0.75 },
      });
    }
    slide.addText(figure, {
      x: x + 0.2, y, w: colW - 0.28, h: 0.48, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 28, color: tone,
    });
    slide.addText(caption, {
      x: x + 0.2, y: y + 0.5, w: colW - 0.28, h: 0.46, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 10.5, color: MUTED, lineSpacing: 12,
    });
  });
}

/* =================================================================== 01 */
{
  const s = pres.addSlide();
  s.background = { color: BG };
  pixelStrip(s, 11);
  s.addShape(pres.ShapeType.ellipse, {
    x: 8.6, y: 2.2, w: 6.4, h: 6.4,
    fill: { color: "1F2B1A", transparency: 55 }, line: { type: "none" },
  });
  s.addText("ਸਾਥੀ  ·  SAATHI", {
    x: M, y: 2.15, w: 10, h: 0.42, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 13, bold: true, color: GOLD, charSpacing: 2.2,
  });
  s.addText("Regenerative agricultural\nintelligence, in the\nfarmer's own voice", {
    x: M, y: 2.66, w: 9.4, h: 2.4, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 40, color: TEXT, lineSpacing: 46,
  });
  s.addText(
    "Every actionable number comes from a validated agronomic model — "
    + "never from the language model.",
    { x: M, y: 5.16, w: 8.6, h: 0.6, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 14.5, color: ACCENT, lineSpacing: 20 });
  s.addShape(pres.ShapeType.line, {
    x: M, y: 5.98, w: 5.2, h: 0, line: { color: BORDER, width: 1 } });
  s.addText(
    "Track 4 · AgriN & Regenerative Agricultural Intelligence · BRICS theme: Cooperation\n"
    + "Harnoor Singh · Japleen Kaur · Thapar Institute of Engineering and Technology\n"
    + "github.com/japi3/agrin",
    { x: M, y: 6.14, w: 10, h: 0.78, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: MUTED, lineSpacing: 16 });
  s.addNotes("Lead with the differentiator in the subtitle. Everything else "
    + "in the deck defends that one sentence.");
}

/* =================================================================== 02 */
{
  const s = pres.addSlide();
  chrome(s, "02 · The problem", 23);
  heading(s, "THE LAST-MILE GAP", "Advice does not reach the field");

  stats(s, 2.02, [
    ["86%", "of India's farmers work two hectares or less\n(Agriculture Census 2015-16)"],
    ["1.08 ha", "average operational holding — too small to\nabsorb one wrong decision"],
    ["22", "official languages, and an assistant that\nreads is no use to someone who does not"],
  ]);

  box(s, { x: M, y: 3.24, w: 3.86, h: 1.78, label: "ADVICE IS NOT LOCAL", tone: GOLD,
    paras: ["District-level advisories cannot know this field's soil, its "
            + "sowing date, or the rain that fell on it last week."] });
  box(s, { x: M + 4.08, y: 3.24, w: 3.86, h: 1.78, label: "THE FARMER MAY NOT READ", tone: GOLD,
    paras: ["Most agricultural software assumes literacy, a smartphone habit "
            + "and English. That excludes the people who most need it."] });
  box(s, { x: M + 8.16, y: 3.24, w: 3.93, h: 1.78, label: "AN AI THAT GUESSES IS WORSE", tone: WARN,
    fill: "2A1D12",
    paras: ["A confident, invented irrigation depth is indistinguishable "
            + "from a correct one to the person standing in the field."] });

  box(s, { x: M, y: 5.2, w: W - M * 2, h: 1.36, label: "THE SAME QUESTION, TWO ANSWERS", tone: ACCENT,
    fill: SUNKEN, size: 12.5,
    paras: [
      "“Should I irrigate my wheat today?”",
      "A general chatbot:  “Wheat usually needs irrigation every 20–25 days, around crown root initiation…”",
      "Saathi:  “No water this week. Your root zone holds 62 mm and the crop needs 41 mm before Friday's rain.”",
    ] });
  s.addNotes("The contrast at the bottom is the whole pitch in three lines. "
    + "Read it aloud if you read nothing else on this slide.");
}

/* =================================================================== 03 */
{
  const s = pres.addSlide();
  chrome(s, "03 · The product, working", 41);
  heading(s, "ONE REAL EXCHANGE", "A Punjabi question, answered from a source");

  box(s, { x: M, y: 2.02, w: 6.0, h: 3.5, label: "WHAT THE FARMER SAID AND HEARD",
    tone: GOLD, fill: SUNKEN, size: 12,
    paras: [
      "🎙  “ਕਣਕ ਦੀ ਬਿਜਾਈ ਤੋਂ ਪਹਿਲਾਂ ਬੀਜ ਦਾ ਇਲਾਜ ਕੀ ਹੈ?”",
      "     (What seed treatment before sowing wheat?)",
      "",
      "🔊  “ਕਾਂਗਿਆਰੀ ਤੋਂ ਬਚਾਅ ਲਈ 40 ਕਿੱਲੋ ਬੀਜ ਨੂੰ 13 ਮਿਲੀਲੀਟਰ",
      "     ਟੈਬੂਕੋਨਾਜ਼ੋਲ 400 ਮਿਲੀਲੀਟਰ ਪਾਣੀ ਵਿੱਚ ਘੋਲ ਕੇ ਲਗਾਓ…”",
      "",
      "     Spoken back in Gurmukhi, with the source page linked beneath.",
    ] });

  box(s, { x: M + 6.25, y: 2.02, w: 5.84, h: 3.5, label: "WHAT HAPPENED IN BETWEEN",
    tone: ACCENT, size: 11.5,
    paras: [
      "1.  Speech → text, with a silence guard so an empty recording never becomes an invented sentence.",
      "2.  Script detected in code — Gurmukhi in, Gurmukhi out — before the model sees the question.",
      "3.  Gemini routes it to the guidance tool: seed treatment is written down, not computed.",
      "4.  Retrieval searches 4,096 passages of government advisory material. Best match 0.77.",
      "5.  Every figure in the reply is checked back against the passage it came from.",
      "6.  Answer read aloud in Punjabi.",
    ] });

  box(s, { x: M, y: 5.68, w: W - M * 2, h: 0.86, label: "", tone: BORDER, fill: SUNKEN,
    size: 12.5,
    paras: ["The corpus is English. The question was Punjabi. Cross-language "
            + "retrieval is what makes one corpus serve twenty-four languages — "
            + "and the source link means the farmer, or the officer they show "
            + "the phone to, can open the original page."] });
  s.addNotes("This is a real exchange from the running app, not a mock-up.");
}

/* =================================================================== 04 */
{
  const s = pres.addSlide();
  chrome(s, "04 · What it does", 59);
  heading(s, "CAPABILITIES", "What a farmer can ask today");

  const rows = [
    ["Should I irrigate?", "A daily root-zone water balance on their field — not a calendar rule."],
    ["How is my crop doing?", "Sentinel-2 greenness against what this crop should have at this stage."],
    ["What is wrong with this plant?", "Disease from a photograph, weighted by weather-driven infection pressure."],
    ["What is my soil like?", "ISRIC SoilGrids, carried locally — anywhere in India answers in ~6 ms."],
    ["What is it worth?", "Yield from the season's water balance, at today's mandi rate and the MSP floor."],
    ["What am I entitled to?", "Six government schemes, with the screening questions to check before travelling."],
    ["What does the book say?", "Varieties, seed rates, spacing, treatment — quoted, with the source link."],
  ];
  rows.forEach(([q, a], i) => {
    const y = 2.04 + i * 0.6;
    s.addText(String(i + 1).padStart(2, "0"), {
      x: M, y, w: 0.6, h: 0.36, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 17, italic: true, color: GOLD });
    s.addText(q, {
      x: M + 0.68, y: y - 0.02, w: 4.0, h: 0.36, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 13.5, bold: true, color: TEXT });
    s.addText(a, {
      x: M + 4.9, y: y - 0.02, w: 7.2, h: 0.5, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 12, color: MUTED, lineSpacing: 15 });
    if (i < rows.length - 1) {
      s.addShape(pres.ShapeType.line, {
        x: M, y: y + 0.5, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.5 } });
    }
  });
  s.addText("…and anything else. It is a capable assistant, not a crop bot.", {
    x: M, y: 6.3, w: 9, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 12, italic: true, color: MUTED });
}

/* =================================================================== 05 */
{
  const s = pres.addSlide();
  chrome(s, "05 · The rule", 77);
  heading(s, "THE TRUST LAYER", "The model never computes agronomy");

  box(s, { x: M, y: 2.06, w: 3.86, h: 1.9, label: "GEMINI UNDERSTANDS", tone: GOLD,
    size: 12,
    paras: ["Listens, detects the language, routes to a tool, explains the "
            + "result and speaks it back. It never produces the number."] });
  box(s, { x: M + 4.08, y: 2.06, w: 3.86, h: 1.9, label: "TOOLS CALCULATE", tone: ACCENT,
    size: 12,
    paras: ["FAO-56 water balance · FAO-33 yield response · RothC-26.3 soil "
            + "carbon · 12 disease models · Sentinel-2 canopy."] });
  box(s, { x: M + 8.16, y: 2.06, w: 3.93, h: 1.9, label: "VALIDATION DECIDES", tone: WARN,
    fill: "2A1D12", size: 12,
    paras: ["A tool that cannot answer abstains. A quoted answer is checked "
            + "back against its source before it is shown."] });

  box(s, { x: M, y: 4.14, w: W - M * 2, h: 1.32, label: "WHY THIS IS THE WHOLE ARCHITECTURE",
    tone: GOLD, fill: SUNKEN, size: 12.5,
    paras: ["An LLM asked for an irrigation depth returns a fluent, confident, "
            + "unfalsifiable number, and it is indistinguishable from a correct "
            + "one to the person standing in the field. Separating the two "
            + "roles is also why swapping model families mid-build touched one "
            + "file: the agronomy never depended on the model."] });

  stats(s, 5.62, [
    ["13", "tools the model can call"],
    ["24", "languages, voice in and out"],
    ["484", "automated tests"],
    ["66 kB", "JavaScript, gzipped"],
  ]);
}

/* =================================================================== 06 */
{
  const s = pres.addSlide();
  chrome(s, "06 · Architecture", 95);
  heading(s, "HOW IT FITS TOGETHER", "One question, end to end");

  const lane = (y, label, tone, text, h = 0.62) => {
    s.addShape(pres.ShapeType.roundRect, {
      x: 2.5, y, w: 8.3, h, rectRadius: 0.05,
      fill: { color: tone === BORDER ? RAISED : SUNKEN },
      line: { color: tone, width: 1.2 } });
    s.addText(label, {
      x: 2.72, y: y + 0.09, w: 2.5, h: 0.3, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, bold: true, color: tone === BORDER ? GOLD : tone });
    s.addText(text, {
      x: 5.3, y: y + 0.09, w: 5.3, h: h - 0.18, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: MUTED, lineSpacing: 14 });
  };
  const arrow = (y) => s.addShape(pres.ShapeType.line, {
    x: 6.65, y, w: 0, h: 0.2,
    line: { color: BORDER, width: 1.4, endArrowType: "triangle" } });

  lane(2.0, "FARMER", GOLD, "Voice · text · a photograph of a leaf");
  arrow(2.64);
  lane(2.86, "GEMINI 3.7 FLASH", GOLD, "Understand · translate · route · explain");
  arrow(3.5);
  lane(3.72, "TOOL ORCHESTRATOR", ACCENT,
    "13 tools · runs them concurrently · 16 key-and-model fallback pairs");
  arrow(4.36);
  lane(4.58, "VALIDATED MODELS + LIVE DATA", ACCENT,
    "FAO-56 · FAO-33 · RothC · NDVI  ×  soil · weather · satellite · market · corpus", 0.72);
  arrow(5.32);
  lane(5.54, "VALIDATION", WARN,
    "Grounded answer, or an honest refusal — in the farmer's own script", 0.62);

  box(s, { x: M, y: 2.0, w: 1.72, h: 4.16, label: "", tone: BORDER, fill: SUNKEN, size: 10.5,
    paras: ["ONE\nCONTAINER", "", "FastAPI serves the API and the app.",
            "", "Runs on a laptop, a VPS or Cloud Run, unchanged.",
            "", "No custom model training.", "", "Free tiers throughout."] });
  box(s, { x: 11.0, y: 2.0, w: 1.71, h: 4.16, label: "", tone: BORDER, fill: SUNKEN, size: 10.5,
    paras: ["EVERY STEP", "", "names its source in the evidence ledger,",
            "", "and may refuse rather than guess.", "",
            "Full diagram in the repository."] });
  s.addNotes("Do not read the layers out. Say: the farmer speaks, Gemini "
    + "routes, validated tools compute, and nothing reaches the farmer that "
    + "has not been checked.");
}

/* =================================================================== 07 */
{
  const s = pres.addSlide();
  chrome(s, "07 · Evidence", 113);
  heading(s, "WHAT WE MEASURED", "The part we would want checked first");

  const rows = [
    ["Reproduces FAO-56 Example 18", "ET₀ = 3.9 mm/day, every intermediate term",
     "the evapotranspiration is the published standard, not an approximation"],
    ["MAE 0.228 mm/day", "264 station-days, five BRICS countries",
     "it agrees with an independent implementation on live weather"],
    ["Closure < 0.5 mm per season", "irrigated and rainfed, sand to clay",
     "the water accounting conserves mass; nothing is invented or lost"],
    ["29/35 retrieval at rank 1", "35 questions, four languages, 8 off-topic",
     "the corpus returns the right subject, and stays silent when it cannot"],
    ["22 real Punjab–Haryana fields", "77% on track · 9% behind · 9% severe",
     "the satellite thresholds are calibrated at population level"],
    ["484 automated tests", "250 agronomy · 80 API · 73 retrieval · 19 federation",
     "the behaviour is pinned, and runs offline without a key"],
  ];
  rows.forEach(([figure, detail, why], i) => {
    const y = 2.04 + i * 0.7;
    s.addText(figure, {
      x: M, y, w: 3.5, h: 0.36, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 12.5, bold: true, color: TEXT });
    s.addText(detail, {
      x: M + 3.6, y, w: 3.3, h: 0.36, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, color: MUTED });
    s.addText("→ " + why, {
      x: M + 7.0, y, w: 5.1, h: 0.56, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, italic: true, color: ACCENT, lineSpacing: 13 });
    if (i < rows.length - 1) {
      s.addShape(pres.ShapeType.line, {
        x: M, y: y + 0.58, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.5 } });
    }
  });
  s.addText("Every one of these is a command in the repository, not a claim in a slide.", {
    x: M, y: 6.3, w: 10, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 12, italic: true, color: MUTED });
}

/* =================================================================== 08 */
{
  const s = pres.addSlide();
  chrome(s, "08 · Grounding", 131);
  heading(s, "THE FAILURE WE FOUND IN OUR OWN SYSTEM",
    "Retrieval was not enough");

  box(s, { x: M, y: 2.04, w: 5.9, h: 2.5, label: "WHAT WENT WRONG", tone: WARN,
    fill: "2A1D12", size: 12,
    paras: [
      "Asked how to deworm a buffalo calf, Saathi retrieved genuine ICAR "
      + "passages giving Albendazole at 10 mg/kg.",
      "",
      "It then added a dosing schedule — day 14, day 35, day 56 — and a "
      + "second drug, neither of which appears in any passage, and told the "
      + "farmer the government advisory said so.",
      "",
      "Retrieval had not removed the invention. It had lent it a citation.",
    ] });

  box(s, { x: M + 6.14, y: 2.04, w: 5.95, h: 2.5, label: "WHAT WE BUILT", tone: ACCENT,
    size: 12,
    paras: [
      "Two rounds of prompt-writing did not stop it. An instruction competes "
      + "with everything else the model is doing, on every token.",
      "",
      "So every figure in a sourced answer is now matched against the "
      + "passages it came from. Unmatched figures raise a warning naming who "
      + "to confirm with.",
      "",
      "It now refuses the question outright.",
    ] });

  box(s, { x: M, y: 4.66, w: W - M * 2, h: 1.06, label: "WHY THIS IS THE SLIDE THAT MATTERS",
    tone: GOLD, fill: SUNKEN, size: 12.5,
    paras: ["Everything else in this system polices what goes into the model. "
            + "This is the only stage that reads what came out. It is also the "
            + "difference between a demo and something a ministry could stand "
            + "behind: we found our own worst failure and engineered around it."] });

  stats(s, 5.78, [
    ["0.62", "similarity floor — below it, nothing is quoted"],
    ["8/8", "off-topic questions correctly refused"],
    ["46", "banned pesticides named, from the CIBRC list"],
    ["6/6", "typed variety codes found in the passage returned"],
  ]);
}

/* =================================================================== 09 */
{
  const s = pres.addSlide();
  chrome(s, "09 · Accessibility and safety", 149);
  heading(s, "BUILT FOR PEOPLE WHO MAY NOT READ", "And honest when it cannot help");

  box(s, { x: M, y: 2.04, w: 5.9, h: 2.42, label: "REACHING A NON-READING USER", tone: GOLD,
    lines: [
      "Voice in and out in 24 languages, synthesised server-side.",
      "Named in each language — Saathi, ਸਾਥੀ, 农友, Parceiro, Umngane.",
      "Pictogram grammar: state → duration → action → quantity.",
      "Familiar units first; prices always carry “per quintal”.",
      "Decision first; the numbers sit underneath.",
    ] });
  box(s, { x: M + 6.14, y: 2.04, w: 5.95, h: 2.42, label: "WHAT IT REFUSES, AT EVERY LAYER",
    tone: WARN, fill: "2A1D12",
    lines: [
      "Microphone — silence never becomes words.",
      "Soil — a masked cell is “no data”, not a nearby guess.",
      "Diagnosis — an unusable photograph is declined.",
      "Prices — today's rate and the MSP floor, never a forecast.",
      "Doses — high-risk figures are never generated from model memory.",
    ] });

  box(s, { x: M, y: 4.64, w: W - M * 2, h: 1.1, label: "WHERE A NUMBER MAY COME FROM",
    tone: ACCENT, fill: SUNKEN, size: 12,
    paras: ["A validated model, a live measurement, or a passage quoted with "
            + "its link. Never the model's memory. A pesticide named on the "
            + "CIBRC banned list is called out as banned — and monocrotophos, "
            + "which is restricted rather than banned, is described exactly "
            + "that way."] });

  s.addText(
    "“A farmer told ‘the soil map is uncertain here — a KVK soil test would be "
    + "firmer’ has been served well. One given a confident wrong number has been harmed.”",
    { x: M + 0.8, y: 5.92, w: W - M * 2 - 1.6, h: 0.7, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 14.5, italic: true, color: TEXT,
      align: "center", lineSpacing: 20 });
}

/* =================================================================== 10 */
{
  const s = pres.addSlide();
  chrome(s, "10 · Cooperation", 167);
  heading(s, "BRICS COOPERATION, MEASURED", "Sharing a model without sharing a farm record");

  box(s, { x: M, y: 2.04, w: 5.9, h: 2.16, label: "THE PROBLEM IS SOVEREIGNTY, NOT MODELLING",
    tone: GOLD, size: 12,
    paras: ["Cross-border agricultural cooperation founders on who holds the "
            + "data. So rather than assert that federated learning solves it, "
            + "we measured it: five country nodes, each a container holding "
            + "data it will not release."] });

  const rows = [
    ["A local model on its own fields", "51 mm"],
    ["A local model on another country's fields", "212 mm  ← the problem"],
    ["The federated model, anywhere", "59 mm"],
    ["Federated, then fine-tuned locally", "50 mm"],
  ];
  s.addText("RMSE, millimetres of seasonal irrigation", {
    x: M + 6.14, y: 2.04, w: 5.95, h: 0.28, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: ACCENT, charSpacing: 1.1 });
  rows.forEach(([label, value], i) => {
    const y = 2.44 + i * 0.44;
    s.addText(label, { x: M + 6.14, y, w: 4.2, h: 0.32, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 11.5, color: MUTED });
    s.addText(value, { x: M + 10.4, y, w: 1.7, h: 0.32, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 11.5, bold: true,
      color: i === 1 ? WARN : TEXT, align: "right" });
  });

  box(s, { x: M, y: 4.38, w: W - M * 2, h: 1.14, label: "THE SAME ARGUMENT SCALES INSIDE INDIA",
    tone: ACCENT, fill: SUNKEN, size: 12.5,
    paras: ["What holds between five countries holds between five states, or "
            + "five FPOs. A cooperative can contribute to a shared irrigation "
            + "model without handing over its members' field records — which "
            + "is the condition most Indian data-sharing agreements actually "
            + "need to meet."] });

  stats(s, 5.68, [
    ["0", "farm records ever transmitted"],
    ["209", "model parameters per node, per round"],
    ["19", "tests asserting the sovereignty claim"],
    ["5", "country nodes, running as containers"],
  ], ACCENT);
  s.addNotes("This is the track's theme. Land the last box: the sovereignty "
    + "argument is what makes state-level adoption practical.");
}

/* =================================================================== 11 */
{
  const s = pres.addSlide();
  chrome(s, "11 · Reach", 185);
  heading(s, "FROM ONE FIELD TO INDIA", "What scales is the tools, not the model");

  const phase = (x, w, tag, title, lines, tone) => {
    box(s, { x, y: 2.04, w, h: 2.6, label: tag, tone, size: 11.5, lines });
    s.addText(title, {
      x: x + 0.24, y: 2.42, w: w - 0.48, h: 0.3, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 15, color: TEXT });
  };
  phase(M, 3.86, "PHASE 1 · PILOT", "Punjab & Haryana", [
    "", "Wheat and rice, the crops already calibrated",
    "A district's KVKs as the distribution channel",
    "Punjabi, Hindi, English",
    "Measure: does the advice get acted on?",
  ], GOLD);
  phase(M + 4.08, 3.86, "PHASE 2 · ZONES", "Five agro-climatic zones", [
    "", "Add the crops of each zone as tool modules",
    "Add the corpus in each zone's language",
    "State agriculture departments and FPOs",
    "Measure: does accuracy hold outside Punjab?",
  ], ACCENT);
  phase(M + 8.16, 3.93, "PHASE 3 · NATIONAL", "India", [
    "", "24 languages already built",
    "Crop and agronomy modules added independently",
    "KVKs · FPOs · state departments · CSCs",
    "Federation lets states pool models, not records",
  ], ACCENT);

  box(s, { x: M, y: 4.82, w: W - M * 2, h: 1.24, label: "WHY THIS IS CHEAP TO EXTEND",
    tone: GOLD, fill: SUNKEN, size: 12.5,
    paras: ["A new state does not need a new model. It needs its crops "
            + "calibrated and its language switched on — and the language is "
            + "already there. Adding a crop is a coefficient table; adding a "
            + "district is a coordinate. The soil map, the satellite pipeline "
            + "and the advisory corpus are national from day one."] });

  s.addText(
    "The phases above are a plan, not traction. Saathi has no farmers yet — "
    + "the engine is built and tested; the pilot is what we are asking for.",
    { x: M, y: 6.2, w: W - M * 2, h: 0.36, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11.5, italic: true, color: WARN });
  s.addNotes("Say the caveat out loud. Judges trust a team that separates "
    + "what it built from what it hopes for.");
}

/* =================================================================== 12 */
{
  const s = pres.addSlide();
  chrome(s, "12 · Deployment and impact", 203);
  heading(s, "PILOT-READY BY DESIGN", "What it would take, and what would change");

  box(s, { x: M, y: 2.04, w: 5.9, h: 2.72, label: "A PILOT, IN FOUR WEEKS", tone: GOLD,
    size: 12,
    lines: [
      "Week 1 — deploy the container; no new infrastructure.",
      "Week 2 — onboard a KVK or department; set the districts.",
      "Week 3 — switch on the zone's languages and crop modules.",
      "Week 4 — farmers onboard; monitor answers and refusals.",
    ] });
  box(s, { x: M + 6.14, y: 2.04, w: 5.95, h: 2.72, label: "WHAT IT DOES NOT NEED",
    tone: ACCENT, size: 12,
    lines: [
      "No custom model training — Gemini plus validated tools.",
      "No new satellite or sensor infrastructure.",
      "No per-state data agreement — sources are open-licensed.",
      "No budget: every service runs on a free tier.",
    ] });

  box(s, { x: M, y: 4.94, w: 5.9, h: 1.5, label: "WHAT WE CAN ALREADY SHOW", tone: ACCENT,
    fill: SUNKEN, size: 11.5,
    paras: ["Irrigation tied to this field's measured water balance rather "
            + "than a calendar. Soil for any coordinate in India in ~6 ms. "
            + "Advice quoted from government sources with the link. A refusal "
            + "when the evidence is thin."] });
  box(s, { x: M + 6.14, y: 4.94, w: 5.95, h: 1.5, label: "WHAT A PILOT WOULD HAVE TO MEASURE",
    tone: WARN, fill: "2A1D12", size: 11.5,
    paras: ["Water saved against a district's usual practice. Whether advice "
            + "is acted on. Yield and margin against a control group. None of "
            + "these are claimed here, because none of them have been "
            + "measured — and a number we invented would undo the point of "
            + "the whole system."] });
  s.addNotes("Close on the right-hand box. The refusal to invent impact "
    + "numbers is the same discipline the product is built on.");
}

pres.writeFile({ fileName: __dirname + "/Saathi-final.pptx" })
  .then((f) => console.log("wrote " + f));
