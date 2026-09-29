// Saathi — 12-slide submission deck.
//
// This is the existing nine-slide deck refined, not replaced. Every slide
// that was there is still here with its content: the problem framing, what
// we built, "How it works" with its models and data cards, the capability
// list, the full system architecture diagram, verification, grounding and
// federation, accessibility and safety.
//
// Three slides are added, for the three things a review against the judging
// rubric found missing rather than weak:
//
//   04  one real exchange, so the product is seen and not only described
//   11  how this reaches India beyond one district
//   12  what a pilot would take, and what it would have to measure
//
// And four existing slides gain a band or a row where they had empty space:
// a quantified problem and the same question answered two ways (02), why
// each verification number matters (08), and a guide to reading the
// architecture (07).
//
// The detailed architecture diagram stays. A review called it too dense for
// a 30-second glance, which is true of any system diagram and not a reason
// to delete the one thing that shows the engineering is real -- so slide 07
// keeps it and adds a short reading order beside it.
//
//   node deck/build_submission_deck.js  ->  deck/Saathi-submission.pptx

const pptxgen = require("pptxgenjs");
const path = require("path");

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
    fontFace: SANS, fontSize: 12, bold: true, color: TEXT });
  slide.addText(label, {
    x: W - M - 5, y: 0.42, w: 5, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, color: MUTED, align: "right" });
  slide.addShape(pres.ShapeType.line, {
    x: M, y: FOOT, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.75 } });
  slide.addText("github.com/japi3/agrin  ↗", {
    x: M, y: H - 0.6, w: 6, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: TEXT });
}

function heading(slide, eyebrow, title, y = 0.98) {
  slide.addText(eyebrow, {
    x: M, y, w: 9, h: 0.26, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 11, bold: true, color: GOLD, charSpacing: 1.5 });
  slide.addText(title, {
    x: M, y: y + 0.26, w: W - M * 2, h: 0.7, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 34, color: TEXT });
}

function box(slide, { x, y, w, h, label, tone = GOLD, fill = RAISED,
                      lines = [], paras = [], size = 12 }) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.05,
    fill: { color: fill }, line: { color: tone === GOLD ? BORDER : tone, width: 1 } });
  let top = y + 0.18;
  if (label) {
    slide.addText(label, {
      x: x + 0.24, y: top, w: w - 0.48, h: 0.26, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, bold: true, color: tone, charSpacing: 1.1 });
    top += 0.36;
  }
  const body = lines.length
    ? lines.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i !== lines.length - 1 } }))
    : paras.map((t, i) => ({ text: t, options: { breakLine: i !== paras.length - 1 } }));
  if (body.length) {
    slide.addText(body, {
      x: x + 0.24, y: top, w: w - 0.48, h: y + h - top - 0.16,
      isTextBox: true, margin: 0, fontFace: SANS, fontSize: size,
      color: MUTED, lineSpacing: size + 4, paraSpaceAfter: 4 });
  }
}

function stats(slide, y, items, tone = GOLD) {
  const colW = (W - M * 2) / items.length;
  items.forEach(([figure, caption], i) => {
    const x = M + i * colW;
    if (i > 0) slide.addShape(pres.ShapeType.line, {
      x, y: y + 0.06, w: 0, h: 0.84, line: { color: BORDER, width: 0.75 } });
    slide.addText(figure, {
      x: x + 0.2, y, w: colW - 0.28, h: 0.46, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 27, color: tone });
    slide.addText(caption, {
      x: x + 0.2, y: y + 0.48, w: colW - 0.28, h: 0.44, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 10.5, color: MUTED, lineSpacing: 12 });
  });
}

/* ============================================================ 01 title */
{
  const s = pres.addSlide();
  s.background = { color: BG };
  pixelStrip(s, 11);
  s.addShape(pres.ShapeType.ellipse, {
    x: 8.6, y: 2.2, w: 6.4, h: 6.4,
    fill: { color: "1F2B1A", transparency: 55 }, line: { type: "none" } });
  s.addText("Saathi  ·  ਸਾਥੀ  🌾", {
    x: M, y: 2.08, w: 10, h: 0.5, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 25, color: TEXT });
  s.addText("Regenerative agricultural intelligence,\nin the farmer's own voice", {
    x: M, y: 2.68, w: 9.6, h: 1.7, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 38, color: TEXT, lineSpacing: 46 });
  s.addText(
    "A voice-first AI farming assistant for Indian farmers, where every "
    + "actionable number comes from a validated agronomic model rather than "
    + "the language model.",
    { x: M, y: 4.5, w: 8.4, h: 0.9, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 14, color: ACCENT, lineSpacing: 20 });
  s.addShape(pres.ShapeType.line, {
    x: M, y: 5.62, w: 5.2, h: 0, line: { color: BORDER, width: 1 } });
  s.addText(
    "TRACK 4 · AGRIN & REGENERATIVE AGRICULTURAL INTELLIGENCE\nBRICS theme: Cooperation",
    { x: M, y: 5.78, w: 10, h: 0.56, isTextBox: true, margin: 0,
      fontFace: MONO, fontSize: 10.5, bold: true, color: GOLD,
      charSpacing: 1.2, lineSpacing: 15 });
  s.addText(
    "Harnoor Singh · Japleen Kaur\nThapar Institute of Engineering and Technology\ngithub.com/japi3/agrin ↗",
    { x: M, y: 6.42, w: 10, h: 0.76, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: MUTED, lineSpacing: 15 });
}

/* ========================================================== 02 problem */
{
  const s = pres.addSlide();
  chrome(s, "02 · The problem", 23);
  heading(s, "THE PROBLEM", "The problem we're solving");

  stats(s, 1.98, [
    ["86%", "of India's farmers work two hectares or less\n(Agriculture Census 2015-16)"],
    ["1.08 ha", "average holding — too small to absorb\none wrong decision"],
    ["22", "official languages; an assistant that reads\nis no use to someone who does not"],
  ]);

  box(s, { x: M, y: 3.14, w: 3.86, h: 1.72, label: "ADVICE DOES NOT REACH THE FIELD",
    tone: GOLD, size: 11.5,
    paras: ["Extension advice is general to a district, not specific to a "
            + "farmer's field.", "", "Saathi brings field context into the conversation."] });
  box(s, { x: M + 4.08, y: 3.14, w: 3.86, h: 1.72, label: "THE FARMER MAY NOT READ",
    tone: GOLD, size: 11.5,
    paras: ["Agricultural software often assumes literacy, smartphone habits "
            + "and English.", "", "Saathi is voice-first and multilingual."] });
  box(s, { x: M + 8.16, y: 3.14, w: 3.93, h: 1.72, label: "AN AI THAT GUESSES IS WORSE",
    tone: WARN, fill: "2A1D12", size: 11.5,
    paras: ["A confident irrigation depth or pesticide dose can look correct "
            + "to the person acting on it.", "",
            "Saathi separates language-model reasoning from validated agronomy."] });

  box(s, { x: M, y: 5.04, w: W - M * 2, h: 1.44, label: "THE SAME QUESTION, TWO ANSWERS",
    tone: ACCENT, fill: SUNKEN, size: 12.5,
    paras: [
      "“Should I irrigate my wheat today?”",
      "A general chatbot:  “Wheat usually needs irrigation every 20–25 days, around crown root initiation…”",
      "Saathi:  “No water this week. Your root zone holds 62 mm and the crop needs 41 mm before Friday's rain.”",
    ] });
  s.addNotes("The three problems were already here. The statistics size them "
    + "and the contrast at the bottom is the pitch in three lines.");
}

/* ===================================================== 03 what we built */
{
  const s = pres.addSlide();
  chrome(s, "03 · What we built", 41);
  heading(s, "WHAT WE BUILT", "What we built");
  s.addText(
    "Saathi is already structured around the farmer's question, field "
    + "context, validated models and source-backed guidance.",
    { x: M, y: 1.94, w: W - M * 2, h: 0.32, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 12.5, color: MUTED });

  box(s, { x: M, y: 2.4, w: W - M * 2, h: 1.28, label: "SAATHI", tone: ACCENT,
    fill: SUNKEN, size: 13,
    paras: ["A multilingual, voice-first farming assistant that accepts text, "
            + "voice and crop photos and returns field-specific guidance in "
            + "the farmer's language — running today against live soil, "
            + "weather, satellite, market and published advisory sources."] });

  const cards = [
    ["24 LANGUAGES", "Voice in and out. Script detection is handled in code before the model sees the request."],
    ["13 TOOLS", "Gemini function calling routes questions to agronomic, data and advisory tools."],
    ["484 TESTS", "≈250 agronomy · 80 API · 73 retrieval · 19 federation · 15 data-layer."],
  ];
  cards.forEach(([label, text], i) => {
    box(s, { x: M + i * 4.08, y: 3.88, w: i === 2 ? 3.93 : 3.86, h: 1.64,
      label, tone: GOLD, size: 12, paras: [text] });
  });

  box(s, { x: M, y: 5.7, w: W - M * 2, h: 0.78, label: "", tone: ACCENT,
    fill: SUNKEN, size: 12.5,
    paras: ["Not a prototype: one container serves the API and the app, every "
            + "data source is open-licensed, and the whole system runs on "
            + "free tiers."] });
}

/* ================================================= 04 NEW · the product */
{
  const s = pres.addSlide();
  chrome(s, "04 · The product, working", 59);
  heading(s, "ONE REAL EXCHANGE", "A Punjabi question, answered from a source");

  box(s, { x: M, y: 2.0, w: 5.96, h: 3.4, label: "WHAT THE FARMER SAID AND HEARD",
    tone: GOLD, fill: SUNKEN, size: 11.5,
    paras: [
      "🎙  “ਕਣਕ ਦੀ ਬਿਜਾਈ ਤੋਂ ਪਹਿਲਾਂ ਬੀਜ ਦਾ ਇਲਾਜ ਕੀ ਹੈ?”",
      "      What seed treatment before sowing wheat?",
      "",
      "🔊  “ਕਾਂਗਿਆਰੀ ਤੋਂ ਬਚਾਅ ਲਈ 40 ਕਿੱਲੋ ਬੀਜ ਨੂੰ 13 ਮਿਲੀਲੀਟਰ",
      "      ਟੈਬੂਕੋਨਾਜ਼ੋਲ 400 ਮਿਲੀਲੀਟਰ ਪਾਣੀ ਵਿੱਚ ਘੋਲ ਕੇ ਲਗਾਓ…”",
      "",
      "      Spoken back in Gurmukhi, with the source page linked beneath —",
      "      so the farmer, or the officer they show the phone to, can",
      "      open the original.",
    ] });

  box(s, { x: M + 6.2, y: 2.0, w: 5.89, h: 3.4, label: "WHAT HAPPENED IN BETWEEN",
    tone: ACCENT, size: 11.5,
    paras: [
      "1.  Speech → text, with a silence guard so an empty recording never becomes an invented sentence.",
      "2.  Script detected in code — Gurmukhi in, Gurmukhi out — before the model sees the question.",
      "3.  Gemini routes to the guidance tool: seed treatment is written down, not computed.",
      "4.  Retrieval searches 4,640 passages of government advisory material. Best match 0.77.",
      "5.  Every figure in the reply is checked back against the passage it came from.",
      "6.  The answer is read aloud in Punjabi.",
    ] });

  box(s, { x: M, y: 5.56, w: W - M * 2, h: 0.92, label: "", tone: ACCENT,
    fill: SUNKEN, size: 12.5,
    paras: ["The corpus is English. The question was Punjabi. Cross-language "
            + "retrieval is what lets one corpus serve twenty-four languages "
            + "— and it is the difference between an assistant that sounds "
            + "knowledgeable and one that can show you where it got that."] });
  s.addNotes("A real exchange from the running app, not a mock-up.");
}

/* ==================================================== 05 how it works */
{
  const s = pres.addSlide();
  chrome(s, "05 · How it works", 77);
  heading(s, "TECHNICAL APPROACH", "How it works");

  box(s, { x: M, y: 2.04, w: 5.96, h: 2.34, label: "MODELS", tone: GOLD, size: 12,
    lines: [
      "Gemini 3.7 Flash routes, translates and explains.",
      "Gemini multimodal handles crop photographs.",
      "Gemini audio understanding handles speech-to-text.",
      "Gemini TTS returns spoken answers.",
      "gemini-embedding-001 supports retrieval.",
    ] });
  box(s, { x: M + 6.2, y: 2.04, w: 5.89, h: 2.34, label: "VALIDATED AGRONOMY + DATA",
    tone: ACCENT, size: 12,
    lines: [
      "FAO-56 Penman-Monteith and daily root-zone water balance.",
      "FAO-33 yield response to water.",
      "RothC-26.3 soil carbon model.",
      "Disease epidemiology and NDVI-based crop assessment.",
      "Soil, weather, satellite, market and published advisory sources.",
    ] });

  box(s, { x: M, y: 4.56, w: W - M * 2, h: 1.36, label: "THE RULE EVERYTHING FOLLOWS FROM",
    tone: GOLD, fill: SUNKEN, size: 12.5,
    paras: ["The language model never computes agronomy. It routes, "
            + "translates and explains — every number a farmer acts on comes "
            + "from a validated model running on real measurements. This is "
            + "not architectural preference. An LLM asked for an irrigation "
            + "depth returns a fluent, confident, unfalsifiable number, and it "
            + "is indistinguishable from a correct one to the person standing "
            + "in the field."] });

  s.addText("Gemini understands.   ·   Tools calculate.   ·   Validation decides what is shown.", {
    x: M, y: 6.1, w: W - M * 2, h: 0.36, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 15, italic: true, color: ACCENT, align: "center" });
}

/* ===================================================== 06 capabilities */
{
  const s = pres.addSlide();
  chrome(s, "06 · What Saathi does", 95);
  heading(s, "KEY CAPABILITIES", "What Saathi does");

  const rows = [
    ["01", "Ask in your language", "Voice or text in the farmer's preferred language, with spoken output."],
    ["02", "Irrigation guidance", "FAO-56 daily root-zone water balance answers whether the field needs water."],
    ["03", "Crop health", "Sentinel-2 NDVI compared with expected crop stage; Gemini vision supports plant-photo analysis."],
    ["04", "Soil & weather", "Local SoilGrids data and live weather provide field context — anywhere in India in ~6 ms."],
    ["05", "Market & schemes", "Seasonal water-balance yield plus mandi data; government schemes with screening questions."],
    ["06", "Published guidance", "Varieties, seed rates, spacing and treatment quoted from government sources, with the link."],
  ];
  rows.forEach(([n, title, text], i) => {
    const y = 2.06 + i * 0.68;
    s.addText(n, { x: M, y, w: 0.6, h: 0.34, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 17, italic: true, color: GOLD });
    s.addText(title, { x: M + 0.66, y: y - 0.02, w: 3.5, h: 0.34, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 13.5, bold: true, color: TEXT });
    s.addText(text, { x: M + 4.35, y: y - 0.02, w: 7.74, h: 0.56, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 12, color: MUTED, lineSpacing: 15 });
    if (i < rows.length - 1) s.addShape(pres.ShapeType.line, {
      x: M, y: y + 0.56, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.5 } });
  });
  s.addText("…and anything else. It is a capable assistant, not a crop bot.", {
    x: M, y: 6.24, w: 9, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 12, italic: true, color: MUTED });
}

/* ==================================================== 07 architecture */
{
  const s = pres.addSlide();
  chrome(s, "07 · System architecture", 113);
  heading(s, "SYSTEM ARCHITECTURE", "How it fits together");

  // Kept full-size. A reviewer called it dense; it is, and that is what a
  // real system looks like. The reading order beside it is the fix -- a
  // judge who knows where to start will not be put off by the rest.
  // The diagram is 3000x1860, so 1.613:1. Height is the binding constraint
  // between the title and the footer rule, so it is fixed at 4.47in and the
  // width follows from the ratio; centring it in the space left by the
  // reading column keeps it from sitting lopsided.
  const imgH = 4.47, imgW = imgH * (3000 / 1860);
  s.addImage({
    path: path.join(__dirname, "Saathi-architecture.png"),
    x: 3.44 + (W - M - 3.44 - imgW) / 2, y: 1.9, w: imgW, h: imgH,
  });

  const hints = [
    ["1", "A farmer speaks, types or photographs a leaf, in any of 24 languages."],
    ["2", "The script is decided in code before Gemini sees the question."],
    ["3", "Gemini routes to tools. It never computes the answer itself."],
    ["4", "Validated models run on live soil, weather, satellite and market data."],
    ["5", "The answer is checked, then spoken back in the farmer's own script."],
  ];
  s.addText("READ IT THIS WAY", {
    x: M, y: 1.92, w: 2.6, h: 0.26, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11, bold: true, color: GOLD, charSpacing: 1.1 });
  hints.forEach(([n, text], i) => {
    const y = 2.3 + i * 0.86;
    s.addText(n, { x: M, y, w: 0.3, h: 0.28, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 15, italic: true, color: ACCENT });
    s.addText(text, { x: M + 0.32, y, w: 2.34, h: 0.8, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 10.5, color: MUTED, lineSpacing: 13 });
  });
  s.addNotes("Do not read the diagram out. Walk the five numbers on the left "
    + "and let the picture carry the rest.");
}

/* ===================================================== 08 verification */
{
  const s = pres.addSlide();
  chrome(s, "08 · Verification", 131);
  heading(s, "VERIFICATION", "How we verify it");

  const rows = [
    ["REFERENCE ET", "FAO-56 worked Example 18 reproduced, including every intermediate term → ET₀ = 3.9 mm/day.",
     "the evapotranspiration is the published standard, not an approximation"],
    ["LIVE REFERENCE ET", "MAE 0.228 mm/day against an independent implementation, 264 station-days, five BRICS members.",
     "it agrees with someone else's code on live weather"],
    ["WATER BALANCE", "Mass conservation closes to < 0.5 mm over a full season, irrigated and rainfed, sand to clay.",
     "the water accounting invents nothing and loses nothing"],
    ["RETRIEVAL", "29/35 questions return the right subject first; 8/8 off-topic questions are refused.",
     "the corpus answers what it knows and stays silent otherwise"],
    ["NDVI CHECK", "Verdict distribution checked against 22 real Punjab–Haryana wheat fields.",
     "the satellite thresholds are calibrated at population level"],
    ["484 AUTOMATED TESTS", "≈250 agronomy · 80 API · 73 retrieval · 19 federation · 15 data-layer. No network needed.",
     "the behaviour is pinned, and a reviewer can run it without a key"],
  ];
  rows.forEach(([label, detail, why], i) => {
    const y = 2.02 + i * 0.72;
    s.addText(label, { x: M, y, w: 2.5, h: 0.32, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11, bold: true, color: GOLD, charSpacing: 1 });
    s.addText(detail, { x: M + 2.6, y: y - 0.02, w: 5.2, h: 0.6, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 11, color: MUTED, lineSpacing: 13 });
    s.addText("→ " + why, { x: M + 7.95, y: y - 0.02, w: 4.14, h: 0.6, isTextBox: true,
      margin: 0, fontFace: SANS, fontSize: 10.5, italic: true, color: ACCENT, lineSpacing: 13 });
    if (i < rows.length - 1) s.addShape(pres.ShapeType.line, {
      x: M, y: y + 0.6, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.5 } });
  });
  s.addText("Every one of these is a command in the repository, not a claim in a slide.", {
    x: M, y: 6.34, w: 10, h: 0.3, isTextBox: true, margin: 0,
    fontFace: SANS, fontSize: 11.5, italic: true, color: MUTED });
}

/* ======================================================== 09 grounding */
{
  const s = pres.addSlide();
  chrome(s, "09 · How we keep AI grounded", 149);
  heading(s, "RAG + FEDERATION", "How we keep AI grounded");

  box(s, { x: M, y: 2.02, w: 5.96, h: 1.92, label: "SOURCE-BACKED GUIDANCE",
    tone: GOLD, size: 11.5,
    paras: [
      "6,396 agriculture passages from Vikaspedia, published by C-DAC under MeitY.",
      "A 0.62 similarity floor turns weak retrieval into abstention: on-topic questions score 0.65–0.80, off-topic 0.52–0.60.",
      "Hindi and Punjabi questions retrieve English source passages and answer in the language asked.",
    ] });
  box(s, { x: M + 6.2, y: 2.02, w: 5.89, h: 1.92, label: "BRICS FEDERATION",
    tone: ACCENT, size: 11.5,
    paras: [
      "Five country nodes train locally and publish weights only.",
      "A local model on another country's fields: 212 mm RMSE. The federated model, anywhere: 59 mm. Federated then fine-tuned: 50 mm.",
      "Field records transmitted: zero. What holds between five countries holds between five states.",
    ] });

  box(s, { x: M, y: 4.1, w: W - M * 2, h: 1.44, label: "THE CHECK THAT READS THE ANSWER BACK",
    tone: WARN, fill: "2A1D12", size: 12,
    paras: ["Retrieval does not stop a model inventing — it lends the "
            + "invention a citation. Asked how to deworm a buffalo calf, the "
            + "assistant retrieved genuine ICAR passages giving Albendazole at "
            + "10 mg/kg, then added a dosing schedule and a second drug that "
            + "appear in no passage, and said the government advisory "
            + "recommended it. Two rounds of prompt-writing did not stop it. "
            + "Every figure in a sourced answer is now matched against the "
            + "passages it came from; unmatched figures raise a warning naming "
            + "who to confirm with. It now refuses the question outright."] });

  stats(s, 5.68, [
    ["4,640", "passages indexed so far, crop production first"],
    ["8/8", "off-topic questions correctly refused"],
    ["46", "banned pesticides named, from the CIBRC list"],
    ["0", "farm records ever transmitted between nodes"],
  ]);
}

/* ==================================================== 10 accessibility */
{
  const s = pres.addSlide();
  chrome(s, "10 · Accessibility and safety", 167);
  heading(s, "ACCESSIBILITY + SAFETY", "Built for real farmers");

  box(s, { x: M, y: 2.02, w: 5.96, h: 2.16, label: "BUILT FOR PEOPLE WHO MAY NOT READ",
    tone: GOLD, size: 11.5,
    lines: [
      "Voice in and out in 24 languages.",
      "Named in each language — Saathi, ਸਾਥੀ, 农友, Parceiro, Umngane.",
      "Pictogram grammar: state → duration → action → quantity.",
      "Familiar units first; prices carry “per quintal”.",
      "Decision-first cards; numbers sit underneath.",
    ] });
  box(s, { x: M + 6.2, y: 2.02, w: 5.89, h: 2.16, label: "HONESTY IS A FEATURE",
    tone: ACCENT, size: 11.5,
    lines: [
      "Unusable crop photographs are refused.",
      "No pesticide dose is emitted by the system.",
      "No price forecasting.",
      "Urban-mask soil displacement is disclosed.",
      "Satellite thresholds are not claimed to be per-field accurate.",
    ] });

  box(s, { x: M, y: 4.34, w: W - M * 2, h: 1.42, label: "WHAT IT REFUSES, AT EVERY LAYER",
    tone: WARN, fill: "2A1D12", size: 11,
    paras: [
      "Microphone — silence never becomes words     ·     Soil — a masked cell is “no data”, not a nearby guess",
      "Water balance — an uncalibrated crop is named, not guessed     ·     Diagnosis — an unusable photo is declined",
      "Prices — today's rate and the MSP floor, never a forecast     ·     Retrieval — below 0.62, nothing is quoted",
      "Output — a figure absent from the source raises a warning     ·     Schemes — navigation, never an eligibility ruling",
    ] });

  s.addText(
    "“A farmer told ‘the soil map is uncertain here — a KVK soil test would be "
    + "firmer’ has been served well. One given a confident wrong number has been harmed.”",
    { x: M + 0.8, y: 5.94, w: W - M * 2 - 1.6, h: 0.64, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 14, italic: true, color: TEXT,
      align: "center", lineSpacing: 19 });
}

/* ======================================================= 11 NEW · reach */
{
  const s = pres.addSlide();
  chrome(s, "11 · Reach across India", 185);
  heading(s, "FROM ONE FIELD TO INDIA", "What scales is the tools, not the model");

  const phase = (x, w, tag, title, lines, tone) => {
    box(s, { x, y: 2.02, w, h: 2.56, label: tag, tone, size: 11, lines });
    s.addText(title, { x: x + 0.24, y: 2.4, w: w - 0.48, h: 0.3, isTextBox: true,
      margin: 0, fontFace: SERIF, fontSize: 15, color: TEXT });
  };
  phase(M, 3.86, "PHASE 1 · PILOT", "Punjab & Haryana", [
    "", "Wheat and rice — already calibrated",
    "A district's KVKs as the distribution channel",
    "Punjabi, Hindi, English",
    "Measure: is the advice acted on?",
  ], GOLD);
  phase(M + 4.08, 3.86, "PHASE 2 · ZONES", "Five agro-climatic zones", [
    "", "Each zone's crops added as tool modules",
    "Each zone's language switched on",
    "State agriculture departments and FPOs",
    "Measure: does accuracy hold outside Punjab?",
  ], ACCENT);
  phase(M + 8.16, 3.93, "PHASE 3 · NATIONAL", "India", [
    "", "24 languages already built",
    "Agronomy modules added independently",
    "KVKs · FPOs · state departments · CSCs",
    "States pool models, never records",
  ], ACCENT);

  box(s, { x: M, y: 4.76, w: W - M * 2, h: 1.26, label: "WHY THIS IS CHEAP TO EXTEND",
    tone: GOLD, fill: SUNKEN, size: 12.5,
    paras: ["A new state does not need a new model. It needs its crops "
            + "calibrated and its language switched on — and the language is "
            + "already there. Adding a crop is a coefficient table; adding a "
            + "district is a coordinate. The soil map, the satellite pipeline "
            + "and the advisory corpus are national from day one."] });

  s.addText(
    "The phases above are a plan, not traction. Saathi has no farmers yet — "
    + "the engine is built and tested; the pilot is what we are asking for.",
    { x: M, y: 6.16, w: W - M * 2, h: 0.34, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 11.5, italic: true, color: WARN });
  s.addNotes("Say the caveat out loud. Judges trust a team that separates "
    + "what it built from what it hopes for.");
}

/* ================================================== 12 NEW · deployment */
{
  const s = pres.addSlide();
  chrome(s, "12 · Deployment and impact", 203);
  heading(s, "PILOT-READY BY DESIGN", "What it would take, and what would change");

  box(s, { x: M, y: 2.02, w: 5.96, h: 2.6, label: "A PILOT, IN FOUR WEEKS", tone: GOLD,
    size: 12,
    lines: [
      "Week 1 — deploy the container. No new infrastructure.",
      "Week 2 — onboard a KVK or department; set the districts.",
      "Week 3 — switch on the zone's languages and crop modules.",
      "Week 4 — farmers onboard; monitor answers and refusals.",
    ] });
  box(s, { x: M + 6.2, y: 2.02, w: 5.89, h: 2.6, label: "WHAT IT DOES NOT NEED",
    tone: ACCENT, size: 12,
    lines: [
      "No custom model training — Gemini plus validated tools.",
      "No new satellite or sensor infrastructure.",
      "No per-state data agreement — sources are open-licensed.",
      "No budget: every service runs on a free tier.",
    ] });

  box(s, { x: M, y: 4.8, w: 5.96, h: 1.52, label: "WHAT WE CAN ALREADY SHOW",
    tone: ACCENT, fill: SUNKEN, size: 11.5,
    paras: ["Irrigation tied to this field's measured water balance rather "
            + "than a calendar. Soil for any coordinate in India in ~6 ms. "
            + "Advice quoted from government sources with the link. A refusal "
            + "when the evidence is thin."] });
  box(s, { x: M + 6.2, y: 4.8, w: 5.89, h: 1.52, label: "WHAT A PILOT WOULD MEASURE",
    tone: WARN, fill: "2A1D12", size: 11.5,
    paras: ["Water saved against a district's usual practice. Whether advice "
            + "is acted on. Yield and margin against a control group. None is "
            + "claimed here, because none has been measured — and a number we "
            + "invented would undo the point of the whole system."] });
  s.addNotes("Close on the right-hand box. Refusing to invent impact numbers "
    + "is the same discipline the product is built on.");
}

pres.writeFile({ fileName: __dirname + "/Saathi-submission.pptx" })
  .then((f) => console.log("wrote " + f));
