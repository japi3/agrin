"""
Ask every configured model whether it is actually alive.

This exists because of a failure that no test caught and no log made
obvious. The deployed service was taking four minutes to answer and then
returning "the service is very busy". The model it was configured to use,
gemini-3.7-flash, had stopped being served: three keys got 504
DEADLINE_EXCEEDED and the fourth 503 UNAVAILABLE, every time, each taking
the full 45-second timeout. The first fallback, gemini-3.8-flash, was dead
the same way. So roughly ninety seconds of every request was spent failing
over to a model that worked, and when the round budget ran out before
reaching one, the farmer got an error after four minutes of waiting.

A dead model in a fallback chain is not a harmless spare. It is a timeout
that every single request pays. And it cannot be caught by a unit test,
because nothing in this repository changed -- the model was withdrawn
upstream.

So: one token from each model, on each key, with the wall time and the
error. Cheap enough to run before a demonstration, which is exactly when
it matters.

    python scripts/probe_models.py
    python scripts/probe_models.py --first-key-only   # one key, faster
    python scripts/probe_models.py --timeout 20

Costs one generation request per model per key, against a free-tier
allowance of twenty per model per key per day. The full matrix is a few
percent of a day's quota; `--first-key-only` quarters it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def classify(message: str) -> str:
    """The distinction that matters: withdrawn, throttled, or broken."""
    if "504" in message or "DEADLINE_EXCEEDED" in message:
        return "504 timeout"
    if "503" in message or "UNAVAILABLE" in message:
        return "503 busy"
    if "429" in message or "RESOURCE_EXHAUSTED" in message:
        return "429 quota"
    if "404" in message or "NOT_FOUND" in message:
        return "404 gone"
    return "error"


async def probe(key: str, model: str, timeout_s: float) -> tuple[str, float, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
    )
    started = time.time()
    try:
        await client.aio.models.generate_content(
            model=model,
            contents="ok",
            config=types.GenerateContentConfig(max_output_tokens=1024),
        )
        return "OK", time.time() - started, ""
    except Exception as exc:  # noqa: BLE001 - every failure mode is the point
        message = str(exc).replace("\n", " ")
        return classify(message), time.time() - started, message[:90]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="seconds to wait for one token (default 30)")
    parser.add_argument("--first-key-only", action="store_true",
                        help="probe one key rather than all of them")
    args = parser.parse_args()

    from agrin_api import llm

    keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
    if not keys:
        single = os.environ.get("GEMINI_API_KEY", "").strip()
        keys = [single] if single else []
    if not keys:
        print("No keys. Set GEMINI_API_KEYS in .env")
        return 2
    if args.first_key_only:
        keys = keys[:1]

    # The default first, then its chain, in the order a request would try
    # them -- so the output reads as the path a question actually takes.
    models: list[str] = []
    for name in [llm.DEFAULT_MODEL, llm.VISION_MODEL, *llm.MODEL_FALLBACK_CHAIN]:
        if name not in models:
            models.append(name)

    print(f"{len(keys)} key(s) x {len(models)} model(s), {args.timeout:.0f}s timeout\n")
    print(f"  {'model':26} {'key':>4}  {'result':11} {'time':>7}")
    print(f"  {'-' * 26} {'-' * 4}  {'-' * 11} {'-' * 7}")

    dead: list[str] = []
    spent: list[str] = []
    for position, model in enumerate(models):
        outcomes = []
        for index, key in enumerate(keys, 1):
            status, elapsed, detail = await probe(key, model, args.timeout)
            outcomes.append(status)
            note = f"  {detail}" if detail else ""
            print(f"  {model:26} {index:>4}  {status:11} {elapsed:6.1f}s{note}")
        if "OK" not in outcomes:
            label = "default" if position == 0 else f"fallback {position}"
            # A spent daily allowance and a withdrawn model look equally
            # dead in a probe and need opposite responses: one resets at
            # midnight UTC and the key rotation already covers it, the
            # other is a timeout on every request until someone edits the
            # configuration. Reporting them together is how you end up
            # deleting a working model, or keeping a dead one.
            if all(o == "429 quota" for o in outcomes):
                spent.append(f"{model} ({label})")
            else:
                dead.append(f"{model} ({label})")

    print()
    if spent:
        print("Out of quota on the key(s) probed — not broken, back at 00:00 UTC:")
        for name in spent:
            print(f"  - {name}")
        print("  (probe without --first-key-only to see whether other keys have room)")
        print()
    if dead:
        print("Not answering, for reasons that will not fix themselves —")
        print("each one is a timeout every request pays:")
        for name in dead:
            print(f"  - {name}")
        print("\nRemove them from AGRIN_MODEL / AGRIN_MODEL_FALLBACKS, in the")
        print("deployment's environment as well as in llm.py. An environment")
        print("variable set in the Render dashboard overrides the code default,")
        print("so changing llm.py alone will not fix the deployment.")
        return 1

    if spent:
        print("Nothing is broken; the allowance is just spent on these keys.")
        return 0

    print("Every configured model answered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
