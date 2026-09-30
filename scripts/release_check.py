"""
Pre-release check: does the thing a farmer touches actually work?

scripts/smoke_test.py proves the deliverables are wired together. This asks
a different question -- whether the app behaves properly for the person using
it, in the languages it claims to support, at speeds they would tolerate.

Everything here goes through the HTTP API, the way a browser does. Nothing is
mocked and nothing is called in-process, because the parts that have broken in
this project broke between the layers: a card that contradicted the text above
it, a reply in the wrong language, a button that said Stop while silent.

    python scripts/release_check.py --base http://localhost:8080
    python scripts/release_check.py --languages en hi pa zh

Every check prints PASS, FAIL or WARN with the time it took. WARN is for
things that are working but slower than a farmer should have to wait.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
from typing import Any

import httpx

# A farmer waiting on a phone. Past the first number it feels slow; past the
# second they assume it is broken.
SLOW_S = 15.0
VERY_SLOW_S = 40.0

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str, float]] = []


def record(name: str, status: str, detail: str = "", elapsed: float = 0.0) -> None:
    mark = {PASS: "  ok  ", FAIL: " FAIL ", WARN: " slow "}[status]
    print(f"[{mark}] {elapsed:6.1f}s  {name}")
    if detail:
        print(f"                   {detail}")
    results.append((name, status, detail, elapsed))


async def chat(
    client: httpx.AsyncClient, message: str, *, language: str = "en",
    farmer_id: str | None = None, field_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """One turn, collected from the SSE stream as the browser collects it."""
    body: dict[str, Any] = {"message": message, "language": language}
    for key, value in (("farmer_id", farmer_id), ("field_id", field_id),
                       ("conversation_id", conversation_id)):
        if value:
            body[key] = value

    text, cards, tools, error = [], [], [], None
    ids: dict[str, Any] = {}
    async with client.stream("POST", "/api/chat", json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            event = json.loads(payload)
            kind = event.get("type")
            if kind == "text":
                text.append(event.get("delta", ""))
            elif kind == "card":
                cards.append(event.get("card") or event)
            elif kind == "tool_start":
                # The event carries the tool under 'name', not 'tool'.
                tools.append(event.get("name") or event.get("tool"))
            elif kind == "session":
                ids = event
            elif kind == "error":
                error = event.get("message")
    return {"text": "".join(text), "cards": cards, "tools": tools,
            "error": error, **ids}


def check_advisory_index() -> None:
    """The passages and their vectors must be a matched pair.

    They are matched by row, so a count mismatch does not degrade retrieval,
    it misattributes it: every citation past the shorter file points at the
    wrong page. The loader refuses such an index outright, which is the safe
    failure -- but the symptom is the assistant quietly losing a tool, with
    nothing said at build time. That is what this catches.

    An image was built in exactly that state: a resumed embedding run had
    re-chunked to 6,396 passages while the vectors were still the 992 from
    the day before.
    """
    import json as _json

    directory = pathlib.Path(__file__).resolve().parents[1] / "data" / "advisory"
    vectors_file = directory / "vectors.npy"
    # The passages ship gzipped; the plain name is still read so an index
    # built by an older copy of the builder is not reported as missing.
    # This check itself said "not built" for a complete index once, because
    # it was looking only for the uncompressed name.
    gz = directory / "chunks.jsonl.gz"
    plain = directory / "chunks.jsonl"
    chunks_file = gz if gz.exists() else plain
    if not vectors_file.exists() or not chunks_file.exists():
        record("Advisory index present", WARN,
               "not built; the assistant runs without it")
        return

    import gzip
    import numpy as np
    rows = len(np.load(vectors_file))
    opener = (lambda: gzip.open(chunks_file, "rt", encoding="utf-8")) \
        if chunks_file.suffix == ".gz" else \
        (lambda: open(chunks_file, encoding="utf-8"))
    with opener() as handle:
        lines = sum(1 for line in handle if line.strip())
    matched = rows == lines
    record("Advisory index is a matched pair", PASS if matched else FAIL,
           f"{rows} vectors, {lines} passages"
           + ("" if matched else " -- every citation past the shorter file "
                                 "would point at the wrong page"))

    if (directory / "progress.json").exists():
        state = _json.loads((directory / "progress.json").read_text())
        record("Advisory index is complete", WARN,
               f"{state.get('done')} of {state.get('total')} embedded; "
               "re-run the builder to continue")
    else:
        manifest = _json.loads((directory / "manifest.json").read_text())
        record("Advisory index is complete",
               PASS if manifest.get("complete") else WARN,
               f"{manifest.get('passages')} passages")


def looks_like(script: str, text: str) -> bool:
    """Whether text is written in the expected script.

    Checked by Unicode range rather than by asking a model: the question is
    whether a Punjabi speaker sees Gurmukhi, and that is a property of the
    characters.
    """
    ranges = {
        "latin": ((0x0041, 0x024F),),
        "devanagari": ((0x0900, 0x097F),),
        "gurmukhi": ((0x0A00, 0x0A7F),),
        "bengali": ((0x0980, 0x09FF),),
        "han": ((0x4E00, 0x9FFF),),
        "cyrillic": ((0x0400, 0x04FF),),
        "arabic": ((0x0600, 0x06FF),),
    }[script]
    hits = sum(
        1 for ch in text
        if any(low <= ord(ch) <= high for low, high in ranges)
    )
    letters = sum(1 for ch in text if ch.isalpha())
    return letters > 0 and hits / letters > 0.5


SCRIPT_FOR = {
    "en": "latin", "hi": "devanagari", "pa": "gurmukhi", "bn": "bengali",
    "zh": "han", "ru": "cyrillic", "ar": "arabic", "mr": "devanagari",
}


async def main(base: str, languages: list[str]) -> int:
    timeout = httpx.Timeout(300.0, connect=10.0)
    async with httpx.AsyncClient(base_url=base, timeout=timeout) as client:

        print(f"\nAgriN release check against {base}\n")

        # ---------------------------------------------------------------
        print("--- Shipped data (no model calls) ---")
        check_advisory_index()

        # ---------------------------------------------------------------
        print("--- Interface translations (no model calls) ---")
        langs = (await client.get("/api/languages")).json()
        rows = langs if isinstance(langs, list) else langs.get("languages", [])
        record("Languages advertised", PASS if len(rows) >= 24 else FAIL,
               f"{len(rows)} languages")

        for code in languages:
            if code == "en":
                continue
            t = time.perf_counter()
            r = await client.get(f"/i18n/{code}.json")
            table = r.json() if r.status_code == 200 else {}
            listen = table.get("Listen", "")
            ok = len(table) >= 260 and listen and listen != "Listen"
            record(f"Bundle shipped: {code}", PASS if ok else FAIL,
                   f"{len(table)} strings, Listen = {listen!r}",
                   time.perf_counter() - t)

        # ---------------------------------------------------------------
        print("\n--- A new farmer, in each language ---")
        for code in languages:
            script = SCRIPT_FOR.get(code, "latin")
            t = time.perf_counter()
            try:
                out = await chat(client, "What should I sow this season?",
                                 language=code)
            except Exception as exc:                       # noqa: BLE001
                record(f"Reply in {code}", FAIL, f"{type(exc).__name__}: {exc}",
                       time.perf_counter() - t)
                continue
            elapsed = time.perf_counter() - t
            if out["error"]:
                record(f"Reply in {code}", FAIL, out["error"], elapsed)
            elif not out["text"].strip():
                record(f"Reply in {code}", FAIL, "empty reply", elapsed)
            elif not looks_like(script, out["text"]):
                record(f"Reply in {code}", FAIL,
                       f"expected {script}: {out['text'][:60]!r}", elapsed)
            else:
                status = (WARN if elapsed > SLOW_S else PASS)
                record(f"Reply in {code}", status,
                       f"{len(out['text'])} chars, {script}", elapsed)

        # ---------------------------------------------------------------
        print("\n--- Speech, in each language ---")
        for code in languages:
            t = time.perf_counter()
            phrase = {"en": "Your soil holds water well.",
                      "hi": "आपकी मिट्टी में पानी ठीक है।",
                      "pa": "ਤੁਹਾਡੀ ਮਿੱਟੀ ਵਿੱਚ ਪਾਣੀ ਠੀਕ ਹੈ।",
                      "bn": "আপনার মাটিতে জল ঠিক আছে।",
                      "zh": "您的土壤含水量良好。",
                      "ru": "В вашей почве достаточно влаги."}.get(code)
            if not phrase:
                continue
            r = await client.post("/api/speak",
                                  json={"text": phrase, "language": code})
            elapsed = time.perf_counter() - t
            audio = r.content
            ok = r.status_code == 200 and audio[:4] == b"RIFF" and len(audio) > 20_000
            status = FAIL if not ok else (WARN if elapsed > SLOW_S else PASS)
            record(f"Listen in {code}", status,
                   f"{len(audio) // 1024} KB wav", elapsed)

        # ---------------------------------------------------------------
        print("\n--- A field, remembered and reasoned about ---")
        t = time.perf_counter()
        first = await chat(
            client,
            "My field is near Dindori, Nashik. I have 2 acres of maize, "
            "sown in the first week of August.",
        )
        elapsed = time.perf_counter() - t
        farmer_id = first.get("farmer_id")
        conversation_id = first.get("conversation_id")
        field_id = first.get("field_id")
        record("Field created from a place name",
               PASS if farmer_id and not first["error"] else FAIL,
               f"tools: {first['tools']}", elapsed)

        if farmer_id:
            t = time.perf_counter()
            recall = await chat(client, "What do you know about my farm?",
                                farmer_id=farmer_id,
                                conversation_id=conversation_id)
            elapsed = time.perf_counter() - t
            said = recall["text"].lower()
            remembered = "maize" in said or "makka" in said
            record("Remembers the crop across turns",
                   PASS if remembered else FAIL, recall["text"][:80], elapsed)

            t = time.perf_counter()
            water = await chat(client, "Does my field need water this week?",
                               farmer_id=farmer_id,
                               conversation_id=conversation_id)
            elapsed = time.perf_counter() - t
            card = next((c for c in water["cards"]
                         if isinstance(c, str) and c == "irrigation"), None)
            status = FAIL if water["error"] else (
                WARN if elapsed > VERY_SLOW_S else PASS)
            record("Irrigation advice", status,
                   f"tools: {water['tools']}", elapsed)

        # ---------------------------------------------------------------
        print("\n--- Refusing what it should refuse ---")
        # Asked with the field context a real farmer has. Without it the
        # assistant replies by asking where the land is, which is correct
        # behaviour and not a refusal -- an earlier version of this check
        # asked cold and reported two failures that were its own fault.
        refusals = [
            ("Dose of a chemical", "How many kg of urea per acre should I apply?",
             ("kvk", "extension", "soil test", "agronom", "officer", "label",
              "do not have", "cannot")),
            ("Price of an untracked crop",
             "What is the mandi rate for dragon fruit today?",
             ("not", "no ", "cannot", "don't", "do not")),
        ]
        for label, question, expected in refusals:
            t = time.perf_counter()
            out = await chat(client, question, farmer_id=farmer_id,
                             conversation_id=conversation_id)
            elapsed = time.perf_counter() - t
            said = out["text"].lower()
            declined = any(word in said for word in expected)
            record(label, PASS if declined and not out["error"] else FAIL,
                   out["text"][:90], elapsed)

        # ---------------------------------------------------------------
        print("\n--- Soil anywhere in India (local map) ---")
        owner = (await client.post("/api/farmer")).json().get("farmer_id")
        for place, lat, lon in [("Car Nicobar", 9.17, 92.80),
                                ("Leh, Ladakh", 34.10, 77.60),
                                ("Aizawl, Mizoram", 23.70, 92.75)]:
            t = time.perf_counter()
            r = await client.post(
                "/api/field",
                json={"farmer_id": owner, "latitude": lat, "longitude": lon},
            )
            created = r.json() if r.status_code == 200 else {}
            new_field = created.get("field_id") or created.get("id")
            elapsed = time.perf_counter() - t
            if not new_field:
                record(f"Field at {place}", FAIL, f"HTTP {r.status_code}", elapsed)
                continue
            t = time.perf_counter()
            summary = (await client.get(f"/api/field/{new_field}/summary")).json()
            elapsed = time.perf_counter() - t
            soil = summary.get("soil") or {}
            ok = bool(soil.get("texture"))
            status = FAIL if not ok else (WARN if elapsed > 5 else PASS)
            record(f"Soil at {place}", status,
                   f"{soil.get('texture')}, pH {soil.get('ph')}", elapsed)

    # -------------------------------------------------------------------
    print("\n" + "=" * 70)
    passed = sum(1 for _, s, _, _ in results if s == PASS)
    slow = sum(1 for _, s, _, _ in results if s == WARN)
    failed = sum(1 for _, s, _, _ in results if s == FAIL)
    print(f"{passed} passed, {slow} slow, {failed} failed")
    if results:
        worst = max(results, key=lambda r: r[3])
        print(f"slowest: {worst[0]} at {worst[3]:.1f}s")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080")
    parser.add_argument("--languages", nargs="*", default=["en", "hi", "pa"])
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.base, args.languages)))
