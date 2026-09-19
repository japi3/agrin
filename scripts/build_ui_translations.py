"""
Pre-translate the interface into every supported language.

Collects every fixed English string the interface can show -- literals passed
to t()/tr() in the frontend, plus the finite set of labels the server sends
(crop names, growth stages, soil classes, scheme text, practice names) -- and
translates each language's full set in a few batched Gemini calls. The results
are written to apps/web/public/i18n/<lang>.json and shipped with the app.

Why ahead of time rather than on demand: translating lazily as the page
discovered strings spent one rate-limited request per wave of rendering, and
on the free tier a first Punjabi visit was still half English minutes later.
Done once here, choosing a language is instant and costs nothing at runtime.

    python scripts/build_ui_translations.py            # all languages
    python scripts/build_ui_translations.py pa hi      # just these
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo"):
    sys.path.insert(0, str(ROOT / pkg))

import os  # noqa: E402
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

OUT = ROOT / "apps" / "web" / "public" / "i18n"
BATCH = 70


def frontend_strings() -> set[str]:
    found: set[str] = set()
    call = re.compile(r"\b(?:t|tr)\(\s*(['\"`])((?:(?!\1).)+?)\1", re.S)
    for path in (ROOT / "apps/web/src").rglob("*.tsx"):
        src = path.read_text()
        for _, text in call.findall(src):
            if "${" not in text:
                found.add(text)
        # Maps whose values are passed through t() at render time.
        for block in re.findall(r"const (?:VERDICT|VERDICT_COPY|URGENCY_COPY|PH_WORD|TOOL_LABEL|ERROR_TEXT)\b[^{]*\{(.*?)\n\}", src, re.S):
            for _, text in re.findall(r"(?:text|head)?\s*:\s*(['\"])((?:(?!\1).)+?)\1", block):
                if len(text) > 2 and not text.startswith(("#", "var(")) and text not in {"good", "warn", "alert", "neutral"}:
                    found.add(text)
    return found


def server_strings() -> set[str]:
    from agronomy.crops import CROPS, TEXTURE_WATER
    from agronomy.schemes import SCHEMES
    found = {c.name_en for c in CROPS.values()}
    found |= {"initial", "development", "mid season", "late season"}
    found |= {t.replace("_", " ") for t in TEXTURE_WATER}
    found |= {"high", "moderate", "low", "severe", "none", "leaf", "stem", "root", "fruit",
              "field size", "what is planted", "when it was sown", "when it was last watered",
              "Residue burned or removed, bare fallow", "Crop residue retained on the field",
              "Residue retained plus a cover crop in the fallow",
              "Residue, cover crop, and 8 t/ha farmyard manure"}
    for s in SCHEMES.values():
        found.add(s.what_it_does)
        found |= set(s.screening_questions) | set(s.common_exclusions) \
               | set(s.key_facts) | set(s.documents_usually_needed)
    return found


async def main(languages: list[str]) -> None:
    from agrin_api.i18n import translate_strings
    from agrin_api.prompts import SUPPORTED_LANGUAGES

    strings = sorted(frontend_strings() | server_strings())
    print(f"{len(strings)} interface strings")
    OUT.mkdir(parents=True, exist_ok=True)
    targets = [l for l in (languages or SUPPORTED_LANGUAGES) if l != "en"]

    for lang in targets:
        table: dict[str, str] = {}
        for i in range(0, len(strings), BATCH):
            chunk = strings[i:i + BATCH]
            for attempt in range(6):
                result = await translate_strings(lang, chunk)
                table.update(result.get("translations", {}))
                if all(s in table for s in chunk):
                    break
                await asyncio.sleep(15)   # free tier: wait out the minute window
        (OUT / f"{lang}.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
        print(f"  {lang}: {len(table)}/{len(strings)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
