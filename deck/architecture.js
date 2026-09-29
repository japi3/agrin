// Saathi — system architecture diagram.
//
// Same shape of drawing as the reference deck's: numbered sections in
// outlined containers, colour-coded cards inside them, labelled arrows
// between stages. Recoloured to Saathi's own palette, and describing the
// system as it actually runs rather than as a plan.

const fs = require("fs");
const sharp = require("sharp");

const BG     = "#1A1611";
const PANEL  = "#12100C";
const RAISED = "#241F18";
const BORDER = "#3A3226";
const TEXT   = "#F2ECE1";
const MUTED  = "#B3A288";
const GREEN  = "#7CB86A";
const DEEP   = "#4E8C3F";
const SOFT   = "#1F2B1A";
const WARN   = "#C2703D";
const WARNBG = "#2A1D12";

const W = 2000, H = 1240;
const SANS = "Helvetica Neue, Helvetica, Arial, sans-serif";
const MONO = "Menlo, Monaco, Courier New, monospace";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const out = [];
const add = (s) => out.push(s);

function section(x, y, w, h, num, title) {
  add(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="16"
        fill="${PANEL}" stroke="${GREEN}" stroke-width="2" opacity="0.98"/>`);
  add(`<text x="${x + 22}" y="${y + 36}" font-family="${SANS}" font-size="21"
        font-weight="700" fill="${GREEN}">${esc(num)} · ${esc(title)}</text>`);
}

function card(x, y, w, h, opts = {}) {
  const {
    title, lines = [], accent = GREEN, fill = RAISED, dashed = false,
    icon, titleSize = 18, lineSize = 15,
  } = opts;
  add(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="11" fill="${fill}"
        stroke="${accent}" stroke-width="1.8"${dashed ? ' stroke-dasharray="7 5"' : ""}/>`);
  let ty = y + 30;
  if (title) {
    const ix = icon ? x + 44 : x + 17;

    add(`<text x="${ix}" y="${ty}" font-family="${SANS}" font-size="${titleSize}"
          font-weight="600" fill="${TEXT}">${esc(title)}</text>`);
    ty += 26;
  }
  lines.forEach((l) => {
    add(`<text x="${x + 17}" y="${ty}" font-family="${SANS}" font-size="${lineSize}"
          fill="${MUTED}">${esc(l)}</text>`);
    ty += 22;
  });
}


// Drawn rather than typed: the SVG rasteriser has no emoji font, and every
// emoji rendered as a solid black box.
function iconMic(x, y, c) {
  return `<g stroke="${c}" stroke-width="2" fill="none">
    <rect x="${x + 6}" y="${y}" width="9" height="15" rx="4.5" fill="${c}"/>
    <path d="M ${x + 1} ${y + 10} a 9.5 9.5 0 0 0 19 0"/>
    <line x1="${x + 10.5}" y1="${y + 19}" x2="${x + 10.5}" y2="${y + 24}"/>
  </g>`;
}
function iconKeys(x, y, c) {
  let d = `<rect x="${x}" y="${y + 3}" width="22" height="16" rx="3" stroke="${c}" stroke-width="2" fill="none"/>`;
  for (let r = 0; r < 2; r++) for (let k = 0; k < 4; k++) {
    d += `<rect x="${x + 3 + k * 4.4}" y="${y + 6.5 + r * 5}" width="2.6" height="2.6" fill="${c}"/>`;
  }
  return d;
}
function iconCam(x, y, c) {
  return `<g stroke="${c}" stroke-width="2" fill="none">
    <rect x="${x}" y="${y + 4}" width="22" height="15" rx="3"/>
    <path d="M ${x + 7} ${y + 4} l 2 -3 h 4 l 2 3"/>
    <circle cx="${x + 11}" cy="${y + 11.5}" r="4"/>
  </g>`;
}
const ICONS = { mic: iconMic, keys: iconKeys, cam: iconCam };

function chip(x, y, w, h, text, accent, icon) {
  add(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="9" fill="${SOFT}"
        stroke="${accent}" stroke-width="1.6"/>`);
  if (icon && ICONS[icon]) add(ICONS[icon](x + 15, y + h / 2 - 12, accent));
  add(`<text x="${x + (icon ? 50 : 16)}" y="${y + h / 2 + 6}" font-family="${SANS}"
        font-size="16" fill="${TEXT}">${esc(text)}</text>`);
}

function arrow(x1, y1, x2, y2, label) {
  add(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${GREEN}"
        stroke-width="2.4" marker-end="url(#head)"/>`);
  if (label) {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const horizontal = Math.abs(y2 - y1) < 6;
    add(`<text x="${mx}" y="${horizontal ? my - 12 : my}" font-family="${MONO}"
          font-size="13" fill="${MUTED}" text-anchor="middle">${esc(label)}</text>`);
  }
}

/* ---------------------------------------------------------------- frame */
add(`<rect width="${W}" height="${H}" fill="${BG}"/>`);
add(`<rect x="18" y="18" width="${W - 36}" height="${H - 36}" rx="20"
      fill="${PANEL}" stroke="${BORDER}" stroke-width="2"/>`);

/* -------------------------------------------------------------- 1 farmer */
section(48, 54, 300, 452, "1", "FARMER");
chip(70, 112, 256, 54, "Speaks a question", GREEN, "mic");
chip(70, 178, 256, 54, "Types a question", GREEN, "keys");
chip(70, 244, 256, 54, "Photographs a leaf", WARN, "cam");
card(70, 318, 256, 166, {
  title: "24 languages",
  lines: ["English · हिन्दी · ਪੰਜਾਬੀ", "বাংলা · தமிழ் · 中文", "Русский · العربية · +16", "Voice or text, either way"],
  accent: DEEP, fill: SOFT, titleSize: 17, lineSize: 15,
});

/* ----------------------------------------------------------------- 2 app */
section(378, 54, 330, 300, "2", "SAATHI PWA");
card(400, 106, 286, 226, {
  title: "Conversation first",
  lines: [
    "Farm panel beside it, not",
    "instead of it",
    "Listen on every answer",
    "Installs on a phone",
    "Offline shell, honest when",
    "there is no signal",
  ],
  accent: GREEN, titleSize: 17, lineSize: 15,
});

/* -------------------------------------------------------------- 3 speech */
section(378, 384, 330, 210, "3", "SPEECH IN");
card(400, 436, 286, 62, { title: "Gemini speech-to-text", accent: GREEN, titleSize: 16 });
card(400, 510, 286, 66, {
  title: "RMS silence guard",
  lines: ["silence never becomes words"],
  accent: WARN, fill: WARNBG, dashed: true, titleSize: 16, lineSize: 14,
});

/* -------------------------------------------------------- 4 orchestrator */
section(738, 54, 640, 640, "4", "ORCHESTRATOR");
card(762, 106, 592, 74, {
  title: "Script detector — counts the characters, before the model sees them",
  lines: ["a reply comes back in the script the farmer wrote in"],
  accent: WARN, fill: WARNBG, titleSize: 16, lineSize: 14,
});
card(762, 194, 592, 92, {
  title: "Gemini 3.7 Flash · function calling",
  lines: [
    "routes, translates and explains — it does not do the agronomy",
    "reasoning traces preserved across turns",
  ],
  accent: GREEN, fill: SOFT, titleSize: 18, lineSize: 15,
});

const tools = [
  "irrigation", "crop health", "photo diagnosis", "mandi prices", "crop value",
  "soil profile", "schemes", "farm memory", "guidance lookup",
];
add(`<text x="762" y="326" font-family="${MONO}" font-size="14" fill="${MUTED}">13 TOOLS</text>`);
tools.forEach((t, i) => {
  const cx = 762 + (i % 5) * 119;
  const cy = 340 + Math.floor(i / 5) * 54;
  // The retrieval tool is drawn apart from the rest: everything else on this
  // row computes an answer, and this one goes and finds who already wrote it.
  const isRag = t === "guidance lookup";
  add(`<rect x="${cx}" y="${cy}" width="110" height="44" rx="8"
        fill="${isRag ? SOFT : RAISED}"
        stroke="${isRag ? GREEN : BORDER}" stroke-width="${isRag ? 1.8 : 1.4}"/>`);
  add(`<text x="${cx + 55}" y="${cy + 27}" font-family="${SANS}" font-size="12.5"
        fill="${TEXT}" text-anchor="middle">${esc(t)}</text>`);
});

card(762, 444, 592, 68, {
  title: "Fallback chain — 16 key-and-model pairs",
  lines: ["an exhausted daily quota never stops a farmer"],
  accent: DEEP, titleSize: 17, lineSize: 14,
});
// The stage that reads the model's own output back. Drawn here, between the
// answer and what leaves the building, because that is where it runs: the
// rest of the architecture polices what goes *into* the model, and this is
// the only thing that checks what came out.
card(762, 520, 592, 90, {
  title: "Grounding check — before the answer is finished",
  lines: [
    "every figure in a quoted answer is matched against",
    "the passages it came from · unmatched ones are flagged",
  ],
  accent: WARN, fill: WARNBG, titleSize: 17, lineSize: 14,
});
card(762, 618, 592, 62, {
  title: "Refusals are first-class",
  lines: ["no dose without a lab test · no price forecast · no guessed crop"],
  accent: WARN, fill: WARNBG, titleSize: 17, lineSize: 14,
});

/* ------------------------------------------------------------ 7 response */
section(1408, 54, 544, 640, "5", "WHAT COMES BACK");
card(1430, 106, 500, 86, {
  title: "The answer, in their script",
  lines: ["Gurmukhi in, Gurmukhi out — decided in code"],
  accent: GREEN, fill: SOFT, titleSize: 18, lineSize: 15,
});
card(1430, 204, 500, 96, {
  title: "Evidence ledger",
  lines: ["“Where did this come from?”", "every figure names its model and inputs"],
  accent: GREEN, titleSize: 18, lineSize: 15,
});
const cards = ["irrigation", "weather", "soil", "crop value",
               "diagnosis", "schemes", "sources"];
add(`<text x="1430" y="336" font-family="${MONO}" font-size="14" fill="${MUTED}">PICTORIAL CARDS</text>`);
cards.forEach((c, i) => {
  const cx = 1430 + (i % 4) * 126;
  const cy = 350 + Math.floor(i / 4) * 50;
  add(`<rect x="${cx}" y="${cy}" width="118" height="40" rx="8" fill="${RAISED}"
        stroke="${BORDER}" stroke-width="1.4"/>`);
  add(`<text x="${cx + 59}" y="${cy + 25}" font-family="${SANS}" font-size="12.5"
        fill="${TEXT}" text-anchor="middle">${esc(c)}</text>`);
});
card(1430, 466, 500, 84, {
  title: "Gemini text-to-speech",
  lines: ["read aloud in 24 languages, stoppable mid-sentence"],
  accent: GREEN, titleSize: 18, lineSize: 15,
});
card(1430, 564, 500, 88, {
  title: "Said plainly when uncertain",
  lines: ["“Soil map uncertain here — a KVK", "soil test would be firmer.”"],
  accent: WARN, fill: WARNBG, titleSize: 17, lineSize: 14,
});

/* -------------------------------------------------------------- 6 models */
section(48, 706, 900, 262, "6", "VALIDATED AGRONOMY — NOT THE LANGUAGE MODEL");
const models = [
  ["FAO-56", "Penman-Monteith ET₀", "dual crop coefficient", "daily root-zone balance"],
  ["FAO-33", "yield response to", "water deficit (Ky)", "16 crops calibrated"],
  ["RothC-26.3", "soil organic carbon", "IPCC Tier 3", "20-year projections"],
  ["EPIDEMIOLOGY", "Smith Periods (1956)", "Analytis · Magarey", "12 disease models"],
];
models.forEach((m, i) => {
  const x = 70 + i * 218;
  card(x, 758, 200, 188, {
    title: m[0], lines: m.slice(1), accent: DEEP, titleSize: 17, lineSize: 14,
  });
});

/* ---------------------------------------------------------------- 7 data */
section(978, 706, 974, 262, "7", "LIVE DATA AND PUBLISHED GUIDANCE — NOTHING MOCKED");
card(1000, 758, 228, 188, {
  title: "Soil",
  lines: [
    "ISRIC SoilGrids",
    "1 km map of India,",
    "carried locally",
    "→ anywhere in India",
    "   answers in ~6 ms",
  ],
  accent: GREEN, fill: SOFT, titleSize: 17, lineSize: 14,
});
card(1244, 758, 228, 188, {
  title: "Weather & satellite",
  lines: [
    "Open-Meteo forecast",
    "and 20-year normals",
    "Sentinel-2 NDVI via",
    "Earth Engine and",
    "Planetary Computer",
  ],
  accent: GREEN, titleSize: 17, lineSize: 14,
});
card(1488, 758, 228, 188, {
  title: "Market & place",
  lines: [
    "Agmarknet prices",
    "(data.gov.in)",
    "MSP floor, by season",
    "Nominatim — a village",
    "name becomes a field",
  ],
  accent: GREEN, titleSize: 17, lineSize: 14,
});
card(1732, 758, 198, 188, {
  title: "Advisory corpus",
  lines: [
    "6,396 passages of",
    "Government of India",
    "guidance, embedded",
    "→ quoted and linked,",
    "   never recalled",
  ],
  accent: GREEN, fill: SOFT, titleSize: 17, lineSize: 13.5,
});

/* ---------------------------------------------------------- 8 federation */
section(48, 1000, 1904, 186, "8", "BRICS FEDERATION — COOPERATION WITHOUT SURRENDERING DATA");
const nodes = [
  ["IN", "India", "150 records"],
  ["BR", "Brazil", "100 records"],
  ["RU", "Russia", "150 records"],
  ["CN", "China", "150 records"],
  ["ZA", "South Africa", "100 records"],
];
nodes.forEach((n, i) => {
  const x = 72 + i * 228;
  add(`<rect x="${x}" y="1052" width="208" height="106" rx="11" fill="${RAISED}"
        stroke="${DEEP}" stroke-width="1.8"/>`);
  add(`<rect x="${x + 16}" y="1068" width="34" height="26" rx="5" fill="${SOFT}"
        stroke="${GREEN}" stroke-width="1.5"/>`);
  add(`<text x="${x + 33}" y="1086" font-family="${MONO}" font-size="14"
        font-weight="700" fill="${GREEN}" text-anchor="middle">${esc(n[0])}</text>`);
  add(`<text x="${x + 60}" y="1088" font-family="${SANS}" font-size="17"
        font-weight="600" fill="${TEXT}">${esc(n[1])}</text>`);
  add(`<text x="${x + 18}" y="1120" font-family="${SANS}" font-size="14"
        fill="${MUTED}">${esc(n[2])} held</text>`);
  add(`<text x="${x + 18}" y="1142" font-family="${SANS}" font-size="14"
        fill="${GREEN}">0 records shared</text>`);
});
card(1228, 1052, 700, 106, {
  title: "Federated averaging — weights travel, farm records never do",
  lines: [
    "Each country trains on its own data and publishes model weights only.",
    "A test asserts no node endpoint will return a record. It is the claim, enforced.",
  ],
  accent: GREEN, fill: SOFT, titleSize: 17, lineSize: 14,
});

/* -------------------------------------------------------------- arrows */
arrow(348, 205, 376, 205, "");
arrow(348, 470, 376, 470, "");
arrow(708, 205, 736, 205, "question");
arrow(708, 480, 736, 480, "transcript");
arrow(1378, 300, 1406, 300, "answer");
add(`<text x="362" y="452" font-family="${MONO}" font-size="13" fill="${MUTED}"
      text-anchor="middle">voice</text>`);
// models and data feed the orchestrator
arrow(500, 704, 500, 678, "");
arrow(1200, 704, 1200, 678, "");
add(`<text x="516" y="696" font-family="${MONO}" font-size="13" fill="${MUTED}">figures</text>`);
add(`<text x="1216" y="696" font-family="${MONO}" font-size="13" fill="${MUTED}">measurements</text>`);

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs>
  <marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="${GREEN}"/>
  </marker>
</defs>
${out.join("\n")}
</svg>`;

fs.writeFileSync("architecture.svg", svg);
sharp(Buffer.from(svg), { density: 200 })
  .resize({ width: 3000 })
  .png()
  .toFile("Saathi-architecture.png")
  .then((i) => console.log(`wrote Saathi-architecture.png ${i.width}x${i.height}`))
  .catch((e) => { console.error(e.message); process.exit(1); });
