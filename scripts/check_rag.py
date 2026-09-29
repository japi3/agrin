"""
Is retrieval actually working?

One command, three questions, a verdict. Written because "is the RAG working"
is the thing you want to answer in ten seconds before a demo, and reading a
score off a debug print is not an answer.

    docker exec agrin python /app/scripts/check_rag.py
    python scripts/check_rag.py                          # against a local checkout

What it checks, in the order that matters:

1. The index loads, and its passages and vectors are a matched pair. They are
   matched by row, so a mismatch does not weaken retrieval, it misattributes
   it -- every citation past the shorter file points at the wrong page.

2. A question the corpus covers comes back quoted, with a source.

3. A question it does not cover comes back refused. This is the one people
   skip, and it is the one that matters. A similarity search always returns
   its best matches; for a question about nothing in the corpus those are
   simply the least irrelevant passages, ranked just as confidently as a real
   answer. A system that quotes them with a government citation attached is
   worse than one with no corpus at all, because the citation is what makes
   the answer look checked.

A pass on 2 without a pass on 3 is not a working system. It is a system that
has not been asked anything hard yet.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    candidate = ROOT / pkg
    if candidate.exists():
        sys.path.insert(0, str(candidate))

import os  # noqa: E402
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

COVERED = "What seed treatment should I use before sowing wheat?"
ALSO_COVERED = "How do I manage pests in brinjal?"
NOT_COVERED = "How do I rebuild a motorcycle gearbox?"

OK, BAD = "  ok  ", " FAIL "


async def main() -> int:
    from rag.index import MIN_SCORE, load_index

    index = load_index()
    if index is None:
        print(f"[{BAD}] index did not load")
        print("        Build it: python scripts/build_advisory_index.py")
        print("        If it exists, the passages and vectors probably disagree;")
        print("        scripts/release_check.py reports that explicitly.")
        return 1

    manifest = index.manifest
    print(f"[{OK}] index loaded — {len(index)} passages, {index.dimensions}d, "
          f"floor {MIN_SCORE}")
    if not manifest.get("complete", True):
        print(f"        partial: {manifest.get('passages')} of "
              f"{manifest.get('passages_available')} embedded")

    from agrin_api import tools

    failures = 0

    for question in (COVERED, ALSO_COVERED):
        result = await tools.look_up_official_guidance(question)
        if result.get("ok"):
            best = result["passages"][0]
            print(f"[{OK}] quoted a source for: {question}")
            print(f"        {best['score']} — {best['section'][:70]}")
            print(f"        {best['url'][:78]}")
        else:
            failures += 1
            print(f"[{BAD}] no source for a question the corpus covers: {question}")
            print(f"        {result.get('abstain_reason', '')[:110]}")

    result = await tools.look_up_official_guidance(NOT_COVERED)
    if result.get("ok"):
        failures += 1
        best = result["passages"][0]
        print(f"[{BAD}] quoted something for an off-topic question — the floor "
              f"is too low")
        print(f"        {best['score']} — {best['section'][:70]}")
        print(f"        Raise MIN_SCORE in packages/rag/rag/index.py")
    else:
        print(f"[{OK}] refused an off-topic question, as it should")

    print()
    print("retrieval is working" if not failures
          else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
