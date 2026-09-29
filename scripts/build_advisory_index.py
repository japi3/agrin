"""
Build the advisory corpus the assistant quotes from.

Source: Vikaspedia's agriculture domain, published by C-DAC under the
Ministry of Electronics and IT. It is the right corpus for this platform for
reasons that are mostly not about its size. It is government material, so
quoting it is defensible in a way that quoting a blog is not. It is written
for Indian conditions -- districts, seasons, schemes, varieties -- rather
than translated from somewhere else. It carries an author and a revision date
on every page, so a citation can say when the advice was last touched. And it
exists in twenty-three languages, which is very nearly the set this app
already speaks.

Its robots.txt allows general crawlers (it names only offline-mirroring
tools), and the crawl below is deliberately unhurried: a few requests at a
time, one pass, cached to disk so a re-run costs the site nothing.

Three stages, each resumable, because the third one takes hours:

    fetch   sitemap -> data/advisory_cache/pages-<lang>.jsonl
    chunk   cached pages -> data/advisory/chunks.jsonl
    embed   chunks -> data/advisory/vectors.npy

Resumability is not a convenience here. Embedding is capped at 90 texts a
minute per key, so a full English corpus is well over an hour of wall clock;
a run that lost its place on a dropped connection would be unusable. Progress
is written after every batch and a re-run picks up at the next unembedded
chunk.

    python scripts/build_advisory_index.py                 # English
    python scripts/build_advisory_index.py --languages en hi
    python scripts/build_advisory_index.py --limit 40      # a quick trial
    python scripts/build_advisory_index.py --stage fetch   # crawl only

The output goes in data/advisory/ and is copied into the image at /app/advisory,
exactly as the soil map is. Without it the assistant loses one tool and keeps
everything else.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    sys.path.insert(0, str(ROOT / pkg))

import os  # noqa: E402
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import httpx  # noqa: E402
import numpy as np  # noqa: E402

from rag.chunking import Chunk, chunk_article  # noqa: E402
from rag.embedding import (  # noqa: E402
    BATCH_SIZE, DIMENSIONS, EMBEDDING_MODEL, RateWindow, embed_texts,
)
from rag.extract import article_from_page  # noqa: E402
from rag.index import CHUNKS_GZ, MANIFEST_FILE, VECTORS_FILE  # noqa: E402

SITEMAP = "https://agriculture.vikaspedia.in/sitemap.xml"
SOURCE_NAME = "Vikaspedia (Government of India, C-DAC)"

CACHE = ROOT / "data" / "advisory_cache"
OUT = ROOT / "data" / "advisory"

# Identifying, with a way to find out what it is. Crawling a public service
# anonymously when a one-line header would explain the traffic is rude.
USER_AGENT = (
    "AgriN/0.1 (+https://github.com/japleenkaur/agrin; "
    "agricultural advisory assistant; contact via repository)"
)

# Four at a time against a government portal that is not a CDN. The crawl
# finishes in minutes either way; the cost of being wrong about what it can
# take is borne by everyone else using the site.
CONCURRENCY = 4
PAUSE_S = 0.25

# Pages shorter than this are stubs -- a title and a sentence -- and retrieve
# badly, matching on their subject while containing no advice about it.
MIN_WORDS = 60


# --------------------------------------------------------------------------
# What to embed first
# --------------------------------------------------------------------------
#
# The free tier allows a thousand passages per key per day, so the corpus is
# built over days rather than in one pass, and the order it is built in
# decides what the assistant can answer in the meantime. Alphabetical by URL
# -- the order that falls out of the sitemap -- would give a corpus that
# knows everything about Ants and nothing about wheat.
#
# So articles are ordered by what a farmer is likely to ask. The tiers below
# come from the corpus itself rather than from a guess about it: of 1,570
# English articles, 735 sit under Crop Production, and 634 of those are
# integrated pest management and packages of practice. That is exactly the
# written-down material this tool exists to quote -- the varieties, the seed
# rates, the spacings, the treatments -- so it goes first.
#
# Lower number, embedded sooner. Everything unlisted lands in the last tier,
# which is the right default: the sections not named here are directories,
# award citations, export statistics and personal stories, which retrieve as
# confidently as advice and are not advice.
TOPIC_TIERS = [
    (0, {"Crop Production"}),
    (1, {"Agri Inputs", "Best Practices"}),
    (2, {"Policies and Schemes", "National Schemes for Farmers",
         "State-specific schemes for farmers", "Agri Insurance", "Agri Credit"}),
    (3, {"Post Harvest Technologies", "Market information"}),
    (4, {"Livestock", "Poultry", "Fisheries", "Forestry"}),
]
LAST_TIER = len(TOPIC_TIERS)


def topic_tier(article) -> int:
    """How soon this article's passages should be embedded.

    The breadcrumb's second entry is the section -- the first is always
    "Agriculture" -- and an article without one is treated as unclassified
    rather than important.
    """
    section = article.path[1] if len(article.path) > 1 else ""
    for tier, names in TOPIC_TIERS:
        if section in names:
            return tier
    return LAST_TIER


# --------------------------------------------------------------------------
# Stage 1: fetch
# --------------------------------------------------------------------------

async def sitemap_urls(client: httpx.AsyncClient, languages: list[str]) -> dict[str, list[str]]:
    response = await client.get(SITEMAP, timeout=120.0)
    response.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", response.text)
    by_language: dict[str, list[str]] = {lang: [] for lang in languages}
    for url in urls:
        found = re.search(r"[?&]lgn=(\w+)", url)
        if found and found.group(1) in by_language:
            by_language[found.group(1)].append(url)
    return by_language


async def fetch_language(
    client: httpx.AsyncClient, language: str, urls: list[str], limit: int | None
) -> Path:
    """Crawl one language, skipping anything already cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"pages-{language}.jsonl"

    done: set[str] = set()
    if path.exists():
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    done.add(json.loads(line)["url"])
                except (ValueError, KeyError):
                    continue

    todo = [u for u in urls if u not in done]
    if limit is not None:
        todo = todo[:limit]
    print(f"  {language}: {len(urls)} in sitemap, {len(done)} cached, {len(todo)} to fetch")
    if not todo:
        return path

    gate = asyncio.Semaphore(CONCURRENCY)
    counts = {"article": 0, "folder": 0, "short": 0, "error": 0}
    handle = open(path, "a", encoding="utf-8")
    lock = asyncio.Lock()
    started = time.monotonic()

    async def one(url: str, position: int) -> None:
        async with gate:
            await asyncio.sleep(PAUSE_S)
            # A handful of pages drop the connection mid-response on a first
            # attempt and serve fine on a second. Two retries, backing off,
            # rather than silently losing those articles from the corpus.
            page = None
            for attempt in range(3):
                try:
                    page = await client.get(url, timeout=60.0)
                    page.raise_for_status()
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        counts["error"] += 1
                        if counts["error"] <= 5:
                            print(f"    ! {type(exc).__name__} {url[-60:]}")
                        return
                    await asyncio.sleep(1.5 * (attempt + 1))
            if page is None:
                return

            article = article_from_page(page.text, url)
            if article is None:
                counts["folder"] += 1
                record = {"url": url, "article": None}
            elif article.words < MIN_WORDS:
                counts["short"] += 1
                record = {"url": url, "article": None}
            else:
                counts["article"] += 1
                record = {
                    "url": url,
                    "article": {
                        "url": article.url, "title": article.title,
                        "language": article.language, "path": article.path,
                        "updated": article.updated, "author": article.author,
                        "blocks": [[b.kind, b.text, b.level] for b in article.blocks],
                    },
                }
            async with lock:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                if position % 200 == 0:
                    handle.flush()
                    rate = position / max(0.1, time.monotonic() - started)
                    print(f"    {position}/{len(todo)}  {rate:.1f}/s  "
                          f"articles={counts['article']}")

    await asyncio.gather(*(one(u, i + 1) for i, u in enumerate(todo)))
    handle.close()
    print(f"  {language}: kept {counts['article']}, skipped "
          f"{counts['folder']} folder + {counts['short']} stub, "
          f"{counts['error']} errors")
    return path


async def stage_fetch(languages: list[str], limit: int | None) -> None:
    print("fetch")
    headers = {"User-Agent": USER_AGENT, "Accept-Language": ",".join(languages)}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        by_language = await sitemap_urls(client, languages)
        for language in languages:
            await fetch_language(client, language, by_language[language], limit)


# --------------------------------------------------------------------------
# Stage 2: chunk
# --------------------------------------------------------------------------

def cached_articles(languages: list[str]):
    from rag.extract import Article, Block
    for language in languages:
        path = CACHE / f"pages-{language}.jsonl"
        if not path.exists():
            print(f"  ! no cache for {language}; run --stage fetch first")
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                data = record.get("article")
                if not data:
                    continue
                yield Article(
                    url=data["url"], title=data["title"], language=data["language"],
                    path=data.get("path") or [], updated=data.get("updated"),
                    author=data.get("author"),
                    blocks=[Block(k, t, lv) for k, t, lv in data["blocks"]],
                )


def stage_chunk(languages: list[str]) -> list[Chunk]:
    print("chunk")
    OUT.mkdir(parents=True, exist_ok=True)
    chunks: list[Chunk] = []
    seen: set[str] = set()
    articles = 0
    tiers: dict[int, int] = {}
    # Most useful first, then by URL. The URL is what makes the order stable
    # across runs: the embedding stage resumes by row number and would
    # otherwise realign onto a different passage after a re-crawl.
    for article in sorted(cached_articles(languages),
                          key=lambda a: (topic_tier(a), a.url)):
        articles += 1
        tiers[topic_tier(article)] = tiers.get(topic_tier(article), 0) + 1
        for chunk in chunk_article(article):
            # The same advice is often published under several paths. An exact
            # repeat wastes a vector and crowds out variety in the results.
            key = f"{chunk.language}:{chunk.text}"
            if key in seen:
                continue
            seen.add(key)
            chunks.append(chunk)

    # Deliberately not written to chunks.jsonl here. The passages and the
    # vectors are matched by row, and the shipped index is only coherent when
    # they agree -- so only finalise() writes that file, next to the vectors
    # it matches.
    #
    # Writing it at this point instead was a real trap. Re-chunking happens on
    # every run, including a run that only resumes embedding, so for the hour
    # that run took, chunks.jsonl held 6,396 passages while vectors.npy still
    # held 992. An image built in that window carried an index that refused to
    # load, and the only symptom was the assistant quietly losing one tool.
    size = sum(len(json.dumps(c.as_dict(), ensure_ascii=False)) for c in chunks) / 1e6
    print(f"  {articles} articles -> {len(chunks)} passages ({size:.1f} MB)")
    names = {0: "crop production", 1: "inputs & practice", 2: "schemes",
             3: "post-harvest & market", 4: "livestock & fisheries",
             LAST_TIER: "everything else"}
    print("  embedding order: " + ", ".join(
        f"{tiers[t]} {names.get(t, t)}" for t in sorted(tiers)))
    return chunks


# --------------------------------------------------------------------------
# Stage 3: embed
# --------------------------------------------------------------------------

# Long enough that a slow-but-live batch is not thrown away, short enough
# that a dead one does not cost an hour. A healthy batch of 32 returns in
# about three seconds.
EMBED_TIMEOUT_S = 120.0

# Consecutive timeouts before giving up. The run is resumable, so stopping is
# cheap and an infinite retry loop that writes nothing is the worse failure.
MAX_STALLS = 12

PARTIAL = "vectors.partial.npy"
PROGRESS = "progress.json"


async def stage_embed(chunks: list[Chunk], languages: list[str]) -> None:
    from agrin_api import llm

    if not llm.is_configured():
        raise SystemExit("no API key: set GEMINI_API_KEY in .env")

    keys = llm.api_keys()
    clients = [llm.client_for(i) for i in range(len(keys))]
    windows = [RateWindow() for _ in keys]
    print(f"embed  {len(chunks)} passages, {len(keys)} key(s), "
          f"{EMBEDDING_MODEL} at {DIMENSIONS}d")

    vectors = np.zeros((len(chunks), DIMENSIONS), dtype=np.float32)
    done = 0
    progress_path = OUT / PROGRESS
    partial_path = OUT / PARTIAL
    if progress_path.exists() and partial_path.exists():
        try:
            state = json.loads(progress_path.read_text())
            if state.get("total") == len(chunks) and state.get("model") == EMBEDDING_MODEL:
                stored = np.load(partial_path)
                done = min(int(state["done"]), len(stored))
                vectors[:done] = stored[:done]
                print(f"  resuming at {done}/{len(chunks)}")
            else:
                print("  cached progress does not match this corpus; starting over")
        except (ValueError, KeyError, OSError):
            print("  unreadable progress file; starting over")

    def save(count: int) -> None:
        np.save(partial_path, vectors[:count])
        progress_path.write_text(json.dumps({
            "done": count, "total": len(chunks),
            "model": EMBEDDING_MODEL, "dimensions": DIMENSIONS,
        }))

    started = time.monotonic()
    # Rows carried over from an earlier run took none of this run's time, so
    # counting them makes the rate meaningless -- a resumed run reported
    # 22,668/min and "0 min left" with most of the corpus still to do.
    resumed_at = done
    turn = 0
    stalls = 0
    exhausted: set[int] = set()
    while done < len(chunks):
        batch = chunks[done:done + BATCH_SIZE]
        texts = [c.for_embedding() for c in batch]

        # Keys are used round-robin, skipping any that has spent its day.
        # Each has its own allowance, so two keys genuinely double the budget
        # rather than sharing one ceiling.
        live = [i for i in range(len(clients)) if i not in exhausted]
        slot = live[turn % len(live)]
        turn += 1
        await windows[slot].take(len(texts))

        try:
            # A timeout is not optional here. Observed on the first full run:
            # one call stopped returning and the whole build sat at zero CPU
            # for forty-five minutes, holding a place it never gave up. The
            # service was fine the entire time -- both keys answered a probe
            # immediately. A batch that has not come back in two minutes is
            # not going to, and retrying it costs seconds.
            vectors[done:done + len(batch)] = await asyncio.wait_for(
                embed_texts(clients[slot], texts), timeout=EMBED_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            stalls += 1
            print(f"  batch at {done} timed out on key {slot}; retrying")
            if stalls > MAX_STALLS:
                save(done)
                raise SystemExit(
                    f"gave up after {stalls} timeouts; resume by re-running"
                )
            continue
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "RESOURCE_EXHAUSTED" in message or "429" in message:
                # Two different 429s, and telling them apart is the whole
                # difference between a pause and a stop. The per-minute cap
                # clears in under a minute. The daily one does not clear
                # until midnight Pacific, and waiting on it burns hours in a
                # loop that cannot succeed -- which is exactly what an
                # earlier run did, silently, because it only ever read the
                # word "RESOURCE_EXHAUSTED".
                if "PerDay" in message:
                    exhausted.add(slot)
                    print(f"  key {slot} has spent its daily allowance")
                    if len(exhausted) >= len(clients):
                        print(f"  all keys exhausted at {done}/{len(chunks)}")
                        if done == 0:
                            # Nothing was embedded, so there is no index to
                            # write -- and finalising would truncate the
                            # passages to match zero vectors, throwing away
                            # the crawl. Leave everything as it is.
                            print("  nothing embedded; run again after the "
                                  "quota resets (midnight Pacific)")
                            return
                        save(done)
                        finalise(vectors, chunks, done, languages)
                        return
                    continue
                wait = 20.0
                found = re.search(r"retry in ([\d.]+)s", message)
                if found:
                    wait = min(90.0, float(found.group(1)) + 2.0)
                print(f"  rate limited on key {slot}; waiting {wait:.0f}s")
                await asyncio.sleep(wait)
                continue
            # Anything else is a real fault. Save what is done and stop
            # loudly rather than writing an index with a hole in it.
            save(done)
            raise

        done += len(batch)
        stalls = 0          # consecutive, so a good batch clears the count
        if done % (BATCH_SIZE * 8) < BATCH_SIZE or done == len(chunks):
            save(done)
            elapsed = time.monotonic() - started
            rate = (done - resumed_at) / max(elapsed, 0.1) * 60
            if rate > 1:
                left = f"~{(len(chunks) - done) / rate:.0f} min left"
            else:
                left = "estimating"
            print(f"  {done}/{len(chunks)}  {rate:.0f}/min  {left}")

    finalise(vectors, chunks, done, languages)


def finalise(vectors, chunks: list[Chunk], done: int, languages: list[str]) -> None:
    """Write a usable index out of however much has been embedded.

    A day's quota buys a fraction of the corpus, so "incomplete" is the normal
    state of this index for as long as it takes to fill, and a partial build
    has to be a working build rather than a failed one. Passages are embedded
    most-useful-first, so the first few thousand are the ones worth having.

    chunks.jsonl is truncated to match the vectors. That is not tidiness:
    vectors and passages are matched by row, and an index carrying passages it
    has no vectors for would attribute every citation past the boundary to the
    wrong page.
    """
    # Always written here, and only here, so that whatever is on disk is a
    # matched pair. Written to a temporary name and moved into place, because
    # a crash midway through this loop would otherwise leave a truncated file
    # that looks complete.
    import gzip
    building = OUT / (CHUNKS_GZ + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        for chunk in chunks[:done]:
            handle.write(json.dumps(chunk.as_dict(), ensure_ascii=False) + "\n")
    building.replace(OUT / CHUNKS_GZ)

    # float16 halves the shipped file; see the note in rag/index.py.
    np.save(OUT / VECTORS_FILE, vectors[:done].astype(np.float16))
    (OUT / MANIFEST_FILE).write_text(json.dumps({
        "source": SOURCE_NAME,
        "source_url": "https://agriculture.vikaspedia.in/",
        "licence_note": (
            "Vikaspedia content is published by C-DAC under the Ministry of "
            "Electronics and Information Technology, Government of India. "
            "Passages are quoted with attribution and a link to the page."
        ),
        "languages": languages,
        "passages": done,
        "passages_available": len(chunks),
        "complete": done >= len(chunks),
        "model": EMBEDDING_MODEL,
        "dimensions": DIMENSIONS,
        "built_on": time.strftime("%Y-%m-%d"),
    }, indent=2))

    size = (OUT / VECTORS_FILE).stat().st_size / 1e6
    print(f"  wrote {OUT / VECTORS_FILE} ({size:.1f} MB), {done} passages")
    if done >= len(chunks):
        (OUT / PARTIAL).unlink(missing_ok=True)
        (OUT / PROGRESS).unlink(missing_ok=True)
    else:
        remaining = len(chunks) - done
        print(f"  {remaining} passages still unembedded — re-run after the "
              f"daily quota resets (midnight Pacific) to continue")


# --------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="+", default=["en"])
    parser.add_argument("--limit", type=int, default=None,
                        help="fetch at most this many new pages per language")
    parser.add_argument("--stage", choices=["fetch", "chunk", "embed", "all"],
                        default="all")
    args = parser.parse_args()

    if args.stage in ("fetch", "all"):
        await stage_fetch(args.languages, args.limit)
    if args.stage in ("chunk", "embed", "all"):
        chunks = stage_chunk(args.languages)
        if args.stage in ("embed", "all"):
            if not chunks:
                raise SystemExit("nothing to embed")
            await stage_embed(chunks, args.languages)


if __name__ == "__main__":
    asyncio.run(main())
