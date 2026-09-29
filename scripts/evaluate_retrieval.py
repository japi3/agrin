"""
Measure the retrieval, instead of asserting it.

Until this existed, every claim about the advisory corpus in this repository
rested on a handful of questions tried by hand. The score floor in
`rag.index` carried a comment saying it was calibrated against on- and
off-topic questions landing at 0.71-0.79 and 0.50-0.55 -- true when it was
written, on a corpus of 399 passages, and never rechecked as that corpus grew
ten times larger. A number like that stops being evidence the moment the
thing it describes changes.

So: a fixed set of questions, a run that prints the same table every time,
and a file anyone can add a failing question to.

    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --k 5 --out eval/results.md

What is measured, and why each one is here:

**Recall@1 and Recall@3** -- does the right subject come back, and is it
first? Reported per language, because the corpus is English and most of the
people asking are not, and an average across languages would hide a
collapse in one of them.

**Abstention on off-topic questions** -- the half that matters more. A
similarity search always returns its best matches; for a question about
nothing in the corpus those are the least irrelevant passages, ranked as
confidently as a real answer. A retriever that never abstains scores
perfectly on recall and is dangerous, because the citation it attaches is
what makes a wrong answer look checked.

**The margin at the floor** -- the gap between the weakest on-topic score
and the strongest off-topic one. Recall and abstention can both read 100%
while that gap is a hundredth of a point wide, which means the next question
decides it by luck. The margin is the number that says whether 0.62 is still
the right place to stand.

Embedding is rationed at 1,000 texts per key per day, and this set is about
forty questions, so a full run costs very little -- but it does need quota,
and it will say so rather than reporting zeroes if there is none left.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    sys.path.insert(0, str(ROOT / pkg))

import os  # noqa: E402
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

SET_FILE = ROOT / "eval" / "retrieval_set.json"


async def embed_all(questions: list[str]) -> list:
    """One vector per question, spreading the cost across every key."""
    from agrin_api import llm
    from rag.embedding import embed_query

    keys = llm.api_keys()
    if not keys:
        raise SystemExit("no API key: set GEMINI_API_KEY in .env")

    vectors = []
    for i, question in enumerate(questions):
        last: Exception | None = None
        for attempt in range(len(keys)):
            client = llm.client_for((i + attempt) % len(keys))
            try:
                vectors.append(await embed_query(client, question))
                last = None
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if last is not None:
            if "PerDay" in str(last):
                raise SystemExit(
                    f"every key has spent its daily embedding allowance "
                    f"({i} of {len(questions)} questions done). "
                    f"Re-run after midnight Pacific."
                )
            raise SystemExit(f"embedding failed: {type(last).__name__}: {last}")
    return vectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None,
                        help="also write the table to this markdown file")
    args = parser.parse_args()

    from rag.index import MIN_SCORE, load_index

    index = load_index(ROOT / "data" / "advisory")
    if index is None:
        raise SystemExit("no index: run scripts/build_advisory_index.py first")

    data = json.loads(SET_FILE.read_text(encoding="utf-8"))
    on_topic = data["on_topic"]
    off_topic = data["off_topic"]

    print(f"corpus: {len(index)} passages, floor {MIN_SCORE}")
    print(f"set:    {len(on_topic)} on-topic, {len(off_topic)} off-topic\n")

    questions = [row["q"] for row in on_topic] + [row["q"] for row in off_topic]
    started = time.monotonic()
    vectors = asyncio.run(embed_all(questions))
    embed_ms = (time.monotonic() - started) / len(questions) * 1000

    hit1 = defaultdict(int)
    hit_k = defaultdict(int)
    total = defaultdict(int)
    on_scores: list[float] = []
    misses: list[str] = []
    search_ms: list[float] = []

    for row, vector in zip(on_topic, vectors):
        lang = row.get("lang", "en")
        total[lang] += 1
        t0 = time.perf_counter()
        hits = index.search(vector, k=args.k, min_score=0.0)
        search_ms.append((time.perf_counter() - t0) * 1000)
        titles = [h.chunk.title.lower() for h in hits]
        want = row["expect"].lower()
        if hits:
            on_scores.append(hits[0].score)
        if titles and want in titles[0]:
            hit1[lang] += 1
        if any(want in t for t in titles):
            hit_k[lang] += 1
        else:
            misses.append(
                f"{row['q'][:58]} → wanted “{row['expect']}”, "
                f"got “{hits[0].chunk.title[:44]}” at {hits[0].score:.3f}"
                if hits else f"{row['q'][:58]} → nothing"
            )

    off_scores: list[float] = []
    false_quotes: list[str] = []
    for row, vector in zip(off_topic, vectors[len(on_topic):]):
        hits = index.search(vector, k=1, min_score=0.0)
        if hits:
            off_scores.append(hits[0].score)
            if hits[0].score >= MIN_SCORE:
                false_quotes.append(
                    f"{row['q'][:52]} → “{hits[0].chunk.title[:40]}” "
                    f"at {hits[0].score:.3f}"
                )

    n = sum(total.values())
    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text)
        lines.append(text)

    say(f"| Metric | Result |")
    say("|---|---|")
    say(f"| Right subject ranked 1st | **{sum(hit1.values())}/{n} "
        f"({sum(hit1.values()) * 100 // n}%)** |")
    say(f"| Right subject in top {args.k} | **{sum(hit_k.values())}/{n} "
        f"({sum(hit_k.values()) * 100 // n}%)** |")
    say(f"| Off-topic questions abstained | "
        f"**{len(off_topic) - len(false_quotes)}/{len(off_topic)}** |")
    say(f"| Search time (median) | {statistics.median(search_ms):.1f} ms |")
    say(f"| Embedding round trip (mean) | {embed_ms:.0f} ms |")
    say()
    say("| Language | 1st | Top 3 |")
    say("|---|---|---|")
    for lang in sorted(total):
        say(f"| {lang} | {hit1[lang]}/{total[lang]} | {hit_k[lang]}/{total[lang]} |")
    say()

    if on_scores and off_scores:
        weakest_on, strongest_off = min(on_scores), max(off_scores)
        margin = weakest_on - strongest_off
        say(f"Scores: on-topic {min(on_scores):.3f}–{max(on_scores):.3f}, "
            f"off-topic {min(off_scores):.3f}–{max(off_scores):.3f}")
        say(f"Margin at the floor: **{margin:+.3f}** "
            f"(weakest on-topic {weakest_on:.3f} − strongest off-topic "
            f"{strongest_off:.3f}); floor is {MIN_SCORE}")
        if margin <= 0:
            say("**The floor cannot separate them.** An off-topic question "
                "now outscores a real one; no single threshold is correct.")
        elif not (strongest_off < MIN_SCORE < weakest_on):
            say(f"**The floor sits outside the gap.** Somewhere between "
                f"{strongest_off:.3f} and {weakest_on:.3f} would separate them.")
        say()

    if misses:
        say(f"Retrieval misses ({len(misses)}):")
        for m in misses:
            say(f"  - {m}")
        say()
    if false_quotes:
        say(f"Off-topic questions that were answered anyway ({len(false_quotes)}):")
        for f in false_quotes:
            say(f"  - {f}")
        say()

    if args.out:
        header = (
            f"# Retrieval evaluation\n\n"
            f"*{time.strftime('%Y-%m-%d')} · {len(index)} passages · "
            f"{n} on-topic and {len(off_topic)} off-topic questions in "
            f"English, Hindi, Punjabi and Hinglish "
            f"(`eval/retrieval_set.json`) · floor {MIN_SCORE}*\n\n"
        )
        args.out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")

    return 0 if not false_quotes and not misses else 1


if __name__ == "__main__":
    raise SystemExit(main())
