"""
Run the same question through each candidate model and time the whole turn.

`probe_models.py` answers whether a model is alive. This answers the
different and more useful question: how long does a real farmer's question
take on each one, and does the model still do the job.

The two come apart. A model can return one token in 0.7 seconds and then be
the wrong choice, because the work here is not generating text -- it is
choosing tools, reading what they return, and writing the result in the
farmer's language. A model that answers instantly by skipping the soil
lookup is not fast, it is wrong.

So this measures time *and* behaviour: how long the turn took, which tools
were called, how many rounds it needed, whether anything was actually said,
and whether the grounding check fired. A candidate is only better if it is
quicker without doing less.

    python scripts/benchmark_models.py
    python scripts/benchmark_models.py --models gemini-3.6-flash,gemini-3.5-flash-lite
    python scripts/benchmark_models.py --question "ਮੇਰੀ ਕਣਕ ਨੂੰ ਪਾਣੀ ਕਦੋਂ ਲਾਵਾਂ?" --language pa

Why this exists: on 2026-10-26 the configured default answered a one-token
probe in 3.6 seconds and, forty minutes later, in 22.3 seconds, while two
other working models stayed under two throughout. Picking between them on
a single probe reading would have been guessing. Picking between them on
one run of this is still a small sample -- Gemini's free-tier capacity
moves hour to hour -- so run it more than once before changing a default,
and prefer the model that is *consistently* adequate over the one that is
occasionally fastest.

Costs a few generation requests per model, against twenty per model per key
per day.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    sys.path.insert(0, str(ROOT / pkg))

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Ludhiana, so the field-scoped tools have somewhere to be.
LAT, LON = 30.90, 75.85

# A question that should make the model work: it needs the weather, the
# soil and the water balance, so a model that under-calls tools shows up
# as a short tool list rather than as a plausible-looking paragraph.
DEFAULT_QUESTION = "My wheat near Ludhiana — when should I irrigate next?"


async def run_once(model: str, question: str, language: str) -> dict:
    from agrin_api import orchestrator

    tools: list[str] = []
    text_parts: list[str] = []
    error: str | None = None
    grounding_fired = False
    first_text_at: float | None = None

    started = time.time()
    try:
        async for event in orchestrator.stream_turn(
            messages=[{"role": "user", "content": question}],
            language=language,
            model=model,
            field_context=f"The farmer's field is at {LAT}, {LON} near Ludhiana, Punjab.",
        ):
            if event.type == "tool_start":
                tools.append(event.data.get("name", "?"))
            elif event.type == "text":
                if first_text_at is None:
                    first_text_at = time.time() - started
                text_parts.append(event.data.get("delta", ""))
            elif event.type == "grounding":
                grounding_fired = True
            elif event.type == "error":
                error = f"{event.data.get('kind', '?')}: {event.data.get('message', '')[:60]}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:80]

    return {
        "model": model,
        "total_s": time.time() - started,
        "first_text_s": first_text_at,
        "tools": tools,
        "chars": len("".join(text_parts)),
        "grounding": grounding_fired,
        "error": error,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=None,
                        help="comma-separated; defaults to the configured default plus its chain")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--language", default="en")
    parser.add_argument("--repeat", type=int, default=1,
                        help="runs per model; capacity varies, so more is better evidence")
    args = parser.parse_args()

    from agrin_api import llm

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models = []
        for name in [llm.DEFAULT_MODEL, *llm.MODEL_FALLBACK_CHAIN]:
            if name not in models:
                models.append(name)

    print(f'question: "{args.question}"  language={args.language}')
    print(f"{len(models)} model(s) x {args.repeat} run(s)\n")

    results: list[dict] = []
    for model in models:
        for run in range(args.repeat):
            outcome = await run_once(model, args.question, args.language)
            results.append(outcome)
            label = f"{model}" + (f" #{run + 1}" if args.repeat > 1 else "")
            if outcome["error"]:
                print(f"  {label:34} FAILED  {outcome['total_s']:6.1f}s  {outcome['error']}")
            else:
                first = outcome["first_text_s"]
                first_s = f"{first:5.1f}s" if first is not None else "    --"
                print(f"  {label:34} ok      {outcome['total_s']:6.1f}s  "
                      f"first text {first_s}  "
                      f"{len(outcome['tools'])} tool(s)  {outcome['chars']} chars")

    print()
    print("| Model | Total | First text | Tools called | Chars | Grounding |")
    print("|---|---|---|---|---|---|")
    for model in models:
        runs = [r for r in results if r["model"] == model]
        ok = [r for r in runs if not r["error"]]
        if not ok:
            print(f"| `{model}` | — | — | failed | — | — |")
            continue
        total = sum(r["total_s"] for r in ok) / len(ok)
        firsts = [r["first_text_s"] for r in ok if r["first_text_s"] is not None]
        first = f"{sum(firsts) / len(firsts):.1f}s" if firsts else "—"
        # The union across runs: a model that calls a tool only sometimes is
        # a finding, not an average.
        called = sorted({t for r in ok for t in r["tools"]})
        chars = int(sum(r["chars"] for r in ok) / len(ok))
        grounded = any(r["grounding"] for r in ok)
        print(f"| `{model}` | {total:.1f}s | {first} | "
              f"{', '.join(called) if called else '**none**'} | {chars} | "
              f"{'fired' if grounded else '—'} |")

    print()
    print("A model is only better if it is quicker *and* calls the same tools.")
    print("An empty tool list with a long answer means the model answered from")
    print("its own recall, which is the failure this whole system exists to")
    print("prevent -- treat it as disqualifying, however fast it was.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
