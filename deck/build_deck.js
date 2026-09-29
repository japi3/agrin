// Saathi — hackathon submission deck.
//
// Follows the reference deck's structure (eyebrow label, serif title with an
// italic accent, rounded cards, pixel strip, footer) in Saathi's own palette:
// the warm near-black and green the app actually ships, rather than the
// reference's amber.

const pptxgen = require("pptxgenjs");

const BG      = "1A1611";   // app --bg
const RAISED  = "241F18";   // app --bg-raised
const SUNKEN  = "12100C";   // app --bg-sunken
const BORDER  = "3A3226";   // app --border
const TEXT    = "F2ECE1";   // app --text
const MUTED   = "B3A288";   // app --text-muted
const ACCENT  = "7CB86A";   // app --accent
const WARN    = "C2703D";   // the app's "check this" orange

const SERIF = "Cambria";
const SANS  = "Calibri";
const MONO  = "Courier New";

const W = 13.33, H = 7.5;
const M = 0.62;                       // side margin

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Harnoor Singh, Japleen Kaur";
pres.title = "Saathi";

// A row of small squares along the top edge. The reference deck's motif,
// recoloured: greens and creams instead of blue and amber.
function pixelStrip(slide, seed) {
  const palette = [ACCENT, TEXT, BORDER, MUTED, ACCENT, BORDER];
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

// Eyebrow + a serif title whose second half is italic and accented.
function heading(slide, eyebrow, plain, italic, y = 1.02) {
  slide.addText(eyebrow, {
    x: M, y, w: 8, h: 0.26, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 11, bold: true, color: ACCENT, charSpacing: 1.5,
  });
  slide.addText(
    [
      { text: plain + " ", options: { fontFace: SERIF, color: TEXT } },
      { text: italic, options: { fontFace: SERIF, color: ACCENT, italic: true } },
    ],
    { x: M, y: y + 0.28, w: W - M * 2, h: 0.85, isTextBox: true, margin: 0, fontSize: 40 },
  );
}

function card(slide, { x, y, w, h, label, lines, tone }) {
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: RAISED }, line: { color: tone || BORDER, width: 1 },
  });
  let cursor = y + 0.18;
  if (label) {
    slide.addText(label, {
      x: x + 0.24, y: cursor, w: w - 0.48, h: 0.26, isTextBox: true, margin: 0,
      fontFace: MONO, fontSize: 10.5, bold: true, color: tone || ACCENT, charSpacing: 1.2,
    });
    cursor += 0.34;
  }
  if (lines && lines.length) {
    slide.addText(
      lines.map((t, i) => ({
        text: t, options: { bullet: { code: "2022" }, breakLine: i !== lines.length - 1 },
      })),
      {
        x: x + 0.24, y: cursor, w: w - 0.48, h: h - (cursor - y) - 0.16,
        isTextBox: true, margin: 0, fontFace: SANS, fontSize: 12.5,
        color: MUTED, lineSpacing: 17, paraSpaceAfter: 5,
      },
    );
  }
}

/* ------------------------------------------------------------------ 01 */
{
  const s = pres.addSlide();
  chrome(s, "Submission deck", 7);

  s.addText("TRACK 4 · AGRIN & REGENERATIVE AGRICULTURAL INTELLIGENCE", {
    x: M, y: 2.0, w: 10, h: 0.3, isTextBox: true, margin: 0,
    fontFace: MONO, fontSize: 11.5, bold: true, color: ACCENT, charSpacing: 1.5,
  });
  s.addText("Saathi", {
    x: M - 0.06, y: 2.34, w: 9, h: 1.5, isTextBox: true, margin: 0,
    fontFace: SERIF, fontSize: 88, color: TEXT,
  });
  s.addText(
    "A voice-first farming assistant that answers from validated agronomic " +
    "models and live satellite, soil and market data — in 24 languages, for " +
    "a farmer who may not read.",
    {
      x: M, y: 3.86, w: 11.4, h: 1.0, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 19, italic: true, color: ACCENT, lineSpacing: 27,
    },
  );

  const col = [
    ["BUILT", ["Working, deployed,", "355 tests passing"]],
    ["THEME", ["BRICS cooperation,", "data sovereignty"]],
    ["MEMBERS", ["Harnoor Singh", "Japleen Kaur"]],
    ["INSTITUTE", ["Thapar Institute of", "Engineering & Technology"]],
  ];
  col.forEach(([label, lines], i) => {
    const x = M + i * 3.1;
    s.addText(label, {
      x, y: 5.28, w: 2.9, h: 0.24, isTextBox: true, margin: 0,
      fontFace: MONO, fontSize: 10, color: MUTED, charSpacing: 1.2,
    });
    s.addText(lines.join("\n"), {
      x, y: 5.56, w: 2.9, h: 0.8, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 14.5, bold: true, color: TEXT, lineSpacing: 19,
    });
  });
  s.addNotes("Saathi is built and running. 355 tests, 24 languages, five BRICS federation nodes.");
}

/* ------------------------------------------------------------------ 02 */
{
  const s = pres.addSlide();
  chrome(s, "02 · The problem", 23);
  heading(s, "THE PROBLEM", "The problem", "we're solving");

  card(s, {
    x: M, y: 2.28, w: 6.0, h: 1.95, label: "WHAT A FARMER FACES",
    lines: [
      "Advice exists — in English, in PDFs, in offices open 10 to 5.",
      "A wrong irrigation or spray decision costs a season's income.",
      "Reading is assumed. For millions of farmers it should not be.",
    ],
  });
  card(s, {
    x: M + 6.3, y: 2.28, w: 6.41 - 0.31, h: 1.95, label: "WHY EXISTING TOOLS MISS",
    lines: [
      "Generic chatbots guess confidently and cite nothing.",
      "Dashboards show data and leave the interpreting to the farmer.",
      "Cross-border research cannot be pooled: nobody will hand over farm data.",
    ],
  });
  card(s, {
    x: M, y: 4.42, w: W - M * 2, h: 1.9, label: "WHAT THAT COSTS",
    lines: [
      "Irrigating a field that did not need it — pumping cost, waterlogging, and yield given away.",
      "A disease named wrongly, and a spray bought for it.",
      "Selling at the local rate while a mandi two districts away pays appreciably more.",
      "A scheme the farmer qualified for and never heard of.",
    ],
  });
  s.addNotes("The gap is not information. It is trustworthy, local, spoken, explainable advice.");
}

/* ------------------------------------------------------------------ 03 */
{
  const s = pres.addSlide();
  chrome(s, "03 · What we built", 41);
  heading(s, "SOLUTION", "What we", "built");

  slideBigQuote(s);
  function slideBigQuote(sl) {
    sl.addShape(pres.ShapeType.roundRect, {
      x: M, y: 2.24, w: W - M * 2, h: 1.32, rectRadius: 0.05,
      fill: { color: RAISED }, line: { color: BORDER, width: 1 },
    });
    sl.addText(
      [
        { text: "Saathi ", options: { color: ACCENT } },
        {
          text: "answers a farmer's question by running the same agronomic models an " +
                "extension officer would use, on their field, and says where every number came from.",
          options: { color: MUTED },
        },
      ],
      { x: M + 0.34, y: 2.44, w: W - M * 2 - 0.68, h: 0.95, isTextBox: true, margin: 0,
        fontFace: SERIF, fontSize: 19, lineSpacing: 28 },
    );
  }

  card(s, {
    x: M, y: 3.78, w: 3.88, h: 2.5, label: "THE FARMER",
    lines: [
      "Speaks or types, in their own language",
      "Photographs a damaged leaf",
      "Names a village — no coordinates needed",
    ],
  });
  card(s, {
    x: M + 4.12, y: 3.78, w: 3.88, h: 2.5, label: "SAATHI ANSWERS",
    lines: [
      "In the language and script they wrote in",
      "Read aloud, for anyone who cannot read",
      "With the field's own soil, weather and satellite",
    ],
  });
  card(s, {
    x: M + 8.24, y: 3.78, w: 3.85, h: 2.5, label: "AND WHEN IT CANNOT",
    tone: WARN,
    lines: [
      "It refuses: no dose without a lab test",
      "Says which figures are uncertain",
      "Every answer carries its sources",
    ],
  });
  s.addNotes("The refusals are the point. Confident wrong advice is what costs a farmer money.");
}

/* ------------------------------------------------------------------ 04 */
{
  const s = pres.addSlide();
  chrome(s, "04 · How it works", 59);
  heading(s, "TECHNICAL APPROACH", "How it", "works");

  card(s, {
    x: M, y: 2.18, w: 6.0, h: 2.36, label: "GOOGLE AI",
    lines: [
      "Gemini 3.7 Flash — routing and translation, over 13 tools",
      "Gemini TTS — answers read aloud in 24 languages",
      "Gemini vision — disease named from a photograph",
      "gemini-embedding-001 — retrieval across languages over published guidance",
      "Sixteen key-and-model pairs — no exhausted quota stops a farmer",
    ],
  });
  card(s, {
    x: M + 6.3, y: 2.18, w: 6.1, h: 2.36, label: "THE AGRONOMY IS NOT THE MODEL",
    lines: [
      "FAO-56 Penman-Monteith ET₀ and dual crop coefficient",
      "FAO-33 yield response to water deficit",
      "RothC-26.3 soil carbon, IPCC Tier 3",
      "12 disease models: Smith Periods, Analytis, Magarey",
    ],
  });
  card(s, {
    x: M, y: 4.68, w: 6.0, h: 1.94, label: "LIVE DATA, NOTHING MOCKED",
    lines: [
      "Sentinel-2 via Earth Engine and Planetary Computer",
      "ISRIC SoilGrids — 1 km map of India carried locally",
      "Open-Meteo weather · Agmarknet prices (data.gov.in)",
      "6,396 passages of Government of India advisory material",
    ],
  });
  card(s, {
    x: M + 6.3, y: 4.68, w: 6.1, h: 1.94, label: "BUILT TO BE DEPLOYED",
    lines: [
      "One container: FastAPI serves the API and the PWA",
      "Runs on a laptop, a VPS, or Cloud Run unchanged",
      "Free tiers throughout — no key costs a rupee",
    ],
  });
  s.addNotes("The language model routes and explains. Every number comes from a published model.");
}

/* ------------------------------------------------------------------ 05 */
{
  const s = pres.addSlide();
  chrome(s, "05 · What it does", 77);
  heading(s, "CAPABILITIES", "What it does", "today");

  const rows = [
    ["01", "Ask in any of 24 languages",
      "Voice or text, answered in the script they wrote in, and read back aloud."],
    ["02", "Should I irrigate?",
      "A daily root-zone water balance on their field — not a rule of thumb."],
    ["03", "How is my crop doing?",
      "Sentinel-2 greenness against what this crop should have at this stage."],
    ["04", "What is wrong with my plant?",
      "Disease from a photograph, weighted by weather-driven infection pressure."],
    ["05", "What is it worth?",
      "Yield from the season's water balance, at today's mandi rate and the MSP floor."],
    ["06", "What am I entitled to?",
      "Six government schemes, with the screening questions to check before travelling."],
    ["07", "What does the book say?",
      "Varieties, seed rates, spacing, treatment — quoted from published guidance, with the link."],
  ];
  rows.forEach(([n, title, body], i) => {
    const y = 2.12 + i * 0.64;
    s.addText(n, {
      x: M, y, w: 0.7, h: 0.4, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 19, italic: true, color: ACCENT,
    });
    s.addText(title, {
      x: M + 0.78, y: y - 0.02, w: 4.5, h: 0.4, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 15, bold: true, color: TEXT,
    });
    s.addText(body, {
      x: M + 5.4, y: y - 0.02, w: 7.0, h: 0.62, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 13, color: MUTED, lineSpacing: 16,
    });
    if (i < rows.length - 1) {
      s.addShape(pres.ShapeType.line, {
        x: M, y: y + 0.54, w: W - M * 2, h: 0, line: { color: BORDER, width: 0.5 },
      });
    }
  });
  s.addNotes("Every one of these runs today against live data.");
}

/* ------------------------------------------------------------------ 06 */
{
  const s = pres.addSlide();
  chrome(s, "06 · Architecture", 91);
  heading(s, "ARCHITECTURE", "How it fits", "together", 0.95);

  // The diagram is drawn separately (architecture.js) and placed as an
  // image, the way the reference deck does it: far more detail than slide
  // shapes can carry, and one file to reuse in a README or a poster.
  s.addImage({
    path: "/Users/japleenkaur/Desktop/agrin/deck/Saathi-architecture.png",
    x: 0.30, y: 1.92, w: 12.73, h: 5.05,
  });
}

/* ------------------------------------------------------------------ 07 */
{
  const s = pres.addSlide();
  chrome(s, "07 · What we measured", 109);
  heading(s, "EVIDENCE", "What we", "measured");

  const stat = (x, value, label, note) => {
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 2.26, w: 2.86, h: 1.72, rectRadius: 0.06,
      fill: { color: RAISED }, line: { color: BORDER, width: 1 },
    });
    s.addText(value, {
      x: x + 0.22, y: 2.44, w: 2.42, h: 0.66, isTextBox: true, margin: 0,
      fontFace: SERIF, fontSize: 34, color: ACCENT,
    });
    s.addText(label, {
      x: x + 0.22, y: 3.1, w: 2.42, h: 0.28, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 12.5, bold: true, color: TEXT,
    });
    s.addText(note, {
      x: x + 0.22, y: 3.38, w: 2.42, h: 0.5, isTextBox: true, margin: 0,
      fontFace: SANS, fontSize: 10.5, color: MUTED, lineSpacing: 13,
    });
  };
  stat(M,        "355",  "tests passing", "agronomy verified against FAO worked examples");
  stat(M + 3.06, "24",   "languages", "interface and replies, 284 strings each");
  stat(M + 6.12, "0",    "records shared", "across five BRICS nodes, enforced by test");
  stat(M + 9.18, "~6 ms", "soil, anywhere", "Car Nicobar to Ladakh, from a local map");

  card(s, {
    x: M, y: 4.18, w: 6.0, h: 2.14, label: "VERIFIED END TO END",
    lines: [
      "FAO-56 reproduces the published Example 18 exactly",
      "Sentinel-2, soil, weather, prices — live, nothing mocked",
      "Photo diagnosis refuses an unusable image rather than guessing",
      "Replies checked by Unicode script, not by asking a model",
    ],
  });
  card(s, {
    x: M + 6.3, y: 4.18, w: 6.1, h: 2.14, label: "STATED PLAINLY, NOT HIDDEN",
    tone: WARN,
    lines: [
      "Satellite verdicts are calibrated at population level, not per field",
      "Federation training data is generated — there is no shared BRICS farm dataset yet",
      "1 km soil is a regional estimate; every card says so and suggests a KVK test",
    ],
  });
  s.addNotes("The limitations slide is deliberate. A system that hides them cannot be trusted with a season's income.");
}

pres.writeFile({ fileName: "/Users/japleenkaur/Desktop/agrin/deck/Saathi.pptx" })
  .then(f => console.log("wrote", f));
